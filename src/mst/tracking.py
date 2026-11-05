"""One-object baseline and linear Kalman filter; consumes observations only."""

from __future__ import annotations

import hashlib
import math
from collections.abc import Sequence
from typing import Literal

import numpy as np
from numpy.typing import NDArray
from scipy.linalg import cho_factor, cho_solve

from .innovations import Innovation, make_innovation
from .schema import VERSION, Observation, SchemaError, TrackEstimate, canonical_json

FloatArray = NDArray[np.float64]
Method = Literal["baseline", "kalman"]
H: FloatArray = np.array([[1.0, 0.0, 0.0, 0.0], [0.0, 1.0, 0.0, 0.0]])
I4: FloatArray = np.eye(4)


def transition(dt: float) -> FloatArray:
    """Constant-velocity state transition for seconds dt >= 0."""
    if not math.isfinite(dt) or dt < 0:
        raise SchemaError("dt must be finite and nonnegative")
    return np.array(
        [
            [1.0, 0.0, dt, 0.0],
            [0.0, 1.0, 0.0, dt],
            [0.0, 0.0, 1.0, 0.0],
            [0.0, 0.0, 0.0, 1.0],
        ]
    )


def process_covariance(dt: float, acceleration_std_mps2: float) -> FloatArray:
    """Q = G sigma_a^2 I G.T for independent piecewise-constant acceleration."""
    transition(dt)
    if not math.isfinite(acceleration_std_mps2) or acceleration_std_mps2 < 0:
        raise SchemaError("acceleration_std_mps2 must be finite and nonnegative")
    half_dt2 = dt * dt / 2
    g: FloatArray = np.array([[half_dt2, 0.0], [0.0, half_dt2], [dt, 0.0], [0.0, dt]])
    return (acceleration_std_mps2**2) * (g @ g.T)


def _config_id(
    method: Method, acceleration_std_mps2: float, initial_velocity_std_mps: float
) -> str:
    config = {
        "method": method,
        "acceleration_std_mps2": acceleration_std_mps2,
        "initial_velocity_std_mps": initial_velocity_std_mps,
    }
    return "cfg-" + hashlib.sha256(canonical_json(config).encode()).hexdigest()[:16]


def _estimate(
    timestamp_s: float,
    state: FloatArray,
    covariance: FloatArray,
    method: Method,
    config_id: str,
) -> TrackEstimate:
    result = TrackEstimate(
        VERSION,
        timestamp_s,
        "track-0001",
        tuple(float(x) for x in state),
        tuple(tuple(float(x) for x in row) for row in covariance),
        "active",
        method,
        config_id,
        "world",
        "m",
        "m/s",
    )
    return TrackEstimate.from_dict(result.to_dict())


def _kalman_update(
    state: FloatArray,
    covariance: FloatArray,
    observation: Observation,
    *,
    track_id: str = "track-0001",
    innovations: list[Innovation] | None = None,
) -> tuple[FloatArray, FloatArray]:
    z: FloatArray = np.asarray(observation.position_m, dtype=float)
    r: FloatArray = np.asarray(observation.covariance_m2, dtype=float)
    innovation = z - H @ state
    s = H @ covariance @ H.T + r
    if innovations is not None:
        innovations.append(
            make_innovation(
                observation.timestamp_s,
                track_id,
                observation.observation_id,
                observation.sensor_id,
                innovation,
                s,
            )
        )
    cross = covariance @ H.T
    try:
        factor, lower = cho_factor(s, lower=True, check_finite=True)
        gain = cho_solve((factor, lower), cross.T).T
    except np.linalg.LinAlgError:
        # Zero-noise repeated observations can make S singular. Its nullspace
        # must agree with the observation; otherwise the model is inconsistent.
        eigenvalues, eigenvectors = np.linalg.eigh((s + s.T) / 2)
        scale = max(1.0, float(np.max(np.abs(eigenvalues))))
        tolerance = 1e-12 * scale
        if float(np.min(eigenvalues)) < -tolerance:
            raise SchemaError("innovation covariance is not positive semidefinite")
        null = eigenvectors[:, eigenvalues <= tolerance]
        if null.size and float(np.linalg.norm(null.T @ innovation)) > 1e-9 * scale:
            raise SchemaError("observation conflicts with zero innovation variance")
        positive = eigenvalues > tolerance
        inverse = (eigenvectors[:, positive] / eigenvalues[positive]) @ eigenvectors[
            :, positive
        ].T
        gain = cross @ inverse
    updated_state = state + gain @ innovation
    residual_operator = I4 - gain @ H
    # Joseph form retains symmetry/PSD better than P - K S K.T.
    updated_covariance = (
        residual_operator @ covariance @ residual_operator.T + gain @ r @ gain.T
    )
    updated_covariance = (updated_covariance + updated_covariance.T) / 2
    return updated_state, updated_covariance


