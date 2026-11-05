"""Normalize recorded CSV or live JSONL into tracker-facing observations."""

from __future__ import annotations

import csv
import hashlib
import json
import math
import sys
from pathlib import Path
from typing import TextIO, cast

from .input_contract import InputContract
from .schema import (
    MAX_JSONL_BYTES,
    Observation,
    SchemaError,
    _name,
    canonical_json,
    parse_json,
)

CSV_FIELDS = ["timestamp_s", "observation_id", "x_m", "y_m"]


def _csv_records(stream: TextIO, sensor_id: str, position_std_m: float):
    if not math.isfinite(position_std_m) or position_std_m < 0:
        raise SchemaError("position_std_m must be finite and nonnegative")
    variance = position_std_m**2
    if not math.isfinite(variance):
        raise SchemaError("position_std_m squared must be finite")
    reader = csv.DictReader(stream)
    if reader.fieldnames != CSV_FIELDS:
        raise SchemaError("CSV header must be: " + ",".join(CSV_FIELDS))
    for line_number, row in enumerate(reader, 2):
        if None in row or any(value is None for value in row.values()):
            raise SchemaError(f"CSV line {line_number}: invalid column count")
        try:
            value = {
                "schema_version": 1,
                "timestamp_s": float(row["timestamp_s"]),
                "observation_id": row["observation_id"],
                "sensor_id": sensor_id,
                "position_m": [float(row["x_m"]), float(row["y_m"])],
                "covariance_m2": [[variance, 0], [0, variance]],
                "frame": "world",
                "time_unit": "s",
            }
            yield Observation.from_dict(value)
        except (ValueError, SchemaError) as exc:
            raise SchemaError(f"CSV line {line_number}: {exc}") from exc


def _jsonl_records(stream: TextIO):
    for line_number, line in enumerate(stream, 1):
        if len(line) > 1_000_000:
            raise SchemaError(f"JSONL line {line_number}: line exceeds 1 MB")
        try:
            yield Observation.from_dict(parse_json(line))
        except SchemaError as exc:
            raise SchemaError(f"JSONL line {line_number}: {exc}") from exc


def _contract_csv_records(stream: TextIO, contract: InputContract):
    reader = csv.DictReader(stream)
    if reader.fieldnames is None or len(reader.fieldnames) != len(
        set(reader.fieldnames)
    ):
        raise SchemaError("CSV header must contain unique field names")
    if set(contract.fields) != set(reader.fieldnames):
        raise SchemaError("CSV header must contain exactly the input contract fields")
    for line_number, row in enumerate(reader, 2):
        if None in row or any(value is None for value in row.values()):
            raise SchemaError(f"CSV line {line_number}: invalid column count")
        try:
            yield contract.convert(
                float(row[contract.fields[0]]),
                row[contract.fields[1]],
                float(row[contract.fields[2]]),
                float(row[contract.fields[3]]),
            )
        except (ValueError, SchemaError) as exc:
            raise SchemaError(f"CSV line {line_number}: {exc}") from exc


