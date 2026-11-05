"""Tracker-facing file boundary; this module has no simulation or truth imports."""

from __future__ import annotations

from pathlib import Path

from .schema import (
    MAX_JSONL_BYTES,
    Observation,
    SchemaError,
    TrackEstimate,
    canonical_json,
    parse_json,
)


def read_observations(path: Path) -> list[Observation]:
    if path.stat().st_size > MAX_JSONL_BYTES:
        raise SchemaError(f"{path.name} exceeds {MAX_JSONL_BYTES} bytes")
    records: list[Observation] = []
    ids: set[str] = set()
    previous_time = -1.0
    with path.open("r", encoding="utf-8") as stream:
        for line_number, line in enumerate(stream, 1):
            if len(line) > 1_000_000:
                raise SchemaError(f"{path.name}:{line_number}: line exceeds 1 MB")
            try:
                record = Observation.from_dict(parse_json(line))
                if record.timestamp_s < previous_time:
                    raise SchemaError("timestamps must be nondecreasing")
                if record.observation_id in ids:
                    raise SchemaError(
                        f"duplicate observation_id {record.observation_id!r}"
                    )
                ids.add(record.observation_id)
                previous_time = record.timestamp_s
                records.append(record)
            except SchemaError as exc:
                raise SchemaError(f"{path.name}:{line_number}: {exc}") from exc
    return records


def write_tracks(path: Path, records: list[TrackEstimate]) -> None:
    data = "".join(
        canonical_json(record.to_dict()) + "\n" for record in records
    ).encode("utf-8")
    if len(data) > MAX_JSONL_BYTES:
        raise SchemaError("track artifact exceeds 64 MB limit")
    with path.open("xb") as stream:
        stream.write(data)


def read_tracks(path: Path) -> list[TrackEstimate]:
    if path.stat().st_size > MAX_JSONL_BYTES:
        raise SchemaError(f"{path.name} exceeds {MAX_JSONL_BYTES} bytes")
    records: list[TrackEstimate] = []
    previous_time = -1.0
    with path.open("r", encoding="utf-8") as stream:
        for line_number, line in enumerate(stream, 1):
            if len(line) > 1_000_000:
                raise SchemaError(f"{path.name}:{line_number}: line exceeds 1 MB")
            try:
                record = TrackEstimate.from_dict(parse_json(line))
                if record.timestamp_s < previous_time:
                    raise SchemaError("timestamps must be nondecreasing")
                previous_time = record.timestamp_s
                records.append(record)
            except SchemaError as exc:
                raise SchemaError(f"{path.name}:{line_number}: {exc}") from exc
    return records
