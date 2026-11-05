# Measured synthetic benchmark

Protocol SHA-256: `0c34b6702239a1ea96ed90c385e72048c7842dfd804e1166ccf2c3bc97d5542e`. Seeds: 101, 102, 103.

Values show arithmetic mean ± sample standard deviation across seeds. RMSE is conditional on matched states; coverage and unmatched counts must be read alongside it. Runtime includes artifact writing for simulation and tracking, and report construction for evaluation. NIS is unavailable because innovation statistics are not persisted. These synthetic results do not establish field performance.

| Case | Method | n | RMSE (m) | Coverage | ID switches | Unmatched truth | Unmatched estimates |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: |
| combined-degraded | multi-kalman | 3 | 0.298 ± 0.059 | 1.000 ± 0.000 | 1.000 ± 1.000 | 0.000 ± 0.000 | 1.333 ± 1.155 |
| crossing | multi-kalman | 3 | 0.149 ± 0.025 | 1.000 ± 0.000 | 4.333 ± 0.577 | 0.000 ± 0.000 | 0.333 ± 0.577 |
| false-high | multi-kalman | 3 | 0.281 ± 0.044 | 1.000 ± 0.000 | 0.667 ± 1.155 | 0.000 ± 0.000 | 3.333 ± 2.517 |
| miss-high | multi-kalman | 3 | 0.299 ± 0.059 | 1.000 ± 0.000 | 0.000 ± 0.000 | 0.000 ± 0.000 | 0.000 ± 0.000 |
| noise-high | multi-kalman | 3 | 0.295 ± 0.057 | 1.000 ± 0.000 | 0.000 ± 0.000 | 0.000 ± 0.000 | 0.000 ± 0.000 |
| offset-high | multi-kalman | 3 | 0.294 ± 0.058 | 1.000 ± 0.000 | 0.000 ± 0.000 | 0.000 ± 0.000 | 0.000 ± 0.000 |
| one-object | baseline | 3 | 0.255 ± 0.085 | 1.000 ± 0.000 | 0.000 ± 0.000 | 0.000 ± 0.000 | 0.000 ± 0.000 |
| one-object | kalman | 3 | 0.235 ± 0.077 | 1.000 ± 0.000 | 0.000 ± 0.000 | 0.000 ± 0.000 | 0.000 ± 0.000 |
| routine-fused | multi-kalman | 3 | 0.293 ± 0.052 | 1.000 ± 0.000 | 0.333 ± 0.577 | 0.000 ± 0.000 | 0.333 ± 0.577 |
| routine-high-only | multi-kalman | 3 | 1.116 ± 0.227 | 0.600 ± 0.000 | 0.667 ± 1.155 | 4.000 ± 0.000 | 0.000 ± 0.000 |
| routine-low-only | multi-kalman | 3 | 0.296 ± 0.057 | 1.000 ± 0.000 | 0.000 ± 0.000 | 0.000 ± 0.000 | 0.000 ± 0.000 |
| sanity | baseline | 3 | 0.000 ± 0.000 | 1.000 ± 0.000 | 0.000 ± 0.000 | 0.000 ± 0.000 | 0.000 ± 0.000 |
| sanity | kalman | 3 | 0.000 ± 0.000 | 1.000 ± 0.000 | 0.000 ± 0.000 | 0.000 ± 0.000 | 0.000 ± 0.000 |

Full per-seed metrics, timings, hashes, and environment details are in `benchmark.json`.
