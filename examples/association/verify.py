"""Check deterministic sensor-order comparison data against frozen evidence."""

from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
from typing import Any

EXPECTED = Path(__file__).with_name("sensor-order-results.json")


def projection(result: dict[str, Any]) -> dict[str, Any]:
    """Exclude machine-dependent timing, environment, and Git dirty state."""
    return {
        "protocol_sha256": result["protocol_sha256"],
        "runs": [
            {key: value for key, value in run.items() if key != "tracking_wall_s"}
            for run in result["runs"]
        ],
    }


def _equal(left: Any, right: Any) -> bool:
    if type(left) is not type(right):
        return False
    if isinstance(left, float):
        return math.isclose(left, right, rel_tol=1e-9, abs_tol=1e-9)
    if isinstance(left, dict):
        return left.keys() == right.keys() and all(
            _equal(left[key], right[key]) for key in left
        )
    if isinstance(left, list):
        return len(left) == len(right) and all(
            _equal(a, b) for a, b in zip(left, right, strict=True)
        )
    return bool(left == right)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--actual", type=Path, required=True)
    parser.add_argument("--expected", type=Path, default=EXPECTED)
    args = parser.parse_args()
    try:
        expected = json.loads(args.expected.read_text(encoding="utf-8"))
        actual = json.loads(args.actual.read_text(encoding="utf-8"))
        if not isinstance(expected, dict) or not isinstance(actual, dict):
            raise TypeError("evidence files must contain JSON objects")
        actual = projection(actual)
        if not _equal(expected, actual):
            print(
                "sensor-order evidence differs: protocol, source, tracks, or metrics changed"
            )
            return 1
    except (OSError, ValueError, TypeError, KeyError) as exc:
        parser.exit(2, f"sensor-order evidence verification: {exc}\n")
    print(f"verified {len(actual['runs'])} deterministic sensor-order runs")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
