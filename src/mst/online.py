"""Bounded, deterministic online tracking of version 1 observation JSONL."""

from __future__ import annotations

import hashlib
import heapq
import json
import math
import sys
from collections.abc import Iterable, Iterator
from pathlib import Path
from typing import Any, TextIO

from .association import AssociationState, track_multiple_objects
from .schema import (
    MAX_JSONL_BYTES,
    Observation,
    SchemaError,
    TrackEstimate,
    _name,
    _positive,
    canonical_json,
    parse_json,
    read_json,
)


def _source_record(path: Path, input_path: Path | None) -> dict[str, Any]:
    value = read_json(path)
    if not isinstance(value, dict):
        raise SchemaError("source record must be an object")
    if type(value.get("schema_version")) is not int or value["schema_version"] not in (
        1,
        2,
    ):
        raise SchemaError("source record schema_version must be 1 or 2")
    _name(value.get("source_label"), "source_label")
    if value.get("source_kind") not in ("generated", "recorded", "live"):
        raise SchemaError("source_kind must be generated, recorded, or live")
    if input_path is None and value["source_kind"] != "live":
        raise SchemaError("stdin requires a live source record")
    if (value.get("frame"), value.get("position_unit"), value.get("time_unit")) != (
        "world",
        "m",
        "s",
    ):
        raise SchemaError("source record must declare world-frame meters and seconds")
    if (
        "measurement_type" in value
        and value["measurement_type"] != "cartesian_position_2d"
    ):
        raise SchemaError("online tracker requires Cartesian 2D positions")
    expected_hash = value.get("observation_sha256")
    if expected_hash is not None:
        if input_path is None:
            raise SchemaError(
                "live source record cannot declare a completed observation hash"
            )
        if not isinstance(expected_hash, str) or len(expected_hash) != 64:
            raise SchemaError("observation_sha256 must be a SHA-256 hex digest")
        with input_path.open("rb") as stream:
            actual_hash = hashlib.file_digest(stream, "sha256").hexdigest()
        if actual_hash != expected_hash:
            raise SchemaError("input observations do not match source record SHA-256")
    return value


class OnlineTracker:
    """Accept arrivals and emit completed epochs at a timestamp watermark.

    An epoch is complete only when its timestamp is strictly below the watermark.
    This preserves same-time multi-sensor assignment, including late arrivals
    within the configured bound. Input order is canonicalized at each epoch.
    """

    def __init__(
        self,
        *,
        max_lateness_s: float = 0.0,
        max_buffered: int = 4096,
        max_records: int = 100_000,
        max_live_tracks: int = 2048,
        expected_interval_s: float | None = None,
        direction_weight: float = 0.0,
    ) -> None:
        if not math.isfinite(max_lateness_s) or max_lateness_s < 0:
            raise SchemaError("max_lateness_s must be finite and nonnegative")
        for name, value in (
            ("max_buffered", max_buffered),
            ("max_records", max_records),
            ("max_live_tracks", max_live_tracks),
        ):
            if type(value) is not int or value < 1:
                raise SchemaError(f"{name} must be a positive integer")
        if expected_interval_s is not None:
            _positive(expected_interval_s, "expected_interval_s")
        self.max_lateness_s = max_lateness_s
        self.max_buffered = max_buffered
        self.max_records = max_records
        self.max_live_tracks = max_live_tracks
        self.expected_interval_s = expected_interval_s
        if not math.isfinite(direction_weight) or not 0 <= direction_weight <= 1e9:
            raise SchemaError("direction_weight must be finite and in [0, 1e9]")
        self.direction_weight = direction_weight
        self.state = AssociationState()
        self.pending: list[tuple[float, str, str, Observation]] = []
        self.pending_ids: set[str] = set()
        self.max_seen_time = -1.0
        self.received = 0
        self.accepted = 0
        self.processed = 0
        self.dropped_late = 0
        self.dropped_duplicate = 0
        self.dropped_buffer = 0
        self.dropped_record_limit = 0
        self.peak_buffered = 0
        self.peak_live_tracks = 0
        self.emitted_estimates = 0
        self.last_sensor_time: dict[str, float] = {}
        self.gap_epochs = 0
        self.gap_count = 0

    def accept(self, record: Observation) -> Iterator[TrackEstimate]:
        Observation.from_dict(record.to_dict())
        self.received += 1
        if (
            record.observation_id in self.pending_ids
            or record.observation_id in self.state.seen_ids
        ):
            self.dropped_duplicate += 1
            return
        if (
            record.timestamp_s <= self.state.previous_time
            or record.timestamp_s < self.max_seen_time - self.max_lateness_s
        ):
            self.dropped_late += 1
            return
        self.max_seen_time = max(self.max_seen_time, record.timestamp_s)
        watermark = self.max_seen_time - self.max_lateness_s
        yield from self._drain(watermark, final=False)
        if len(self.state.seen_ids) + len(self.pending_ids) >= self.max_records:
            self.dropped_record_limit += 1
            return
        if len(self.pending) >= self.max_buffered:
            self.dropped_buffer += 1
            return
        self.accepted += 1
        self.pending_ids.add(record.observation_id)
        heapq.heappush(
            self.pending,
            (record.timestamp_s, record.sensor_id, record.observation_id, record),
        )
        self.peak_buffered = max(self.peak_buffered, len(self.pending))

    def finish(self) -> Iterator[TrackEstimate]:
        return self._drain(math.inf, final=True)

    def _drain(self, watermark: float, *, final: bool) -> Iterator[TrackEstimate]:
        while self.pending and (final or self.pending[0][0] < watermark):
            timestamp = self.pending[0][0]
            epoch: list[Observation] = []
            while self.pending and self.pending[0][0] == timestamp:
                _, _, identifier, record = heapq.heappop(self.pending)
                self.pending_ids.remove(identifier)
                epoch.append(record)
            for record in epoch:
                previous = self.last_sensor_time.get(record.sensor_id)
                if previous is not None and self.expected_interval_s is not None:
                    missing = max(
                        0,
                        math.floor(
                            (record.timestamp_s - previous + 1e-9)
                            / self.expected_interval_s
                        )
                        - 1,
                    )
                    if missing:
                        self.gap_count += 1
                        self.gap_epochs += missing
                self.last_sensor_time[record.sensor_id] = record.timestamp_s
            estimates = track_multiple_objects(
                epoch,
                _state=self.state,
                _max_live_tracks=self.max_live_tracks,
                direction_weight=self.direction_weight,
            )
            self.processed += len(epoch)
            self.emitted_estimates += len(estimates)
            self.peak_live_tracks = max(self.peak_live_tracks, len(self.state.tracks))
            yield from estimates

    def quality(self) -> dict[str, Any]:
        return {
            "received": self.received,
            "accepted": self.accepted,
            "processed": self.processed,
            "emitted_estimates": self.emitted_estimates,
            "dropped_late": self.dropped_late,
            "dropped_duplicate": self.dropped_duplicate,
            "dropped_buffer": self.dropped_buffer,
            "dropped_record_limit": self.dropped_record_limit,
            "dropped_track_limit": self.state.dropped_track_limit,
            "dropped_records": (
                self.dropped_late
                + self.dropped_duplicate
                + self.dropped_buffer
                + self.dropped_record_limit
                + self.state.dropped_track_limit
            ),
            "gap_count": self.gap_count
            if self.expected_interval_s is not None
            else None,
            "missing_sensor_epochs": self.gap_epochs
            if self.expected_interval_s is not None
            else None,
            "peak_buffered": self.peak_buffered,
            "peak_live_tracks": self.peak_live_tracks,
            "max_lateness_s": self.max_lateness_s,
            "max_buffered": self.max_buffered,
            "max_records": self.max_records,
            "max_live_tracks": self.max_live_tracks,
            "expected_interval_s": self.expected_interval_s,
            "direction_weight": self.direction_weight,
        }


