"""Versioned, tracker-facing association decisions for run inspection."""

from __future__ import annotations

import math
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from .schema import (
    MAX_JSONL_BYTES,
    Observation,
    SchemaError,
    TrackEstimate,
    _name,
    _number,
    _record,
    canonical_json,
    parse_json,
)

KINDS = frozenset({"match", "rejected", "birth", "confirm", "delete"})
REASONS = frozenset(
    {"accepted", "gated", "assigned_elsewhere", "unmatched", "confirmed", "missed"}
)


@dataclass(frozen=True)
class AssociationEvent:
    schema_version: int
    timestamp_s: float
    kind: str
    track_id: str
    observation_id: str | None
    sensor_id: str | None
    distance_squared: float | None
    gate_squared: float | None
    reason: str

    @classmethod
    def from_dict(cls, value: Any) -> AssociationEvent:
        data = _record(value, "association event", set(cls.__dataclass_fields__))
        if type(data["schema_version"]) is not int or data["schema_version"] != 1:
            raise SchemaError("unsupported association event schema_version")
        kind = data["kind"]
        reason = data["reason"]
        if (
            type(kind) is not str
            or type(reason) is not str
            or kind not in KINDS
            or reason not in REASONS
        ):
            raise SchemaError("unknown association event kind or reason")
        expected = {
            "match": "accepted",
            "birth": "unmatched",
            "confirm": "confirmed",
            "delete": "missed",
        }
        if kind in expected and reason != expected[kind]:
            raise SchemaError("association event kind and reason disagree")
        if kind == "rejected" and reason not in ("gated", "assigned_elsewhere"):
            raise SchemaError("rejected candidate needs a gate or assignment reason")
        has_observation = kind in ("match", "rejected", "birth")
        observation_id = data["observation_id"]
        sensor_id = data["sensor_id"]
        if has_observation != (observation_id is not None and sensor_id is not None):
            raise SchemaError("association event observation fields disagree with kind")
        if not has_observation and (
            observation_id is not None or sensor_id is not None
        ):
            raise SchemaError("lifecycle event cannot reference an observation")
        scored = kind in ("match", "rejected")
        distance = data["distance_squared"]
        gate = data["gate_squared"]
        if scored != (gate is not None):
            raise SchemaError("candidate event requires gate_squared")
        if scored and reason != "gated" and distance is None:
            raise SchemaError("non-gated candidate requires distance_squared")
        if not scored and distance is not None:
            raise SchemaError("lifecycle event cannot have distance_squared")
        result = cls(
            1,
            _number(data["timestamp_s"], "timestamp_s", minimum=0),
            kind,
            _name(data["track_id"], "track_id"),
            _name(observation_id, "observation_id")
            if observation_id is not None
            else None,
            _name(sensor_id, "sensor_id") if sensor_id is not None else None,
            _number(distance, "distance_squared", minimum=0)
            if distance is not None
            else None,
            _number(gate, "gate_squared", minimum=0) if gate is not None else None,
            reason,
        )
        if result.gate_squared is not None and result.gate_squared <= 0:
            raise SchemaError("gate_squared must be positive")
        if (
            result.kind == "match"
            and result.distance_squared is not None
            and result.gate_squared is not None
            and result.distance_squared > result.gate_squared
        ):
            raise SchemaError("accepted match is outside the gate")
        if (
            result.kind == "rejected"
            and result.reason == "gated"
            and result.distance_squared is not None
            and result.gate_squared is not None
            and result.distance_squared <= result.gate_squared
        ):
            raise SchemaError("gated candidate is inside the gate")
        if (
            result.kind == "rejected"
            and result.reason == "assigned_elsewhere"
            and result.distance_squared is not None
            and result.gate_squared is not None
            and result.distance_squared > result.gate_squared
        ):
            raise SchemaError("assignment-rejected candidate is outside the gate")
        return result

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def event(
    timestamp_s: float,
    kind: str,
    track_id: str,
    *,
    observation: Observation | None = None,
    distance_squared: float | None = None,
    gate_squared: float | None = None,
    reason: str,
) -> AssociationEvent:
    if distance_squared is not None and not math.isfinite(distance_squared):
        distance_squared = None
    return AssociationEvent.from_dict(
        {
            "schema_version": 1,
            "timestamp_s": timestamp_s,
            "kind": kind,
            "track_id": track_id,
            "observation_id": observation.observation_id if observation else None,
            "sensor_id": observation.sensor_id if observation else None,
            "distance_squared": distance_squared,
            "gate_squared": gate_squared,
            "reason": reason,
        }
    )


