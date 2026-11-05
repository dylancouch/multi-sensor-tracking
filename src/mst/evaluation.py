"""Scoring-only code. Truth never enters tracking or association modules."""

from __future__ import annotations

import hashlib
import math
import statistics
from collections import defaultdict
from pathlib import Path
from typing import Any

import numpy as np
from scipy.linalg import cho_factor, cho_solve
from scipy.optimize import linear_sum_assignment

from . import __version__
from .innovations import Innovation
from .provenance import environment_versions, source_state
from .schema import (
    MAX_JSONL_BYTES,
    Manifest,
    Observation,
    SchemaError,
    TrackEstimate,
    Truth,
    canonical_json,
    parse_json,
)


def read_truth(path: Path) -> list[Truth]:
    if path.stat().st_size > MAX_JSONL_BYTES:
        raise SchemaError(f"{path.name} exceeds {MAX_JSONL_BYTES} bytes")
    records: list[Truth] = []
    seen: set[tuple[float, str]] = set()
    previous_time = -1.0
    with path.open("r", encoding="utf-8") as stream:
        for line_number, line in enumerate(stream, 1):
            if len(line) > 1_000_000:
                raise SchemaError(f"{path.name}:{line_number}: line exceeds 1 MB")
            try:
                record = Truth.from_dict(parse_json(line))
                key = (record.timestamp_s, record.object_id)
                if record.timestamp_s < previous_time:
                    raise SchemaError("timestamps must be nondecreasing")
                if key in seen:
                    raise SchemaError("duplicate truth timestamp/object_id")
                seen.add(key)
                previous_time = record.timestamp_s
                records.append(record)
            except SchemaError as exc:
                raise SchemaError(f"{path.name}:{line_number}: {exc}") from exc
    return records


def identity_metrics(
    truth: list[Truth], estimates: list[TrackEstimate], *, gate_m: float = 10.0
) -> dict[str, int | float]:
    """Planar IDF1 with a single global truth-to-track assignment.

    Potential identity matches are exact-time pairs inside the distance gate.
    Only final non-deleted states at truth timestamps count as detections.
    This keeps the input and timing policy aligned with ``score`` while the
    sequence-global identity pairing follows the ID metrics convention.
    """
    if not math.isfinite(gate_m) or not 0 < gate_m <= 1e6:
        raise SchemaError("gate_m must be finite and in (0, 1e6]")
    if not truth:
        raise SchemaError("cannot score an empty truth dataset")
    truth_by_time: dict[float, list[Truth]] = defaultdict(list)
    seen_truth: set[tuple[float, str]] = set()
    for truth_item in truth:
        Truth.from_dict(truth_item.to_dict())
        key = (truth_item.timestamp_s, truth_item.object_id)
        if key in seen_truth:
            raise SchemaError("duplicate truth timestamp/object_id")
        seen_truth.add(key)
        truth_by_time[truth_item.timestamp_s].append(truth_item)
    final_estimate: dict[tuple[float, str], TrackEstimate] = {}
    for estimate_item in estimates:
        TrackEstimate.from_dict(estimate_item.to_dict())
        final_estimate[(estimate_item.timestamp_s, estimate_item.track_id)] = (
            estimate_item
        )
    live_by_time: dict[float, list[TrackEstimate]] = defaultdict(list)
    for (timestamp, _), estimate_item in final_estimate.items():
        if timestamp in truth_by_time and estimate_item.lifecycle != "deleted":
            live_by_time[timestamp].append(estimate_item)
    truth_ids = sorted({item.object_id for item in truth})
    track_ids = sorted(
        {item.track_id for frame in live_by_time.values() for item in frame}
    )
    potential = np.zeros((len(truth_ids), len(track_ids)), dtype=np.int64)
    truth_index = {item: index for index, item in enumerate(truth_ids)}
    track_index = {item: index for index, item in enumerate(track_ids)}
    for timestamp, truth_frame in truth_by_time.items():
        for actual in truth_frame:
            for estimate in live_by_time[timestamp]:
                if (
                    math.hypot(
                        actual.state[0] - estimate.state[0],
                        actual.state[1] - estimate.state[1],
                    )
                    <= gate_m
                ):
                    potential[
                        truth_index[actual.object_id], track_index[estimate.track_id]
                    ] += 1
    idtp = 0
    if potential.size:
        rows, columns = linear_sum_assignment(-potential)
        idtp = int(potential[rows, columns].sum())
    truth_detections = len(truth)
    tracker_detections = sum(len(frame) for frame in live_by_time.values())
    idfn = truth_detections - idtp
    idfp = tracker_detections - idtp
    return {
        "idtp": idtp,
        "idfp": idfp,
        "idfn": idfn,
        "id_precision": idtp / tracker_detections if tracker_detections else 0.0,
        "id_recall": idtp / truth_detections,
        "idf1": 2 * idtp / (truth_detections + tracker_detections),
    }