def track_stream(
    input_path: Path | None,
    output_path: Path,
    source_path: Path,
    *,
    max_lateness_s: float = 0.0,
    max_buffered: int = 4096,
    max_records: int = 100_000,
    max_live_tracks: int = 2048,
    expected_interval_s: float | None = None,
    direction_weight: float = 0.0,
    input_stream: TextIO | None = None,
) -> tuple[int, Path]:
    """Write and flush estimates per completed epoch; no reference data is read."""
    summary_path = output_path.with_name(output_path.stem + ".stream.json")
    paths = [output_path, summary_path, source_path]
    if input_path is not None:
        paths.append(input_path)
    if len({path.resolve() for path in paths}) != len(paths):
        raise SchemaError("input, source, track, and summary paths must differ")
    if output_path.exists() or summary_path.exists():
        raise FileExistsError("track or stream summary output already exists")
    source_record = _source_record(source_path, input_path)
    tracker = OnlineTracker(
        max_lateness_s=max_lateness_s,
        max_buffered=max_buffered,
        max_records=max_records,
        max_live_tracks=max_live_tracks,
        expected_interval_s=expected_interval_s,
        direction_weight=direction_weight,
    )
    stream = (
        input_path.open("r", encoding="utf-8")
        if input_path is not None
        else (input_stream if input_stream is not None else sys.stdin)
    )
    created_output = False
    created_summary = False
    digest = hashlib.sha256()
    size = 0

    def emit(records: Iterable[TrackEstimate], output: TextIO) -> None:
        nonlocal size
        wrote = False
        for record in records:
            data = (canonical_json(record.to_dict()) + "\n").encode("utf-8")
            size += len(data)
            if size > MAX_JSONL_BYTES:
                raise SchemaError("stream track artifact exceeds 64 MB limit")
            output.write(data.decode("utf-8"))
            digest.update(data)
            wrote = True
        if wrote:
            output.flush()

    try:
        with output_path.open("x", encoding="utf-8") as output:
            created_output = True
            line_number = 0
            while True:
                line = stream.readline(1_000_001)
                if not line:
                    break
                line_number += 1
                if len(line) > 1_000_000:
                    raise SchemaError(f"JSONL line {line_number}: line exceeds 1 MB")
                try:
                    record = Observation.from_dict(parse_json(line))
                    emit(tracker.accept(record), output)
                except SchemaError as exc:
                    raise SchemaError(f"JSONL line {line_number}: {exc}") from exc
            emit(tracker.finish(), output)
        if (
            input_path is not None
            and source_record.get("observation_sha256") is not None
        ):
            with input_path.open("rb") as stream_for_hash:
                final_hash = hashlib.file_digest(stream_for_hash, "sha256").hexdigest()
            if final_hash != source_record["observation_sha256"]:
                raise SchemaError("input observations changed during streaming replay")
        summary = {
            "schema_version": 1,
            "source_id": source_record["source_label"],
            "source_record": source_record,
            "quality": tracker.quality(),
            "track_sha256": digest.hexdigest(),
        }
        with summary_path.open("x", encoding="utf-8") as output:
            created_summary = True
            json.dump(summary, output, sort_keys=True, separators=(",", ":"))
            output.write("\n")
    except BaseException:
        if created_output:
            output_path.unlink(missing_ok=True)
        if created_summary:
            summary_path.unlink(missing_ok=True)
        raise
    finally:
        if input_path is not None:
            stream.close()
    return tracker.emitted_estimates, summary_path
