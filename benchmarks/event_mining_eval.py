#!/usr/bin/env python3
"""Event-level evaluation of the Event Mining Engine: hard numbers on whole trips, not mAP on single frames.

For every labelled video the full pipeline (EventMiner.mine) runs exactly as in the product, and its event
proposals are matched to the team's time-interval labels:

  detection   a proposal (kind != baseline) is a true positive when [t_start - tol, t_end + tol] overlaps a
              still unmatched label of a compatible type; greedy one-to-one, largest overlap first.  tol is
              max(--tol, one analysed-frame interval), so a ~1 fps photo sequence gets a frame of slack.  A proposal
              that overlaps a label another proposal already took is a duplicate (counted, not a false alert).
              Safety types must match exactly.  Road damage is scored twice: "road damage (any type)" merges
              overlapping damage labels of any type into one stretch that any damage proposal can match, and the
              per-type rows require the exact type.
              -> per type, overall and per video: GT, predictions, TP, duplicates, FP, precision, recall,
                 false alerts per hour of video
  reduction   kept_ratio = seconds kept in clips / seconds analysed;
              event retention = share of labelled events overlapping at least one kept clip
  latency     ms per analysed frame (p50/p95), wall seconds per minute of video, execution provider

Labels: CSV with header video,start_s,end_s,type,note (see benchmarks/README.md).  A row of type `none` spanning
the whole video says "no events here": the video still counts for false alerts per hour.  Rows whose video field
starts with '#' are comments.

Usage:
  python3 benchmarks/event_mining_eval.py --videos . --tracks samples
  python3 benchmarks/event_mining_eval.py --dry-run          # validate the label file only
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import os
import platform
import shutil
import sys
import tempfile
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

DAMAGE = ("pothole", "alligator_crack", "transverse_crack", "longitudinal_crack")
SAFETY = ("forward_collision_risk", "vru_near_path", "cut_in", "hard_braking")
TYPES = SAFETY + DAMAGE
NONE = "none"
COLUMNS = ("video", "start_s", "end_s", "type", "note")
CAVEATS = [
    "Tiny test set: the numbers below come from very few labelled minutes and events; they show how the "
    "pipeline is measured, not how well it performs in general (see the 95 % intervals).",
    "Labels by the team (one annotator, no second-annotator agreement), from frames reviewed every 0.5 s (video) "
    "or every photo (photo sequences) and frame by frame around events; judgement calls are in the label file's "
    "note column. On a road cracked almost everywhere, which crack counts as 'clearly visible' is subjective: the "
    "family-level road-damage row is more robust than the per-type rows.",
    "Two sources only: the team's dashcam (one 24 s clip) and one phone's Mapillary photo sequence (134 s, one "
    "photo every 1.1 s); one city, daylight; no night, rain or other mounts.",
    "False alerts per hour are extrapolated from the short labelled footage: one false alert in a minute "
    "of video reads as 60 per hour.",
    "kept_ratio includes the 5 s random baseline clip the product keeps per trip; event-only figures are "
    "reported next to it.",
]


# --------------------------------------------------------------------------------------------- labels
def video_duration(path: Path) -> float | None:
    import cv2

    cap = cv2.VideoCapture(str(path))
    if not cap.isOpened():
        return None
    fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
    fps = fps if 0.2 <= fps < 240.0 else 30.0  # same rule as the miner (a ~1 fps photo sequence is a video too)
    n = int(cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0)
    cap.release()
    return round(n / fps, 2) if n > 0 else None


def find_track(tracks_dir: Path | None, video: str, videos_dir: Path | None = None) -> Path | None:
    """<video stem>.csv|.gpx in --tracks, else next to the video itself."""
    stem = Path(video).stem
    dirs = [d for d in (tracks_dir, (videos_dir / video).parent if videos_dir is not None else None) if d is not None]
    for d in dirs:
        for ext in (".csv", ".gpx", ".CSV", ".GPX"):
            p = d / f"{stem}{ext}"
            if p.exists():
                return p
    return None


def load_labels(path: Path, videos_dir: Path, tracks_dir: Path | None):
    """Parse and validate the label file. Returns (videos, errors, warnings); videos: {video: {...}}."""
    errors, warnings = [], []
    videos: dict[str, dict] = {}
    if not path.exists():
        return videos, [f"label file not found: {path}"], warnings
    with open(path, newline="", encoding="utf-8-sig") as f:
        rd = csv.DictReader(f)
        header = [c.strip().lower() for c in (rd.fieldnames or [])]
        missing = [c for c in COLUMNS if c not in header]
        if missing:
            return videos, [f"header must be {','.join(COLUMNS)} (missing: {', '.join(missing)})"], warnings
        for ln, raw in enumerate(rd, start=2):
            if None in raw:
                errors.append(f"line {ln}: more than {len(COLUMNS)} fields (quote notes that contain commas)")
                continue
            r = {k.strip().lower(): (v or "").strip() for k, v in raw.items()}
            if not any(r.values()) or r["video"].startswith("#"):
                continue
            try:
                s, e = float(r["start_s"]), float(r["end_s"])
            except ValueError:
                errors.append(f"line {ln}: start_s and end_s must be numbers (got {r['start_s']!r}, {r['end_s']!r})")
                continue
            typ = r["type"].lower()
            if typ not in TYPES and typ != NONE:
                errors.append(f"line {ln}: unknown type {r['type']!r} (allowed: {', '.join(TYPES)}, none)")
                continue
            if not (math.isfinite(s) and math.isfinite(e)) or s < 0 or e < s:
                errors.append(f"line {ln}: need 0 <= start_s <= end_s (got {s}, {e})")
                continue
            v = videos.setdefault(r["video"], {"video": r["video"], "events": [], "none": False})
            if typ == NONE:
                v["none"] = True
                v["none_span"] = (s, e)
            else:
                v["events"].append({"line": ln, "type": typ, "start_s": s, "end_s": e, "note": r["note"]})
    for name, v in videos.items():
        p = videos_dir / name
        v["path"] = p
        if v["none"] and v["events"]:
            errors.append(f"{name}: has a 'none' row and event rows; use one or the other")
        if not p.exists():
            errors.append(f"{name}: video not found under {videos_dir}")
            continue
        dur = video_duration(p)
        v["duration_s"] = dur
        if dur is None:
            errors.append(f"{name}: cannot decode the video or read its length")
            continue
        for ev in v["events"]:
            if ev["start_s"] > dur:
                errors.append(f"{name} line {ev['line']}: starts at {ev['start_s']} s, after the end of the video ({dur} s)")
            elif ev["end_s"] > dur + 0.25:
                warnings.append(f"{name} line {ev['line']}: ends at {ev['end_s']} s, after the end of the video ({dur} s)")
        if v["none"]:
            s, e = v["none_span"]
            if s > 0.5 or e < dur - 0.5:
                warnings.append(f"{name}: the 'none' row covers {s}-{e} s but the video is {dur} s long; "
                                "'none' means the WHOLE video was checked")
        by_type = defaultdict(list)
        for ev in v["events"]:
            by_type[ev["type"]].append(ev)
        for typ, evs in by_type.items():
            evs = sorted(evs, key=lambda x: x["start_s"])
            for a, b in zip(evs, evs[1:]):
                if b["start_s"] <= a["end_s"]:
                    warnings.append(f"{name}: {typ} intervals on lines {a['line']} and {b['line']} overlap; "
                                    "merge them if they are one event")
        v["track"] = find_track(tracks_dir, name, videos_dir)
    return videos, errors, warnings


# --------------------------------------------------------------------------------------------- matching
def _compatible(pred_type: str, gt_type: str) -> bool:
    """Exact type, or any damage type against a merged "road_damage" event (family level)."""
    return pred_type == gt_type or (gt_type == "road_damage" and pred_type in DAMAGE)


def merge_damage(gts: list[dict], gap: float) -> list[dict]:
    """Family level: damage labels of any type that overlap or are within `gap` s form one road-damage event
    (a cracked stretch labelled alligator + longitudinal + transverse is one place to send a crew to)."""
    out: list[dict] = []
    for g in sorted([g for g in gts if g["type"] in DAMAGE], key=lambda g: g["start_s"]):
        if out and g["start_s"] <= out[-1]["end_s"] + gap:
            out[-1]["end_s"] = max(out[-1]["end_s"], g["end_s"])
            out[-1]["lines"].append(g["line"])
            out[-1]["types"].add(g["type"])
        else:
            out.append({"type": "road_damage", "start_s": g["start_s"], "end_s": g["end_s"], "lines": [g["line"]],
                        "types": {g["type"]}})
    safety = [{**g, "lines": [g["line"]], "types": {g["type"]}} for g in gts if g["type"] not in DAMAGE]
    return sorted(safety + out, key=lambda g: g["start_s"])


def match(preds: list[dict], gts: list[dict], tol: float) -> tuple[dict[int, int], set[int]]:
    """Greedy one-to-one matching by overlap, largest overlap first.

    Returns ({pred index: gt index}, duplicates): a duplicate is a prediction left unmatched although it overlaps a
    compatible label - another prediction already took that label (e.g. the same crack proposed twice)."""
    pairs = []
    for i, p in enumerate(preds):
        a = min(p["t_start"], p["t_peak"]) - tol
        b = max(p["t_end"], p["t_peak"]) + tol
        for j, g in enumerate(gts):
            if not _compatible(p["type"], g["type"]):
                continue
            lo, hi = max(a, g["start_s"]), min(b, g["end_s"])
            if hi >= lo:  # closed intervals: a single-frame label still matches
                centre = (g["start_s"] + g["end_s"]) / 2
                pairs.append((hi - lo, -abs(p["t_peak"] - centre), i, j))
    pairs.sort(key=lambda x: (-x[0], -x[1], x[2], x[3]))
    out, used = {}, set()
    for _, _, i, j in pairs:
        if i not in out and j not in used:
            out[i] = j
            used.add(j)
    dups = {i for _, _, i, _ in pairs if i not in out}
    return out, dups


def tally(preds, gts, m, dups, ptypes, gtypes) -> list[int]:
    """[gt, pred, tp, dup] for predictions of `ptypes` against labels of `gtypes`."""
    return [sum(g["type"] in gtypes for g in gts), sum(p["type"] in ptypes for p in preds),
            sum(preds[i]["type"] in ptypes for i in m), sum(preds[i]["type"] in ptypes for i in dups)]


def wilson(k: int, n: int, z: float = 1.96) -> list[float] | None:
    if n == 0:
        return None
    p = k / n
    d = 1 + z * z / n
    c = (p + z * z / (2 * n)) / d
    h = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / d
    return [round(max(0.0, c - h), 3), round(min(1.0, c + h), 3)]


def score(gt: int, pred: int, tp: int, dup: int, hours: float) -> dict:
    fp = pred - tp - dup
    return {"gt": gt, "pred": pred, "tp": tp, "dup": dup, "fp": fp, "fn": gt - tp,
            "precision": round(tp / pred, 3) if pred else None, "precision_ci95": wilson(tp, pred),
            "precision_incl_duplicates": round((tp + dup) / pred, 3) if pred else None,
            "recall": round(tp / gt, 3) if gt else None, "recall_ci95": wilson(tp, gt),
            "false_alerts_per_hour": round(fp / hours, 1) if hours > 0 else None,
            "duplicates_per_hour": round(dup / hours, 1) if hours > 0 else None}


def _overlaps(a0, a1, b0, b1) -> bool:
    return min(a1, b1) >= max(a0, b0)


# rows of the detection table: name -> (level, prediction types, label types)
ROWS = {**{t: ("exact", {t}, {t}) for t in TYPES},
        "road_damage_any_type": ("family", set(DAMAGE), {"road_damage"}),
        "safety": ("family", set(SAFETY), set(SAFETY)),
        "overall": ("family", set(TYPES), set(SAFETY) | {"road_damage"}),
        "overall_exact_types": ("exact", set(TYPES), set(TYPES))}


# --------------------------------------------------------------------------------------------- run
def provider_label(p: str | None) -> str:
    if not p:
        return "unknown"
    return "GPU (CUDA)" if "CUDA" in p else "GPU (TensorRT)" if "Tensorrt" in p else "CPU" if "CPU" in p else p


def cpu_name() -> str:
    try:
        for line in Path("/proc/cpuinfo").read_text().splitlines():
            if line.startswith("model name"):
                return line.split(":", 1)[1].strip()
    except OSError:
        pass
    return platform.processor() or platform.machine()


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def evaluate(args, videos: dict) -> dict:
    import numpy as np

    from swarmsight.detector import load_default_detectors
    from swarmsight.mining import EventMiner
    from swarmsight.telemetry import parse_track

    load_before = os.getloadavg()[0] if hasattr(os, "getloadavg") else None
    dets = load_default_detectors(threads=args.threads)
    if not dets:
        sys.exit("no detector weights found (models/yolo11n_coco.onnx, models/road_damage_yolo11n.onnx)")
    media = Path(args.media_dir) if args.media_dir else Path(tempfile.mkdtemp(prefix="event_eval_"))
    miner = EventMiner(dets, media)
    per_video, details, all_ms = [], [], []
    counts = defaultdict(lambda: [0, 0, 0, 0])  # row -> [gt, pred, tp, dup], all videos
    retention = {"any_clip": 0, "event_clip": 0, "via_match": 0, "n": 0}
    tot = {"analysed_s": 0.0, "kept_s": 0.0, "kept_event_s": 0.0, "wall_s": 0.0, "analysis_s": 0.0}
    info = {}
    try:
        for name, v in videos.items():
            track = None
            if v["track"] is not None:
                track = parse_track(v["track"].read_bytes(), v["track"].name, args.track_offset_s)
            print(f"  mining {name} ({v['duration_s']} s{', telemetry ' + v['track'].name if track else ''}) ...",
                  flush=True)
            ms: list[float] = []
            res = miner.mine(str(v["path"]), f"eval:{name}", track, args.sample_fps, args.max_seconds,
                             on_frame=lambda fr, i, n: ms.append(fr["ms"]))
            info = res["info"]
            all_ms += ms
            analysed = float(res["reduction"]["analysed_s"])
            # one analysed-frame interval of slack at least: a photo sequence has a frame every ~1 s
            frame_dt = 1.0 / float(info["sample_fps"]) if info.get("sample_fps") else 0.0
            tol = round(max(args.tol, frame_dt), 3)
            preds = [e for e in res["events"] if e["kind"] != "baseline"]
            gts = [g for g in v["events"] if g["start_s"] <= analysed]
            fam = merge_damage(gts, tol)
            skipped = len(v["events"]) - len(gts)
            clips = res["clips"]
            kinds = {e["local_id"]: e["kind"] for e in res["events"]}
            ev_clips = [c for c in clips if any(kinds.get(i) != "baseline" for i in c["events"])]
            clip_by_id = {c["id"]: c for c in clips}
            kept = sum(c["t1"] - c["t0"] for c in clips)
            kept_ev = sum(c["t1"] - c["t0"] for c in ev_clips)
            m_ex, d_ex = match(preds, gts, tol)
            m_fam, d_fam = match(preds, fam, tol)
            vcounts = {}
            for row, (lvl, ptypes, gtypes) in ROWS.items():
                c = tally(preds, fam, m_fam, d_fam, ptypes, gtypes) if lvl == "family" else \
                    tally(preds, gts, m_ex, d_ex, ptypes, gtypes)
                vcounts[row] = c
                counts[row] = [a + b for a, b in zip(counts[row], c)]
            gt_of = {j: i for i, j in m_fam.items()}
            ex_of = {j: i for i, j in m_ex.items()}
            ev_rows, n_ret, n_via = [], 0, 0
            for j, g in enumerate(fam):
                any_c = [c["id"] for c in clips if _overlaps(g["start_s"], g["end_s"], c["t0"], c["t1"])]
                ev_c = [c["id"] for c in ev_clips if _overlaps(g["start_s"], g["end_s"], c["t0"], c["t1"])]
                pi = gt_of.get(j)
                pc = clip_by_id.get(preds[pi]["clip_id"]) if pi is not None else None
                via = pc is not None and _overlaps(g["start_s"], g["end_s"], pc["t0"], pc["t1"])
                retention["n"] += 1
                retention["any_clip"] += bool(any_c)
                retention["event_clip"] += bool(ev_c)
                retention["via_match"] += via
                n_ret += bool(any_c)
                n_via += via
                ev_rows.append({"type": g["type"], "types": sorted(g["types"]), "start_s": g["start_s"],
                                "end_s": g["end_s"], "label_lines": g["lines"], "matched_pred": pi,
                                "retained": bool(any_c), "retained_via_matched_event": via})
            gt_rows = [{"line": g["line"], "type": g["type"], "start_s": g["start_s"], "end_s": g["end_s"],
                        "matched_pred_exact_type": ex_of.get(j), "note": g["note"]} for j, g in enumerate(gts)]
            pred_rows = []
            for i, p in enumerate(preds):
                j = m_fam.get(i)
                pred_rows.append({"index": i, "type": p["type"], "t_start": p["t_start"], "t_end": p["t_end"],
                                  "t_peak": p["t_peak"], "conf": p["conf"], "severity": p["severity"],
                                  "status": "TP" if j is not None else "DUP" if i in d_fam else "FP",
                                  "status_exact_type": "TP" if i in m_ex else "DUP" if i in d_ex else "FP",
                                  "matched_label_lines": fam[j]["lines"] if j is not None else None,
                                  "clip_id": p["clip_id"], "evidence": p["evidence"]})
            perf = res["perf"]
            hours_v = analysed / 3600.0
            per_video.append({
                "video": name, "duration_s": v["duration_s"], "analysed_s": analysed,
                "sample_fps": round(float(info["sample_fps"]), 3), "frames": perf["frames"],
                "match_tolerance_s": tol, "telemetry": v["track"].name if track is not None else None,
                "labelled_none": v["none"], "gt_labels": len(gts), "gt_events": len(fam),
                "gt_labels_after_analysed_span": skipped, "predictions": len(preds),
                "detection": {row: score(*vcounts[row], hours_v) for row in ("road_damage_any_type", "safety", "overall",
                                                                              "overall_exact_types")},
                "kept_s": round(kept, 2), "kept_event_s": round(kept_ev, 2),
                "kept_ratio": round(kept / analysed, 4) if analysed else None,
                "kept_ratio_event_clips_only": round(kept_ev / analysed, 4) if analysed else None,
                "event_retention": round(n_ret / len(fam), 3) if fam else None,
                "event_retention_via_matched_event": round(n_via / len(fam), 3) if fam else None,
                "clips": [{"t0": c["t0"], "t1": c["t1"],
                           "kind": "event" if c in ev_clips else "baseline"} for c in clips],
                "ms_per_frame_p50": perf["ms_per_frame_p50"], "ms_per_frame_p95": perf["ms_per_frame_p95"],
                "analysis_s": perf["analysis_s"], "clips_s": perf["clips_s"], "wall_s": perf["wall_s"],
                "wall_s_per_video_minute": round(perf["wall_s"] / (analysed / 60), 2) if analysed else None,
            })
            details.append({"video": name, "events": ev_rows, "labels": gt_rows, "predictions": pred_rows})
            tot["analysed_s"] += analysed
            tot["kept_s"] += kept
            tot["kept_event_s"] += kept_ev
            tot["wall_s"] += perf["wall_s"]
            tot["analysis_s"] += perf["analysis_s"]
    finally:
        if not args.media_dir:
            shutil.rmtree(media, ignore_errors=True)

    hours = tot["analysed_s"] / 3600.0
    rows = {row: score(*counts[row], hours) for row in ROWS}
    n = retention["n"]
    a = tot["analysed_s"]
    provider = info.get("provider")
    pct = lambda x: round(float(np.percentile(all_ms, x)), 1) if all_ms else None  # noqa: E731
    return {
        "per_video": per_video, "detection": rows, "details": details,
        "reduction": {
            "analysed_s": round(a, 2), "kept_s": round(tot["kept_s"], 2), "kept_event_s": round(tot["kept_event_s"], 2),
            "kept_ratio": round(tot["kept_s"] / a, 4) if a else None,
            "kept_ratio_event_clips_only": round(tot["kept_event_s"] / a, 4) if a else None,
            "gt_events": n,
            "event_retention": round(retention["any_clip"] / n, 3) if n else None,
            "event_retention_event_clips_only": round(retention["event_clip"] / n, 3) if n else None,
            "event_retention_via_matched_event": round(retention["via_match"] / n, 3) if n else None,
            "retained": retention["any_clip"], "retained_via_matched_event": retention["via_match"],
            "note": "events = labelled safety events plus road-damage stretches (damage labels of any type that "
                    "overlap or touch merged into one), the same units as the 'overall' detection row",
        },
        "latency": {
            "frames": len(all_ms), "ms_per_frame_p50": pct(50), "ms_per_frame_p95": pct(95),
            "wall_s_per_video_minute": round(tot["wall_s"] / (a / 60), 2) if a else None,
            "analysis_s_per_video_minute": round(tot["analysis_s"] / (a / 60), 2) if a else None,
            "realtime_factor": round(a / tot["wall_s"], 2) if tot["wall_s"] else None,
            "provider": provider_label(provider), "execution_provider": provider,
            "cpu": cpu_name(), "cpu_count": os.cpu_count(),
            "load_avg_1min_before": round(load_before, 2) if load_before is not None else None,
            "threads": args.threads or int(os.environ.get("SWARMSIGHT_THREADS", "0") or 0) or "onnxruntime default",
            "note": "ms per frame = both detectors + tracking on one analysed frame; wall time includes decoding, "
                    "proposals and writing the anonymised clips (ffmpeg); per minute of video depends on the frame "
                    "rate (a 1 fps photo sequence has 5x fewer frames per minute than video sampled at 5 fps); "
                    "a load average near or above cpu_count means other processes shared the CPU",
        },
        "model_version": info.get("model_version"),
    }


# --------------------------------------------------------------------------------------------- output
def _f(x, pct=False, nd=0):
    if x is None:
        return "-"
    return f"{100 * x:.{nd}f}%" if pct else f"{x:g}"


def _row(name: str, s: dict, w: int = 26) -> str:
    return (f"{name:<{w}}{s['gt']:>4}{s['pred']:>6}{s['tp']:>4}{s['dup']:>5}{s['fp']:>4}{_f(s['precision'], True):>7}"
            f"{_f(s['recall'], True):>8}{_f(s['false_alerts_per_hour']):>8}")


def print_table(out: dict) -> None:
    r, d, lat = out["reduction"], out["detection"], out["latency"]
    print(f"\nEvent mining eval: {len(out['videos'])} video(s), {r['analysed_s']} s analysed, {r['gt_events']} labelled "
          f"events ({out['labels']['events']} label rows), {lat['provider']}")
    head = f"{'GT':>4}{'pred':>6}{'TP':>4}{'dup':>5}{'FP':>4}{'prec':>7}{'recall':>8}{'FA/h':>8}"
    print(f"{'type':<26}{head}")
    order = [t for t in TYPES if d[t]["gt"] or d[t]["pred"]]
    for name in order + ["road_damage_any_type", "safety", "overall", "overall_exact_types"]:
        print(_row(name, d[name]))
    hidden = [t for t in TYPES if t not in order]
    if hidden:
        print(f"  (no GT and no predictions: {', '.join(hidden)})")
    print(f"\n{'per video (overall row)':<26}{head}{'kept':>7}{'ret.':>6}{'s/min':>7}")
    for v in out["per_video"]:
        print(_row(Path(v["video"]).name[:25], v["detection"]["overall"])
              + f"{_f(v['kept_ratio'], True):>7}{_f(v['event_retention'], True):>6}{_f(v['wall_s_per_video_minute']):>7}"
              + f"   ({v['sample_fps']} fps, tol {v['match_tolerance_s']} s)")
    print(f"\nReduction: kept {_f(r['kept_ratio'], True, 1)} of the video ({_f(r['kept_ratio_event_clips_only'], True, 1)} "
          f"without the baseline clips); event retention {_f(r['event_retention'], True)} ({r['retained']}/{r['gt_events']}), "
          f"through a correctly matched event {_f(r['event_retention_via_matched_event'], True)} "
          f"({r['retained_via_matched_event']}/{r['gt_events']})")
    print(f"Latency: {lat['ms_per_frame_p50']} ms/frame p50, {lat['ms_per_frame_p95']} p95; "
          f"{lat['wall_s_per_video_minute']} s wall per minute of video ({lat['realtime_factor']}x real time); "
          f"{lat['execution_provider']} on {lat['cpu']} (load {lat['load_avg_1min_before']} on {lat['cpu_count']} CPUs)")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--labels", default=str(ROOT / "benchmarks" / "event_labels.csv"))
    ap.add_argument("--videos", default=str(ROOT), help="directory the label file's video paths are relative to")
    ap.add_argument("--tracks", default=None, help="directory with <video stem>.csv|.gpx telemetry (optional)")
    ap.add_argument("--track-offset-s", type=float, default=0.0, help="track time at the start of each video")
    ap.add_argument("--sample-fps", type=float, default=5.0)
    ap.add_argument("--max-seconds", type=float, default=7200.0, help="analyse at most this much of each video")
    ap.add_argument("--tol", type=float, default=1.0, help="seconds added on both sides of a prediction for matching")
    ap.add_argument("--threads", type=int, default=None, help="ONNX Runtime intra-op threads")
    ap.add_argument("--media-dir", default=None, help="keep the clips the miner writes here (default: temp, deleted)")
    ap.add_argument("--out", default=str(ROOT / "benchmarks" / "results" / "event_mining_eval.json"))
    ap.add_argument("--dry-run", action="store_true", help="validate the label file and exit")
    args = ap.parse_args()

    labels = Path(args.labels)
    tracks_dir = Path(args.tracks) if args.tracks else None
    if tracks_dir is not None and not tracks_dir.is_dir():
        sys.exit(f"--tracks: not a directory: {tracks_dir}")
    videos, errors, warnings = load_labels(labels, Path(args.videos), tracks_dir)
    for w in warnings:
        print("warning:", w)
    for e in errors:
        print("error:", e)
    if not videos and not errors:
        errors.append("no labelled videos in the label file")
        print("error:", errors[-1])
    if args.dry_run or errors:
        for name, v in videos.items():
            types = ", ".join(f"{g['type']} {g['start_s']}-{g['end_s']} s" for g in v["events"]) or (
                "none (no events)" if v["none"] else "no rows")
            trk = v.get("track").name if v.get("track") else "no telemetry"
            print(f"  {name}: {v.get('duration_s', '?')} s, {trk}; {types}")
        print(f"{labels}: {len(videos)} video(s), {sum(len(v['events']) for v in videos.values())} event(s), "
              f"{len(errors)} error(s), {len(warnings)} warning(s)")
        sys.exit(1 if errors else 0)

    res = evaluate(args, videos)
    try:
        label_name = str(labels.resolve().relative_to(ROOT))
    except ValueError:
        label_name = str(labels)
    out = {
        "benchmark": "event_mining_eval",
        "date": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "labels": {"file": label_name, "sha256": sha256(labels),
                   "videos": len(videos), "events": sum(len(v["events"]) for v in videos.values())},
        "code": {"mining_py_sha256": sha256(ROOT / "swarmsight" / "mining.py"), "model_version": res["model_version"]},
        "config": {"sample_fps": args.sample_fps,
                   "sample_fps_effective": {v["video"]: v["sample_fps"] for v in res["per_video"]},
                   "max_seconds": args.max_seconds, "match_tolerance_s": args.tol,
                   "match_tolerance_rule": "max(--tol, one analysed-frame interval) per video",
                   "matching": "prediction [t_start - tol, t_end + tol] overlaps an unmatched label of a compatible "
                               "type; greedy one-to-one by overlap; an unmatched prediction overlapping an already "
                               "matched label is a duplicate (dup), not a false alert; precision = TP / predictions; "
                               "family level merges overlapping damage labels of any type into one road-damage "
                               "event; baseline clips are not predictions",
                   "telemetry": bool(tracks_dir)},
        "provider": res["latency"]["provider"],
        "videos": [{"video": v["video"], "duration_s": v["duration_s"]} for v in res["per_video"]],
        "detection": res["detection"],
        "reduction": res["reduction"],
        "latency": res["latency"],
        "per_video": res["per_video"],
        "details": res["details"],
        "caveats": [f"Tiny test set: {len(res['per_video'])} video(s), {res['reduction']['analysed_s']} s of video, "
                    f"{res['reduction']['gt_events']} labelled event(s); 95 % intervals are given for every rate."] + CAVEATS[1:],
    }
    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    Path(args.out).write_text(json.dumps(out, indent=1, default=lambda o: o.item() if hasattr(o, "item") else str(o)))
    print_table(out)
    print(f"\nwrote {args.out}")


if __name__ == "__main__":
    main()