def track_single_object(
    observations: Sequence[Observation],
    method: Method,
    *,
    acceleration_std_mps2: float = 1.0,
    initial_velocity_std_mps: float = 10.0,
    innovations: list[Innovation] | None = None,
) -> list[TrackEstimate]:
    """Track one object; reject repeated sensor/time pairs as ambiguous."""
    if method not in ("baseline", "kalman"):
        raise SchemaError("method must be baseline or kalman")
    if not math.isfinite(initial_velocity_std_mps) or initial_velocity_std_mps <= 0:
        raise SchemaError("initial_velocity_std_mps must be finite and positive")
    if not math.isfinite(acceleration_std_mps2) or acceleration_std_mps2 < 0:
        raise SchemaError("acceleration_std_mps2 must be finite and nonnegative")
    if not observations:
        return []
    seen_pairs: set[tuple[float, str]] = set()
    previous_time = -1.0
    for observation in observations:
        # Revalidate dataclass instances at the algorithm boundary.
        Observation.from_dict(observation.to_dict())
        pair = (observation.timestamp_s, observation.sensor_id)
        if pair in seen_pairs:
            raise SchemaError(
                "one-object tracker received multiple observations from one sensor at one time"
            )
        if observation.timestamp_s < previous_time:
            raise SchemaError("observations must be in nondecreasing timestamp order")
        seen_pairs.add(pair)
        previous_time = observation.timestamp_s

    first = observations[0]
    state: FloatArray = np.array([first.position_m[0], first.position_m[1], 0.0, 0.0])
    covariance: FloatArray = np.zeros((4, 4))
    covariance[:2, :2] = np.asarray(first.covariance_m2)
    covariance[2:, 2:] = np.eye(2) * initial_velocity_std_mps**2
    config_id = _config_id(method, acceleration_std_mps2, initial_velocity_std_mps)
    result = [_estimate(first.timestamp_s, state, covariance, method, config_id)]
    last_time = first.timestamp_s
    last_position: FloatArray = np.asarray(first.position_m, dtype=float)
    last_r: FloatArray = np.asarray(first.covariance_m2, dtype=float)

    for observation in observations[1:]:
        dt = observation.timestamp_s - last_time
        if method == "kalman":
            f = transition(dt)
            state = f @ state
            covariance = f @ covariance @ f.T + process_covariance(
                dt, acceleration_std_mps2
            )
            state, covariance = _kalman_update(
                state, covariance, observation, innovations=innovations
            )
        else:
            z: FloatArray = np.asarray(observation.position_m, dtype=float)
            r: FloatArray = np.asarray(observation.covariance_m2, dtype=float)
            if dt > 0:
                state[2:] = (z - last_position) / dt
                covariance[2:, 2:] = (r + last_r) / dt**2
            state[:2] = z
            covariance[:2, :2] = r
        result.append(
            _estimate(observation.timestamp_s, state, covariance, method, config_id)
        )
        last_time = observation.timestamp_s
        last_position = np.asarray(observation.position_m, dtype=float)
        last_r = np.asarray(observation.covariance_m2, dtype=float)
    return result
