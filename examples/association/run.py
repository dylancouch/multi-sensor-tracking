"""Reproduce the predeclared association comparison; never use truth for association."""

from __future__ import annotations

import argparse
import hashlib
import json
import statistics
import time
from pathlib import Path
from typing import Any

from mst.association import track_multiple_objects
from mst.evaluation import score
from mst.events import AssociationEvent
from mst.innovations import Innovation
from mst.observation_io import read_observations
from mst.provenance import environment_versions, source_state
from mst.schema import Scenario, SchemaError, TrackEstimate, canonical_json, read_json
from mst.sensors import generate_observations
from mst.simulation import generate_truth

ROOT = Path(__file__).resolve().parents[2]
PROTOCOL = Path(__file__).with_name("protocol.json")
METRICS = (
    "id_switches",
    "coverage",
    "position_rmse_m",
    "unmatched_truth_states",
    "unmatched_estimate_states",
    "nees_mean",
    "nis_mean",
    "nis_samples",
)


def _stats(values: list[int | float | None]) -> dict[str, float | int | None]:
    valid = [float(value) for value in values if value is not None]
    return {
        "n": len(valid),
        "mean": statistics.fmean(valid) if valid else None,
        "sample_stddev": statistics.stdev(valid) if len(valid) > 1 else None,
    }


def _diagnostics(
    events: list[AssociationEvent], estimates: list[TrackEstimate]
) -> dict[str, int]:
    return {
        "births": sum(item.kind == "birth" for item in events),
        "matches": sum(item.kind == "match" for item in events),
        "confirmed_tracks": len(
            {item.track_id for item in estimates if item.lifecycle == "confirmed"}
        ),
        "track_count": len({item.track_id for item in estimates}),
    }


def run() -> dict[str, Any]:
    protocol = read_json(PROTOCOL)
    assert isinstance(protocol, dict)
    tracker = protocol["tracker"]
    weight = protocol["variant"]["direction_weight"]
    runs: list[dict[str, Any]] = []
    for case in protocol["generated_cases"]:
        scenario_path = ROOT / "examples/scenarios" / case["config"]
        scenario_data = scenario_path.read_bytes()
        scenario = Scenario.from_dict(read_json(scenario_path))
        truth = generate_truth(scenario)
        for seed in protocol["held_out_seeds"]:
            observations = generate_observations(scenario, truth, seed)
            observation_hash = hashlib.sha256(
                "".join(
                    canonical_json(item.to_dict()) + "\n" for item in observations
                ).encode()
            ).hexdigest()
            for method, direction_weight in (("baseline", 0.0), ("direction", weight)):
                innovations: list[Innovation] = []
                start = time.perf_counter()
                estimates = track_multiple_objects(
                    observations,
                    **tracker,
                    direction_weight=direction_weight,
                    innovations=innovations,
                )
                elapsed = time.perf_counter() - start
                metrics = score(
                    truth,
                    estimates,
                    gate_m=protocol["matching_gate_m"],
                    innovations=innovations,
                    observations=observations,
                )
                runs.append(
                    {
                        "source": case["name"],
                        "source_kind": "generated",
                        "seed": seed,
                        "method": method,
                        "scenario_sha256": hashlib.sha256(scenario_data).hexdigest(),
                        "observation_sha256": observation_hash,
                        "config_id": estimates[0].config_id,
                        "metrics": {key: metrics[key] for key in METRICS},
                        "tracking_wall_s": elapsed,
                    }
                )
    recorded_path = ROOT / protocol["recorded_source"]
    source_path = recorded_path.with_suffix(".source.json")
    source_record = read_json(source_path)
    if not isinstance(source_record, dict):
        raise SchemaError("recorded source manifest must be an object")
    source_hash = hashlib.sha256(recorded_path.read_bytes()).hexdigest()
    if source_record.get("observation_sha256") != source_hash:
        raise SchemaError("recorded observations do not match the source record")
    observations = read_observations(recorded_path)
    for method, direction_weight in (("baseline", 0.0), ("direction", weight)):
        innovations = []
        events: list[AssociationEvent] = []
        start = time.perf_counter()
        estimates = track_multiple_objects(
            observations,
            **tracker,
            direction_weight=direction_weight,
            innovations=innovations,
            events=events,
        )
        elapsed = time.perf_counter() - start
        runs.append(
            {
                "source": "ibtracs_laura_2020",
                "source_kind": "recorded",
                "method": method,
                "observation_sha256": source_hash,
                "source_record_sha256": hashlib.sha256(
                    source_path.read_bytes()
                ).hexdigest(),
                "config_id": estimates[0].config_id,
                "diagnostics": _diagnostics(events, estimates),
                "nis_mean": statistics.fmean(
                    item.nis for item in innovations if item.nis is not None
                )
                if any(item.nis is not None for item in innovations)
                else None,
                "nis_samples": sum(item.nis is not None for item in innovations),
                "tracking_wall_s": elapsed,
            }
        )
    summary = []
    for source in dict.fromkeys(item["source"] for item in runs):
        for method in ("baseline", "direction"):
            selected = [
                item
                for item in runs
                if item["source"] == source and item["method"] == method
            ]
            fields = (
                METRICS
                if selected[0]["source_kind"] == "generated"
                else tuple(selected[0]["diagnostics"]) + ("nis_mean", "nis_samples")
            )
            summary.append(
                {
                    "source": source,
                    "method": method,
                    "repetitions": len(selected),
                    **{
                        field: _stats(
                            [
                                item["metrics"][field]
                                if "metrics" in item
                                else item["diagnostics"].get(field, item.get(field))
                                for item in selected
                            ]
                        )
                        for field in fields
                    },
                    "tracking_wall_s": _stats(
                        [item["tracking_wall_s"] for item in selected]
                    ),
                }
            )
    return {
        "protocol_sha256": hashlib.sha256(PROTOCOL.read_bytes()).hexdigest(),
        "source_state": source_state(),
        "environment": environment_versions(),
        "runs": runs,
        "summary": summary,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    result = run()
    with args.output.open("x", encoding="utf-8") as stream:
        json.dump(result, stream, sort_keys=True, indent=2, allow_nan=False)
        stream.write("\n")


if __name__ == "__main__":
    main()
