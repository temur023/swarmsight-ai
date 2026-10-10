"""DataMine: which clips are worth keeping for a regional dataset, and the versioned export.

DataValue = 0.35 novelty + 0.25 uncertainty + 0.20 quality + 0.20 coverage_gap   (weights are our starting point,
not a tuned standard; they need validation against annotation usefulness)
  novelty       1 - cosine similarity to the closest sample already collected (16x9 grey thumbnail embedding)
  uncertainty   1 - |2 conf - 1|: the model is least sure near 0.5, where a label teaches it most
  quality       sharpness (variance of the Laplacian) with a penalty for very dark or blown-out frames
  coverage_gap  1 / sqrt(1 + samples of this label already collected)

Quality levels (from the concept): raw_candidate (found by the model) -> reviewed (a person confirmed or corrected the
label).  Boxes in the export are model pre-annotations, not human-checked: no sample is claimed "annotated" or
"benchmark-ready".  Split by trip, never by frame, so near-identical frames cannot leak between train and test.
"""
from __future__ import annotations

import hashlib
import io
import json
import time
import zipfile
from collections import Counter
from pathlib import Path

import numpy as np

from .store import Store

WEIGHTS = {"novelty": 0.35, "uncertainty": 0.25, "quality": 0.20, "coverage_gap": 0.20}
CLASSES = ["person", "cyclist", "motorcyclist", "bicycle", "motorcycle", "car", "truck", "bus", "vehicle", "two_wheeler",
           "pothole", "alligator_crack", "transverse_crack", "longitudinal_crack"]
RIGHTS = {"road_only": "road events only: clips are not used for datasets",
          "road_and_dataset": "road events and the regional dataset (consent recorded at upload)"}


def split_of(trip_id: str) -> str:
    h = int(hashlib.sha1(trip_id.encode()).hexdigest()[:8], 16) % 100
    return "train" if h < 70 else "val" if h < 85 else "test"


def data_value(store: Store, obs: dict) -> tuple[float, dict]:
    others = store.query("SELECT id, label, embedding FROM observations WHERE id != ? AND trip_id != ? AND embedding IS NOT NULL "
                         "AND review_status != 'rejected'", (obs["id"], obs["trip_id"]))
    emb = np.asarray(obs["embedding"] or [], np.float32)
    if len(emb) and others:
        m = np.asarray([o["embedding"] for o in others], np.float32)
        novelty = float(np.clip(1.0 - (m @ emb).max(), 0.0, 1.0))
    else:
        novelty = 1.0
    unc = obs["uncertainty"] if obs["uncertainty"] is not None else 0.0
    quality = obs["quality"] if obs["quality"] is not None else 0.5
    same = sum(1 for o in others if o["label"] == obs["label"])
    gap = 1.0 / np.sqrt(1.0 + same)
    parts = {"novelty": round(novelty, 3), "uncertainty": round(float(unc), 3), "quality": round(float(quality), 3),
             "coverage_gap": round(float(gap), 3)}
    return round(sum(WEIGHTS[k] * v for k, v in parts.items()), 3), parts


def summary(store: Store) -> dict:
    obs = store.query("SELECT o.*, t.rights_scope FROM observations o JOIN trips t ON t.id = o.trip_id")
    usable = [o for o in obs if o["rights_scope"] == "road_and_dataset" and o["clip_id"]]
    trips = store.query("SELECT id, analysed_s, kept_s, rights_scope FROM trips WHERE status='done'")
    analysed = sum(t["analysed_s"] or 0 for t in trips)
    kept = sum(t["kept_s"] or 0 for t in trips)
    by = lambda rows, key: dict(Counter(key(o) for o in rows))  # noqa: E731
    return {
        "trips": len(trips), "analysed_s": round(analysed, 1), "kept_s": round(kept, 1),
        "kept_ratio": round(kept / analysed, 4) if analysed else None,
        "candidates": len(obs), "with_dataset_rights": len(usable),
        "by_level": by(usable, lambda o: "reviewed" if o["review_status"] in ("confirmed", "corrected") else
                       "rejected" if o["review_status"] == "rejected" else "raw_candidate"),
        "by_label": by([o for o in usable if o["review_status"] != "rejected"], lambda o: o["label"]),
        "by_kind": by([o for o in usable if o["review_status"] != "rejected"], lambda o: o["kind"]),
        "by_split": by([o for o in usable if o["review_status"] in ("confirmed", "corrected")], lambda o: split_of(o["trip_id"])),
        "top_value": [{"id": o["id"], "label": o["label"], "data_value": o["data_value"], "thumb": o["thumb"], "trip_id": o["trip_id"]}
                      for o in sorted([o for o in usable if o["review_status"] != "rejected" and o["data_value"] is not None],
                                      key=lambda o: -o["data_value"])[:8]],
        "weights": WEIGHTS, "rights": RIGHTS,
        "exports": store.query("SELECT version, created_at, n_samples, summary FROM dataset_exports ORDER BY created_at DESC"),
    }


