# Evaluation protocol — mandatory

## Scientific rules

- Declare scenario families, seeds, train/tuning/evaluation separation (if parameters are tuned), and metrics before running headline benchmarks. No selecting only favorable random seeds.
- Keep model/tracker tuning separate from frozen final comparison scenarios; no using truth labels for online association.
- Always evaluate at comparable time points and apply documented track-to-truth matching, including penalties for unmatched tracks/objects.
- Report arithmetic mean and spread across seeds, not only a showcase run. Include the scenario generation configuration and source revision in reports.
- State the data source and reference quality for each result. Generated-fixture results do not establish performance on recorded or live data; results without suitable reference truth cannot report truth-based accuracy metrics.

## Source records and evidence coverage

For each new dataset or stream used for development, examples, or evaluation, maintain a source record alongside its import or generation recipe. Record the domain and use case; whether the origin is generated, recorded, or live; measurement type and sensor identity; sampling cadence, timestamp basis, ordering, and known gaps; coordinate frame, units, and any transforms; uncertainty representation and calibration assumptions; provenance, version, and integrity hash where available; reference-truth availability, quality, alignment, and permitted metrics; and license, consent or access basis, redistribution limits, and other permitted-use restrictions. Mark unknown fields explicitly. The record must not expose private data, credentials, or identifying details that cannot be published. If the source itself cannot be redistributed, keep the source record and a permitted import recipe without publishing the data.

Maintain an evidence coverage matrix with one row per evaluated source and columns for domain, origin, measurement type, reference quality, supported metrics, evaluation split or seeds, and reproduction path. List unsupported or unevaluated combinations as gaps. An input adapter demonstrates compatibility with a format, not tracking accuracy on that source. A generated scenario with a new domain label does not establish cross-domain evidence.

input contracts intake examples have source records in `examples/inputs/README.md` (two generated local-frame fixtures) and `examples/recorded/README.md` (NOAA IBTrACS 2020 Laura recipe). These demonstrate conversion and provenance only. The IBTrACS best-track points are used as observations with assumed uncertainty; no independent reference truth or real-data accuracy claim is available for that example.

streaming provides a small recorded Laura replay fixture and source sidecar in `examples/recorded/`. Byte-identical batch and online track files establish that the two processing paths agree for the same ordered observations. This is a reproducibility check, not an independent truth-based performance result. A stream's inferred missing sensor epochs depend on an explicitly supplied nominal cadence; they are not detection-miss metrics. Dropped-record counters describe intake quality, not accuracy.

Predeclare source selection, splits or seeds, and metrics before comparisons. Report results per source and domain before any aggregate; pool only sources whose metric definitions, reference quality, and evaluation conditions are comparable, and state the weighting. Report truth-free diagnostics separately from reference-based accuracy. Claim generality only over the domains, measurement types, and source conditions actually evaluated. Use generated fixtures for controlled tests and recorded or live evidence for external validity when permitted and suitable; neither substitutes for the other.

## Core metrics

1. Position RMSE in meters on matched states, with coverage (fraction of truth states matched) reported alongside it. RMSE alone can improve by discarding difficult tracks.
2. Position MAE or median position error (meters), alongside RMSE.
3. Track identity stability: ID switches counted under an explicit truth-to-estimate matching convention.
4. Missed/false tracks or unmatched truth/estimate counts per scenario; define whether per-frame or track-level.
5. State uncertainty: NEES where full state truth and covariance are valid; NIS where innovation statistics are available. Report finite-sample limitations and reject singular/invalid covariance as appropriate.
6. Runtime measurement (wall time, machine details), with separate simulation/tracking/evaluation costs.

