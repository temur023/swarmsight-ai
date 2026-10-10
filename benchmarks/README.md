# Benchmarks

| script | measures | result |
|---|---|---|
| `training/eval_road_damage.py` | detector mAP on the RDD2022 test split | `results/road_damage_eval.json` |
| `training/eval_tashkent.py` | image-level damage precision / recall on Tashkent photos | `results/tashkent_eval.json` |
| `benchmarks/event_mining_eval.py` | **the whole pipeline on whole trips**: event precision / recall, false alerts per hour, data reduction, latency | `results/event_mining_eval.json` |

## Event mining evaluation

```bash
python3 benchmarks/event_mining_eval.py --dry-run                    # check the label file only
python3 benchmarks/event_mining_eval.py --videos . --tracks samples  # run (CPU: ~30 s for both sample trips)
```

Options: `--labels` (default `benchmarks/event_labels.csv`), `--videos DIR` (the label paths are relative to it,
default the repo root), `--tracks DIR` (telemetry `<video stem>.csv|.gpx`, optional; `--track-offset-s`),
`--sample-fps` (default 5, as in the product), `--tol` (matching slack, default 1 s; never less than one analysed
frame interval, so a ~1 fps photo sequence gets ~1.1 s), `--threads`, `--out`.
Set `SWARMSIGHT_DEVICE=cpu` to force the CPU on a GPU machine. The JSON records the label file's SHA-256, the
hash of `swarmsight/mining.py`, the model versions, provider, date and every prediction / label with its outcome.

### Labelling a new video

1. Put the video under the `--videos` directory (anonymise first) and, if you have it, its telemetry as
   `<stem>.csv` or `<stem>.gpx` in the `--tracks` directory.
2. Watch the **whole** video. Every event of the types below that is present must get a row, otherwise a correct
   detection counts as a false alert. Extract frames every 0.5 s (and every frame around events) if it helps.
   For a photo sequence turned into a video (one frame per photo, e.g. Mapillary at ~1 fps) look at every photo and
   label an event as the interval from the first to the last photo where it is visible (a single photo: start = end).
   Road damage: only clearly visible damage on the drivable surface of our lane or the next lane - not patches,
   manholes, markings or ravelling. A stretch with several damage types gets one row per type.
3. Add rows to `event_labels.csv`:

```csv
video,start_s,end_s,type,note
trips/2026-10-09_chilonzor.mp4,41.5,44.0,cut_in,"white Cobalt from the right lane, ends ~1 car length ahead"
trips/2026-10-09_chilonzor.mp4,63.2,63.8,pothole,"right wheel track"
trips/2026-10-09_ring_road.mp4,0,312.4,none,"watched all of it, nothing to report"
"# comment rows start with # in the video column",,,,
```

- `start_s`, `end_s`: seconds from the start of the video; the interval in which the event is visible / happening.
- `type`: `pothole`, `alligator_crack`, `transverse_crack`, `longitudinal_crack`, `forward_collision_risk`
  (a road user in our path with time to contact under ~3 s), `vru_near_path` (a pedestrian or rider close in front
  of us), `cut_in` (a vehicle moving sideways into our lane ahead), `hard_braking` (our deceleration over 3 m/s²),
  or `none` (one row spanning the whole video: "checked, no events" - it still counts for false alerts per hour).
- `note`: free text; write down every judgement call. Quote it if it contains commas.

### What the numbers mean

- **Detection**, per type, overall and per video. A prediction (baseline clips excluded) is a true positive (TP)
  when its interval widened by the tolerance on both sides overlaps a not yet matched label of a compatible type;
  matching is greedy one-to-one, largest overlap first. A prediction that overlaps a label another prediction
  already took is a **duplicate** (`dup`: the same crack proposed twice) - reported, but not a false alert.
  Safety types must match exactly. Road damage is scored at two levels: `road_damage_any_type` merges overlapping
  damage labels of any type into one **stretch** that any damage prediction can match ("is there road damage
  here"), and the per-type rows need the exact type. `overall` = safety (exact) + road-damage stretches; this is
  the headline row. `overall_exact_types` uses every label row with exact types.
  - precision = TP / predictions (strict: duplicates count against it; `precision_incl_duplicates` in the JSON
    does not), recall = TP / labelled events, with 95 % Wilson intervals in the JSON,
  - **false alerts per hour** = predictions matching no label at all / hours of analysed video (all labelled
    videos, including `none` ones) - the number a fleet reviewer feels.
- **Data reduction**. `kept_ratio` = seconds kept in clips / seconds analysed (the product also keeps one 5 s
  random baseline clip per trip, so the event-clips-only ratio is reported too). **Event retention** = share of
  labelled events (the units of the `overall` row: safety events + road-damage stretches) whose interval overlaps
  at least one kept clip: "we kept 8 % of the video and 80 % of the events". `event_retention_via_matched_event`
  only counts events kept because the pipeline found *them*, not because another (possibly false) event's clip
  happened to cover them.
- **Latency**: ms per analysed frame (both detectors + tracking) p50 / p95, wall seconds per minute of video
  (decode, analysis, proposals, anonymised clip encoding), the real-time factor and the execution provider (CPU / GPU).
  Per minute of video depends on the frame rate: a 1 fps photo sequence has ~5x fewer frames per minute than a
  video sampled at 5 fps, so the per-video rows matter more than the pooled figure.

### Current label set and results

| trip | source | length | labels |
|---|---|---|---|
| `samples/tashkent_crossing.mp4` | team dashcam, 24 fps video | 23.8 s | `vru_near_path` (traffic officer we pass at 1-2 m), `forward_collision_risk` (motorcycle hits the car ahead in the last 0.4 s; judgement call, see note) |
| `samples/tashkent_redmi.mp4` | one phone's Mapillary photo sequence, 120 photos at 0.894 fps | 134.2 s | 20 damage rows (alligator / longitudinal / transverse / one small pothole) = 8 road-damage stretches; no safety events (checked: the pipeline's cut_in and hard_braking there are false alarms, see the comment row) |

`results/event_mining_eval.json` holds the latest run (date, code hash and label hash inside). Run of 2026-10-10
with the code at that time: 1 of 10 labelled events found (a longitudinal crack), 2 false alerts (cut_in and
hard_braking on the photo trip), 19 % of the video kept, 20 % of the events retained. The damage detector itself
fires (conf >= 0.35) on many of the cracked photos, but the pipeline drops damage seen in a single photo (see the
JSON `details`).

### Read this before quoting the numbers

The label set is **two short trips (2.6 min, 10 events)** labelled by one person on the team. That is enough to
show how the pipeline is measured and to find concrete failure modes, not to claim a precision, recall or
false-alert rate: one false alert in 2.6 minutes reads as 23 per hour. More of the team's own videos - ideally
tens of minutes of ordinary driving with `none` rows plus every incident clip we have, labelled by two people -
must be added before these numbers mean much.
