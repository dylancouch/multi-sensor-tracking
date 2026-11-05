# Tracking diagnostics and source coverage

`protocol.json` freezes four generated scenario families, seeds 101–103, the 10 m reference matching gate, the default multi-Kalman tracker, and two recorded sources. The generated runs reuse seeds from the earlier fixed benchmark to diagnose known cases; this is a diagnostic extension, not a fresh held-out tuning experiment. `results.json` contains all twelve generated runs and two truth-free recorded runs, including input hashes. The runner writes validated generated run artifacts, tracks, innovations, JSON diagnostics per run, six-panel plots for the first seed of each generated case, and plots for both recorded sources. The plots report sample counts and label unavailable metrics. The checked-in summary excludes runtime and environment-dependent manifest fields.

```bash
.venv/bin/python -m examples.diagnostics.verify
.venv/bin/python -m examples.diagnostics.run --output output/diagnostic-reproduction
```

The first command checks the five hand-counted identity vectors in `idf1-vectors.json`, then regenerates the complete summary and compares it byte for byte with `results.json`. Both commands require the plotting extra. The output directory must be new. `mst diagnose` also accepts a validated generated `--run`, or `--observations` plus a matching recorded `--source` sidecar; it never accepts unverified recorded data without a source record.

## Metric and matching policy

IDF1 follows the global identity-assignment definition in [Ristani et al.](https://arxiv.org/abs/1609.01775) and the pair-count assignment in [TrackEval's reference implementation](https://github.com/JonathonLuiten/TrackEval/blob/master/trackeval/metrics/identity.py): count every truth/track pair at the *same timestamp* within the 10 m planar gate, choose one sequence-global truth-ID-to-track-ID assignment maximizing matched pairs, then calculate `IDTP`, `IDFN = truth detections - IDTP`, `IDFP = estimate detections - IDTP`, and `IDF1 = 2 IDTP / (truth detections + estimate detections)`. Final live estimate states at reference timestamps are detections; deleted states and off-grid estimates are excluded, in line with the existing scorer. The hand vectors cover perfect tracks, swapped identities, fragmentation, an extra track, and an off-grid estimate. This is a planar-distance adaptation; it is not comparable to image-box MOT leaderboard scores.

The six-panel report uses the existing scorer's exact-time minimum-distance per-frame matching for misses, false tracks, switches, position error, and NEES. NIS comes from linked innovation records. Per-epoch JSON keeps `null` for unavailable values and lists unavailable metric names. Panel titles show the relevant denominator or sample count. Counts of misses and false tracks are per reference frame, and identity changes include changes across unmatched gaps. A source without independent truth receives no truth-based score or IDF1.

## Source records and coverage

| Source | Domain/origin | Measurement and timing | Frame/uncertainty | Provenance, reference, permitted use | Evidence and reproduction |
| --- | --- | --- | --- | --- | --- |
| Routine, crossing, false-high, degraded | Generic kinematic simulation; generated | Two noisy Cartesian position sensors, scenario-defined cadence and offsets; exact simulator timestamps | World meters; scenario-defined Gaussian noise/covariance | Deterministic scenario files and seeds 101–103; separate exact simulator truth, including velocity; code MIT; all scorer, IDF1, NEES, NIS metrics permitted | Twelve fixed runs in `results.json`; `python -m examples.diagnostics.verify` |
| NOAA Laura | Tropical cyclone; recorded | IBTrACS analysis positions, 3-hour excerpt; relative UTC-derived seconds | Local projected world meters; illustrative 20 km isotropic uncertainty | NOAA IBTrACS v04r01, pinned source hash in [record](../recorded/laura-2020.source.json); no independent truth; public NOAA data | Eight observations; NIS and intake/track diagnostics only; `run.py` |
| FHWA NGSIM Peachtree | Urban road traffic; recorded | Video-derived positions, 10 Hz relative frame time | Local world meters after feet conversion; illustrative 0.75 m isotropic uncertainty | U.S. DOT/FHWA NGSIM, pinned selected-row and observation hashes in [record](../recorded/ngsim-peachtree.source.json); no independent truth; CC BY-SA 3.0 for derived data | 155 observations; NIS and intake/track diagnostics only; `run.py` and [import recipe](../recorded/README.md) |
| Live sensor streams | Unevaluated | Version 1 Cartesian JSONL accepted | World meters and per-record covariance required | No permitted, documented live stream or reference dataset in this study | Interface exists; no diagnostics empirical coverage |

**Gaps:** Recorded cyclone and traffic sources have different cadence and motion, but neither has an independent reference. Thus cross-domain *accuracy*, identity preservation, and calibration of the assumed observation covariance remain unverified. No radar, camera detection, bearings/ranges, 3D, sensor-local live feed, or real multi-sensor reference benchmark is evaluated. The generated families demonstrate controlled behavior only. No aggregate mixes generated scores with truth-free recorded diagnostics.
