"""Prepare a short, recorded IBTrACS track for truth-free intake demonstration.

Input is NOAA's v04r01 North Atlantic CSV, downloaded separately. This script
does not score a tracker or interpret best-track positions as independent truth.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
from datetime import UTC, datetime
from pathlib import Path

EARTH_RADIUS_M = 6_371_000.0


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--metadata", type=Path, required=True)
    parser.add_argument(
        "--expected-sha256",
        help="required source snapshot hash, when pinning a reproduction",
    )
    args = parser.parse_args()
    if args.output.exists() or args.metadata.exists():
        parser.error("output and metadata paths must be new")
    with args.input.open("rb") as source:
        input_hash = hashlib.file_digest(source, "sha256").hexdigest()
    if args.expected_sha256 is not None and input_hash != args.expected_sha256:
        parser.error(f"source SHA-256 differs: got {input_hash}")
    rows: list[tuple[datetime, float, float]] = []
    with args.input.open("r", encoding="utf-8", newline="") as source:
        reader = csv.DictReader(source)
        required = {"NAME", "SEASON", "TRACK_TYPE", "ISO_TIME", "LAT", "LON"}
        if reader.fieldnames is None or not required <= set(reader.fieldnames):
            parser.error("IBTrACS v04r01 CSV columns are missing")
        next(reader, None)  # NOAA CSV second row holds units.
        for row in reader:
            if row["NAME"] != "LAURA" or row["SEASON"] != "2020":
                continue
            if row["TRACK_TYPE"].lower() != "main" or not row["LAT"] or not row["LON"]:
                continue
            instant = datetime.strptime(
                row["ISO_TIME"].strip(), "%Y-%m-%d %H:%M:%S"
            ).replace(tzinfo=UTC)
            lat, lon = float(row["LAT"]), float(row["LON"])
            if not (-90 <= lat <= 90 and -180 <= lon <= 180):
                parser.error("invalid latitude or longitude")
            rows.append((instant, lat, lon))
    rows = sorted(set(rows))[:8]
    if len(rows) < 2:
        parser.error("expected at least two 2020 Laura main-track positions")
    start, lat0, lon0 = rows[0]
    if len({instant for instant, _, _ in rows}) != len(rows):
        parser.error("duplicate timestamps require manual review")
    created_output = False
    created_metadata = False
    try:
        with args.output.open("x", encoding="utf-8", newline="") as output:
            created_output = True
            writer = csv.writer(output)
            writer.writerow(("timestamp_s", "observation_id", "x_m", "y_m"))
            for index, (instant, lat, lon) in enumerate(rows):
                x = (
                    EARTH_RADIUS_M
                    * math.cos(math.radians(lat0))
                    * math.radians(lon - lon0)
                )
                y = EARTH_RADIUS_M * math.radians(lat - lat0)
                writer.writerow(
                    (int((instant - start).total_seconds()), f"laura_{index:02d}", x, y)
                )
        metadata = {
            "source": "NOAA IBTrACS v04r01 North Atlantic CSV",
            "input_sha256": input_hash,
            "selection": "2020 LAURA, main track, first eight distinct positions",
            "projection": "local equirectangular; R=6371000 m; anchor is first position",
            "anchor_lat_deg": lat0,
            "anchor_lon_deg": lon0,
            "time_origin_utc": start.isoformat(),
            "output_count": len(rows),
            "uncertainty": "20 km isotropic standard deviation is an illustrative assumption, not NOAA calibration",
            "reference": "none supplied; best-track points are used only as observations",
        }
        with args.metadata.open("x", encoding="utf-8") as output:
            created_metadata = True
            json.dump(metadata, output, sort_keys=True, indent=2)
            output.write("\n")
    except BaseException:
        if created_output:
            args.output.unlink(missing_ok=True)
        if created_metadata:
            args.metadata.unlink(missing_ok=True)
        raise


if __name__ == "__main__":
    main()
