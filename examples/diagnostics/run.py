"""Reproduce generated and truth-free recorded diagnostic evidence."""

from __future__ import annotations

import argparse
import copy
import json
from pathlib import Path
from typing import Any

from mst.artifacts import create_run, validate_run
from mst.association import track_multiple_objects
from mst.diagnostics import (
    attach_hashes,
    diagnostic_report,
    plot_diagnostics,
    write_diagnostic_report,
)
from mst.evaluation import read_truth
from mst.innovations import Innovation, write_innovations
from mst.observation_io import read_observations, write_tracks
from mst.online import _source_record
from mst.schema import Scenario, SchemaError, canonical_json

ROOT = Path(__file__).resolve().parents[2]
PROTOCOL = Path(__file__).with_name("protocol.json")


def run(output: Path) -> dict[str, Any]:
    protocol = json.loads(PROTOCOL.read_text())
    if output.exists():
        raise FileExistsError(output)
    output.mkdir(parents=True)
    summary: dict[str, Any] = {"schema_version": 1, "protocol": protocol, "runs": []}
    gate = protocol["matching_gate_m"]
    params = {k: v for k, v in protocol["tracker"].items() if k != "method"}
    for case in protocol["generated_cases"]:
        config = ROOT / "examples/scenarios" / case["config"]
        scenario_data = copy.deepcopy(json.loads(config.read_text()))
        for sensor in scenario_data["sensors"]:
            sensor.update(case.get("sensor_overrides", {}).get(sensor["sensor_id"], {}))
        scenario = Scenario.from_dict(scenario_data)
        for seed in protocol["seeds"]:
            name = f"{case['name']}-{seed}"
            directory = output / name
            manifest = create_run(directory, scenario, seed)
            validate_run(directory)
            obs_path = directory / manifest.artifacts["observations"]
            truth_path = directory / manifest.artifacts["truth"]
            observations = read_observations(obs_path)
            truth = read_truth(truth_path)
            innovations: list[Innovation] = []
            tracks = track_multiple_objects(
                observations, innovations=innovations, **params
            )
            track_path = directory / "tracks.jsonl"
            innovation_path = directory / "innovations.jsonl"
            write_tracks(track_path, tracks)
            write_innovations(innovation_path, innovations)
            report = diagnostic_report(
                observations, tracks, truth=truth, innovations=innovations, gate_m=gate
            )
            report["source_label"] = f"generated-{case['name']}-{seed}"
            attach_hashes(
                report,
                observation_path=obs_path,
                track_path=track_path,
                truth_path=truth_path,
                innovation_path=innovation_path,
            )
            write_diagnostic_report(directory / "diagnostics.json", report)
            if seed == protocol["seeds"][0]:
                plot_diagnostics(directory / "diagnostics.png", report)
            summary["runs"].append(
                {
                    "source": name,
                    "kind": "generated",
                    "identity": report["identity"],
                    "scoring": {
                        key: report["scoring"][key]
                        for key in (
                            "matched_states",
                            "unmatched_truth_states",
                            "unmatched_estimate_states",
                            "id_switches",
                            "position_rmse_m",
                            "nees_mean",
                            "nis_mean",
                        )
                    },
                    "input_sha256": report["input_sha256"],
                }
            )
    for source in protocol["recorded_sources"]:
        name = f"recorded-{source}"
        directory = output / name
        directory.mkdir()
        obs_path = ROOT / "examples/recorded" / f"{source}.jsonl"
        source_path = ROOT / "examples/recorded" / f"{source}.source.json"
        source_record = _source_record(source_path, obs_path)
        if (
            source_record["source_kind"] != "recorded"
            or source_record.get("observation_sha256") is None
        ):
            raise SchemaError("recorded evidence needs a hashed recorded source")
        observations = read_observations(obs_path)
        innovations = []
        tracks = track_multiple_objects(observations, innovations=innovations, **params)
        track_path = directory / "tracks.jsonl"
        innovation_path = directory / "innovations.jsonl"
        write_tracks(track_path, tracks)
        write_innovations(innovation_path, innovations)
        report = diagnostic_report(
            observations, tracks, innovations=innovations, gate_m=gate
        )
        report["source_label"] = source
        attach_hashes(
            report,
            observation_path=obs_path,
            track_path=track_path,
            innovation_path=innovation_path,
            source_path=source_path,
        )
        write_diagnostic_report(directory / "diagnostics.json", report)
        plot_diagnostics(directory / "diagnostics.png", report)
        if report["identity"] is not None or report["scoring"] is not None:
            raise SchemaError("recorded source has no independent truth")
        summary["runs"].append(
            {
                "source": name,
                "kind": "recorded",
                "identity": None,
                "scoring": None,
                "nis_samples": sum(item["nis_samples"] for item in report["series"]),
                "input_sha256": report["input_sha256"],
            }
        )
    (output / "summary.json").write_text(canonical_json(summary) + "\n")
    return summary


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    summary = run(args.output)
    print(f"created {len(summary['runs'])} diagnostic runs in {args.output}")


if __name__ == "__main__":
    main()