def score(
    truth: list[Truth],
    estimates: list[TrackEstimate],
    *,
    gate_m: float = 10.0,
    innovations: list[Innovation] | None = None,
    observations: list[Observation] | None = None,
) -> dict[str, Any]:
    """Match each truth frame to final live estimates at the exact same timestamp.

    Matching minimizes total planar distance among gated pairs, preferring the
    maximum possible number of matches. Unmatched counts are per truth frame.
    """
    if not math.isfinite(gate_m) or not 0 < gate_m <= 1e6:
        raise SchemaError("gate_m must be finite and in (0, 1e6]")
    if not truth:
        raise SchemaError("cannot score an empty truth dataset")
    truth_by_time: dict[float, list[Truth]] = defaultdict(list)
    truth_ids: set[tuple[float, str]] = set()
    for truth_record in truth:
        Truth.from_dict(truth_record.to_dict())
        key = (truth_record.timestamp_s, truth_record.object_id)
        if key in truth_ids:
            raise SchemaError("duplicate truth timestamp/object_id")
        truth_ids.add(key)
        truth_by_time[truth_record.timestamp_s].append(truth_record)
    final_estimate: dict[tuple[float, str], TrackEstimate] = {}
    for estimate_record in estimates:
        TrackEstimate.from_dict(estimate_record.to_dict())
        final_estimate[(estimate_record.timestamp_s, estimate_record.track_id)] = (
            estimate_record
        )
    nis_values: list[float] = []
    nis_skipped = 0
    observation_by_id = (
        {item.observation_id: item for item in observations}
        if observations is not None
        else None
    )
    if observations is not None and len(observation_by_id or {}) != len(observations):
        raise SchemaError("duplicate observation_id in evaluation observations")
    if innovations is not None:
        seen_observations: set[str] = set()
        for item in innovations:
            Innovation.from_dict(item.to_dict())
            if item.observation_id in seen_observations:
                raise SchemaError("duplicate innovation observation_id")
            seen_observations.add(item.observation_id)
            track = final_estimate.get((item.timestamp_s, item.track_id))
            if track is None or track.method == "baseline":
                raise SchemaError(
                    "innovation does not reference a Kalman track at its timestamp"
                )
            if observation_by_id is not None:
                source = observation_by_id.get(item.observation_id)
                if (
                    source is None
                    or source.timestamp_s != item.timestamp_s
                    or source.sensor_id != item.sensor_id
                ):
                    raise SchemaError(
                        "innovation does not match its source observation"
                    )
            if item.nis is None:
                nis_skipped += 1
            else:
                nis_values.append(item.nis)
    estimates_by_time: dict[float, list[TrackEstimate]] = defaultdict(list)
    unscored = 0
    for (time, _track_id), estimate_record in final_estimate.items():
        if time in truth_by_time:
            if estimate_record.lifecycle != "deleted":
                estimates_by_time[time].append(estimate_record)
        else:
            unscored += 1

    errors_squared: list[float] = []
    radial_errors: list[float] = []
    nees: list[float] = []
    nees_skipped = 0
    nees_unavailable = 0
    switches = 0
    last_track_for_truth: dict[str, str] = {}
    unmatched_truth = 0
    unmatched_estimates = 0
    for timestamp in sorted(truth_by_time):
        truth_frame = sorted(truth_by_time[timestamp], key=lambda item: item.object_id)
        estimate_frame = sorted(
            estimates_by_time[timestamp], key=lambda item: item.track_id
        )
        matches: list[tuple[int, int]] = []
        if truth_frame and estimate_frame:
            distances = np.array(
                [
                    [
                        math.hypot(t.state[0] - e.state[0], t.state[1] - e.state[1])
                        for e in estimate_frame
                    ]
                    for t in truth_frame
                ]
            )
            penalty = (max(len(truth_frame), len(estimate_frame)) + 1) * gate_m + 1
            costs = np.where(distances <= gate_m, distances, penalty)
            rows, columns = linear_sum_assignment(costs)
            matches = [
                (int(row), int(column))
                for row, column in zip(rows, columns, strict=True)
                if distances[row, column] <= gate_m
            ]
        unmatched_truth += len(truth_frame) - len(matches)
        unmatched_estimates += len(estimate_frame) - len(matches)
        for row, column in matches:
            actual = truth_frame[row]
            estimate = estimate_frame[column]
            error = math.hypot(
                actual.state[0] - estimate.state[0], actual.state[1] - estimate.state[1]
            )
            radial_errors.append(error)
            errors_squared.append(error * error)
            previous_track = last_track_for_truth.get(actual.object_id)
            if previous_track is not None and previous_track != estimate.track_id:
                switches += 1
            last_track_for_truth[actual.object_id] = estimate.track_id
            if estimate.method == "baseline":
                nees_unavailable += 1
                continue
            covariance = np.asarray(estimate.covariance, dtype=float)
            state_error = np.asarray(estimate.state) - np.asarray(actual.state)
            try:
                factor, lower = cho_factor(covariance, lower=True, check_finite=True)
                value = float(state_error @ cho_solve((factor, lower), state_error))
                if math.isfinite(value):
                    nees.append(value)
                else:
                    nees_skipped += 1
            except np.linalg.LinAlgError:
                nees_skipped += 1

    matched = len(radial_errors)
    return {
        "schema_version": 2,
        "matching_gate_m": gate_m,
        "truth_states": len(truth),
        "matched_states": matched,
        "coverage": matched / len(truth),
        "position_rmse_m": math.sqrt(statistics.fmean(errors_squared))
        if matched
        else None,
        "median_position_error_m": statistics.median(radial_errors)
        if matched
        else None,
        "id_switches": switches,
        "unmatched_truth_states": unmatched_truth,
        "unmatched_estimate_states": unmatched_estimates,
        "unscored_estimate_states": unscored,
        "nees_mean": statistics.fmean(nees) if nees else None,
        "nees_samples": len(nees),
        "nees_skipped_singular": nees_skipped,
        "nees_unavailable_baseline": nees_unavailable,
        "nis_mean": statistics.fmean(nis_values) if nis_values else None,
        "nis_samples": len(nis_values),
        "nis_skipped_singular": nis_skipped,
        "nis_reason": (
            "innovation artifact not supplied"
            if innovations is None
            else "no Kalman updates"
            if not innovations
            else None
        ),
        "mota": 1 - (unmatched_truth + unmatched_estimates + switches) / len(truth),
        "motp_m": statistics.fmean(radial_errors) if radial_errors else None,
    }


