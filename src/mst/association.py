"""Deterministic multi-object association from tracker-facing observations."""

from __future__ import annotations

import hashlib
import math
from dataclasses import dataclass
from itertools import groupby

import numpy as np
from numpy.typing import NDArray
from scipy.optimize import linear_sum_assignment

from .events import AssociationEvent, event
from .innovations import Innovation
from .schema import VERSION, Observation, SchemaError, TrackEstimate, canonical_json
from .tracking import H, _kalman_update, process_covariance, transition

FloatArray = NDArray[np.float64]


@dataclass
class _Track:
    track_id: str
    state: FloatArray
    covariance: FloatArray
    timestamp_s: float
    hits: int = 1
    missed: int = 0
    confirmed: bool = False


def _distance_squared(track: _Track, observation: Observation) -> float:
    innovation = np.asarray(observation.position_m) - H @ track.state
    s = H @ track.covariance @ H.T + np.asarray(observation.covariance_m2)
    values, vectors = np.linalg.eigh((s + s.T) / 2)
    scale = max(1.0, float(np.max(np.abs(values))))
    tolerance = 1e-12 * scale
    if float(np.min(values)) < -tolerance:
        raise SchemaError("innovation covariance is not positive semidefinite")
    projected = vectors.T @ innovation
    if np.any(np.abs(projected[values <= tolerance]) > 1e-9 * scale):
        return math.inf
    positive = values > tolerance
    return float(np.sum(projected[positive] ** 2 / values[positive]))


def _new_track(observation: Observation, serial: int, velocity_std: float) -> _Track:
    state: FloatArray = np.array([*observation.position_m, 0.0, 0.0])
    covariance: FloatArray = np.zeros((4, 4))
    covariance[:2, :2] = np.asarray(observation.covariance_m2)
    covariance[2:, 2:] = np.eye(2) * velocity_std**2
    return _Track(f"track-{serial:04d}", state, covariance, observation.timestamp_s)


def _estimate(track: _Track, lifecycle: str, config_id: str) -> TrackEstimate:
    estimate = TrackEstimate(
        VERSION,
        track.timestamp_s,
        track.track_id,
        tuple(float(value) for value in track.state),
        tuple(tuple(float(value) for value in row) for row in track.covariance),
        lifecycle,
        "multi-kalman",
        config_id,
        "world",
        "m",
        "m/s",
    )
    return TrackEstimate.from_dict(estimate.to_dict())


