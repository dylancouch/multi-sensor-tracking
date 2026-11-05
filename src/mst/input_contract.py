"""Explicit, versioned contracts for Cartesian CSV observation sources."""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any

from .schema import Observation, SchemaError, _covariance, _name, _number, _record

_UNITS = {"m": 1.0, "km": 1000.0, "ft": 0.3048}
_TIME_UNITS = {"s": 1.0, "ms": 0.001, "h": 3600.0}


@dataclass(frozen=True)
class InputContract:
    """A source-specific conversion into version 1 world-frame observations."""

    raw: dict[str, Any]
    source_id: str
    sensor_id: str
    fields: tuple[str, str, str, str]
    time_scale: float
    time_origin_s: float
    position_scale: float
    rotation: tuple[tuple[float, float], tuple[float, float]]
    translation_m: tuple[float, float]
    input_covariance: tuple[tuple[float, float], tuple[float, float]]

    @classmethod
    def from_dict(cls, value: Any) -> InputContract:
        keys = {
            "schema_version",
            "source_id",
            "source_kind",
            "measurement_type",
            "input_format",
            "sensor_id",
            "time",
            "position",
            "uncertainty",
        }
        if isinstance(value, dict) and "transform" in value:
            keys.add("transform")
        data = _record(value, "input contract", keys)
        if type(data["schema_version"]) is not int or data["schema_version"] != 1:
            raise SchemaError("unsupported input contract schema_version; expected 1")
        source_id = _name(data["source_id"], "source_id")
        sensor_id = _name(data["sensor_id"], "sensor_id")
        if data["source_kind"] not in ("generated", "recorded", "live"):
            raise SchemaError("source_kind must be generated, recorded, or live")
        if data["measurement_type"] != "cartesian_position_2d":
            raise SchemaError(
                "measurement_type requires a supported explicit measurement model; only cartesian_position_2d is supported"
            )
        if data["input_format"] != "csv":
            raise SchemaError("input contract currently supports CSV only")
        time = _record(data["time"], "time", {"field", "unit", "basis", "origin_s"})
        position = _record(
            data["position"], "position", {"x_field", "y_field", "unit", "frame"}
        )
        fields = (
            _name(time["field"], "CSV time field"),
            "observation_id",
            _name(position["x_field"], "CSV x field"),
            _name(position["y_field"], "CSV y field"),
        )
        if len(set(fields)) != 4:
            raise SchemaError("CSV fields must be distinct")
        if not isinstance(time["unit"], str) or time["unit"] not in _TIME_UNITS:
            raise SchemaError("unsupported time unit")
        if time["basis"] not in ("elapsed", "unix"):
            raise SchemaError("time basis must be elapsed or unix")
        origin = _number(time["origin_s"], "time origin_s", minimum=0)
        if time["basis"] == "elapsed" and origin != 0:
            raise SchemaError("elapsed time requires origin_s 0")
        if time["basis"] == "unix" and origin == 0:
            raise SchemaError("unix time requires an explicit nonzero origin_s")
        if not isinstance(position["unit"], str) or position["unit"] not in _UNITS:
            raise SchemaError("unsupported position unit")
        frame = _name(position["frame"], "position frame")
        transform = data.get("transform")
        if frame == "world":
            if transform is not None:
                raise SchemaError("world-frame input must omit transform")
            rotation = ((1.0, 0.0), (0.0, 1.0))
            translation = (0.0, 0.0)
        else:
            if transform is None:
                raise SchemaError(
                    "sensor-local frame requires an explicit transform to world"
                )
            transform = _record(
                transform, "transform", {"target_frame", "rotation", "translation_m"}
            )
            if transform["target_frame"] != "world":
                raise SchemaError("transform target_frame must be world")
            rotation = _matrix(transform["rotation"], "rotation")
            translation = _pair(transform["translation_m"], "translation_m")
            r = rotation
            if not (
                math.isclose(sum(r[0][i] ** 2 for i in range(2)), 1, abs_tol=1e-9)
                and math.isclose(sum(r[1][i] ** 2 for i in range(2)), 1, abs_tol=1e-9)
                and math.isclose(
                    sum(r[0][i] * r[1][i] for i in range(2)), 0, abs_tol=1e-9
                )
                and math.isclose(r[0][0] * r[1][1] - r[0][1] * r[1][0], 1, abs_tol=1e-9)
            ):
                raise SchemaError("rotation must be a proper orthonormal 2D rotation")
        uncertainty = data["uncertainty"]
        if not isinstance(uncertainty, dict) or "kind" not in uncertainty:
            raise SchemaError("uncertainty must declare a kind")
        if uncertainty["kind"] == "isotropic_std":
            uncertainty = _record(uncertainty, "uncertainty", {"kind", "std", "unit"})
            std = _number(uncertainty["std"], "uncertainty std", minimum=0)
            if not math.isfinite(std * std):
                raise SchemaError("uncertainty variance must be finite")
            input_covariance = ((std * std, 0.0), (0.0, std * std))
        elif uncertainty["kind"] == "fixed_covariance":
            uncertainty = _record(
                uncertainty, "uncertainty", {"kind", "matrix", "unit"}
            )
            input_covariance = _covariance(uncertainty["matrix"])
        else:
            raise SchemaError("unsupported uncertainty kind")
        if uncertainty["unit"] != position["unit"]:
            raise SchemaError("uncertainty unit must match position unit")
        return cls(
            data,
            source_id,
            sensor_id,
            fields,
            _TIME_UNITS[time["unit"]],
            origin,
            _UNITS[position["unit"]],
            rotation,
            translation,
            input_covariance,
        )

    def convert(
        self, timestamp: float, observation_id: str, x: float, y: float
    ) -> Observation:
        t = _number(timestamp, "timestamp") * self.time_scale - self.time_origin_s
        x, y = _number(x, "x"), _number(y, "y")
        r, scale = self.rotation, self.position_scale
        px = scale * (r[0][0] * x + r[0][1] * y) + self.translation_m[0]
        py = scale * (r[1][0] * x + r[1][1] * y) + self.translation_m[1]
        c = self.input_covariance
        a = r[0][0] * c[0][0] + r[0][1] * c[1][0]
        b = r[0][0] * c[0][1] + r[0][1] * c[1][1]
        d = r[1][0] * c[0][0] + r[1][1] * c[1][0]
        e = r[1][0] * c[0][1] + r[1][1] * c[1][1]
        factor = scale * scale
        covariance = [
            [
                factor * (a * r[0][0] + b * r[0][1]),
                factor * (a * r[1][0] + b * r[1][1]),
            ],
            [
                factor * (d * r[0][0] + e * r[0][1]),
                factor * (d * r[1][0] + e * r[1][1]),
            ],
        ]
        return Observation.from_dict(
            {
                "schema_version": 1,
                "timestamp_s": t,
                "observation_id": observation_id,
                "sensor_id": self.sensor_id,
                "position_m": [px, py],
                "covariance_m2": covariance,
                "frame": "world",
                "time_unit": "s",
            }
        )


def _pair(value: Any, name: str) -> tuple[float, float]:
    if not isinstance(value, list) or len(value) != 2:
        raise SchemaError(f"{name} must contain two numbers")
    return _number(value[0], name), _number(value[1], name)


def _matrix(value: Any, name: str) -> tuple[tuple[float, float], tuple[float, float]]:
    if not isinstance(value, list) or len(value) != 2:
        raise SchemaError(f"{name} must be a 2x2 matrix")
    return _pair(value[0], name), _pair(value[1], name)
