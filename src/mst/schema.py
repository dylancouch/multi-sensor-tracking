"""Version 1 data contracts. All positions are world-frame meters and times seconds."""

from __future__ import annotations

import hashlib
import json
import math
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, TypeAlias, cast

import numpy as np

VERSION = 1
MANIFEST_VERSION = 2
MAX_JSON_BYTES = 1_000_000
MAX_JSONL_BYTES = 64_000_000
JsonDict: TypeAlias = dict[str, Any]


class SchemaError(ValueError):
    """An input is incompatible with the declared data contract."""


def _record(value: Any, name: str, keys: set[str]) -> JsonDict:
    if not isinstance(value, dict) or set(value) != keys:
        raise SchemaError(f"{name} must contain exactly: {', '.join(sorted(keys))}")
    return value


def _version(value: Any) -> None:
    if type(value) is not int or value != VERSION:
        raise SchemaError(f"unsupported schema_version {value!r}; expected {VERSION}")


def _number(value: Any, name: str, *, minimum: float | None = None) -> float:
    if type(value) not in (int, float) or not math.isfinite(value):
        raise SchemaError(f"{name} must be a finite number")
    result = float(value)
    if minimum is not None and result < minimum:
        raise SchemaError(f"{name} must be >= {minimum}")
    return result


def _positive(value: Any, name: str) -> float:
    result = _number(value, name)
    if result <= 0:
        raise SchemaError(f"{name} must be positive")
    return result


def _name(value: Any, name: str) -> str:
    if (
        not isinstance(value, str)
        or not value
        or not value.isascii()
        or not all(c.isalnum() or c in "_-" for c in value)
    ):
        raise SchemaError(f"{name} must be a nonempty ASCII identifier")
    return value


def _vector(value: Any, length: int, name: str) -> tuple[float, ...]:
    if not isinstance(value, list) or len(value) != length:
        raise SchemaError(f"{name} must be a {length}-element array")
    return tuple(_number(item, name) for item in value)


def _covariance(value: Any) -> tuple[tuple[float, float], tuple[float, float]]:
    if not isinstance(value, list) or len(value) != 2:
        raise SchemaError("covariance_m2 must be a 2x2 array")
    rows = [_vector(row, 2, "covariance_m2 row") for row in value]
    a, b = rows[0]
    c, d = rows[1]
    scale = max(1.0, abs(a), abs(b), abs(c), abs(d))
    tol = 1e-10 * scale
    if abs(b - c) > tol or a < -tol or d < -tol or a * d - b * c < -tol * scale:
        raise SchemaError("covariance_m2 must be symmetric positive semidefinite")
    return ((a, b), (c, d))


def _exact(value: Any, expected: str, name: str) -> str:
    if value != expected:
        raise SchemaError(f"{name} must be {expected!r}")
    return expected


def _steps(interval: float, step: float, name: str) -> int:
    ratio = interval / step
    count = round(ratio)
    if count < 1 or not math.isclose(ratio, count, rel_tol=0, abs_tol=1e-9):
        raise SchemaError(f"{name} must be a positive integer multiple of step_s")
    return count


@dataclass(frozen=True)
class ObjectConfig:
    object_id: str
    initial_state: tuple[float, ...]

    @classmethod
    def from_dict(cls, value: Any) -> ObjectConfig:
        data = _record(value, "object", {"object_id", "initial_state"})
        return cls(
            _name(data["object_id"], "object_id"),
            _vector(data["initial_state"], 4, "initial_state"),
        )

    def to_dict(self) -> JsonDict:
        return cast(JsonDict, json.loads(json.dumps(asdict(self))))


