# Recorded source: NOAA IBTrACS 2020 Laura

This example selects a short recorded tropical-cyclone path from NOAA's [IBTrACS v04r01 North Atlantic CSV](https://www.ncei.noaa.gov/data/international-best-track-archive-for-climate-stewardship-ibtracs/v04r01/access/csv/ibtracs.NA.list.v04r01.csv). NOAA [documents its columns and update schedule](https://www.ncei.noaa.gov/products/international-best-track-archive). The file is updated regularly, so record the downloaded file's SHA-256 and access date when reproducing. The source CSV is not bundled with this repository.

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
| Permitted use | NOAA publishes IBTrACS for public use; cite NOAA and do not present transformed data as an official NOAA product. This recipe redistributes no source rows. Check the [NOAA product terms](https://www.ncei.noaa.gov/products/international-best-track-archive) for downstream redistribution. No credentials or private data are required. |

## Import recipe

Download the North Atlantic CSV into a local path outside the repository, then run from the repository root (choose new output paths):

```bash
python examples/recorded/prepare_ibtracs.py --input /path/to/ibtracs.NA.list.v04r01.csv --output output/laura.csv --metadata output/laura.import.json --expected-sha256 666681be5b12caf5bad7a511bae5f6e5fa8b03789f7f6dd00ee2f0aaa41c2c97
mst ingest --format csv --input output/laura.csv --contract examples/recorded/ibtracs-contract.json --output output/laura.jsonl
mst track --input output/laura.jsonl --output output/laura-tracks.jsonl --method multi-kalman
```

The preparer selects the first eight distinct main-track rows for the named storm in 2020, converts UTC to elapsed seconds, and projects geographic coordinates using a documented local approximation. Its metadata preserves the source hash, anchor, and assumptions; the ingest sidecar preserves the prepared CSV and contract hashes. The exercised snapshot produced eight observations and eight truth-free track estimates. If NOAA has updated the source file, the pinned-hash command fails; retain the original download for exact reproduction or record a new hash and treat it as a new source snapshot. There is no reference truth file, and this is not a measured performance claim. A future evaluation can only use an independently justified reference and appropriate alignment policy.
