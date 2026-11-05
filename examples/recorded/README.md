# Recorded source: NOAA IBTrACS 2020 Laura

This example selects a short recorded tropical-cyclone path from NOAA's [IBTrACS v04r01 North Atlantic CSV](https://www.ncei.noaa.gov/data/international-best-track-archive-for-climate-stewardship-ibtracs/v04r01/access/csv/ibtracs.NA.list.v04r01.csv). NOAA [documents its columns and update schedule](https://www.ncei.noaa.gov/products/international-best-track-archive). The full NOAA source CSV is not bundled. The eight derived, projected observations in `laura-2020.jsonl` and their `laura-2020.source.json` provenance record are bundled as a small recorded replay fixture. The source file is updated regularly, so retain its SHA-256 and access date when reproducing the import.

## Source record

| Field | Value |
| --- | --- |
| Domain and use | Tropical cyclone trajectory; recorded intake demonstration only |
| Origin and measurement | NOAA IBTrACS v04r01 multi-agency best-track analysis, 2020 storm named LAURA; combined latitude/longitude positions, treated as one recorded position source `ibtracs_analysis` |
| Timing | `ISO_TIME` UTC; first eight available `main` track positions after sorting, elapsed seconds from first selected point; the exercised 2026-11-05 snapshot yielded timestamps 0 through 75,600 seconds at 10,800-second intervals with no selected-row gaps |
| Frame and units | Original geographic latitude/longitude in degrees (datum not asserted here); recipe projects to a local equirectangular plane in meters, anchored at the first point with radius 6,371,000 m; local planar approximation has distortion and is limited to the short selected segment |
| Uncertainty | Dataset does not provide calibrated per-point position covariance for this example. Contract assigns an illustrative fixed 20 km isotropic standard deviation; it must not be interpreted as NOAA accuracy or calibration. |
| Provenance and integrity | NOAA NCEI IBTrACS v04r01 North Atlantic CSV, [dataset DOI](https://doi.org/10.25921/82ty-9e16); accessed 2026-11-05. Downloaded snapshot SHA-256: `666681be5b12caf5bad7a511bae5f6e5fa8b03789f7f6dd00ee2f0aaa41c2c97` (57,593,323 bytes). Recipe selected eight rows, anchored at 14.4° N, 47.3° W. Metadata records source hash, selection, projection anchor, and output count. Upstream v04r01 content may change. |
| Reference quality and metrics | Best-track positions are postprocessed estimates, not independent sensor observations or reference truth for this pipeline. No separate reference is supplied. Truth-based accuracy, ID metrics, and NEES are unavailable; inspection and NIS are exploratory only because covariance is assumed. |
| Permitted use | NOAA publishes IBTrACS for public use; cite NOAA and do not present transformed data as an official NOAA product. The repository includes eight derived positions for replay, while the full source CSV remains at NOAA. Check the [NOAA product terms](https://www.ncei.noaa.gov/products/international-best-track-archive) for downstream redistribution. No credentials or private data are required. |

## Import recipe

Download the North Atlantic CSV into a local path outside the repository, then run from the repository root (choose new output paths):

```bash
python examples/recorded/prepare_ibtracs.py --input /path/to/ibtracs.NA.list.v04r01.csv --output output/laura.csv --metadata output/laura.import.json --expected-sha256 666681be5b12caf5bad7a511bae5f6e5fa8b03789f7f6dd00ee2f0aaa41c2c97
mst ingest --format csv --input output/laura.csv --contract examples/recorded/ibtracs-contract.json --output output/laura.jsonl
mst track --input output/laura.jsonl --output output/laura-tracks.jsonl --method multi-kalman
```

The preparer selects the first eight distinct main-track rows for the named storm in 2020, converts UTC to elapsed seconds, and projects geographic coordinates using a documented local approximation. Its metadata preserves the source hash, anchor, and assumptions; the ingest sidecar preserves the prepared CSV and contract hashes. The exercised snapshot produced eight observations and eight truth-free track estimates. If NOAA has updated the source file, the pinned-hash command fails; retain the original download for exact reproduction or record a new hash and treat it as a new source snapshot. There is no reference truth file, and this is not a measured performance claim. A future evaluation can only use an independently justified reference and appropriate alignment policy.

## Reproduce online tracking against batch

```bash
mst track --input examples/recorded/laura-2020.jsonl --output output/laura-batch.jsonl --method multi-kalman
mst track-stream --input examples/recorded/laura-2020.jsonl --source examples/recorded/laura-2020.source.json --output output/laura-stream.jsonl --expected-interval-s 10800
cmp output/laura-batch.jsonl output/laura-stream.jsonl
```

The replay is byte-identical to batch for this ordered eight-record fixture. The `.stream.json` sidecar embeds the recorded source manifest and reports zero inferred missing sensor epochs and zero dropped records for this input. The comparison establishes processing equivalence on these observations, not tracking accuracy on the cyclone.

## FHWA NGSIM Peachtree traffic slice

The [U.S. DOT NGSIM trajectory dataset](https://catalog.data.gov/dataset/next-generation-simulation-ngsim-vehicle-trajectories-and-supporting-data) provides video-derived road vehicle positions. `ngsim-peachtree.jsonl` is a 155-observation, 31-frame excerpt from the Peachtree location, with five moving vehicles. It is a **recorded traffic observation fixture**, distinct from the NOAA cyclone example. The [source sidecar](ngsim-peachtree.source.json) records selection, transform, uncertainty assumption, provenance, SHA-256, reference quality, and use limits. Derived trajectory data are attributed to U.S. DOT/FHWA NGSIM and shared under the dataset's [CC BY-SA 3.0 terms](https://creativecommons.org/licenses/by-sa/3.0/); the project's code license does not relicense these data.

The public API's `local_x`/`local_y` are feet in the Peachtree local frame. The converter scales both axes by 0.3048 and keeps the local orientation as the tracker's `world` frame. It assigns relative seconds from frame 3370 at the documented 10 Hz cadence. The API's `global_time` values do not unambiguously identify UTC milliseconds in this excerpt, so they are checked for frame consistency but not used as absolute timestamps. The fixed 0.75 m standard deviation is illustrative, not a calibrated measurement error. Original vehicle IDs select a stable slice but never enter tracker observations as truth IDs. There is no independently measured reference; misses, false tracks, identity changes, position error, NEES, and IDF1 are unavailable. NIS and track counts remain available as truth-free diagnostics.

To regenerate from the selected public API response (a change to the selected rows fails the pinned hash check):

```bash
.venv/bin/python -m examples.recorded.prepare_ngsim --download \
  --expected-sha256 ad884c11302d5ba876be95e3574d89ea86d1c896b786398b4ce9c093e44eb5dd \
  --output output/ngsim-peachtree.jsonl \
  --source-record output/ngsim-peachtree.source.json
```

To analyze the bundled fixture, first run `mst track --input examples/recorded/ngsim-peachtree.jsonl --method multi-kalman --output output/ngsim-tracks.jsonl --innovations output/ngsim-innovations.jsonl`, then run `mst diagnose --observations examples/recorded/ngsim-peachtree.jsonl --source examples/recorded/ngsim-peachtree.source.json --tracks output/ngsim-tracks.jsonl --innovations output/ngsim-innovations.jsonl --report output/ngsim-diagnostics.json --output output/ngsim-diagnostics.png`. Paths must be new.
