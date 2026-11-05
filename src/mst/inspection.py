"""Self-contained, truth-optional inspection of tracker-facing runs."""

from __future__ import annotations

import json
import math
from importlib.resources import files
from pathlib import Path
from typing import Any

import numpy as np
from scipy.optimize import linear_sum_assignment

from .events import AssociationEvent, validate_links
from .innovations import Innovation
from .schema import MAX_JSONL_BYTES, Observation, SchemaError, TrackEstimate, Truth


def _reference_matches(
    truth: list[Truth], tracks: list[TrackEstimate], gate_m: float
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Use the scorer's exact-time, maximum-cardinality planar matching rule."""
    final = {(item.timestamp_s, item.track_id): item for item in tracks}
    by_time: dict[float, list[TrackEstimate]] = {}
    for (timestamp, _), estimate in final.items():
        if estimate.lifecycle != "deleted":
            by_time.setdefault(timestamp, []).append(estimate)
    truth_by_time: dict[float, list[Truth]] = {}
    for reference in truth:
        truth_by_time.setdefault(reference.timestamp_s, []).append(reference)
    errors: list[dict[str, Any]] = []
    switches: list[dict[str, Any]] = []
    prior_track: dict[str, str] = {}
    for timestamp, truth_frame in sorted(truth_by_time.items()):
        truth_frame.sort(key=lambda item: item.object_id)
        track_frame = sorted(by_time.get(timestamp, []), key=lambda item: item.track_id)
        if not track_frame:
            continue
        distances = np.asarray(
            [
                [
                    math.hypot(
                        actual.state[0] - estimate.state[0],
                        actual.state[1] - estimate.state[1],
                    )
                    for estimate in track_frame
                ]
                for actual in truth_frame
            ]
        )
        penalty = (max(len(truth_frame), len(track_frame)) + 1) * gate_m + 1
        rows, columns = linear_sum_assignment(
            np.where(distances <= gate_m, distances, penalty)
        )
        for row, column in zip(rows, columns, strict=True):
            if distances[row, column] > gate_m:
                continue
            actual = truth_frame[int(row)]
            estimate = track_frame[int(column)]
            errors.append(
                {
                    "timestamp_s": timestamp,
                    "object_id": actual.object_id,
                    "track_id": estimate.track_id,
                    "error_m": float(distances[row, column]),
                }
            )
            previous = prior_track.get(actual.object_id)
            if previous is not None and previous != estimate.track_id:
                switches.append(
                    {
                        "timestamp_s": timestamp,
                        "object_id": actual.object_id,
                        "previous_track_id": previous,
                        "track_id": estimate.track_id,
                    }
                )
            prior_track[actual.object_id] = estimate.track_id
    return errors, switches


def inspection_data(
    observations: list[Observation],
    tracks: list[TrackEstimate],
    *,
    events: list[AssociationEvent] | None = None,
    innovations: list[Innovation] | None = None,
    truth: list[Truth] | None = None,
    gate_m: float = 10.0,
) -> dict[str, Any]:
    if not math.isfinite(gate_m) or not 0 < gate_m <= 1e6:
        raise SchemaError("gate_m must be finite and in (0, 1e6]")
    observation_by_id = {item.observation_id: item for item in observations}
    if len(observation_by_id) != len(observations):
        raise SchemaError("duplicate observation_id")
    track_at_time = {(item.timestamp_s, item.track_id): item for item in tracks}
    for observation in observations:
        Observation.from_dict(observation.to_dict())
    for estimate in tracks:
        TrackEstimate.from_dict(estimate.to_dict())
    if events is not None:
        validate_links(events, observations, tracks)
    if innovations is not None:
        seen: set[str] = set()
        for innovation in innovations:
            Innovation.from_dict(innovation.to_dict())
            source = observation_by_id.get(innovation.observation_id)
            target = track_at_time.get((innovation.timestamp_s, innovation.track_id))
            if (
                innovation.observation_id in seen
                or source is None
                or target is None
                or target.method == "baseline"
                or source.timestamp_s != innovation.timestamp_s
                or source.sensor_id != innovation.sensor_id
            ):
                raise SchemaError(
                    "innovation does not match a unique observation and Kalman track"
                )
            seen.add(innovation.observation_id)
    if truth is not None:
        seen_truth: set[tuple[float, str]] = set()
        for reference in truth:
            Truth.from_dict(reference.to_dict())
            key = (reference.timestamp_s, reference.object_id)
            if key in seen_truth:
                raise SchemaError("duplicate truth timestamp/object_id")
            seen_truth.add(key)
    errors, switches = (
        _reference_matches(truth, tracks, gate_m) if truth is not None else ([], [])
    )
    timestamps = sorted(
        {item.timestamp_s for item in observations}
        | {item.timestamp_s for item in tracks}
        | ({item.timestamp_s for item in truth} if truth is not None else set())
    )
    return {
        "schema_version": 1,
        "timestamps_s": timestamps,
        "sensors": sorted({item.sensor_id for item in observations}),
        "track_ids": sorted({item.track_id for item in tracks}),
        "observations": [item.to_dict() for item in observations],
        "tracks": [item.to_dict() for item in tracks],
        "events": [item.to_dict() for item in events] if events is not None else None,
        "innovations": [item.to_dict() for item in innovations]
        if innovations is not None
        else None,
        "truth": [item.to_dict() for item in truth] if truth is not None else None,
        "errors": errors,
        "id_switches": switches,
        "matching_gate_m": gate_m,
    }


def write_inspection(
    output: Path,
    observations: list[Observation],
    tracks: list[TrackEstimate],
    *,
    events: list[AssociationEvent] | None = None,
    innovations: list[Innovation] | None = None,
    truth: list[Truth] | None = None,
    gate_m: float = 10.0,
) -> None:
    if output.suffix.lower() != ".html":
        raise SchemaError("inspection output must end in .html")
    data = inspection_data(
        observations,
        tracks,
        events=events,
        innovations=innovations,
        truth=truth,
        gate_m=gate_m,
    )
    payload = json.dumps(
        data, ensure_ascii=True, allow_nan=False, separators=(",", ":")
    )
    payload = (
        payload.replace("<", "\\u003c").replace(">", "\\u003e").replace("&", "\\u0026")
    )
    template = (
        files("mst").joinpath("inspection_template.html").read_text(encoding="utf-8")
    )
    html = template.replace("__MST_INSPECTION_DATA__", payload)
    encoded = html.encode("utf-8")
    if len(encoded) > MAX_JSONL_BYTES:
        raise SchemaError("inspection HTML exceeds 64 MB limit")
    created = False
    try:
        with output.open("xb") as stream:
            created = True
            stream.write(encoded)
    except Exception:
        if created:
            output.unlink(missing_ok=True)
        raise