def validate_links(
    events: list[AssociationEvent],
    observations: list[Observation],
    tracks: list[TrackEstimate],
) -> None:
    observation_by_id = {item.observation_id: item for item in observations}
    track_at_time = {(item.timestamp_s, item.track_id): item for item in tracks}
    if len(observation_by_id) != len(observations):
        raise SchemaError("duplicate observation_id")
    if not tracks and events:
        raise SchemaError("association events require tracks")
    seen_events: set[tuple[float, str, str, str | None]] = set()
    decisions: dict[str, str] = {}
    for item in events:
        AssociationEvent.from_dict(item.to_dict())
        event_key = (item.timestamp_s, item.kind, item.track_id, item.observation_id)
        if event_key in seen_events:
            raise SchemaError("duplicate association event")
        seen_events.add(event_key)
        track = track_at_time.get((item.timestamp_s, item.track_id))
        if track is None or track.method != "multi-kalman":
            raise SchemaError(
                "association event does not reference a multi-kalman track at its timestamp"
            )
        if item.kind == "delete" and track.lifecycle != "deleted":
            raise SchemaError("delete event disagrees with track lifecycle")
        if item.kind == "confirm" and track.lifecycle != "confirmed":
            raise SchemaError("confirm event disagrees with track lifecycle")
        if item.observation_id is not None:
            observation = observation_by_id.get(item.observation_id)
            if (
                observation is None
                or observation.timestamp_s != item.timestamp_s
                or observation.sensor_id != item.sensor_id
            ):
                raise SchemaError("association event does not match its observation")
            if item.kind in ("match", "birth"):
                if item.observation_id in decisions:
                    raise SchemaError("duplicate association decision for observation")
                decisions[item.observation_id] = item.kind
    if set(decisions) != set(observation_by_id):
        raise SchemaError(
            "association events must decide every observation exactly once"
        )


def write_events(path: Path, records: list[AssociationEvent]) -> None:
    data = "".join(canonical_json(item.to_dict()) + "\n" for item in records).encode(
        "utf-8"
    )
    if len(data) > MAX_JSONL_BYTES:
        raise SchemaError("association event artifact exceeds 64 MB limit")
    created = False
    try:
        with path.open("xb") as stream:
            created = True
            stream.write(data)
    except Exception:
        if created:
            path.unlink(missing_ok=True)
        raise


def read_events(path: Path) -> list[AssociationEvent]:
    if path.stat().st_size > MAX_JSONL_BYTES:
        raise SchemaError(f"{path.name} exceeds {MAX_JSONL_BYTES} bytes")
    records: list[AssociationEvent] = []
    previous_time = -1.0
    with path.open("r", encoding="utf-8") as stream:
        for line_number, line in enumerate(stream, 1):
            if len(line) > 1_000_000:
                raise SchemaError(f"{path.name}:{line_number}: line exceeds 1 MB")
            try:
                item = AssociationEvent.from_dict(parse_json(line))
                if item.timestamp_s < previous_time:
                    raise SchemaError("timestamps must be nondecreasing")
                records.append(item)
                previous_time = item.timestamp_s
            except SchemaError as exc:
                raise SchemaError(f"{path.name}:{line_number}: {exc}") from exc
    return records
