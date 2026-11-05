"""Compare reproduced deterministic benchmark data with checked-in evidence."""

from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]


def _metric_equal(expected: Any, actual: Any) -> bool:
    if type(expected) is not type(actual):
        return False
    if isinstance(expected, float):
        return math.isclose(expected, actual, rel_tol=1e-9, abs_tol=1e-9)
    if isinstance(expected, dict):
        return expected.keys() == actual.keys() and all(
            _metric_equal(expected[key], actual[key]) for key in expected
        )
    if isinstance(expected, list):
        return len(expected) == len(actual) and all(
            _metric_equal(left, right)
            for left, right in zip(expected, actual, strict=True)
        )
    return bool(expected == actual)


def compare(expected: dict[str, Any], actual: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    for key in ("protocol_sha256", "seeds", "matching_gate_m"):
        if expected.get(key) != actual.get(key):
            errors.append(f"{key} differs")
    expected_runs = expected.get("runs", [])
    actual_runs = actual.get("runs", [])
    if len(expected_runs) != len(actual_runs):
        errors.append(f"run count differs: {len(expected_runs)} != {len(actual_runs)}")
    for index, (left, right) in enumerate(zip(expected_runs, actual_runs)):
        for key in (
            "case",
            "method",
            "seed",
            "scenario_sha256",
            "observation_sha256",
            "track_sha256",
            "config_id",
        ):
            if left.get(key) != right.get(key):
                errors.append(f"run {index} {key} differs")
        if not _metric_equal(left.get("metrics"), right.get("metrics")):
            errors.append(f"run {index} metrics differ")
    return errors


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--actual", required=True, type=Path)
    parser.add_argument(
        "--expected",
        type=Path,
        default=ROOT / "examples/benchmark/results.json",
    )
    args = parser.parse_args()
    try:
        expected = json.loads(args.expected.read_text(encoding="utf-8"))
        actual = json.loads(args.actual.read_text(encoding="utf-8"))
        if not isinstance(expected, dict) or not isinstance(actual, dict):
            raise TypeError("benchmark artifacts must be JSON objects")
        errors = compare(expected, actual)
    except (OSError, ValueError, TypeError) as exc:
        parser.exit(2, f"evidence verification: {exc}\n")
    if errors:
        for error in errors[:20]:
            print(f"evidence verification: {error}")
        if len(errors) > 20:
            print(f"... and {len(errors) - 20} more differences")
        return 1
    print(f"verified {len(actual['runs'])} deterministic benchmark runs")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
