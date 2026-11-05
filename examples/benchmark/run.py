"""Run the frozen synthetic protocol and write measured, versioned evidence."""

from __future__ import annotations

import argparse
import copy
import hashlib
import math
import statistics
import tempfile
import time
from collections import defaultdict
from pathlib import Path
from typing import Any

from mst import __version__
from mst.artifacts import create_run
from mst.association import track_multiple_objects
from mst.evaluation import read_truth, report
from mst.innovations import write_innovations
from mst.observation_io import read_observations, write_tracks
from mst.schema import Scenario, SchemaError, canonical_json, read_json
from mst.tracking import track_single_object

ROOT = Path(__file__).resolve().parents[2]


def _scenario(case: dict[str, Any]) -> Scenario:
    config_name = case["config"]
    if (
        not isinstance(config_name, str)
        or Path(config_name).name != config_name
        or not config_name.endswith(".json")
    ):
        raise SchemaError(
            "case config must be a JSON filename inside examples/scenarios/"
        )
    value = read_json(ROOT / "examples/scenarios" / config_name)
    if not isinstance(value, dict):
        raise SchemaError("scenario config must be an object")
    value = copy.deepcopy(value)
    selected = case.get("sensors")
    if selected is not None:
        if (
            not isinstance(selected, list)
            or not selected
            or len(set(selected)) != len(selected)
        ):
            raise SchemaError("case sensors must be unique nonempty IDs")
        value["sensors"] = [
            sensor for sensor in value["sensors"] if sensor["sensor_id"] in selected
        ]
        if {sensor["sensor_id"] for sensor in value["sensors"]} != set(selected):
            raise SchemaError("case references an unknown sensor")
    overrides = case.get("sensor_overrides", {})
    if not isinstance(overrides, dict):
        raise SchemaError("sensor_overrides must be an object")
    for sensor_id, fields in overrides.items():
        if not isinstance(fields, dict) or not set(fields) <= {
            "noise_std_m",
            "miss_probability",
            "false_alarm_probability",
            "false_alarm_bounds_m",
            "timestamp_offset_s",
        }:
            raise SchemaError("unsupported sensor override")
        matching = [
            sensor for sensor in value["sensors"] if sensor["sensor_id"] == sensor_id
        ]
        if len(matching) != 1:
            raise SchemaError("sensor override references an unknown sensor")
        matching[0].update(fields)
    return Scenario.from_dict(value)


def _stats(values: list[float | int | None]) -> dict[str, Any]:
    finite = [float(value) for value in values if value is not None]
    return {
        "n": len(finite),
        "mean": statistics.fmean(finite) if finite else None,
        "sample_stddev": statistics.stdev(finite) if len(finite) > 1 else None,
    }


