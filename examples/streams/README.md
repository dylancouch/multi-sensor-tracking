# Online tracking and replay

`mst track-stream` consumes version 1 world-frame observation JSONL in arrival order, either from a file or standard input. It emits version 1 track estimates as soon as a timestamp epoch is complete and flushes them to disk. For an open live feed, a later timestamp must arrive before the earlier epoch can be safely emitted; an epoch still awaiting same-time observations remains buffered. No truth file is read.

For a live program producing canonical observation JSONL, use an explicit source record with `source_label`, `source_kind: "live"`, `frame: "world"`, `position_unit: "m"`, `time_unit: "s"`, and provenance and permitted-use details. The checked-in `live-source.json` is a template; replace its source details for real inputs:

```bash
sensor_program | mst track-stream --source examples/streams/live-source.json --output output/live-tracks.jsonl --max-lateness-s 0.5 --expected-interval-s 1
```

`output/live-tracks.stream.json` embeds the supplied source record, SHA-256 of emitted tracks, counters for received, accepted, processed, emitted, and dropped records, and the configured limits. A file replay can use the `.source.json` manifest from `mst ingest`; if it declares an observation SHA-256, replay checks the file before and after processing. Never supply reference truth to this command. Handle live track and source artifacts according to their data permissions.

## Ordering and resource policy

- The watermark is the greatest arrival timestamp minus `--max-lateness-s` (default `0`). An epoch is emitted only when its timestamp is **strictly below** the watermark; EOF flushes remaining epochs. Arrivals older than the watermark or at/before the last emitted epoch are counted as late and dropped. Same-time and bounded out-of-order arrivals are sorted by timestamp, sensor ID, and observation ID before association.
- Duplicate observation IDs are counted and dropped. A configured `--expected-interval-s` infers missing **sensor epochs** from gaps between distinct timestamps for each sensor; it cannot prove how many individual objects were missed. Without a cadence, gap fields are `null`.
- Input is processed synchronously, so reading pauses while association and output writes run. The pending reorder buffer defaults to 4,096 observations; `--max-buffered` overflow drops a new arrival and counts it. `--max-records` defaults to 100,000 accepted unique IDs, bounding retained ID history. `--max-live-tracks` defaults to 2,048 and counts unmatched observations dropped when the active-track cap is reached. Input lines are limited to 1 MB and the track artifact to 64 MB. All limits are configurable except the artifact size. Overflow and late records are never silently rewritten into another timestamp.
- An output path must be new. A failed run removes its partial track file and summary. Successful output is deterministic for the same ordered arrivals, source record, and policy. A recorded replay with its original order and zero drops should equal batch tracking exactly.

The simple constant-velocity tracker remains the algorithm used by both paths. Backpressure here means synchronous processing plus explicit bounded buffering and counted drops; this command is not a distributed streaming service or a hardware connector.
