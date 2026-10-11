"""Reference labels: compare a processed trip with the team's own labels of the same footage, live.

A trip is compared only when its file is byte-identical to a labelled video (SHA-1 of the bytes), so any upload of
that file, from any browser, is checked against the same labels; other trips have no reference.  Labels come from
benchmarks/event_labels.csv (the event-mining benchmark), with optional Russian descriptions in
benchmarks/event_labels_ru.csv (same rows).  Nothing here depends on the model's output for that trip.

Rule (as in benchmarks/event_mining_eval.py, at family level): an observation and a labelled moment match when
[t_start - tol, t_end + tol] of the observation overlaps the labelled interval and the types are compatible (the same
type, or both road damage, or both safety).  tol = max(1 s, one analysed-frame interval).  Repeat sightings of one
labelled moment all count as correct; a labelled moment is found when at least one observation matches it.
"""
from __future__ import annotations

import csv
import hashlib
import threading
from pathlib import Path

DAMAGE = {"pothole", "alligator_crack", "transverse_crack", "longitudinal_crack"}
SAFETY = {"forward_collision_risk", "vru_near_path", "cut_in", "hard_braking"}


def _family(t: str) -> str:
    return "damage" if t in DAMAGE else "safety" if t in SAFETY else t


def _sha1(path: Path) -> str:
    h = hashlib.sha1()
    with open(path, "rb") as f:
        while chunk := f.read(1 << 20):
            h.update(chunk)
    return h.hexdigest()


def _rows(path: Path) -> list[dict]:
    if not path.exists():
        return []
    with open(path, newline="", encoding="utf-8") as f:
        return [r for r in csv.DictReader(f) if r.get("video") and not r["video"].lstrip().startswith("#")]


class Reference:
    def __init__(self, root: Path):
        self.root = root
        self.labels_path = root / "benchmarks" / "event_labels.csv"
        self.ru_path = root / "benchmarks" / "event_labels_ru.csv"
        self._index: dict[str, str] | None = None  # sha1 -> labelled video path (as written in the label file)
        self._lock = threading.Lock()

    def index(self) -> dict[str, str]:
        with self._lock:
            if self._index is None:
                idx = {}
                for v in sorted({r["video"] for r in _rows(self.labels_path)}):
                    p = self.root / v
                    if p.is_file():
                        idx[_sha1(p)] = v
                self._index = idx
            return self._index

    def labels(self, video: str) -> list[dict]:
        ru = {(r["video"], r["start_s"], r["type"]): r.get("note", "") for r in _rows(self.ru_path)}
        out = []
        for r in _rows(self.labels_path):
            if r["video"] != video or r["type"] == "none":
                continue
            out.append({"start_s": float(r["start_s"]), "end_s": float(r["end_s"]), "type": r["type"],
                        "note": r.get("note", ""), "note_ru": ru.get((r["video"], r["start_s"], r["type"]), "")})
        return sorted(out, key=lambda x: (x["start_s"], x["type"]))

    def compare(self, trip: dict, observations: list[dict]) -> dict:
        video = self.index().get(trip.get("content_sha1") or "")
        if not video:
            return {"available": False}
        gts = self.labels(video)
        fps = (trip.get("info") or {}).get("sample_fps") or 5.0
        tol = round(max(1.0, 1.0 / fps), 3)
        preds = [o for o in observations if o["kind"] != "baseline"]
        for g in gts:
            g["matches"], g["exact"] = [], False
        out_obs = []
        for o in preds:
            a, b = min(o["t_start"], o["t_peak"]) - tol, max(o["t_end"], o["t_peak"]) + tol
            hit = [g for g in gts if a <= g["end_s"] and g["start_s"] <= b and _family(g["type"]) == _family(o["type"])]
            for g in hit:
                g["matches"].append(o["id"])
                g["exact"] = g["exact"] or g["type"] == o["type"]
            out_obs.append({"id": o["id"], "type": o["type"], "t_peak": o["t_peak"], "correct": bool(hit),
                            "label_types": sorted({g["type"] for g in hit})})
        found = [g for g in gts if g["matches"]]
        n_ok = sum(o["correct"] for o in out_obs)
        return {
            "available": True, "video": video, "tolerance_s": tol,
            "labels": [{**g, "found": bool(g["matches"])} for g in gts],
            "observations": out_obs,
            "summary": {"labelled": len(gts), "found": len(found), "found_exact_type": sum(g["exact"] for g in gts),
                        "observations": len(out_obs), "correct": n_ok, "false_alerts": len(out_obs) - n_ok,
                        "recall": round(len(found) / len(gts), 3) if gts else None,
                        "precision": round(n_ok / len(out_obs), 3) if out_obs else None},
            "rule": "an observation is correct when its interval (± tolerance) overlaps a labelled moment of the same "
                    "family (road damage or safety); a labelled moment is found when at least one observation matches it",
        }