def export(store: Store, media_dir: Path, out_dir: Path, include_unreviewed: bool = False) -> dict:
    """Write a versioned ZIP: manifest, README, clips, key frames with YOLO pre-annotations, COCO-style annotations."""
    levels = ("confirmed", "corrected") + (("needs_review",) if include_unreviewed else ())
    rows = store.query(f"SELECT o.*, t.rights_scope, t.created_at AS trip_created FROM observations o JOIN trips t ON t.id = o.trip_id "
                       f"WHERE t.rights_scope='road_and_dataset' AND o.clip_id IS NOT NULL AND o.review_status IN ({','.join('?' * len(levels))}) "
                       f"ORDER BY o.trip_id, o.t_peak", levels)
    n = len(store.query("SELECT version FROM dataset_exports")) + 1
    version = f"v{n}-{time.strftime('%Y%m%d-%H%M', time.gmtime())}"
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / f"swarmsight-dataset-{version}.zip"
    clips = {c["id"]: c for c in store.query("SELECT * FROM clips")}
    samples, coco_images, coco_anns, written = [], [], [], set()
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        for o in rows:
            c = clips.get(o["clip_id"])
            if not c:
                continue
            split = split_of(o["trip_id"])
            if c["file"] and c["file"] not in written and (media_dir / c["file"]).exists():
                z.write(media_dir / c["file"], c["file"])
                written.add(c["file"])
            frames = []
            for kf in c["keyframes"] or []:
                if not (o["t_start"] - 1.0 <= kf["t"] <= o["t_end"] + 1.0):
                    continue
                img = f"images/{split}/{Path(kf['file']).name}"
                if img not in written and (media_dir / kf["file"]).exists():
                    z.write(media_dir / kf["file"], img)
                    w, h = c["size"]
                    lines = []
                    for b in kf["boxes"]:
                        if b["cls"] not in CLASSES:
                            continue
                        x1, y1, x2, y2 = b["bbox"]
                        lines.append(f"{CLASSES.index(b['cls'])} {(x1 + x2) / 2 / w:.5f} {(y1 + y2) / 2 / h:.5f} {(x2 - x1) / w:.5f} {(y2 - y1) / h:.5f}")
                        coco_anns.append({"id": len(coco_anns) + 1, "image": img, "category": b["cls"], "bbox_xyxy": b["bbox"],
                                          "score": b["conf"], "track_id": b["track"], "source": "model pre-annotation"})
                    z.writestr(f"labels/{split}/{Path(kf['file']).stem}.txt", "\n".join(lines))
                    coco_images.append({"file": img, "width": w, "height": h, "clip": c["file"], "t_in_trip": kf["t"], "split": split})
                    written.add(img)
                frames.append(img)
            samples.append({
                "sample_id": f"obs-{o['id']}", "trip": hashlib.sha1(o["trip_id"].encode()).hexdigest()[:10], "split": split,
                "label": o["label"], "model_label": o["type"], "kind": o["kind"],
                "quality_level": "reviewed" if o["review_status"] in ("confirmed", "corrected") else "raw_candidate",
                "review_status": o["review_status"], "interval_s": [o["t_start"], o["t_end"]], "peak_s": o["t_peak"],
                "clip": c["file"], "clip_interval_s": [c["t0"], c["t1"]], "frames": frames,
                "location": {"lat": round(o["lat"], 5), "lon": round(o["lon"], 5), "source": o["loc_source"],
                             "uncertainty_m": o["loc_uncertainty_m"]} if o["lat"] is not None else None,
                "model_confidence": o["conf"], "data_value": o["data_value"], "value_parts": o["value_parts"],
                "image_quality": o["quality"], "rights_scope": o["rights_scope"], "model_version": o["model_version"],
                "privacy": "faces and plate areas blurred from detector boxes (best effort)",
            })
        manifest = {
            "name": "SwarmSight regional road dataset", "version": version, "created": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "samples": samples, "classes": CLASSES, "n_samples": len(samples),
            "counts": {"by_label": dict(Counter(s["label"] for s in samples)), "by_split": dict(Counter(s["split"] for s in samples)),
                       "by_level": dict(Counter(s["quality_level"] for s in samples))},
            "split_rule": "by trip (sha1 of the trip id): 70% train, 15% val, 15% test; never by frame",
            "rights": "only trips uploaded with rights scope road_and_dataset", "data_value_weights": WEIGHTS,
            "annotations": "boxes are model pre-annotations (YOLO11n road users, our road-damage model) and are NOT human-verified",
        }
        z.writestr("manifest.json", json.dumps(manifest, indent=1))
        z.writestr("annotations.json", json.dumps({"images": coco_images, "annotations": coco_anns, "categories": CLASSES}))
        z.writestr("classes.txt", "\n".join(CLASSES))
        z.writestr("README.md", README.format(version=version, n=len(samples)))
    path.write_bytes(buf.getvalue())
    summ = {k: manifest["counts"][k] for k in manifest["counts"]} | {"bytes": path.stat().st_size, "include_unreviewed": include_unreviewed}
    store.insert("dataset_exports", {"version": version, "created_at": time.time(), "n_samples": len(samples), "summary": summ,
                                     "file": path.name})
    return {"version": version, "n_samples": len(samples), "file": path.name, "summary": summ}


README = """# SwarmSight regional road dataset {version}

{n} samples mined from fleet trips by the SwarmSight Event Mining Engine.

* `manifest.json`: one entry per sample: label (after human review), the model's original label, interval in the trip,
  clip, key frames, location with its source and uncertainty, rights scope, data value and its parts.
* `clips/`: anonymised H.264 clips with context before and after the event.
* `images/<split>/`, `labels/<split>/`: key frames and YOLO-format boxes (`classes.txt`).
* `annotations.json`: the same boxes with scores and track ids.

Quality levels: `reviewed` = a moderator confirmed or corrected the event label; `raw_candidate` = found by the model only.
Boxes are model pre-annotations and have not been checked by a person. Split by trip, never by frame.
Faces and plates are blurred from detector boxes (best effort, not a guarantee). Use only within the recorded rights scope.
"""