def track_multiple_objects(
    observations: list[Observation],
    *,
    acceleration_std_mps2: float = 1.0,
    initial_velocity_std_mps: float = 10.0,
    gate_squared: float = 9.21,
    min_hits: int = 2,
    max_missed: int = 2,
    innovations: list[Innovation] | None = None,
    events: list[AssociationEvent] | None = None,
) -> list[TrackEstimate]:
    """Assign per sensor and timestamp with a global minimum-cost matching.

    Unmatched observations start tentative tracks. Tracks confirm at min_hits
    matches and delete after more than max_missed observation epochs without a hit.
    """
    if not math.isfinite(acceleration_std_mps2) or acceleration_std_mps2 < 0:
        raise SchemaError("acceleration_std_mps2 must be finite and nonnegative")
    if not math.isfinite(initial_velocity_std_mps) or initial_velocity_std_mps <= 0:
        raise SchemaError("initial_velocity_std_mps must be finite and positive")
    if not math.isfinite(gate_squared) or not 0 < gate_squared <= 1e9:
        raise SchemaError("gate_squared must be finite and in (0, 1e9]")
    if (
        type(min_hits) is not int
        or min_hits < 1
        or type(max_missed) is not int
        or max_missed < 0
    ):
        raise SchemaError("min_hits must be positive and max_missed nonnegative")
    seen_ids: set[str] = set()
    previous_time = -1.0
    for observation in observations:
        Observation.from_dict(observation.to_dict())
        if observation.timestamp_s < previous_time:
            raise SchemaError("observations must be in nondecreasing timestamp order")
        if observation.observation_id in seen_ids:
            raise SchemaError("duplicate observation_id")
        seen_ids.add(observation.observation_id)
        previous_time = observation.timestamp_s

    config = {
        "acceleration_std_mps2": acceleration_std_mps2,
        "initial_velocity_std_mps": initial_velocity_std_mps,
        "gate_squared": gate_squared,
        "min_hits": min_hits,
        "max_missed": max_missed,
    }
    config_id = (
        "cfg-" + hashlib.sha256(canonical_json(config).encode()).hexdigest()[:16]
    )
    tracks: list[_Track] = []
    estimates: list[TrackEstimate] = []
    next_serial = 1
    for timestamp, group in groupby(observations, key=lambda item: item.timestamp_s):
        epoch = list(group)
        for track in tracks:
            dt = timestamp - track.timestamp_s
            f = transition(dt)
            track.state = f @ track.state
            track.covariance = f @ track.covariance @ f.T + process_covariance(
                dt, acceleration_std_mps2
            )
            track.timestamp_s = timestamp
        matched_ids: set[str] = set()
        for sensor_id in sorted({item.sensor_id for item in epoch}):
            sensor_observations = sorted(
                (item for item in epoch if item.sensor_id == sensor_id),
                key=lambda item: item.observation_id,
            )
            candidates = sorted(tracks, key=lambda item: item.track_id)
            matched_observations: set[int] = set()
            if candidates and sensor_observations:
                costs = np.array(
                    [
                        [_distance_squared(track, item) for item in sensor_observations]
                        for track in candidates
                    ]
                )
                # Invalid edges cost much more than any gated edge. scipy's
                # assignment is deterministic for this canonically sorted input.
                invalid_cost = (
                    max(len(candidates), len(sensor_observations)) + 1
                ) * gate_squared + 1
                finite_costs = np.where(costs <= gate_squared, costs, invalid_cost)
                rows, columns = linear_sum_assignment(finite_costs)
                accepted: set[tuple[int, int]] = set()
                for row, column in zip(rows, columns, strict=True):
                    if costs[row, column] > gate_squared:
                        continue
                    track = candidates[row]
                    observation = sensor_observations[column]
                    track.state, track.covariance = _kalman_update(
                        track.state,
                        track.covariance,
                        observation,
                        track_id=track.track_id,
                        innovations=innovations,
                    )
                    track.hits += 1
                    matched_ids.add(track.track_id)
                    matched_observations.add(int(column))
                    accepted.add((int(row), int(column)))
                    if events is not None:
                        events.append(
                            event(
                                timestamp,
                                "match",
                                track.track_id,
                                observation=observation,
                                distance_squared=float(costs[row, column]),
                                gate_squared=gate_squared,
                                reason="accepted",
                            )
                        )
                if events is not None:
                    for candidate_index, track in enumerate(candidates):
                        for observation_index, observation in enumerate(
                            sensor_observations
                        ):
                            if (candidate_index, observation_index) in accepted:
                                continue
                            score = float(costs[candidate_index, observation_index])
                            events.append(
                                event(
                                    timestamp,
                                    "rejected",
                                    track.track_id,
                                    observation=observation,
                                    distance_squared=score,
                                    gate_squared=gate_squared,
                                    reason="gated"
                                    if score > gate_squared
                                    else "assigned_elsewhere",
                                )
                            )
            for observation_index, observation in enumerate(sensor_observations):
                if observation_index not in matched_observations:
                    track = _new_track(
                        observation, next_serial, initial_velocity_std_mps
                    )
                    next_serial += 1
                    tracks.append(track)
                    matched_ids.add(track.track_id)
                    if events is not None:
                        events.append(
                            event(
                                timestamp,
                                "birth",
                                track.track_id,
                                observation=observation,
                                reason="unmatched",
                            )
                        )
        retained: list[_Track] = []
        for track in sorted(tracks, key=lambda item: item.track_id):
            if track.track_id not in matched_ids:
                track.missed += 1
            else:
                track.missed = 0
            if track.missed > max_missed:
                lifecycle = "deleted"
            elif track.hits >= min_hits:
                lifecycle = "confirmed"
                if not track.confirmed and events is not None:
                    events.append(
                        event(timestamp, "confirm", track.track_id, reason="confirmed")
                    )
                track.confirmed = True
            else:
                lifecycle = "tentative"
            if lifecycle == "deleted" and events is not None:
                events.append(
                    event(timestamp, "delete", track.track_id, reason="missed")
                )
            estimates.append(_estimate(track, lifecycle, config_id))
            if lifecycle != "deleted":
                retained.append(track)
        tracks = retained
    return estimates
