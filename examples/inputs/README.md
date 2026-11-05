# Frame and unit intake fixtures

`frame_a` and `frame_b` represent the same two world-frame points, `(11, 22)` and `(12, 23)` meters, at 0 and 1 seconds. They use different named sensor-local frames, positions in meters versus feet, and timestamps in seconds versus milliseconds. Their stated isotropic input uncertainty converts to one meter standard deviation in both cases. These are deterministic conversion examples, not evidence of tracking accuracy.

From the repository root, with the package installed:

```bash
mst ingest --format csv --input examples/inputs/frame_a.csv --contract examples/inputs/frame_a.contract.json --output output/frame-a.jsonl
mst ingest --format csv --input examples/inputs/frame_b.csv --contract examples/inputs/frame_b.contract.json --output output/frame-b.jsonl
```

The adapter writes world-frame version 1 observations and a version 2 `.source.json` sidecar for each input. It rejects missing transforms, nonorthonormal rotations, unknown units, invalid covariance, invalid/descending times, and duplicate observation IDs. Compare the two position and covariance arrays with floating-point tolerance. Output paths must be new.

## Source records

| Field | `frame_a_fixture` | `frame_b_fixture` |
| --- | --- | --- |
| Domain and use | Coordinate conversion demonstration | Coordinate conversion demonstration |
| Origin and measurement | Generated Cartesian 2D position, sensor `sensor_a` | Generated Cartesian 2D position, sensor `sensor_b` |
| Timing | 0 and 1 seconds, elapsed, ordered, no known gaps | 0 and 1000 milliseconds, elapsed, ordered, no known gaps |
| Frame, units, transform | `sensor_a_local`, meters, identity rotation and `(10, 20)` m translation | `sensor_b_local`, feet, 90 degree rotation and `(10, 20)` m translation |
| Uncertainty | Fixed isotropic 1 m standard deviation, illustrative | Fixed isotropic 3.280839895013123 ft standard deviation, illustrative |
| Provenance and integrity | Checked-in CSV and contract; Git revision identifies version, source hashes recorded at import | Checked-in CSV and contract; Git revision identifies version, source hashes recorded at import |
| Reference quality and metrics | Known constructed positions for conversion only; no independent tracking reference or accuracy metric | Known constructed positions for conversion only; no independent tracking reference or accuracy metric |
| Permitted use | Project-authored example, MIT repository license; redistribution allowed | Project-authored example, MIT repository license; redistribution allowed |

The version 1 contract requires `source_id`, `source_kind`, `measurement_type`, `input_format`, `sensor_id`, `time`, `position`, `uncertainty`, and a `transform` for non-world frames. CSV must contain a literal `observation_id` column. `time` declares a numeric field, `s`/`ms`/`h`, `elapsed` or `unix` basis, and `origin_s`; Unix input requires an explicit nonzero epoch in seconds. `position` declares numeric x/y fields, `m`/`km`/`ft`, and a frame. A local frame transform declares a proper 2D rotation and world-frame translation in meters. Uncertainty is either an isotropic standard deviation or fixed 2×2 covariance in the same unit as the input positions; it is rotated and scaled into square meters. The source manifest stores the full contract, contract hash, output hash, conversion assumptions, and input hash for file inputs.

Other measurement types require a separate, versioned measurement-model contract defining observation vector, predicted measurement function, Jacobian or equivalent filter interface, noise units/covariance, frame, and validation. Non-Cartesian values must not be disguised as Cartesian positions or sent through the current linear position tracker. No such model is currently implemented.
