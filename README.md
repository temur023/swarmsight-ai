# SwarmSight AI · Taxi Fleet Intelligence Network

**Every taxi trip makes roads safer and AI smarter.** SwarmSight turns the dashcams and phones already in taxi fleets into
road sensors. A trip video goes in; a handful of short, anonymised, verifiable clips come out, and the same clips feed
three products:

| Line | What it produces | Who uses it |
|---|---|---|
| **RoadSense** | verified, deduplicated road-damage events with position and uncertainty (map, GeoJSON, CIFS-style feed) | map platforms, road services, fleets |
| **Safety** | explained driving episodes: hard braking together with what the front camera saw before it | fleet safety teams (coaching, not fines) |
| **DataMine** | a versioned regional dataset of the rare, uncertain, well-exposed moments, with rights and a split by trip | automotive AI / ADAS teams |

WIUT Computer Vision final, Tashkent, startup track. Every number in this README and on the site is computed by the
server or by a script in this repository. Nothing is hard-coded: a trip with no events returns no events.

## Try it

* **Web:** open the deployed site → *Upload a trip*. Drop any dashcam or phone video (MP4/MOV/WEBM, first 2 minutes
  analysed) or a road photo; optionally add a GPS track (GPX, or CSV `t,lat,lon[,speed_kmh][,accel_long_ms2]`) or pin one
  position. No footage at hand: run one of the bundled Tashkent trips, which go through exactly the same code path.
* **Then:** *Review* (confirm / reject / correct each candidate) → *Road events & API* (verified events, partner feeds)
  → *DataMine* (export a dataset version as ZIP) → *Evidence* (measured quality, speed, failures).

### Run locally

```bash
pip install -r requirements.txt        # Python 3.12+, ffmpeg on PATH for H.264 clips
uvicorn swarmsight.server:app --port 7860
# open http://localhost:7860
python -m pytest -q                    # tests (pip install -r requirements-dev.txt)
```

### Moderation on a public deployment

Set `SWARMSIGHT_MODERATOR_TOKEN` (env var, or the GitHub secret of the same name for the Modal workflow) and review,
manual geotagging and dataset export require it; the site asks for it once per browser. Uploading and reading stay open.
Without it (default) anyone can review, which is what the demo uses.

### Deploy (GPU, Modal)

See [docs/DEPLOY_MODAL.md](docs/DEPLOY_MODAL.md): `modal deploy modal_app.py`. The same app runs on CPU anywhere with the
`Dockerfile`. `GET /api/v1/health` reports whether inference runs on GPU or CPU.

## How it works

```
trip video (+ GPS track)                                           pass 1
  └ decode, sample 5 fps (10 on GPU) → YOLO11n road users + our road-damage YOLO11n (ONNX Runtime)
    → ByteTrack → temporal event proposals from the tracks and the telemetry
                                                                   pass 2
  └ clip per event with context before/after (by type) → faces and plates blurred → key frames with model boxes
    → thumbnail, image quality, embedding → location from the track at the event's moment (never invented)
                                                                   server
  └ observations (needs_review) → data value → fusion into road events → review → partner feed / dataset export
```

**Event types** (what one front camera plus telemetry can support, nothing more):

| Type | Line | Rule (`swarmsight/mining.py`) |
|---|---|---|
| pothole, alligator / transverse / longitudinal crack | road | damage track of one class seen in ≥ 2 analysed frames (1 for photo sequences); tracks joined across id switches |
| forward_collision_risk | safety | road user in our lane with time to contact < 3 s (log box-scale expansion), ≥ 2 frames |
| vru_near_path | safety | pedestrian or rider close in front of us (box > 12 % of frame height, in our lane) |
| cut_in | safety | vehicle whose lateral offset, in its own widths and corrected for our own turning, moves from ≥ 1 to ≤ 0.75 |
| hard_braking | safety | deceleration > 3 m/s² from the IMU or median-smoothed GPS speed; linked to safety events seen up to 4 s before; `causal_claim: not_established`, `driver_fault: not_determined` |
| baseline_drive | dataset | one seeded random 5 s of ordinary driving per trip, against selection bias |

