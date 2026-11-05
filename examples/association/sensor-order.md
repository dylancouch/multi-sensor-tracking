# Sensor-order association comparison

The [protocol](sensor-order-protocol.json) fixed the question, cases, tracker parameters, source selection, 10 m evaluation gate, and **new held-out seeds 301–320** before the comparison. Development used seeds 7–12 and the previously published benchmark seeds 101–103. The earlier 201–205 split was not used to select this method. Both methods receive identical observations. The baseline processes same-time sensors by ID; the variant processes them by increasing mean covariance trace, with ID as a deterministic tie-breaker. Gating, assignment, filtering, and track lifecycle remain otherwise identical. This uses reported measurement uncertainty, not reference truth, and assumes the covariance values are meaningful. ID order remains the default.

The four generated cases are the short crossing, routine two-sensor scenario, the routine scenario with a 0.5 false-alarm probability on the high-noise sensor, and the combined degraded scenario. Each has analytic generated truth and 20 independently seeded observation sets. The fifth source is the eight-record permitted NOAA IBTrACS Laura replay, which has no independent reference and receives only truth-free diagnostics. The runner records scenario, observation, source-record, track, and protocol hashes. The [frozen deterministic results](sensor-order-results.json) contain all 162 method/case/seed records; runtime and environment are available in a fresh run's full JSON.

## Held-out results

Means ± sample standard deviations across 20 generated seeds are shown below. Both methods had coverage 1.0 and zero unmatched truth states in all four cases. Position RMSE is conditional on matches. ID switches use the documented exact-time, 10 m distance matching policy.

| Case | Method | ID switches | Position RMSE (m) | Unmatched estimate states | MOTA |
| --- | --- | ---: | ---: | ---: | ---: |
| Crossing | ID order | 1.65 ± 2.08 | 0.1396 ± 0.0205 | 0.30 ± 1.13 | 0.805 ± 0.268 |
| Crossing | Precision first | 1.30 ± 1.87 | 0.1399 ± 0.0207 | 0.30 ± 1.13 | 0.840 ± 0.223 |
| Routine | ID order | 0.10 ± 0.45 | 0.2778 ± 0.0403 | 0.15 ± 0.67 | 0.975 ± 0.112 |
| Routine | Precision first | 0.10 ± 0.45 | 0.2770 ± 0.0396 | 0.15 ± 0.67 | 0.975 ± 0.112 |
| False alarms | ID order | 0.30 ± 0.73 | 0.2752 ± 0.0412 | 3.95 ± 2.11 | 0.575 ± 0.220 |
| False alarms | Precision first | 1.55 ± 1.19 | 0.2766 ± 0.0420 | 5.35 ± 3.25 | 0.310 ± 0.419 |
| Degraded | ID order | 2.60 ± 2.68 | 0.2814 ± 0.0439 | 1.85 ± 1.66 | 0.555 ± 0.429 |
| Degraded | Precision first | 2.60 ± 2.68 | 0.2814 ± 0.0439 | 1.85 ± 1.66 | 0.555 ± 0.429 |

On crossing seeds, precision first reduced switches in four runs, increased them in two, and left fourteen unchanged. The mean paired difference was −0.35 switches with sample standard deviation 2.18. This is a **small, unstable improvement on this scorer and source**, not evidence of a general identity advantage. The false-alarm regression is material: mean switches rose by 1.25, unmatched estimate states by 1.40, and MOTA fell by 0.265. The degraded case is unchanged because its high-noise sensor's timestamp offset puts its observations in separate epochs. The crossing source's objects nearly coincide; distance-only reference matching can itself change identity at the overlap. Thus the scorer's ID-switch changes do not prove physical identity preservation.

Mean NEES / NIS by case were 4.52 / 0.97 versus 4.02 / 0.93 for crossing, 2.64 / 1.20 versus 2.63 / 1.20 for routine, 3.23 / 1.16 versus 6.04 / 1.08 for false alarms, and 21.14 / 1.17 for both methods on degraded inputs. The frozen records include sample counts. These averages do not establish calibrated uncertainty, especially with short trajectories and high variability. No EKF or UKF is justified: the supported state and measurement models are linear Cartesian ones.

The recorded Laura replay yielded one track, one birth, seven matches, and seven usable NIS updates for each method, with mean NIS 0.00000573. This single-object source cannot test sensor ordering or multi-object identity. It provides no truth-based accuracy or identity claim.

Precision ordering adds per-epoch covariance aggregation and sorting, about O(S×M + S log S) for S sensors and M observations with the current grouping. The dominant gated Hungarian assignment is unchanged. On the measured Linux x86_64 Python 3.15.0 environment with NumPy 2.5.4 and SciPy 1.18.1, mean tracking wall times were:

| Source | ID order (ms) | Precision first (ms) |
| --- | ---: | ---: |
| Crossing | 2.26 | 2.23 |
| Routine | 2.22 | 2.23 |
| False alarms | 2.68 | 2.78 |
| Degraded | 2.89 | 2.90 |
| Recorded Laura | 1.61 | 1.62 |

These short wall times are noisy and are not throughput claims. The algorithm remains optional because its false-alarm failure outweighs the narrow crossing gain as a general default.

## Reproduce and verify

From the repository root after installation, choose a new output path:

```bash
python -m examples.association.run --protocol examples/association/sensor-order-protocol.json --output output/sensor-order-comparison.json
python -m examples.association.verify --actual output/sensor-order-comparison.json
```

The verifier checks the protocol hash, per-run source and track hashes, and numerical metrics against the checked-in results with a 1e-9 floating-point tolerance. It excludes variable runtime, environment, and Git dirty state. Recorded-source integrity is checked against its source sidecar before tracking. No source-specific results are pooled.