def run_protocol(protocol: dict[str, Any]) -> dict[str, Any]:
    if protocol.get("schema_version") != 1:
        raise SchemaError("unsupported experiment schema_version")
    seeds = protocol.get("seeds")
    cases = protocol.get("cases")
    if (
        not isinstance(seeds, list)
        or not seeds
        or len(set(seeds)) != len(seeds)
        or any(type(seed) is not int or not 0 <= seed < 2**64 for seed in seeds)
    ):
        raise SchemaError("seeds must be unique 64-bit unsigned integers")
    if (
        not isinstance(cases, list)
        or not cases
        or any(not isinstance(case, dict) for case in cases)
        or len({case.get("name") for case in cases}) != len(cases)
    ):
        raise SchemaError("cases must have unique names")
    tracker = protocol.get("tracker")
    if not isinstance(tracker, dict):
        raise SchemaError("tracker parameters must be an object")
    gate_m = protocol.get("matching_gate_m")
    if isinstance(gate_m, bool) or not isinstance(gate_m, (int, float)):
        raise SchemaError("matching_gate_m must be finite and in (0, 1e6]")
    if not math.isfinite(gate_m) or not 0 < gate_m <= 1e6:
        raise SchemaError("matching_gate_m must be finite and in (0, 1e6]")
    gate_m = float(gate_m)
    runs: list[dict[str, Any]] = []
    for case in cases:
        if not isinstance(case, dict) or set(case) - {
            "name",
            "config",
            "methods",
            "sensors",
            "sensor_overrides",
        }:
            raise SchemaError("invalid case object")
        if not isinstance(case.get("name"), str) or not case["name"]:
            raise SchemaError("case name must be nonempty")
        methods = case.get("methods")
        if (
            not isinstance(methods, list)
            or not methods
            or len(set(methods)) != len(methods)
            or any(
                method not in ("baseline", "kalman", "multi-kalman")
                for method in methods
            )
        ):
            raise SchemaError("case methods must be supported and unique")
        scenario = _scenario(case)
        for seed in seeds:
            with tempfile.TemporaryDirectory(prefix="mst-benchmark-") as temp:
                run_dir = Path(temp) / "run"
                start = time.perf_counter()
                manifest = create_run(run_dir, scenario, seed)
                simulation_s = time.perf_counter() - start
                observations = read_observations(run_dir / "observations.jsonl")
                truth = read_truth(run_dir / "truth.jsonl")
                for method in methods:
                    start = time.perf_counter()
                    innovations = [] if method != "baseline" else None
                    if method == "multi-kalman":
                        estimates = track_multiple_objects(
                            observations,
                            acceleration_std_mps2=tracker["acceleration_std_mps2"],
                            initial_velocity_std_mps=tracker[
                                "initial_velocity_std_mps"
                            ],
                            gate_squared=tracker["gate_squared"],
                            min_hits=tracker["min_hits"],
                            max_missed=tracker["max_missed"],
                            innovations=innovations,
                        )
                    else:
                        estimates = track_single_object(
                            observations,
                            method,
                            acceleration_std_mps2=tracker["acceleration_std_mps2"],
                            initial_velocity_std_mps=tracker[
                                "initial_velocity_std_mps"
                            ],
                            innovations=innovations,
                        )
                    track_path = Path(temp) / f"{method}.jsonl"
                    write_tracks(track_path, estimates)
                    innovation_path = Path(temp) / f"{method}-innovations.jsonl"
                    if innovations is not None:
                        write_innovations(innovation_path, innovations)
                    tracking_s = time.perf_counter() - start
                    start = time.perf_counter()
                    value = report(
                        manifest,
                        truth,
                        estimates,
                        track_path.read_bytes(),
                        gate_m=gate_m,
                        innovations=innovations,
                        innovation_bytes=innovation_path.read_bytes()
                        if innovations is not None
                        else None,
                        observations=observations,
                    )
                    evaluation_s = time.perf_counter() - start
                    value["runtime"] = {
                        "simulation_wall_s": simulation_s,
                        "tracking_wall_s": tracking_s,
                        "evaluation_wall_s": evaluation_s,
                    }
                    value["case"] = case["name"]
                    runs.append(value)
    groups: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    for value in runs:
        groups[(value["case"], value["method"])].append(value)
    summary = []
    for (case, method), values in sorted(groups.items()):
        metrics = [value["metrics"] for value in values]
        summary.append(
            {
                "case": case,
                "method": method,
                "repetitions": len(values),
                "position_rmse_m": _stats(
                    [item["position_rmse_m"] for item in metrics]
                ),
                "coverage": _stats([item["coverage"] for item in metrics]),
                "id_switches": _stats([item["id_switches"] for item in metrics]),
                "unmatched_truth_states": _stats(
                    [item["unmatched_truth_states"] for item in metrics]
                ),
                "unmatched_estimate_states": _stats(
                    [item["unmatched_estimate_states"] for item in metrics]
                ),
                "nees_mean": _stats([item["nees_mean"] for item in metrics]),
                "nis_mean": _stats([item["nis_mean"] for item in metrics]),
                "mota": _stats([item["mota"] for item in metrics]),
                "motp_m": _stats([item["motp_m"] for item in metrics]),
                "simulation_wall_s": _stats(
                    [item["runtime"]["simulation_wall_s"] for item in values]
                ),
                "tracking_wall_s": _stats(
                    [item["runtime"]["tracking_wall_s"] for item in values]
                ),
                "evaluation_wall_s": _stats(
                    [item["runtime"]["evaluation_wall_s"] for item in values]
                ),
            }
        )
    return {
        "schema_version": 2,
        "benchmark_version": __version__,
        "protocol_sha256": hashlib.sha256(
            canonical_json(protocol).encode()
        ).hexdigest(),
        "question": protocol.get("question"),
        "seeds": seeds,
        "matching_gate_m": gate_m,
        "tracker": tracker,
        "summary": summary,
        "runs": runs,
    }


def _cell(stats: dict[str, Any]) -> str:
    if stats["mean"] is None:
        return "NA"
    if stats["sample_stddev"] is None:
        return f"{stats['mean']:.3f}"
    return f"{stats['mean']:.3f} ± {stats['sample_stddev']:.3f}"


def markdown_summary(value: dict[str, Any]) -> str:
    lines = [
        "# Measured synthetic benchmark",
        "",
        f"Protocol SHA-256: `{value['protocol_sha256']}`. Seeds: {', '.join(map(str, value['seeds']))}.",
        "",
        "Values show arithmetic mean ± sample standard deviation across seeds. RMSE and MOTP are conditional on matched states; coverage and unmatched counts must be read alongside them. NIS uses saved Kalman update innovations and is unavailable for the baseline. Runtime includes artifact writing for simulation and tracking, and report construction for evaluation. These generated-fixture results do not establish field performance.",
        "",
        "| Case | Method | n | RMSE (m) | Coverage | MOTA | MOTP (m) | NIS | ID switches | Unmatched truth | Unmatched estimates |",
        "| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
    ]
    for item in value["summary"]:
        lines.append(
            f"| {item['case']} | {item['method']} | {item['repetitions']} | {_cell(item['position_rmse_m'])} | {_cell(item['coverage'])} | {_cell(item['mota'])} | {_cell(item['motp_m'])} | {_cell(item['nis_mean'])} | {_cell(item['id_switches'])} | {_cell(item['unmatched_truth_states'])} | {_cell(item['unmatched_estimate_states'])} |"
        )
    lines.extend(
        [
            "",
            "Full per-seed metrics, timings, hashes, and environment details are in `benchmark.json`.",
            "",
        ]
    )
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--protocol", type=Path, default=ROOT / "examples/benchmark/protocol.json"
    )
    parser.add_argument(
        "--output", required=True, type=Path, help="new output directory"
    )
    args = parser.parse_args()
    try:
        protocol = read_json(args.protocol)
        if not isinstance(protocol, dict):
            raise SchemaError("protocol must be a JSON object")
        value = run_protocol(protocol)
        args.output.mkdir(exist_ok=False)
        with (args.output / "benchmark.json").open("x", encoding="utf-8") as stream:
            stream.write(canonical_json(value) + "\n")
        with (args.output / "summary.md").open("x", encoding="utf-8") as stream:
            stream.write(markdown_summary(value))
        print(f"wrote {len(value['runs'])} runs to {args.output}")
        return 0
    except (OSError, SchemaError, KeyError, TypeError) as exc:
        parser.exit(2, f"benchmark: {exc}\n")


if __name__ == "__main__":
    raise SystemExit(main())