def report(
    manifest: Manifest,
    truth: list[Truth],
    estimates: list[TrackEstimate],
    track_bytes: bytes,
    *,
    gate_m: float = 10.0,
    evaluation_wall_s: float | None = None,
    innovations: list[Innovation] | None = None,
    innovation_bytes: bytes | None = None,
    observations: list[Observation] | None = None,
) -> dict[str, Any]:
    methods = sorted({item.method for item in estimates})
    configs = sorted({item.config_id for item in estimates})
    if len(methods) > 1 or len(configs) > 1:
        raise SchemaError(
            "one evaluation report requires one tracker method and config"
        )
    if (innovations is None) != (innovation_bytes is None):
        raise SchemaError("innovations and innovation_bytes must be supplied together")
    metrics = score(
        truth,
        estimates,
        gate_m=gate_m,
        innovations=innovations,
        observations=observations,
    )
    return {
        "schema_version": 2,
        "benchmark_version": __version__,
        "generator_version": manifest.generator_version,
        "seed": manifest.seed,
        "scenario_sha256": hashlib.sha256(
            canonical_json(manifest.scenario.to_dict()).encode()
        ).hexdigest(),
        "track_sha256": hashlib.sha256(track_bytes).hexdigest(),
        "innovation_sha256": hashlib.sha256(innovation_bytes).hexdigest()
        if innovation_bytes is not None
        else None,
        "observation_sha256": manifest.sha256["observations"],
        "source": source_state(),
        "method": methods[0] if methods else None,
        "config_id": configs[0] if configs else None,
        "metrics": metrics,
        "runtime": {
            "simulation_wall_s": None,
            "tracking_wall_s": None,
            "evaluation_wall_s": evaluation_wall_s,
        },
        "environment": environment_versions(),
    }


def write_report(path: Path, value: dict[str, Any]) -> None:
    with path.open("x", encoding="utf-8") as stream:
        stream.write(canonical_json(value) + "\n")