**Fusion and trust** (`swarmsight/events.py`): a located road observation joins a live event of the same type within its
radius (widened by the observation's position uncertainty), else starts one. Confidence is a noisy-OR over *devices*,
each weighted by a Beta-posterior reliability learnt from moderator decisions; repeated sightings by one device are not
independent. Lifecycle: candidate → corroborated (≥ 2 devices) → verified (a moderator confirmed) | rejected, and expired
after the type's lifetime (pothole 30 days, cracks 90 days) without a new sighting. Every decision is in the audit log.

**Data value** (`swarmsight/datamine.py`): `0.35 novelty + 0.25 uncertainty + 0.20 quality + 0.20 coverage gap`
(novelty = distance to the closest clip already collected; weights are a starting point, not a tuned standard).
Exports contain only trips uploaded with dataset rights, split by trip (never by frame), with honest quality levels:
`raw_candidate` or `reviewed`. Boxes are model pre-annotations.

## Measured results

All on data the models never saw in training. Result files: `benchmarks/results/`.

| What | Result | Data | Script |
|---|---|---|---|
| Road-damage detector, all 4 types | **mAP@0.5 0.48** (P 0.58, R 0.46) | RDD2022, 1,500 held-out images, 6 countries | `training/eval_road_damage.py` |
| … potholes | AP@0.5 0.50 | same | same |
| … by country | 0.13 (Norway) – 0.70 (China motorbike) | 250 images each | same |
| … in Tashkent (image level) | **AP 0.77** (random 0.45), precision 81 %, recall 60 % | 77 Mapillary street photos, our labels | `training/eval_tashkent.py` |
| Event mining on labelled trips | **7 of 10 events found, 0 false alerts** (7 more proposals repeat a stretch already found); event clips keep 35 % of the video | 2 Tashkent trips, 158 s, labelled by us (`benchmarks/event_labels.csv`) | `benchmarks/event_mining_eval.py` |
| Speed (CPU, 4 vCPU) | ~110 ms per analysed frame for both detectors + tracking; ~33 s server time per minute of dashcam video at 5 fps | sample trips | same |

Event-level numbers come from one or two short trips labelled by the team and have wide confidence intervals; they show
how the pipeline is measured, not how good it is. More labelled trips are the first task of the pilot.

### Known failures (also on the site)

* Small, distant road users (a motorcycle 25–50 px tall) are missed: the crash in our own Tashkent trip is **not** mined.
* Time to contact from box growth also fires when braking normally behind a queue; safety episodes therefore always go to review.
* Shadows, patches, manholes and wet asphalt look like damage; night and rain cut recall (−58 % mAP at night in our robustness test).
* One forward camera does not see side lanes; phone GPS is ±5–15 m, so a pothole can land in the next lane. Positions carry their uncertainty.
* Blurring comes from detector boxes: a face or plate the detector misses can stay visible.

## API

OpenAPI at `/docs`. Main endpoints:

```
POST /api/v1/trips                         video (+ track | lat/lon) + rights_scope → {trip_id, job_id}
WS   /ws/jobs/{job_id}                     live frames and progress;  GET /api/v1/jobs/{job_id}
GET  /api/v1/trips/{trip_id}               trip report: events, clips, reduction, timings, track
GET  /api/v1/samples · POST /api/v1/samples/{id}/run   bundled trips, run through the same pipeline
GET  /api/v1/observations?status=needs_review&kind=road|safety|baseline      review queue
POST /api/v1/observations/{id}/review      {action: confirm|reject|correct, label?, note, reviewer}
POST /api/v1/observations/{id}/location    manual geotag (recorded as such)
GET  /api/v1/events?status=verified        road events, GeoJSON
GET  /api/v1/partners/road-feed[?format=cifs]   verified events for partners (no devices, routes or video)
GET  /api/v1/safety/reviews                safety episodes (internal role)
GET  /api/v1/datasets/summary · POST /api/v1/datasets/exports · GET /api/v1/datasets/exports/{version}
GET  /api/v1/health · /api/v1/metrics · /api/v1/data
```

## Data, models and licences

| Item | Use | Licence |
|---|---|---|
| RDD2022 (Arya et al., 2022) | training and held-out test of the road-damage model | CC BY-SA 4.0 |
| Mapillary street photos, Tashkent | Tashkent test set (never trained on), one sample trip, photo samples | CC BY-SA 4.0, contributors credited in `samples/*.json` and the manifest |
| Our dashcam trip, Tashkent, 16 July 2026 | sample trip and labelled test trip | © SwarmSight team; faces and plates blurred by us |
| YOLO11n (Ultralytics), COCO weights | road users | AGPL-3.0 |
| Our road-damage YOLO11n | road damage | trained by us with Ultralytics (AGPL-3.0) |

This repository is AGPL-3.0 accordingly. Full registry: `docs/data_registry.json` (also on the *Evidence* page).
Code reused from our earlier prototype in this hackathon (detector wrapper, tracker, blurring, road-damage model and its
training scripts) is part of this repository and declared here.

## Privacy and safety position

* Uploads are deleted after processing. Stored clips and frames have faces and plate areas blurred (best effort).
* Device ids are pseudonymised; GPS tracks are internal and never in partner feeds; partners get verified events only.
* Safety episodes are for coaching with a person in the loop: no automatic scores or sanctions, cause never claimed.
* Not an autopilot, not a way to blame a driver from one camera, not access to Yandex, Yandex Go or carmaker data.
* Uzbekistan's personal-data law (ZRU-547 with the 2026 amendments) applies to a real pilot; a local privacy review comes first.

## Repository

```
swarmsight/   mining.py (Event Mining Engine) · events.py (fusion, trust, review) · datamine.py · telemetry.py
              server.py (FastAPI) · store.py (SQLite) · detector.py · tracker.py · roadusers.py · privacy.py
web/          single-page UI (no build step)
benchmarks/   event_mining_eval.py, event_labels.csv, results/
training/     road-damage data preparation, training and evaluation
samples/      bundled trips (anonymised video + GPS) · scripts/: how they were built
models/       ONNX weights
```
