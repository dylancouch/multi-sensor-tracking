"""Bounded JSON/JSONL I/O and run integrity checks."""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any

from . import __version__
from .provenance import environment_versions, source_state
from .schema import (
    MANIFEST_VERSION,
    MAX_JSONL_BYTES,
    Manifest,
    Observation,
    Scenario,
    SchemaError,
    Truth,
    canonical_json,
    parse_json,
    read_json,
)
from .sensors import generate_observations, sensor_seed
from .simulation import generate_truth


def _jsonl(records: list[Truth] | list[Observation]) -> bytes:
    return ("".join(canonical_json(item.to_dict()) + "\n" for item in records)).encode(
        "utf-8"
    )


def create_run(output: Path, scenario: Scenario, seed: int) -> Manifest:
    if type(seed) is not int or not 0 <= seed < 2**64:
        raise SchemaError("seed must be a 64-bit unsigned integer")
    truth = generate_truth(scenario)
    observations = generate_observations(scenario, truth, seed)
    payloads = {"truth": _jsonl(truth), "observations": _jsonl(observations)}
    if any(len(data) > MAX_JSONL_BYTES for data in payloads.values()):
        raise SchemaError("generated artifact exceeds 64 MB limit")
    source = source_state()
    manifest = Manifest(
        MANIFEST_VERSION,
        __version__,
        seed,
        {s.sensor_id: sensor_seed(seed, s.sensor_id) for s in scenario.sensors},
        scenario,
        {"truth": "truth.jsonl", "observations": "observations.jsonl"},
        {name: hashlib.sha256(data).hexdigest() for name, data in payloads.items()},
        {"truth": len(truth), "observations": len(observations)},
        source["revision"],
        source["dirty"],
        environment_versions(),
        hashlib.sha256(canonical_json(scenario.to_dict()).encode()).hexdigest(),
    )
    # mkdir is exclusive. Every file is also opened exclusively; existing data is never clobbered.
    output.mkdir(parents=False, exist_ok=False)
    for name, data in payloads.items():
        with (output / manifest.artifacts[name]).open("xb") as stream:
            stream.write(data)
    with (output / "manifest.json").open("x", encoding="utf-8") as stream:
        stream.write(canonical_json(manifest.to_dict()) + "\n")
    return manifest


def _read_jsonl(path: Path, kind: str) -> list[Truth | Observation]:
    if path.stat().st_size > MAX_JSONL_BYTES:
        raise SchemaError(f"{path.name} exceeds {MAX_JSONL_BYTES} bytes")
    records: list[Truth | Observation] = []
    previous_time = -1.0
    ids: set[Any] = set()
    with path.open("r", encoding="utf-8") as stream:
        for line_number, line in enumerate(stream, 1):
            if len(line) > 1_000_000:
                raise SchemaError(f"{path.name}:{line_number}: line exceeds 1 MB")
            try:
                value = parse_json(line)
                record: Truth | Observation
                identity: tuple[float, str] | str
                if kind == "truth":
                    record = Truth.from_dict(value)
                    identity = (record.timestamp_s, record.object_id)
                else:
                    record = Observation.from_dict(value)
                    identity = record.observation_id
                if record.timestamp_s < previous_time:
                    raise SchemaError("timestamps must be nondecreasing")
                if identity in ids:
                    raise SchemaError(f"duplicate record ID {identity!r}")
                previous_time = record.timestamp_s
                ids.add(identity)
                records.append(record)
            except SchemaError as exc:
                raise SchemaError(f"{path.name}:{line_number}: {exc}") from exc
    return records


def validate_run(directory: Path) -> Manifest:
    manifest = Manifest.from_dict(read_json(directory / "manifest.json"))
    for kind in ("truth", "observations"):
        path = directory / manifest.artifacts[kind]
        if path.stat().st_size > MAX_JSONL_BYTES:
            raise SchemaError(f"{path.name} exceeds {MAX_JSONL_BYTES} bytes")
        data = path.read_bytes()
        if hashlib.sha256(data).hexdigest() != manifest.sha256[kind]:
            raise SchemaError(f"{path.name} SHA-256 mismatch")
        records = _read_jsonl(path, kind)
        if len(records) != manifest.counts[kind]:
            raise SchemaError(f"{path.name} count mismatch")
        if kind == "observations":
            sensor_ids = {sensor.sensor_id for sensor in manifest.scenario.sensors}
            if any(
                not isinstance(item, Observation) or item.sensor_id not in sensor_ids
                for item in records
            ):
                raise SchemaError("observations contain unknown sensor_id")
    return manifest
