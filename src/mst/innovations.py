"""Versioned, observation-linked Kalman innovation diagnostics."""

from __future__ import annotations

import json
import math
from collections.abc import Sequence
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

import numpy as np

from .schema import (
    MAX_JSONL_BYTES,
    SchemaError,
    _covariance,
    _name,
    _number,
    _record,
    _vector,
    canonical_json,
    parse_json,
)


@dataclass(frozen=True)
class Innovation:
    schema_version: int
    timestamp_s: float
    track_id: str
    observation_id: str
    sensor_id: str
    residual_m: tuple[float, ...]
    covariance_m2: tuple[tuple[float, float], tuple[float, float]]
    nis: float | None

    @classmethod
    def from_dict(cls, value: Any) -> Innovation:
        data = _record(
            value,
            "innovation",
            {
                "schema_version",
                "timestamp_s",
                "track_id",
                "observation_id",
                "sensor_id",
                "residual_m",
                "covariance_m2",
                "nis",
            },
        )
        if type(data["schema_version"]) is not int or data["schema_version"] != 1:
            raise SchemaError("unsupported innovation schema_version")
        residual = _vector(data["residual_m"], 2, "residual_m")
        covariance = _covariance(data["covariance_m2"])
        expected = normalized_innovation_squared(residual, covariance)
        recorded = data["nis"]
        if expected is None:
            if recorded is not None:
                raise SchemaError("singular innovation covariance requires null nis")
        elif recorded is None or not math.isclose(
            _number(recorded, "nis", minimum=0), expected, rel_tol=1e-8, abs_tol=1e-9
        ):
            raise SchemaError("nis disagrees with residual and covariance")
        return cls(
            1,
            _number(data["timestamp_s"], "timestamp_s", minimum=0),
            _name(data["track_id"], "track_id"),
            _name(data["observation_id"], "observation_id"),
            _name(data["sensor_id"], "sensor_id"),
            residual,
            covariance,
            expected,
        )

    def to_dict(self) -> dict[str, Any]:
        return json.loads(json.dumps(asdict(self)))


def normalized_innovation_squared(
    residual: Sequence[float],
    covariance: Sequence[Sequence[float]],
) -> float | None:
    """Return r.T S^-1 r for positive-definite S; skip singular S."""
    matrix = np.asarray(covariance, dtype=float)
    try:
        factor = np.linalg.cholesky(matrix)
    except np.linalg.LinAlgError:
        return None
    solved = np.linalg.solve(factor, np.asarray(residual, dtype=float))
    result = float(solved @ solved)
    return result if math.isfinite(result) else None


def make_innovation(
    timestamp_s: float,
    track_id: str,
    observation_id: str,
    sensor_id: str,
    residual: np.ndarray,
    covariance: np.ndarray,
) -> Innovation:
    data = {
        "schema_version": 1,
        "timestamp_s": timestamp_s,
        "track_id": track_id,
        "observation_id": observation_id,
        "sensor_id": sensor_id,
        "residual_m": residual.tolist(),
        "covariance_m2": covariance.tolist(),
    }
    data["nis"] = normalized_innovation_squared(
        tuple(data["residual_m"]), tuple(tuple(row) for row in data["covariance_m2"])
    )
    return Innovation.from_dict(data)


def write_innovations(path: Path, records: list[Innovation]) -> None:
    data = "".join(
        canonical_json(record.to_dict()) + "\n" for record in records
    ).encode()
    if len(data) > MAX_JSONL_BYTES:
        raise SchemaError("innovation artifact exceeds 64 MB limit")
    with path.open("xb") as stream:
        stream.write(data)


def read_innovations(path: Path) -> list[Innovation]:
    if path.stat().st_size > MAX_JSONL_BYTES:
        raise SchemaError(f"{path.name} exceeds {MAX_JSONL_BYTES} bytes")
    records: list[Innovation] = []
    seen: set[str] = set()
    previous_time = -1.0
    with path.open("r", encoding="utf-8") as stream:
        for line_number, line in enumerate(stream, 1):
            if len(line) > 1_000_000:
                raise SchemaError(f"{path.name}:{line_number}: line exceeds 1 MB")
            try:
                record = Innovation.from_dict(parse_json(line))
                if record.timestamp_s < previous_time:
                    raise SchemaError("timestamps must be nondecreasing")
                if record.observation_id in seen:
                    raise SchemaError("duplicate innovation observation_id")
                seen.add(record.observation_id)
                previous_time = record.timestamp_s
                records.append(record)
            except SchemaError as exc:
                raise SchemaError(f"{path.name}:{line_number}: {exc}") from exc
    return records
