# Synthetic tracking experiment report

## Question and frozen design

How do the one-object baseline and Kalman filter compare on identical observations, and how do sensor fusion and controlled degradation affect multi-object tracking? `protocol.json` fixed the scenario variants, tracker parameters, evaluation gate, metrics, and held-out seeds **101, 102, 103** before the reported run. Parameters were not tuned on those seeds. The checked-in run used package version 0.4.0 from clean revision `1ffc4667272cd91fb9be4c26778505ba4b278d48` on Linux x86_64, Python 3.14.8, NumPy 2.5.4, SciPy 1.18.1, with 32 logical CPUs.

The generator uses analytic constant-velocity world-frame truth and two independent Cartesian position sensors. The baseline and one-object Kalman filter receive the same observation arrays and initialization rules. The multi-object tracker uses a fixed squared Mahalanobis gate of 9.21, two hits to confirm, and deletion after more than two missed observation epochs. The evaluator uses a fixed 10 m matching gate at exact truth timestamps, with per-frame unmatched penalties. Full definitions and uncertainty limitations are in [`docs/EVALUATION.md`](../../docs/EVALUATION.md).

## Measured results

These are arithmetic means ± sample standard deviations across three seeds. RMSE is conditional on matched truth states; coverage and unmatched counts are required context. The complete 39 per-run records, hashes, NEES values, and separate wall times are in [`results.json`](results.json); the generated table is in [`summary.md`](summary.md).

| Case | Method | Position RMSE (m) | Coverage | ID switches | Unmatched estimate states |
| --- | --- | ---: | ---: | ---: | ---: |
| Noise-free sanity | Baseline | 0.000 ± 0.000 | 1.000 | 0.000 | 0.000 |
| Noise-free sanity | Kalman | 0.000 ± 0.000 | 1.000 | 0.000 | 0.000 |
| One object, noisy | Baseline | 0.255 ± 0.085 | 1.000 | 0.000 | 0.000 |
| One object, noisy | Kalman | 0.235 ± 0.077 | 1.000 | 0.000 | 0.000 |
| Routine, low sensor only | Multi-Kalman | 0.296 ± 0.057 | 1.000 | 0.000 | 0.000 |
| Routine, high sensor only | Multi-Kalman | 1.116 ± 0.227 | 0.600 | 0.667 | 0.000 |
| Routine, fused | Multi-Kalman | 0.293 ± 0.052 | 1.000 | 0.333 | 0.333 |
| Crossing | Multi-Kalman | 0.149 ± 0.025 | 1.000 | 4.333 | 0.333 |
| Combined degradation | Multi-Kalman | 0.298 ± 0.059 | 1.000 | 1.000 | 1.333 |

The one-object Kalman mean RMSE was 0.020 m lower than the baseline over these three seeds; that small sample does not establish a general advantage. Fusion's routine RMSE was close to the low-noise sensor alone, while the fused case had some identity switches and false tracks. The high-noise sensor alone sampled every two seconds, giving only 0.600 coverage and four unmatched truth states per seed, so its RMSE is not directly comparable without that coverage context. Crossing produced frequent ID switches despite low position RMSE. The one-variable noise, miss, false-alarm, and timing-offset sweeps are in the full summary. In the false-alarm sweep, unmatched estimate states averaged 3.333 ± 2.517 per seed.

Mean wall time for the routine fused case was 0.00185 s simulation, 0.00776 s tracking, and 0.00685 s evaluation on this machine. These tiny durations include artifact writing for simulation/tracking and provenance collection for evaluation; they are not throughput claims. The JSON contains every per-seed timing.

## Reproduction and limits

From a fresh editable install, run:

```bash
.venv/bin/python -m examples.benchmark.run --output output/benchmark-reproduction
```

The output directory must not exist. Reproduction should match per-seed numerical metrics under the same Python and dependency versions; wall times and source dirty state can differ. A small generated run is checked in under [`sample`](../sample/), with separate truth and tracker-facing observation files, multi-object estimates, a metrics report, and a [headless trajectory plot](../sample/plot.png). The plot was rendered later with package version 0.6.0 from the validated sample records; it is a visual aid, not a correctness oracle. The records can be validated using `mst validate --run examples/sample` and `mst validate-tracks --input examples/sample/tracks.jsonl`.

The benchmark is synthetic, planar, short, and based on only three held-out seeds. It does not test physical sensors, deployment conditions, or real surveillance data. The offset model is a fixed reported-time shift. The evaluator does not interpolate off-grid track states. NEES excludes singular covariance cases and is unavailable for the heuristic baseline covariance; NIS is unavailable because innovations are not persisted. No claim of field performance, robustness, or calibrated operational safety follows from these results.