@dataclass(frozen=True)
class SensorConfig:
    sensor_id: str
    sample_interval_s: float
    noise_std_m: float
    miss_probability: float = 0.0
    false_alarm_probability: float = 0.0
    false_alarm_bounds_m: tuple[float, float, float, float] = (-10.0, -10.0, 10.0, 10.0)
    timestamp_offset_s: float = 0.0

    @classmethod
    def from_dict(cls, value: Any, step_s: float) -> SensorConfig:
        required = {"sensor_id", "sample_interval_s", "noise_std_m"}
        optional = {
            "miss_probability",
            "false_alarm_probability",
            "false_alarm_bounds_m",
            "timestamp_offset_s",
        }
        if (
            not isinstance(value, dict)
            or not required <= set(value)
            or not set(value) <= required | optional
        ):
            raise SchemaError(
                "sensor must contain sensor_id, sample_interval_s, noise_std_m and only supported optional fields"
            )
        data = value
        interval = _positive(data["sample_interval_s"], "sample_interval_s")
        _steps(interval, step_s, "sample_interval_s")
        noise_std = _number(data["noise_std_m"], "noise_std_m", minimum=0)
        if not math.isfinite(noise_std * noise_std):
            raise SchemaError("noise_std_m squared must be finite")
        miss_probability = _number(
            data.get("miss_probability", 0), "miss_probability", minimum=0
        )
        false_alarm_probability = _number(
            data.get("false_alarm_probability", 0), "false_alarm_probability", minimum=0
        )
        if miss_probability > 1 or false_alarm_probability > 1:
            raise SchemaError("sensor probabilities must be <= 1")
        bounds = _vector(
            data.get("false_alarm_bounds_m", [-10, -10, 10, 10]),
            4,
            "false_alarm_bounds_m",
        )
        if bounds[0] >= bounds[2] or bounds[1] >= bounds[3]:
            raise SchemaError(
                "false_alarm_bounds_m must have increasing x and y limits"
            )
        offset = _number(
            data.get("timestamp_offset_s", 0), "timestamp_offset_s", minimum=0
        )
        return cls(
            _name(data["sensor_id"], "sensor_id"),
            interval,
            noise_std,
            miss_probability,
            false_alarm_probability,
            (bounds[0], bounds[1], bounds[2], bounds[3]),
            offset,
        )

    def to_dict(self) -> JsonDict:
        return cast(JsonDict, json.loads(json.dumps(asdict(self))))


