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
from .evaluation import read_truth, report, write_report
from .ingest import ingest
from .innovations import read_innovations, write_innovations
from .observation_io import read_observations, read_tracks, write_tracks
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
        "--source-label", required=True, help="source provenance identifier"
    )
    ingestion.add_argument("--sensor-id", help="CSV sensor identifier")
    ingestion.add_argument(
        "--position-std-m", type=float, help="CSV isotropic position standard deviation"
    )
    track = commands.add_parser("track", help="track one object from observations only")
    track.add_argument("--input", required=True, type=Path, help="observations.jsonl")
    track.add_argument("--output", required=True, type=Path, help="new tracks.jsonl")
    track.add_argument("--innovations", type=Path, help="new Kalman innovations JSONL")
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
        "--min-hits", type=int, default=2, help="hits to confirm a multi-object track"
    )
    track.add_argument(
        "--max-missed", type=int, default=2, help="missed epochs before deletion"
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
    plot = commands.add_parser(
        "plot", help="render a headless trajectory and uncertainty plot"
    )
    plot.add_argument("--run", required=True, type=Path)
    plot.add_argument("--tracks", required=True, type=Path)
    plot.add_argument(
        "--output", required=True, type=Path, help="new .png or .svg file"
    )
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
            count, source_path = ingest(
                args.input,
                args.output,
                format=args.format,
                source_label=args.source_label,
                sensor_id=args.sensor_id,
                position_std_m=args.position_std_m,
            )
            print(f"created {args.output}: {count} observations; source {source_path}")
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
        elif args.command == "plot":
            manifest = validate_run(args.run)
            plot_run(
                args.output,
                read_truth(args.run / manifest.artifacts["truth"]),
                read_observations(args.run / manifest.artifacts["observations"]),
                read_tracks(args.tracks),
            )
            print(f"created {args.output}")
        elif args.command == "track":
            observations = read_observations(args.input)
            if args.method == "baseline" and args.innovations:
                raise SchemaError("baseline has no Kalman innovations")
            if args.innovations and (args.output.exists() or args.innovations.exists()):
                raise FileExistsError("track or innovation output already exists")
            innovations = [] if args.innovations else None
            if args.method == "multi-kalman":
                records = track_multiple_objects(
                    observations,
                    acceleration_std_mps2=args.acceleration_std,
                    initial_velocity_std_mps=args.initial_velocity_std,
                    gate_squared=args.gate_squared,
                    min_hits=args.min_hits,
                    max_missed=args.max_missed,
                    innovations=innovations,
                )
            else:
                records = track_single_object(
                    observations,
                    args.method,
                    acceleration_std_mps2=args.acceleration_std,
                    initial_velocity_std_mps=args.initial_velocity_std,
                    innovations=innovations,
                )
            write_tracks(args.output, records)
            if args.innovations:
                try:
                    write_innovations(args.innovations, innovations or [])
                except Exception:
                    args.output.unlink(missing_ok=True)
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
                tracks = track_multiple_objects(observations, innovations=innovations)
                track_path = args.output / "tracks.jsonl"
                write_tracks(track_path, tracks)
                innovation_path = args.output / "innovations.jsonl"
                write_innovations(innovation_path, innovations)
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
