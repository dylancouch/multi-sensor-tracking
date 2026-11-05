"""Convert a pinned FHWA NGSIM Peachtree API slice to truth-free observations."""

from __future__ import annotations

import argparse
import hashlib
import json
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any

from mst.schema import Observation, SchemaError, canonical_json

API = "https://data.transportation.gov/resource/8ect-6jqj.json"
VEHICLES = ("228", "244", "297", "319", "367")
FIRST_FRAME = 3370
LAST_FRAME = 3400
FEET_TO_METERS = 0.3048
STD_M = 0.75  # illustrative; not calibrated to the video extraction process
QUERY = {
    "$select": "vehicle_id,frame_id,global_time,local_x,local_y,location",
    "$where": "location='peachtree' AND frame_id between 3370 and 3400 AND vehicle_id in ('228','244','297','319','367')",
    "$order": "frame_id,vehicle_id",
    "$limit": "500",
}


def convert(rows: Any) -> list[Observation]:
    if not isinstance(rows, list) or len(rows) != 155:
        raise SchemaError("expected exactly 155 NGSIM rows")
    seen: set[tuple[int, str]] = set()
    records: list[Observation] = []
    expected_keys = {
        "vehicle_id",
        "frame_id",
        "global_time",
        "local_x",
        "local_y",
        "location",
    }
    for row in rows:
        if not isinstance(row, dict) or set(row) != expected_keys:
            raise SchemaError("unexpected NGSIM columns")
        vehicle = row["vehicle_id"]
        frame = int(row["frame_id"])
        if (
            row["location"] != "peachtree"
            or vehicle not in VEHICLES
            or not FIRST_FRAME <= frame <= LAST_FRAME
        ):
            raise SchemaError("unexpected NGSIM selection")
        if (frame, vehicle) in seen:
            raise SchemaError("duplicate NGSIM frame and vehicle")
        seen.add((frame, vehicle))
        # API global_time units are ambiguous; use the documented 10 Hz frame cadence.
        if int(row["global_time"]) != 1163355600 + (frame - FIRST_FRAME) * 100:
            raise SchemaError("NGSIM frame/time alignment changed")
        records.append(
            Observation.from_dict(
                {
                    "schema_version": 1,
                    "timestamp_s": round((frame - FIRST_FRAME) / 10, 1),
                    "observation_id": f"ngsim_{frame}_{vehicle}",
                    "sensor_id": "ngsim_video_trajectory",
                    "position_m": [
                        float(row["local_x"]) * FEET_TO_METERS,
                        float(row["local_y"]) * FEET_TO_METERS,
                    ],
                    "covariance_m2": [[STD_M**2, 0.0], [0.0, STD_M**2]],
                    "frame": "world",
                    "time_unit": "s",
                }
            )
        )
    if len(seen) != (LAST_FRAME - FIRST_FRAME + 1) * len(VEHICLES):
        raise SchemaError("incomplete NGSIM frame coverage")
    return records


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--input", type=Path, help="saved selected API JSON response")
    source.add_argument(
        "--download", action="store_true", help="fetch the selected API slice"
    )
    parser.add_argument(
        "--expected-sha256", required=True, help="pinned selected response SHA-256"
    )
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--source-record", type=Path, required=True)
    args = parser.parse_args()
    if (
        args.output.resolve() == args.source_record.resolve()
        or args.output.exists()
        or args.source_record.exists()
    ):
        parser.error("output paths must be distinct new files")
    if args.download:
        url = API + "?" + urllib.parse.urlencode(QUERY)
        with urllib.request.urlopen(url, timeout=30) as response:
            rows = json.load(response)
    else:
        with args.input.open("r", encoding="utf-8") as stream:
            rows = json.load(stream)
    # Hash canonical selected rows, independent of API whitespace or key ordering.
    selected_hash = hashlib.sha256(canonical_json(rows).encode()).hexdigest()
    if selected_hash != args.expected_sha256:
        parser.error(f"source slice SHA-256 differs: {selected_hash}")
    records = convert(rows)
    observations = "".join(
        canonical_json(item.to_dict()) + "\n" for item in records
    ).encode()
    sidecar = {
        "schema_version": 2,
        "source_label": "fhwa_ngsim_peachtree_3370_3400",
        "source_kind": "recorded",
        "domain": "urban road traffic",
        "measurement_type": "cartesian_position_2d",
        "frame": "world",
        "position_unit": "m",
        "time_unit": "s",
        "timing": "10 Hz relative frame time; frame 3370 is t=0; global_time is not interpreted as UTC",
        "coordinates": "NGSIM local_x/local_y feet converted to meters by 0.3048; unrotated local axes",
        "uncertainty": "isotropic 0.75 m standard deviation assumed; not calibrated",
        "provenance": API,
        "selection": QUERY["$where"],
        "selected_rows_sha256": selected_hash,
        "observation_sha256": hashlib.sha256(observations).hexdigest(),
        "observation_count": len(records),
        "reference_quality": "none independent; video-derived positions are observations only",
        "permitted_metrics": "truth-free tracker and innovation diagnostics only",
        "license": "CC BY-SA 3.0, attributed to U.S. DOT FHWA NGSIM",
    }
    created: list[Path] = []
    try:
        with args.output.open("xb") as stream:
            created.append(args.output)
            stream.write(observations)
        with args.source_record.open("x", encoding="utf-8") as stream:
            created.append(args.source_record)
            stream.write(canonical_json(sidecar) + "\n")
    except BaseException:
        for path in created:
            path.unlink(missing_ok=True)
        raise


if __name__ == "__main__":
    main()
