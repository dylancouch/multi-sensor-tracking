# Measured synthetic benchmark

Protocol SHA-256: `0c34b6702239a1ea96ed90c385e72048c7842dfd804e1166ccf2c3bc97d5542e`. Seeds: 101, 102, 103.

Values show arithmetic mean ± sample standard deviation across seeds. RMSE and MOTP are conditional on matched states; coverage and unmatched counts must be read alongside them. NIS uses saved Kalman update innovations and is unavailable for the baseline. Runtime includes artifact writing for simulation and tracking, and report construction for evaluation. These generated-fixture results do not establish field performance.

| Case | Method | n | RMSE (m) | Coverage | MOTA | MOTP (m) | NIS | ID switches | Unmatched truth | Unmatched estimates |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| combined-degraded | multi-kalman | 3 | 0.298 ± 0.059 | 1.000 ± 0.000 | 0.767 ± 0.208 | 0.278 ± 0.069 | 0.981 ± 0.284 | 1.000 ± 1.000 | 0.000 ± 0.000 | 1.333 ± 1.155 |
| crossing | multi-kalman | 3 | 0.149 ± 0.025 | 1.000 ± 0.000 | 0.533 ± 0.115 | 0.137 ± 0.029 | 0.897 ± 0.359 | 4.333 ± 0.577 | 0.000 ± 0.000 | 0.333 ± 0.577 |
| false-high | multi-kalman | 3 | 0.281 ± 0.044 | 1.000 ± 0.000 | 0.600 ± 0.265 | 0.263 ± 0.053 | 1.227 ± 0.252 | 0.667 ± 1.155 | 0.000 ± 0.000 | 3.333 ± 2.517 |
| miss-high | multi-kalman | 3 | 0.299 ± 0.059 | 1.000 ± 0.000 | 1.000 ± 0.000 | 0.281 ± 0.066 | 1.152 ± 0.475 | 0.000 ± 0.000 | 0.000 ± 0.000 | 0.000 ± 0.000 |
| noise-high | multi-kalman | 3 | 0.295 ± 0.057 | 1.000 ± 0.000 | 1.000 ± 0.000 | 0.277 ± 0.064 | 1.346 ± 0.409 | 0.000 ± 0.000 | 0.000 ± 0.000 | 0.000 ± 0.000 |
| offset-high | multi-kalman | 3 | 0.294 ± 0.058 | 1.000 ± 0.000 | 1.000 ± 0.000 | 0.276 ± 0.068 | 1.227 ± 0.300 | 0.000 ± 0.000 | 0.000 ± 0.000 | 0.000 ± 0.000 |
| one-object | baseline | 3 | 0.255 ± 0.085 | 1.000 ± 0.000 | 1.000 ± 0.000 | 0.234 ± 0.089 | NA | 0.000 ± 0.000 | 0.000 ± 0.000 | 0.000 ± 0.000 |
| one-object | kalman | 3 | 0.235 ± 0.077 | 1.000 ± 0.000 | 1.000 ± 0.000 | 0.212 ± 0.077 | 0.802 ± 0.209 | 0.000 ± 0.000 | 0.000 ± 0.000 | 0.000 ± 0.000 |
| routine-fused | multi-kalman | 3 | 0.293 ± 0.052 | 1.000 ± 0.000 | 0.933 ± 0.115 | 0.275 ± 0.059 | 1.158 ± 0.325 | 0.333 ± 0.577 | 0.000 ± 0.000 | 0.333 ± 0.577 |
| routine-high-only | multi-kalman | 3 | 1.116 ± 0.227 | 0.600 ± 0.000 | 0.533 ± 0.115 | 0.969 ± 0.241 | 0.434 ± 0.195 | 0.667 ± 1.155 | 4.000 ± 0.000 | 0.000 ± 0.000 |
| routine-low-only | multi-kalman | 3 | 0.296 ± 0.057 | 1.000 ± 0.000 | 1.000 ± 0.000 | 0.278 ± 0.066 | 0.777 ± 0.140 | 0.000 ± 0.000 | 0.000 ± 0.000 | 0.000 ± 0.000 |
| sanity | baseline | 3 | 0.000 ± 0.000 | 1.000 ± 0.000 | 1.000 ± 0.000 | 0.000 ± 0.000 | NA | 0.000 ± 0.000 | 0.000 ± 0.000 | 0.000 ± 0.000 |
| sanity | kalman | 3 | 0.000 ± 0.000 | 1.000 ± 0.000 | 1.000 ± 0.000 | 0.000 ± 0.000 | 0.004 ± 0.000 | 0.000 ± 0.000 | 0.000 ± 0.000 | 0.000 ± 0.000 |

Full per-seed metrics, timings, hashes, and environment details are in `benchmark.json` (`results.json` in the checked-in report).
