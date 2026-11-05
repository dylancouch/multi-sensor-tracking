"""Command-line interface for ingestion, tracking, and evaluation."""

from __future__ import annotations

import argparse
import importlib.util
import sys
import time
from collections.abc import Sequence
from pathlib import Path

from . import __version__
from .artifacts import create_run, validate_run
from .association import track_multiple_objects
from .diagnostics import (
    attach_hashes,
    diagnostic_report,
    plot_diagnostics,
    write_diagnostic_report,
)
from .evaluation import read_truth, report, write_report
from .events import AssociationEvent, read_events, write_events
from .ingest import ingest
from .innovations import read_innovations, write_innovations
from .inspection import write_inspection
from .observation_io import read_observations, read_tracks, write_tracks
from .online import _source_record, track_stream
from .schema import Scenario, SchemaError, read_json
from .tracking import track_single_object
from .visualization import plot_run


def _seed(value: str) -> int:
    try:
        seed = int(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("seed must be an integer") from exc
    if not 0 <= seed < 2**64:
        raise argparse.ArgumentTypeError("seed must be between 0 and 2^64-1")
    return seed


def _default_scenario() -> Scenario:
    return Scenario.from_dict(
        {
            "schema_version": 1,
            "frame": "world",
            "position_unit": "m",
            "velocity_unit": "m/s",
            "time_unit": "s",
            "duration_s": 4.0,
            "step_s": 1.0,
            "objects": [
                {"object_id": "object-a", "initial_state": [0, 0, 1, 0.25]},
                {"object_id": "object-b", "initial_state": [8, 2, -0.5, 0.5]},
            ],
            "sensors": [
                {
                    "sensor_id": "sensor-low-noise",
                    "sample_interval_s": 1,
                    "noise_std_m": 0.2,
                },
                {
                    "sensor_id": "sensor-high-noise",
                    "sample_interval_s": 2,
                    "noise_std_m": 0.8,
                },
            ],
        }
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="mst", description="Multi-sensor tracking and evaluation toolkit"
    )
    parser.add_argument("--version", action="version", version=f"mst {__version__}")
    commands = parser.add_subparsers(dest="command", required=True)
    demo = commands.add_parser(
        "demo", help="generate a deterministic two-sensor example"
    )
    demo.add_argument("--output", required=True, type=Path, help="new output directory")
    demo.add_argument("--seed", type=_seed, default=7)
    demo.add_argument("--config", type=Path, help="optional scenario JSON file")
    demo.add_argument(
        "--plot", action="store_true", help="also write a PNG (requires plot extra)"
    )
    simulate = commands.add_parser(
        "simulate", help="generate from a scenario JSON file"
    )
    simulate.add_argument("--config", required=True, type=Path)
    simulate.add_argument(
        "--output", required=True, type=Path, help="new output directory"
    )
    simulate.add_argument("--seed", type=_seed, default=7)
    validate = commands.add_parser("validate", help="validate run artifacts and hashes")
    validate.add_argument("--run", required=True, type=Path, help="run directory")
    ingestion = commands.add_parser(
        "ingest", help="normalize recorded CSV or live JSONL from stdin"
    )
    ingestion.add_argument(
        "--input", type=Path, help="recorded input file; omit for live stdin"
    )
    ingestion.add_argument(
        "--output", required=True, type=Path, help="new observations JSONL"
    )
    ingestion.add_argument("--format", choices=("csv", "jsonl"), required=True)
    ingestion.add_argument(
        "--source-label",
        help="source provenance identifier; required without --contract",
    )
    ingestion.add_argument(
        "--contract", type=Path, help="version 1 Cartesian CSV source contract JSON"
    )
    ingestion.add_argument("--sensor-id", help="CSV sensor identifier")
    ingestion.add_argument(
        "--position-std-m", type=float, help="CSV isotropic position standard deviation"
    )
    track = commands.add_parser("track", help="track objects from observations only")
    track.add_argument("--input", required=True, type=Path, help="observations.jsonl")
    track.add_argument("--output", required=True, type=Path, help="new tracks.jsonl")
    track.add_argument("--innovations", type=Path, help="new Kalman innovations JSONL")
    track.add_argument(
        "--events", type=Path, help="new multi-object association events JSONL"
    )
    track.add_argument(
        "--method", choices=("baseline", "kalman", "multi-kalman"), required=True
    )
    track.add_argument(
        "--acceleration-std",
        type=float,
        default=1.0,
        help="m/s^2, Kalman process model",
    )
    track.add_argument("--initial-velocity-std", type=float, default=10.0, help="m/s")
    track.add_argument(
        "--gate-squared",
        type=float,
        default=9.21,
        help="squared Mahalanobis gate for multi-kalman",
    )
    track.add_argument(
        "--direction-weight",
        type=float,
        default=0.0,
        help="velocity-direction association cost; 0 preserves the baseline",
    )
    track.add_argument(
        "--sensor-order",
        choices=("id", "precision"),
        default="id",
        help="per-epoch sensor processing order for multi-kalman",
    )
    track.add_argument(
        "--min-hits", type=int, default=2, help="hits to confirm a multi-object track"
    )
    track.add_argument(
        "--max-missed", type=int, default=2, help="missed epochs before deletion"
    )
    stream_track = commands.add_parser(
        "track-stream", help="track JSONL as it arrives and flush completed epochs"
    )
    stream_track.add_argument("--input", type=Path, help="replay file; omit for stdin")
    stream_track.add_argument(
        "--source", required=True, type=Path, help="source record JSON"
    )
    stream_track.add_argument(
        "--output", required=True, type=Path, help="new tracks JSONL"
    )
    stream_track.add_argument("--max-lateness-s", type=float, default=0.0)
    stream_track.add_argument("--max-buffered", type=int, default=4096)
    stream_track.add_argument("--max-records", type=int, default=100_000)
    stream_track.add_argument("--max-live-tracks", type=int, default=2048)
    stream_track.add_argument("--expected-interval-s", type=float)
    stream_track.add_argument("--direction-weight", type=float, default=0.0)
    stream_track.add_argument(
        "--sensor-order", choices=("id", "precision"), default="id"
    )
    validate_tracks = commands.add_parser(
        "validate-tracks", help="validate track estimate JSONL"
    )
    validate_tracks.add_argument("--input", required=True, type=Path)
    evaluate = commands.add_parser(
        "evaluate", help="score tracks against scoring-only truth"
    )
    evaluate.add_argument(
        "--run", required=True, type=Path, help="validated synthetic run directory"
    )
    evaluate.add_argument(
        "--tracks", required=True, type=Path, help="track estimate JSONL"
    )
    evaluate.add_argument("--innovations", type=Path, help="matching innovations JSONL")
    evaluate.add_argument(
        "--output", required=True, type=Path, help="new metrics JSON file"
    )
    evaluate.add_argument(
        "--gate-m", type=float, default=10.0, help="maximum match distance in meters"
    )
    diagnose = commands.add_parser(
        "diagnose", help="write per-epoch diagnostic JSON and six-panel plot"
    )
    diagnostic_input = diagnose.add_mutually_exclusive_group(required=True)
    diagnostic_input.add_argument("--run", type=Path, help="validated generated run")
    diagnostic_input.add_argument(
        "--observations", type=Path, help="recorded observations"
    )
    diagnose.add_argument("--source", type=Path, help="recorded source sidecar")
    diagnose.add_argument("--tracks", required=True, type=Path)
    diagnose.add_argument("--innovations", type=Path)
    diagnose.add_argument("--gate-m", type=float, default=10.0)
    diagnose.add_argument("--report", required=True, type=Path, help="new JSON file")
    diagnose.add_argument("--output", required=True, type=Path, help="new PNG or SVG")
    plot = commands.add_parser(
        "plot", help="render a headless trajectory and uncertainty plot"
    )
    plot.add_argument("--run", required=True, type=Path)
    plot.add_argument("--tracks", required=True, type=Path)
    plot.add_argument(
        "--output", required=True, type=Path, help="new .png or .svg file"
    )
    inspect = commands.add_parser(
        "inspect", help="build a self-contained interactive HTML timeline"
    )
    inspect.add_argument("--observations", required=True, type=Path)
    inspect.add_argument("--tracks", required=True, type=Path)
    inspect.add_argument("--events", type=Path)
    inspect.add_argument("--innovations", type=Path)
    inspect.add_argument(
        "--truth", type=Path, help="optional scoring-only reference overlay"
    )
    inspect.add_argument("--gate-m", type=float, default=10.0)
    inspect.add_argument("--output", required=True, type=Path, help="new .html file")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        if args.command == "validate":
            manifest = validate_run(args.run)
            print(
                f"valid run: {manifest.counts['truth']} truth, {manifest.counts['observations']} observations"
            )
        elif args.command == "validate-tracks":
            records = read_tracks(args.input)
            print(f"valid tracks: {len(records)} estimates")
        elif args.command == "ingest":
            if args.contract is None and args.source_label is None:
                raise SchemaError("ingest requires --source-label without --contract")
            count, source_path = ingest(
                args.input,
                args.output,
                format=args.format,
                source_label=args.source_label,
                sensor_id=args.sensor_id,
                position_std_m=args.position_std_m,
                contract_path=args.contract,
            )
            print(f"created {args.output}: {count} observations; source {source_path}")
        elif args.command == "track-stream":
            count, summary_path = track_stream(
                args.input,
                args.output,
                args.source,
                max_lateness_s=args.max_lateness_s,
                max_buffered=args.max_buffered,
                max_records=args.max_records,
                max_live_tracks=args.max_live_tracks,
                expected_interval_s=args.expected_interval_s,
                direction_weight=args.direction_weight,
                sensor_order=args.sensor_order,
            )
            print(f"created {args.output}: {count} estimates; stream {summary_path}")
        elif args.command == "evaluate":
            start = time.perf_counter()
            manifest = validate_run(args.run)
            truth = read_truth(args.run / manifest.artifacts["truth"])
            tracks = read_tracks(args.tracks)
            innovations = (
                read_innovations(args.innovations) if args.innovations else None
            )
            value = report(
                manifest,
                truth,
                tracks,
                args.tracks.read_bytes(),
                gate_m=args.gate_m,
                evaluation_wall_s=time.perf_counter() - start,
                innovations=innovations,
                innovation_bytes=args.innovations.read_bytes()
                if args.innovations
                else None,
                observations=read_observations(
                    args.run / manifest.artifacts["observations"]
                ),
            )
            write_report(args.output, value)
            metrics = value["metrics"]
            print(
                f"evaluated {metrics['matched_states']}/{metrics['truth_states']} truth states; RMSE={metrics['position_rmse_m']} m"
            )
        elif args.command == "diagnose":
            if args.run is not None:
                if args.source is not None:
                    raise SchemaError("--source requires --observations")
                manifest = validate_run(args.run)
                observation_path = args.run / manifest.artifacts["observations"]
                truth_path = args.run / manifest.artifacts["truth"]
                source_path = None
                source_label = f"generated-seed-{manifest.seed}"
                truth = read_truth(truth_path)
            else:
                if args.source is None:
                    raise SchemaError("recorded diagnostics require --source")
                observation_path = args.observations
                assert observation_path is not None
                source_path = args.source
                source_record = _source_record(source_path, observation_path)
                if (
                    source_record["source_kind"] != "recorded"
                    or source_record.get("observation_sha256") is None
                ):
                    raise SchemaError(
                        "recorded diagnostics require a recorded source with an observation hash"
                    )
                source_label = source_record["source_label"]
                truth_path = None
                truth = None
            input_paths = [
                observation_path,
                args.tracks,
                truth_path,
                args.innovations,
                source_path,
            ]
            outputs = [args.report, args.output]
            if (
                len({path.resolve() for path in outputs}) != len(outputs)
                or any(path.exists() for path in outputs)
                or any(
                    path.resolve()
                    in {item.resolve() for item in input_paths if item is not None}
                    for path in outputs
                )
            ):
                raise FileExistsError("diagnostic outputs must be distinct new files")
            value = diagnostic_report(
                read_observations(observation_path),
                read_tracks(args.tracks),
                truth=truth,
                innovations=read_innovations(args.innovations)
                if args.innovations
                else None,
                gate_m=args.gate_m,
            )
            value["source_label"] = source_label
            attach_hashes(
                value,
                observation_path=observation_path,
                track_path=args.tracks,
                truth_path=truth_path,
                innovation_path=args.innovations,
                source_path=source_path,
            )
            try:
                plot_diagnostics(args.output, value)
                write_diagnostic_report(args.report, value)
            except BaseException:
                args.output.unlink(missing_ok=True)
                args.report.unlink(missing_ok=True)
                raise
            print(f"created {args.output} and {args.report}")
        elif args.command == "plot":
            manifest = validate_run(args.run)
            plot_run(
                args.output,
                read_truth(args.run / manifest.artifacts["truth"]),
                read_observations(args.run / manifest.artifacts["observations"]),
                read_tracks(args.tracks),
            )
            print(f"created {args.output}")
        elif args.command == "inspect":
            write_inspection(
                args.output,
                read_observations(args.observations),
                read_tracks(args.tracks),
                events=read_events(args.events) if args.events else None,
                innovations=read_innovations(args.innovations)
                if args.innovations
                else None,
                truth=read_truth(args.truth) if args.truth else None,
                gate_m=args.gate_m,
            )
            print(f"created {args.output}")
        elif args.command == "track":
            observations = read_observations(args.input)
            if args.method == "baseline" and args.innovations:
                raise SchemaError("baseline has no Kalman innovations")
            if args.events and args.method != "multi-kalman":
                raise SchemaError("association events require multi-kalman")
            outputs = [
                item
                for item in (args.output, args.innovations, args.events)
                if item is not None
            ]
            if len({item.resolve() for item in outputs}) != len(outputs) or any(
                item.exists() for item in outputs
            ):
                raise FileExistsError(
                    "track, innovation, and event outputs must be distinct new files"
                )
            innovations = [] if args.innovations else None
            events: list[AssociationEvent] | None = [] if args.events else None
            if args.method == "multi-kalman":
                records = track_multiple_objects(
                    observations,
                    acceleration_std_mps2=args.acceleration_std,
                    initial_velocity_std_mps=args.initial_velocity_std,
                    gate_squared=args.gate_squared,
                    min_hits=args.min_hits,
                    max_missed=args.max_missed,
                    direction_weight=args.direction_weight,
                    sensor_order=args.sensor_order,
                    innovations=innovations,
                    events=events,
                )
            else:
                records = track_single_object(
                    observations,
                    args.method,
                    acceleration_std_mps2=args.acceleration_std,
                    initial_velocity_std_mps=args.initial_velocity_std,
                    innovations=innovations,
                )
            written: list[Path] = []
            try:
                write_tracks(args.output, records)
                written.append(args.output)
                if args.innovations:
                    write_innovations(args.innovations, innovations or [])
                    written.append(args.innovations)
                if args.events:
                    write_events(args.events, events or [])
                    written.append(args.events)
            except Exception:
                for item in written:
                    item.unlink(missing_ok=True)
                raise
            print(f"created {args.output}: {len(records)} estimates")
        else:
            scenario = (
                Scenario.from_dict(read_json(args.config))
                if args.config
                else _default_scenario()
            )
            if (
                args.command == "demo"
                and args.plot
                and importlib.util.find_spec("matplotlib") is None
            ):
                raise SchemaError(
                    "demo --plot requires the optional dependency: pip install -e '.[plot]'"
                )
            simulation_start = time.perf_counter()
            manifest = create_run(args.output, scenario, args.seed)
            simulation_wall_s = time.perf_counter() - simulation_start
            if args.command == "demo":
                observations = read_observations(
                    args.output / manifest.artifacts["observations"]
                )
                tracking_start = time.perf_counter()
                innovations = []
                events = []
                tracks = track_multiple_objects(
                    observations, innovations=innovations, events=events
                )
                track_path = args.output / "tracks.jsonl"
                write_tracks(track_path, tracks)
                innovation_path = args.output / "innovations.jsonl"
                write_innovations(innovation_path, innovations)
                write_events(args.output / "events.jsonl", events)
                tracking_wall_s = time.perf_counter() - tracking_start
                truth = read_truth(args.output / manifest.artifacts["truth"])
                evaluation_start = time.perf_counter()
                value = report(
                    manifest,
                    truth,
                    tracks,
                    track_path.read_bytes(),
                    innovations=innovations,
                    innovation_bytes=innovation_path.read_bytes(),
                    observations=observations,
                )
                evaluation_wall_s = time.perf_counter() - evaluation_start
                value["runtime"] = {
                    "simulation_wall_s": simulation_wall_s,
                    "tracking_wall_s": tracking_wall_s,
                    "evaluation_wall_s": evaluation_wall_s,
                }
                write_report(args.output / "metrics.json", value)
                write_inspection(
                    args.output / "inspect.html",
                    observations,
                    tracks,
                    events=events,
                    innovations=innovations,
                    truth=truth,
                )
                if args.plot:
                    plot_run(args.output / "plot.png", truth, observations, tracks)
            print(
                f"created {args.output}: {manifest.counts['truth']} truth, {manifest.counts['observations']} observations"
            )
    except (OSError, UnicodeError, SchemaError) as exc:
        print(f"mst: {exc}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