@dataclass(frozen=True)
class Scenario:
    schema_version: int
    frame: str
    position_unit: str
    velocity_unit: str
    time_unit: str
    duration_s: float
    step_s: float
    objects: tuple[ObjectConfig, ...]
    sensors: tuple[SensorConfig, ...]

    @classmethod
    def from_dict(cls, value: Any) -> Scenario:
        keys = {
            "schema_version",
            "frame",
            "position_unit",
            "velocity_unit",
            "time_unit",
            "duration_s",
            "step_s",
            "objects",
            "sensors",
        }
        data = _record(value, "scenario", keys)
        _version(data["schema_version"])
        step = _positive(data["step_s"], "step_s")
        duration = _positive(data["duration_s"], "duration_s")
        n_steps = _steps(duration, step, "duration_s")
        if n_steps > 100_000:
            raise SchemaError("duration_s permits at most 100000 steps")
        if (
            not isinstance(data["objects"], list)
            or not 1 <= len(data["objects"]) <= 100
        ):
            raise SchemaError("objects must contain 1 to 100 entries")
        if not isinstance(data["sensors"], list) or not 1 <= len(data["sensors"]) <= 16:
            raise SchemaError("sensors must contain 1 to 16 entries")
        objects = tuple(ObjectConfig.from_dict(item) for item in data["objects"])
        sensors = tuple(SensorConfig.from_dict(item, step) for item in data["sensors"])
        for obj in objects:
            px, py, vx, vy = obj.initial_state
            if not math.isfinite(px + vx * duration) or not math.isfinite(
                py + vy * duration
            ):
                raise SchemaError(
                    f"object {obj.object_id} has non-finite terminal position"
                )
        if any(
            not math.isfinite(duration + sensor.timestamp_offset_s)
            for sensor in sensors
        ):
            raise SchemaError("sensor timestamp offset yields non-finite timestamp")
        estimated_truth = (n_steps + 1) * len(objects)
        estimated_observations = sum(
            (n_steps // _steps(sensor.sample_interval_s, step, "sample_interval_s") + 1)
            * (len(objects) + (1 if sensor.false_alarm_probability > 0 else 0))
            for sensor in sensors
        )
        if estimated_truth > 100_000 or estimated_observations > 100_000:
            raise SchemaError(
                "scenario permits at most 100000 truth and observation records each"
            )
        if len({item.object_id for item in objects}) != len(objects):
            raise SchemaError("duplicate object_id")
        if len({item.sensor_id for item in sensors}) != len(sensors):
            raise SchemaError("duplicate sensor_id")
        return cls(
            VERSION,
            _exact(data["frame"], "world", "frame"),
            _exact(data["position_unit"], "m", "position_unit"),
            _exact(data["velocity_unit"], "m/s", "velocity_unit"),
            _exact(data["time_unit"], "s", "time_unit"),
            duration,
            step,
            objects,
            sensors,
        )

    def to_dict(self) -> JsonDict:
        return cast(JsonDict, json.loads(json.dumps(asdict(self))))


@dataclass(frozen=True)
class Truth:
    schema_version: int
    timestamp_s: float
    object_id: str
    state: tuple[float, ...]
    frame: str
    position_unit: str
    velocity_unit: str

    @classmethod
    def from_dict(cls, value: Any) -> Truth:
        data = _record(
            value,
            "truth",
            {
                "schema_version",
                "timestamp_s",
                "object_id",
                "state",
                "frame",
                "position_unit",
                "velocity_unit",
            },
        )
        _version(data["schema_version"])
        return cls(
            VERSION,
            _number(data["timestamp_s"], "timestamp_s", minimum=0),
            _name(data["object_id"], "object_id"),
            _vector(data["state"], 4, "state"),
            _exact(data["frame"], "world", "frame"),
            _exact(data["position_unit"], "m", "position_unit"),
            _exact(data["velocity_unit"], "m/s", "velocity_unit"),
        )

    def to_dict(self) -> JsonDict:
        return cast(JsonDict, json.loads(json.dumps(asdict(self))))


@dataclass(frozen=True)
class Observation:
    schema_version: int
    timestamp_s: float
    observation_id: str
    sensor_id: str
    position_m: tuple[float, ...]
    covariance_m2: tuple[tuple[float, float], tuple[float, float]]
    frame: str
    time_unit: str

    @classmethod
    def from_dict(cls, value: Any) -> Observation:
        data = _record(
            value,
            "observation",
            {
                "schema_version",
                "timestamp_s",
                "observation_id",
                "sensor_id",
                "position_m",
                "covariance_m2",
                "frame",
                "time_unit",
            },
        )
        _version(data["schema_version"])
        return cls(
            VERSION,
            _number(data["timestamp_s"], "timestamp_s", minimum=0),
            _name(data["observation_id"], "observation_id"),
            _name(data["sensor_id"], "sensor_id"),
            _vector(data["position_m"], 2, "position_m"),
            _covariance(data["covariance_m2"]),
            _exact(data["frame"], "world", "frame"),
            _exact(data["time_unit"], "s", "time_unit"),
        )

    def to_dict(self) -> JsonDict:
        return cast(JsonDict, json.loads(json.dumps(asdict(self))))


@dataclass(frozen=True)
class TrackEstimate:
    schema_version: int
    timestamp_s: float
    track_id: str
    state: tuple[float, ...]
    covariance: tuple[tuple[float, ...], ...]
    lifecycle: str
    method: str
    config_id: str
    frame: str
    position_unit: str
    velocity_unit: str

    @classmethod
    def from_dict(cls, value: Any) -> TrackEstimate:
        data = _record(
            value,
            "track estimate",
            {
                "schema_version",
                "timestamp_s",
                "track_id",
                "state",
                "covariance",
                "lifecycle",
                "method",
                "config_id",
                "frame",
                "position_unit",
                "velocity_unit",
            },
        )
        _version(data["schema_version"])
        raw = data["covariance"]
        if not isinstance(raw, list) or len(raw) != 4:
            raise SchemaError("covariance must be a 4x4 array")
        covariance = tuple(_vector(row, 4, "covariance row") for row in raw)
        matrix = np.asarray(covariance, dtype=float)
        scale = max(1.0, float(np.max(np.abs(matrix))))
        tolerance = 1e-10 * scale
        if (
            not np.allclose(matrix, matrix.T, rtol=0, atol=tolerance)
            or float(np.min(np.linalg.eigvalsh((matrix + matrix.T) / 2))) < -tolerance
        ):
            raise SchemaError("covariance must be symmetric positive semidefinite")
        if data["lifecycle"] not in ("active", "tentative", "confirmed", "deleted"):
            raise SchemaError(
                "lifecycle must be active, tentative, confirmed, or deleted"
            )
        if data["method"] not in ("baseline", "kalman", "multi-kalman"):
            raise SchemaError("method must be baseline, kalman, or multi-kalman")
        return cls(
            VERSION,
            _number(data["timestamp_s"], "timestamp_s", minimum=0),
            _name(data["track_id"], "track_id"),
            _vector(data["state"], 4, "state"),
            covariance,
            data["lifecycle"],
            data["method"],
            _name(data["config_id"], "config_id"),
            _exact(data["frame"], "world", "frame"),
            _exact(data["position_unit"], "m", "position_unit"),
            _exact(data["velocity_unit"], "m/s", "velocity_unit"),
        )

    def to_dict(self) -> JsonDict:
        return cast(JsonDict, json.loads(json.dumps(asdict(self))))


@dataclass(frozen=True)
class Manifest:
    schema_version: int
    generator_version: str
    seed: int
    sensor_seeds: dict[str, int]
    scenario: Scenario
    artifacts: dict[str, str]
    sha256: dict[str, str]
    counts: dict[str, int]
    software_revision: str | None = None
    source_dirty: bool | None = None
    environment: dict[str, Any] | None = None
    scenario_sha256: str | None = None

    @classmethod
    def from_dict(cls, value: Any) -> Manifest:
        if not isinstance(value, dict):
            raise SchemaError("manifest must be a JSON object")
        version = value.get("schema_version")
        if type(version) is not int or version not in (1, MANIFEST_VERSION):
            raise SchemaError(f"unsupported manifest schema_version {version!r}")
        keys = {
            "schema_version",
            "generator_version",
            "seed",
            "sensor_seeds",
            "scenario",
            "artifacts",
            "sha256",
            "counts",
        }
        if version == MANIFEST_VERSION:
            keys |= {
                "software_revision",
                "source_dirty",
                "environment",
                "scenario_sha256",
            }
        data = _record(value, "manifest", keys)
        scenario = Scenario.from_dict(data["scenario"])
        if (
            not isinstance(data["generator_version"], str)
            or not data["generator_version"]
        ):
            raise SchemaError("generator_version must be nonempty")
        if type(data["seed"]) is not int or not 0 <= data["seed"] < 2**64:
            raise SchemaError("seed must be a 64-bit unsigned integer")
        seeds = data["sensor_seeds"]
        if (
            not isinstance(seeds, dict)
            or set(seeds) != {s.sensor_id for s in scenario.sensors}
            or any(type(v) is not int or not 0 <= v < 2**64 for v in seeds.values())
        ):
            raise SchemaError(
                "sensor_seeds must contain one unsigned 64-bit seed per sensor"
            )
        artifacts = _record(data["artifacts"], "artifacts", {"truth", "observations"})
        if artifacts != {"truth": "truth.jsonl", "observations": "observations.jsonl"}:
            raise SchemaError(
                "artifact filenames must be truth.jsonl and observations.jsonl"
            )
        hashes = _record(data["sha256"], "sha256", {"truth", "observations"})
        if any(
            not isinstance(v, str)
            or len(v) != 64
            or any(c not in "0123456789abcdef" for c in v)
            for v in hashes.values()
        ):
            raise SchemaError("sha256 entries must be lowercase hex digests")
        counts = _record(data["counts"], "counts", {"truth", "observations"})
        if any(type(v) is not int or v < 0 for v in counts.values()):
            raise SchemaError("counts must be nonnegative integers")
        revision: str | None = None
        dirty: bool | None = None
        environment: dict[str, Any] | None = None
        scenario_hash: str | None = None
        if version == MANIFEST_VERSION:
            revision = data["software_revision"]
            dirty = data["source_dirty"]
            if revision is not None and (
                not isinstance(revision, str)
                or len(revision) not in (40, 64)
                or any(c not in "0123456789abcdef" for c in revision)
            ):
                raise SchemaError(
                    "software_revision must be a Git hex revision or null"
                )
            if dirty is not None and type(dirty) is not bool:
                raise SchemaError("source_dirty must be boolean or null")
            environment = _record(
                data["environment"],
                "environment",
                {
                    "python",
                    "architecture",
                    "logical_cpus",
                    "platform",
                    "numpy",
                    "scipy",
                },
            )
            if any(
                not isinstance(environment[key], str) or not environment[key]
                for key in ("python", "architecture", "platform", "numpy", "scipy")
            ):
                raise SchemaError("environment versions must be nonempty strings")
            cpus = environment["logical_cpus"]
            if cpus is not None and (type(cpus) is not int or cpus < 1):
                raise SchemaError("logical_cpus must be positive or null")
            scenario_hash = hashlib.sha256(
                canonical_json(scenario.to_dict()).encode()
            ).hexdigest()
            if data["scenario_sha256"] != scenario_hash:
                raise SchemaError("scenario_sha256 does not match scenario")
        return cls(
            version,
            data["generator_version"],
            data["seed"],
            seeds,
            scenario,
            artifacts,
            hashes,
            counts,
            revision,
            dirty,
            environment,
            scenario_hash,
        )

    def to_dict(self) -> JsonDict:
        value = cast(JsonDict, json.loads(json.dumps(asdict(self))))
        if self.schema_version == 1:
            for key in (
                "software_revision",
                "source_dirty",
                "environment",
                "scenario_sha256",
            ):
                value.pop(key)
        return value


def _unique_pairs(pairs: list[tuple[str, Any]]) -> JsonDict:
    result: JsonDict = {}
    for key, value in pairs:
        if key in result:
            raise SchemaError(f"duplicate JSON key: {key}")
        result[key] = value
    return result


def parse_json(data: str) -> Any:
    try:
        return json.loads(
            data,
            object_pairs_hook=_unique_pairs,
            parse_constant=lambda x: (_ for _ in ()).throw(
                SchemaError(f"non-finite JSON value: {x}")
            ),
        )
    except SchemaError:
        raise
    except (ValueError, UnicodeError, RecursionError) as exc:
        raise SchemaError(f"invalid JSON: {exc}") from exc


def read_json(path: Path) -> Any:
    if path.stat().st_size > MAX_JSON_BYTES:
        raise SchemaError(f"{path.name} exceeds {MAX_JSON_BYTES} bytes")
    return parse_json(path.read_text(encoding="utf-8"))


def canonical_json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False)