def ingest(
    input_path: Path | None,
    output_path: Path,
    *,
    format: str,
    source_label: str | None,
    sensor_id: str | None = None,
    position_std_m: float | None = None,
    contract_path: Path | None = None,
) -> tuple[int, Path]:
    """Consume to EOF, emitting canonical JSONL and a source/assumption manifest.

    None input means stdin, which can be an ongoing sensor feed. Input must
    already use world-frame meters and nonnegative seconds unless an explicit
    versioned CSV input contract supplies their conversion.
    """
    if format not in ("csv", "jsonl"):
        raise SchemaError("format must be csv or jsonl")
    contract = None
    contract_sha256 = None
    if contract_path is not None:
        if format != "csv" or sensor_id is not None or position_std_m is not None:
            raise SchemaError(
                "CSV input contract replaces --sensor-id and --position-std-m"
            )
        raw = contract_path.read_bytes()
        contract_sha256 = hashlib.sha256(raw).hexdigest()
        contract = InputContract.from_dict(parse_json(raw.decode("utf-8")))
        if source_label is not None and source_label != contract.source_id:
            raise SchemaError("source_label must equal input contract source_id")
        source_label = contract.source_id
    _name(source_label, "source_label")
    if format == "csv" and contract is None:
        if sensor_id is None or position_std_m is None:
            raise SchemaError("CSV requires sensor_id and position_std_m")
        _name(sensor_id, "sensor_id")
    elif format == "jsonl" and (sensor_id is not None or position_std_m is not None):
        raise SchemaError("JSONL carries sensor IDs and covariance; omit CSV options")
    provenance_path = output_path.with_name(output_path.stem + ".source.json")
    if input_path is not None and input_path.resolve() in (
        output_path.resolve(),
        provenance_path.resolve(),
    ):
        raise SchemaError("input and output paths must differ")
    if contract_path is not None and contract_path.resolve() in (
        output_path.resolve(),
        provenance_path.resolve(),
    ):
        raise SchemaError("contract and output paths must differ")
    if output_path.exists() or provenance_path.exists():
        raise FileExistsError("output or source manifest already exists")
    input_sha256 = None
    if contract is not None and input_path is not None:
        with input_path.open("rb") as source:
            input_sha256 = hashlib.file_digest(source, "sha256").hexdigest()
    count = 0
    size = 0
    digest = hashlib.sha256()
    seen: set[str] = set()
    last_time = -1.0
    stream = (
        input_path.open("r", encoding="utf-8", newline="") if input_path else sys.stdin
    )
    created_output = False
    created_provenance = False
    try:
        with output_path.open("x", encoding="utf-8") as output:
            created_output = True
            if contract is not None:
                records = _contract_csv_records(stream, contract)
            elif format == "csv":
                records = _csv_records(
                    stream, cast(str, sensor_id), cast(float, position_std_m)
                )
            else:
                records = _jsonl_records(stream)
            for record in records:
                if record.timestamp_s < last_time:
                    raise SchemaError("timestamps must be nondecreasing")
                if record.observation_id in seen:
                    raise SchemaError("duplicate observation_id")
                seen.add(record.observation_id)
                last_time = record.timestamp_s
                data = (canonical_json(record.to_dict()) + "\n").encode("utf-8")
                size += len(data)
                if size > MAX_JSONL_BYTES:
                    raise SchemaError("observation artifact exceeds 64 MB limit")
                output.write(data.decode("utf-8"))
                output.flush()
                digest.update(data)
                count += 1
        provenance = {
            "schema_version": 2 if contract is not None else 1,
            "source_kind": contract.raw["source_kind"]
            if contract is not None
            else ("live" if input_path is None else "recorded"),
            "source_label": source_label,
            "input_format": format,
            "sensor_id": contract.sensor_id if contract is not None else sensor_id,
            "position_std_m": position_std_m,
            "frame": "world",
            "position_unit": "m",
            "time_unit": "s",
            "observation_count": count,
            "observation_sha256": digest.hexdigest(),
            "covariance_assumption": contract.raw["uncertainty"]["kind"]
            if contract is not None
            else ("isotropic, fixed" if format == "csv" else "per observation"),
        }
        if contract is not None:
            provenance["input_contract"] = contract.raw
            provenance["input_contract_sha256"] = contract_sha256
            if input_path is not None:
                with input_path.open("rb") as source:
                    final_input_sha256 = hashlib.file_digest(
                        source, "sha256"
                    ).hexdigest()
                if input_sha256 != final_input_sha256:
                    raise SchemaError("input file changed during ingestion")
                provenance["input_sha256"] = input_sha256
        with provenance_path.open("x", encoding="utf-8") as output:
            created_provenance = True
            json.dump(provenance, output, sort_keys=True, separators=(",", ":"))
            output.write("\n")
    except BaseException:
        if created_output:
            output_path.unlink(missing_ok=True)
        if created_provenance:
            provenance_path.unlink(missing_ok=True)
        raise
    finally:
        if input_path is not None:
            stream.close()
    return count, provenance_path