The scorer reports CLEAR MOT MOTA and MOTP under the exact-time, 2D distance-gated matching convention below. MOTA is `1 - (unmatched truth + unmatched estimates + ID switches) / truth states` and can be negative. MOTP is mean Euclidean position error in meters over matched states, or `null` when there are no matches. These formulas follow the [MOTChallenge definitions](https://link.springer.com/article/10.1007/s11263-020-01393-0); MOTChallenge uses image-box overlap and its own association details, so these planar scores must not be compared directly with MOTChallenge leaderboard numbers. HOTA remains a possible later addition.

## Benchmarks

- **Sanity:** no noise, one object, known constant velocity and aligned observations. Check reconstructed positions, covariance behavior and units.
- **Routine:** two or more objects, two independent position sensors, configurable independent noise and timing.
- **Crossing:** two objects cross paths without sharing identities; explicitly quantify any ID switches.
- **Degraded:** one sensor has missed observations, false alarms, temporal misalignment, and increased noise; include at least a single-parameter sweep per variable and a combined stress case.
- **Reproducibility:** same scenario and seed produces byte-for-byte equivalent canonical output or numerically identical arrays with explicitly documented floating-point tolerance; different seeds produce meaningfully different observations.

## Experimental fairness

The baseline and Kalman tracker receive identical tracker-facing observations and comparable initialization rules. Tune on development scenarios; freeze parameters before evaluating held-out seeds. Compare computational costs honestly. Never use privileged simulator state to initialize a tracker unless both methods receive the same clearly disclosed oracle initialization and results are labeled oracle-assisted.

## Reporting template

Document: question, data source and provenance, generation process when applicable, reference-truth quality, methods/configs, predeclared metrics, number of repetitions, aggregate results (with spread), notable failure cases, reproduction commands, known limitations and supported conclusions. Avoid calling a model 'robust' without defined perturbation levels and results.

## Implemented version 1 scoring and experiment protocol

`mst evaluate --run RUN --tracks TRACKS --output metrics.json` first validates the run manifest, truth, and observations, then reads the independently generated track file. Only this evaluation command and `examples/benchmark/run.py` read truth. A report records scenario, observation, and track hashes; package version; source revision and dirty state when available; seed; dependency/Python/machine architecture versions; and the evaluation wall time. The standalone CLI does not know simulation or tracking wall times and records them as `null`. The experiment runner measures those phases separately.

At each exact truth timestamp, scoring takes the final non-deleted estimate for each track ID at that timestamp. Estimates reported at other timestamps are counted as unscored, with no interpolation or hindsight prediction. It sorts truth object IDs and track IDs, uses minimum-total-distance assignment with a maximum distance of 10 meters by default, and favors the maximum number of gated matches. Matched planar Euclidean errors yield position RMSE and median position error in meters. Coverage is matched truth states divided by all truth states. Unmatched truth and estimate counts are **per truth frame**, not unique trajectory counts. Tentative and confirmed tracks both count as estimates; deleted tracks do not.

An ID switch is counted when an object's assigned tracker ID differs from its previous matched frame, including across an unmatched gap. NEES uses the full four-state error and a positive-definite estimate covariance; singular covariances are skipped and counted. Baseline covariance is heuristic, so baseline NEES is unavailable. NIS uses each saved Kalman update residual `r = z - H x_prior` and innovation covariance `S = H P_prior H^T + R`, with value `r^T S^-1 r`. Initial observations that create a track have no innovation. Singular `S` is skipped and counted, including consistent noiseless updates. NIS is independent of reference truth and is computed only when an innovations artifact is supplied. This metric does not by itself demonstrate calibration; interpret its sample count and data assumptions. These conventions are implemented in `mst/evaluation.py` and `mst/innovations.py`.

`mst track --innovations INNOVATIONS.jsonl` writes versioned update diagnostics without changing version 1 track records. `mst evaluate --innovations INNOVATIONS.jsonl` validates their track/time links and records the artifact SHA-256. Existing track files remain readable and report `nis_mean: null` when no innovation artifact is provided. `mst demo` writes `innovations.jsonl` automatically.

`mst inspect` can show accepted and rejected association candidates, track births and lifecycle changes from a separate version 1 `events.jsonl` sidecar. Without truth, these are tracker decisions, not reference-based ID switches or accuracy. With a separate truth file, the viewer derives position errors and ID-switch labels using the scorer's exact-time, 10 m default planar gate and final live estimate at each timestamp. These views are exploratory; headline claims still require the frozen benchmark protocol and complete evaluation report. Missing innovation or reference inputs are shown as unavailable, not as zero error.

`examples/benchmark/protocol.json` freezes methods, tracker parameters, the evaluation gate, scenario variants, and evaluation seeds 101, 102, 103. No parameters were tuned on these seeds; development fixtures used other seeds. The runner compares baseline and Kalman on identical one-object observations, compares individual sensors with fused observations on the same routine truth, and varies one high-noise sensor's noise, miss probability, false-alarm probability, and timestamp offset separately against the routine-fused reference. It also runs a crossing case and a combined degradation. Aggregates are arithmetic means and sample standard deviations across seeds. Runtime varies by machine and load; deterministic output applies to simulation/metrics, not wall times.

Reproduce with:

```bash
.venv/bin/python -m examples.benchmark.run --output output/benchmark-reproduction
```

The output directory must be new. Results in `examples/benchmark/` are generated by that script and include exact per-seed data and limitations; no field-performance inference is supported.
