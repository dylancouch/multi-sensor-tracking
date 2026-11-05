"""Verify hand-counted IDF1 cases and frozen diagnostics reproduction output."""

from __future__ import annotations

import argparse
import json
import math
import tempfile
from pathlib import Path

from mst.evaluation import identity_metrics
from mst.schema import TrackEstimate, Truth, canonical_json

from .run import run

HERE = Path(__file__).parent


def verify_vectors() -> None:
    value = json.loads((HERE / "idf1-vectors.json").read_text())
    for case in value["cases"]:
        truth = [
            Truth.from_dict(
                {
                    "schema_version": 1,
                    "timestamp_s": t,
                    "object_id": identifier,
                    "state": [x, 0, 0, 0],
                    "frame": "world",
                    "position_unit": "m",
                    "velocity_unit": "m/s",
                }
            )
            for t, identifier, x in case["truth"]
        ]
        estimates = [
            TrackEstimate.from_dict(
                {
                    "schema_version": 1,
                    "timestamp_s": t,
                    "track_id": identifier,
                    "state": [x, 0, 0, 0],
                    "covariance": [
                        [1, 0, 0, 0],
                        [0, 1, 0, 0],
                        [0, 0, 1, 0],
                        [0, 0, 0, 1],
                    ],
                    "lifecycle": "confirmed",
                    "method": "multi-kalman",
                    "config_id": "idf1-vector",
                    "frame": "world",
                    "position_unit": "m",
                    "velocity_unit": "m/s",
                }
            )
            for t, identifier, x in case["estimates"]
        ]
        actual = identity_metrics(truth, estimates, gate_m=value["gate_m"])
        for key, expected in case["expected"].items():
            if not math.isclose(actual[key], expected, abs_tol=1e-12):
                raise AssertionError(
                    f"{case['name']} {key}: {actual[key]} != {expected}"
                )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--vectors-only", action="store_true")
    args = parser.parse_args()
    verify_vectors()
    if not args.vectors_only:
        expected = (HERE / "results.json").read_text()
        with tempfile.TemporaryDirectory(prefix="mst-diagnostics-") as temp:
            actual = canonical_json(run(Path(temp) / "evidence")) + "\n"
        if actual != expected:
            raise AssertionError("diagnostics reproduction differs from frozen results.json")
    print("diagnostics IDF1 vectors and reproducible evidence verified")


if __name__ == "__main__":
    main()
