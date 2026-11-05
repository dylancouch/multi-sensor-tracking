# Multi-Sensor Tracking

Multi-Sensor Tracking is a toolkit for estimating object trajectories from multiple observation streams and comparing tracking methods. It accepts timestamped position observations and can score estimates when reference trajectories are available. The current demo and checked-in benchmark generate their own observations; live sensor connections and data adapters are possible future additions.

## Project map

| Path | What belongs there |
| --- | --- |
| `src/mst/` | Installable Python application package: simulation, sensors, trackers, scoring, plots, and CLI. |
| `examples/` | Scenarios to run, a frozen benchmark with measured results, and a small checked-in sample. |
| `docs/EVALUATION.md` | Metric definitions, scoring conventions, benchmark protocol, and limitations. |
| `output/` | Your generated runs; generated files stay local. |

`pyproject.toml` defines installation metadata and runtime dependencies. `src/` contains the importable Python package. Packaging tools may create `build/` or `dist/`; those are disposable generated files.

Inside `examples/`, `scenarios/` contains editable inputs, `benchmark/` keeps its protocol, reproduction code, report, and results together, and `sample/` is a small checked-in output. The many files inside `output/` are local run data and are ignored by Git.

## Run a demo

Use Python 3.11 or newer. From the repository root:

```bash
python3 -m venv .venv
.venv/bin/python -m pip install '.[plot]'
.venv/bin/mst demo --output output/demo --seed 7 --plot
.venv/bin/mst validate --run output/demo
```

`output/demo` must be new. If it already exists, choose another name such as `output/demo-2`. The demo writes a manifest, separate `truth.jsonl` and `observations.jsonl`, `tracks.jsonl`, `metrics.json`, and `plot.png`. The tracker receives observations only; truth is read afterward for scoring and plotting. To use a different scenario:

```bash
.venv/bin/mst simulate --config examples/scenarios/degraded.json --output output/degraded --seed 7
.venv/bin/mst track --input output/degraded/observations.jsonl --output output/degraded/tracks.jsonl --method multi-kalman
.venv/bin/mst evaluate --run output/degraded --tracks output/degraded/tracks.jsonl --output output/degraded/metrics.json
```

`mst --help` lists all commands. `mst track` also supports `baseline` and `kalman` for the one-object scenario. It needs only an observation file, not the run manifest or truth file. Outputs are created exclusively, so commands do not silently replace files.

## Reproduce the benchmark

The benchmark protocol and its measured results live together in [examples/benchmark](examples/benchmark/README.md). Run it into a new local folder, then compare deterministic metrics with the checked-in results:

```bash
.venv/bin/python -m examples.benchmark.run --output output/benchmark-reproduction
.venv/bin/python -m examples.benchmark.verify --actual output/benchmark-reproduction/benchmark.json
```

The results use three held-out seeds and include identity-switch failures in a crossing scenario. They establish behavior only for these synthetic fixtures. See [the evaluation protocol](docs/EVALUATION.md) for matching, uncertainty, and timing definitions.

![Synthetic sample trajectories, observations, and estimated tracks](examples/sample/plot.png)

See [the evaluation protocol](docs/EVALUATION.md) for scoring definitions, benchmark methods, and limitations.
