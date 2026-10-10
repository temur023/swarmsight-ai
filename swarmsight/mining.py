"""Event Mining Engine: one trip video (plus optional telemetry) becomes a few verifiable, time-stamped clips.

  pass 1  decode -> sample frames -> detect road users + road damage -> track (ByteTrack)
          -> temporal event proposals from the tracks and the telemetry
  pass 2  clip extraction with context before and after each event -> faces and plates blurred
          -> key frames with model pre-annotations -> thumbnail, image quality and an embedding for novelty

Event types (what the front camera and the telemetry can support, nothing more):
  road    pothole, alligator_crack, transverse_crack, longitudinal_crack (road-damage detector, tracked)
  safety  forward_collision_risk  a road user in our path with time to contact under 3 s (box expansion)
          vru_near_path           a pedestrian or rider close in front of the car
          cut_in                  a vehicle moving sideways into our path, relative to the rest of the scene
          hard_braking            deceleration over 3 m/s2 from the telemetry; linked to what the camera saw before it
  baseline one random stretch of ordinary driving per trip, so the dataset is not made of incidents only

A proposal is a candidate for human review, not a verdict: safety episodes carry causal_claim = not_established.
"""
from __future__ import annotations

import hashlib
import shutil
import subprocess
import time
import uuid
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from pathlib import Path

import cv2
import numpy as np

from .detector import Detections, YoloOnnxDetector
from .privacy import _blur
from .roadusers import GROUP, GROUP_IDS, VEHICLES, VRU, compose_road_users, iou
from .telemetry import Track
from .tracker import ByteTracker, time_to_contact

MAX_SIDE = 1280
CLIP_W = 960
TTC_WARN_S = 3.0
DAMAGE_TYPES = ("pothole", "alligator_crack", "transverse_crack", "longitudinal_crack")
BASE_SEVERITY = {"pothole": 0.9, "alligator_crack": 0.6, "transverse_crack": 0.35, "longitudinal_crack": 0.3}
# seconds of context before / after the event in its clip
WINDOWS = {**{t: (2.0, 1.5) for t in DAMAGE_TYPES}, "forward_collision_risk": (4.0, 2.0), "vru_near_path": (3.0, 2.0),
           "cut_in": (4.0, 3.0), "hard_braking": (6.0, 3.0), "baseline_drive": (0.0, 5.0)}
SAFETY_PRIORITY = {"cut_in": 3, "forward_collision_risk": 2, "vru_near_path": 1}
MAX_CLIPS = 16
MAX_CLIP_S = 14.0


def kind_of(event_type: str) -> str:
    return "road" if event_type in DAMAGE_TYPES else "baseline" if event_type == "baseline_drive" else "safety"


def damage_severity(cls: str, bbox, w: int, h: int, conf: float) -> float:
    """0..1 priority: damage type x apparent size x proximity (lower in the frame = closer)."""
    x1, y1, x2, y2 = bbox
    size = min(1.0, float(np.sqrt(max(0.0, (x2 - x1) * (y2 - y1)) / (w * h))) / 0.35)
    proximity = min(1.0, max(0.0, y2 / h))
    return round(float(min(1.0, BASE_SEVERITY.get(cls, 0.5) * (0.55 + 0.25 * size + 0.2 * proximity) * (0.7 + 0.3 * conf))), 3)


def _resize(img):
    h, w = img.shape[:2]
    s = MAX_SIDE / max(h, w)
    return cv2.resize(img, (int(w * s), int(h * s)), interpolation=cv2.INTER_AREA) if s < 1 else img


def _in_corridor(box, w, h) -> bool:
    """Our own path for a forward-facing camera: the central band of the lower part of the frame."""
    cx = (box[0] + box[2]) / 2
    return 0.3 * w <= cx <= 0.7 * w and box[3] >= 0.45 * h


def _intervals(times: list[float], gap: float) -> list[list[float]]:
    out: list[list[float]] = []
    for t in sorted(times):
        if out and t - out[-1][1] <= gap:
            out[-1][1] = t
        else:
            out.append([t, t])
    return out


def ffmpeg_available() -> bool:
    return shutil.which("ffmpeg") is not None


@dataclass
class Proposal:
    type: str
    t_start: float
    t_end: float
    t_peak: float
    conf: float
    severity: float
    bbox: list | None
    track_ids: list = field(default_factory=list)
    evidence: dict = field(default_factory=dict)
    context: list = field(default_factory=list)

    @property
    def kind(self) -> str:
        return kind_of(self.type)

    @property
    def score(self) -> float:
        return self.conf * (0.5 + self.severity) if self.kind == "road" else 0.5 + self.severity


class EventMiner:
    def __init__(self, detectors: dict[str, YoloOnnxDetector], media_dir: str | Path):
        self.users = detectors.get("road_users")
        self.damage = detectors.get("road_damage")
        self.media_dir = Path(media_dir)
        for sub in ("clips", "frames", "thumbs"):
            (self.media_dir / sub).mkdir(parents=True, exist_ok=True)

    @property
    def model_version(self) -> str:
        return "+".join(d.name for d in (self.users, self.damage) if d)

    # ------------------------------------------------------------------------------------------- pass 1
    def _analyse(self, path, sample_fps, max_seconds, on_frame, should_stop):
        cap = cv2.VideoCapture(str(path))
        if not cap.isOpened():
            raise ValueError("cannot decode the video (supported: mp4, mov, webm, avi with H.264/H.265/VP8/VP9)")
        fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
        fps = fps if 1.0 < fps < 240.0 else 30.0
        n_total = int(cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0)
        step = max(1, int(round(fps / sample_fps)))
        max_frames = int(max_seconds * fps)
        n_expected = min(n_total, max_frames) if n_total > 0 else max_frames
        utrack = ByteTracker(high_thr=0.45, low_thr=0.15, new_track_thr=0.5, track_buffer=10, min_hits=2)
        dtrack = ByteTracker(high_thr=0.35, low_thr=0.15, new_track_thr=0.35, match_thr=0.95, track_buffer=4, min_hits=2)
        gnames = {v: k for k, v in GROUP_IDS.items()}
        labels: dict[int, Counter] = defaultdict(Counter)
        frames, lat = [], []
        idx, w, h = 0, None, None
        while idx < max_frames:
            if not cap.grab():
                break
            if idx % step:
                idx += 1
                continue
            ok, img = cap.retrieve()
            if not ok:
                break
            if should_stop and should_stop():
                break
            t = idx / fps
            img = _resize(img)
            h, w = img.shape[:2]
            t0 = time.perf_counter()
            u = self.users(img) if self.users else Detections.empty()
            d = self.damage(img) if self.damage else Detections.empty()
            users = compose_road_users(u)
            ud = Detections(np.array([x[0] for x in users], np.float32).reshape(-1, 4), np.array([x[2] for x in users], np.float32),
                            np.array([GROUP_IDS[GROUP[x[1]]] for x in users], np.int32), gnames)
            fu = []
            for tr in utrack.update(ud, t):
                box = tr.history[-1][1]
                best = max(range(len(users)), key=lambda i: iou(users[i][0], box), default=None)
                if best is not None:
                    labels[tr.track_id][users[best][1]] += 1
                cls = labels[tr.track_id].most_common(1)[0][0] if labels[tr.track_id] else gnames[tr.cls]
                rec = {"id": tr.track_id, "cls": cls, "bbox": [round(float(v), 1) for v in box], "conf": round(tr.conf, 2),
                       "corridor": bool(_in_corridor(box, w, h))}
                ttc = time_to_contact(tr) if rec["corridor"] else None
                if ttc is not None and ttc < 10:
                    rec["ttc"] = round(ttc, 2)
                fu.append(rec)
            fd = []
            for tr in dtrack.update(d, t):
                box = tr.history[-1][1]
                cls = d.names.get(tr.cls, str(tr.cls))
                fd.append({"id": tr.track_id, "cls": cls, "bbox": [round(float(v), 1) for v in box], "conf": round(tr.conf, 2),
                           "severity": damage_severity(cls, box, w, h, tr.conf)})
            dt = (time.perf_counter() - t0) * 1e3
            lat.append(dt)
            # raw detector boxes are what we blur in the clips (a rider's head, a plate on a partly hidden car)
            blur = [(u.label(i), [float(v) for v in u.xyxy[i]]) for i in range(len(u)) if u.label(i) in GROUP]
            fr = {"t": round(t, 3), "w": w, "h": h, "users": fu, "damage": fd, "ms": round(dt, 1), "_blur": blur}
            frames.append(fr)
            if on_frame:
                on_frame({k: v for k, v in fr.items() if k != "_blur"}, idx, n_expected)
            idx += 1
        cap.release()
        if w is None:
            raise ValueError("no frames could be decoded")
        return frames, {"fps": fps, "sample_fps": fps / step, "analysed_s": round(idx / fps, 2), "width": w, "height": h,
                        "n_total_frames": n_total, "duration_s": round(n_total / fps, 2) if n_total else round(idx / fps, 2),
                        "ms_per_frame_p50": round(float(np.median(lat)), 1) if lat else None,
                        "ms_per_frame_p95": round(float(np.percentile(lat, 95)), 1) if lat else None}, labels

    # ------------------------------------------------------------------------------------------- proposals
    @staticmethod
    def propose(frames: list[dict], track: Track | None = None) -> list[Proposal]:
        if not frames:
            return []
        w, h = frames[0]["w"], frames[0]["h"]
        dt = float(np.median(np.diff([f["t"] for f in frames]))) if len(frames) > 1 else 0.2
        out: list[Proposal] = []
        # road damage: tracks of one class, joined across short gaps (id switches as the car drives over it)
        dtracks: dict[int, list] = defaultdict(list)
        for f in frames:
            for d in f["damage"]:
                dtracks[d["id"]].append((f["t"], d))
        by_cls: dict[str, list] = defaultdict(list)
        for tid, obs in dtracks.items():
            if len(obs) < 2:
                continue
            cls = Counter(o["cls"] for _, o in obs).most_common(1)[0][0]
            by_cls[cls].append((obs[0][0], obs[-1][0], tid, obs))
        for cls, items in by_cls.items():
            items.sort()
            groups: list[list] = []
            for it in items:
                if groups and it[0] - groups[-1][-1][1] <= 1.0:
                    groups[-1].append(it)
                else:
                    groups.append([it])
            for g in groups:
                allobs = [(t, o) for it in g for t, o in it[3]]
                tp, op = max(allobs, key=lambda x: x[1]["conf"] * (0.5 + x[1]["severity"]))
                out.append(Proposal(cls, g[0][0], max(it[1] for it in g), tp, max(o["conf"] for _, o in allobs),
                                    max(o["severity"] for _, o in allobs), op["bbox"], [it[2] for it in g],
                                    {"frames_seen": len(allobs), "tracks": len(g)}))
        # safety: per road-user track
        utracks: dict[int, list] = defaultdict(list)
        for f in frames:
            for u in f["users"]:
                utracks[u["id"]].append((f["t"], u))
        # scene motion between frames: median sideways shift of all tracks (the camera turning moves them all)
        shift: dict[tuple, float] = {}

        def scene_shift(t0, t1):
            k = (t0, t1)
            if k not in shift:
                f0 = next(f for f in frames if f["t"] == t0)
                f1 = next(f for f in frames if f["t"] == t1)
                b0 = {u["id"]: u["bbox"] for u in f0["users"]}
                d = [((u["bbox"][0] + u["bbox"][2]) - (b0[u["id"]][0] + b0[u["id"]][2])) / 2 for u in f1["users"] if u["id"] in b0]
                shift[k] = (float(np.median(d)), len(d))
            return shift[k]

        for tid, obs in utracks.items():
            cls = Counter(o["cls"] for _, o in obs).most_common(1)[0][0]
            ttc_t = [(t, o) for t, o in obs if o.get("ttc") is not None and o["ttc"] < TTC_WARN_S]
            for a, b in _intervals([t for t, _ in ttc_t], 0.6 + dt):
                inside = [(t, o) for t, o in ttc_t if a <= t <= b]
                if len(inside) < 2:
                    continue
                tp, op = min(inside, key=lambda x: x[1]["ttc"])
                out.append(Proposal("forward_collision_risk", a, b, tp, max(o["conf"] for _, o in inside),
                                    round(float(np.clip(1 - op["ttc"] / 4, 0.2, 1)), 3), op["bbox"], [tid],
                                    {"min_ttc_s": op["ttc"], "road_user": cls, "frames_seen": len(inside)}))
            if cls in VRU:
                near = [(t, o) for t, o in obs if o["corridor"] and (o["bbox"][3] - o["bbox"][1]) > 0.12 * h]
                for a, b in _intervals([t for t, _ in near], 0.6 + dt):
                    inside = [(t, o) for t, o in near if a <= t <= b]
                    if len(inside) < 2:
                        continue
                    tp, op = max(inside, key=lambda x: x[1]["bbox"][3] - x[1]["bbox"][1])
                    size = (op["bbox"][3] - op["bbox"][1]) / h
                    out.append(Proposal("vru_near_path", a, b, tp, max(o["conf"] for _, o in inside),
                                        round(float(np.clip(0.4 + size, 0.4, 1)), 3), op["bbox"], [tid],
                                        {"road_user": cls, "frames_seen": len(inside)}))
            if cls in VEHICLES:
                for i, (t, o) in enumerate(obs):
                    bw, bh = o["bbox"][2] - o["bbox"][0], o["bbox"][3] - o["bbox"][1]
                    if not (o["corridor"] and o["bbox"][3] >= 0.5 * h and bh >= 0.08 * h):
                        continue
                    for t0, o0 in obs[:i]:
                        if t - t0 > 1.5 or t - t0 < 0.3:
                            continue
                        cx0, cx = (o0["bbox"][0] + o0["bbox"][2]) / 2, (o["bbox"][0] + o["bbox"][2]) / 2
                        if 0.3 * w <= cx0 <= 0.7 * w:
                            continue
                        m, n = scene_shift(t0, t)
                        rel = (cx - cx0) - (m if n >= 3 else 0.0)
                        if abs(rel) >= 0.5 * bw and np.sign(rel) == np.sign(w / 2 - cx0):
                            out.append(Proposal("cut_in", t0, t, t, o["conf"], round(float(np.clip(0.5 + bh / h, 0.5, 1)), 3),
                                                o["bbox"], [tid], {"road_user": cls, "from_side": "left" if cx0 < w / 2 else "right",
                                                                   "lateral_px": round(float(rel), 1), "over_s": round(t - t0, 2)}))
                            break
                    else:
                        continue
                    break
        out = _dedupe_safety(out)
        # hard braking from the telemetry, linked to what the front camera saw just before it
        if track is not None:
            for br in track.braking():
                if br["t_peak"] > frames[-1]["t"] + 1:
                    continue
                ctx = [p for p in out if p.kind == "safety" and br["t_start"] - 4.0 <= p.t_peak <= br["t_end"] + 1.0]
                out.append(Proposal("hard_braking", br["t_start"], br["t_end"], br["t_peak"], 1.0,
                                    round(float(np.clip(br["peak_decel_ms2"] / 6.0, 0.3, 1)), 3), None, [],
                                    {**br, "visual_context": [{"type": p.type, "t": round(p.t_peak, 2)} for p in ctx],
                                     "interpretation": ("possible forced reaction: the camera saw " + ", ".join(sorted({p.type for p in ctx}))
                                                        if ctx else "no trigger visible to the front camera"),
                                     "causal_claim": "not_established", "driver_fault": "not_determined"}))
        out.sort(key=lambda p: p.t_peak)
        return out

    # ------------------------------------------------------------------------------------------- pass 2
    def _segments(self, props: list[Proposal], analysed_s: float, trip_id: str) -> tuple[list[dict], dict]:
        wins = []
        for i, p in enumerate(props):
            b, a = WINDOWS.get(p.type, (2.0, 2.0))
            t0, t1 = max(0.0, min(p.t_start, p.t_peak) - b), min(analysed_s, max(p.t_end, p.t_peak) + a)
            if t1 - t0 > MAX_CLIP_S:
                t0, t1 = max(0.0, p.t_peak - MAX_CLIP_S / 2), min(analysed_s, p.t_peak + MAX_CLIP_S / 2)
            wins.append((t0, t1, i))
        # cap: keep the clips of the strongest events; the rest keep a thumbnail
        keep = set(sorted(range(len(props)), key=lambda i: -props[i].score)[:MAX_CLIPS])
        wins = sorted(x for x in wins if x[2] in keep)
        segs: list[dict] = []
        for t0, t1, i in wins:
            if segs and t0 <= segs[-1]["t1"] + 0.5:
                segs[-1]["t1"] = max(segs[-1]["t1"], t1)
                segs[-1]["events"].append(i)
            else:
                segs.append({"t0": t0, "t1": t1, "events": [i]})
        # baseline: one seeded stretch of ordinary driving away from every event
        baseline = None
        if analysed_s >= 12:
            rng = np.random.default_rng(int(hashlib.sha1(trip_id.encode()).hexdigest()[:8], 16))
            busy = [(s["t0"] - 1, s["t1"] + 1) for s in segs]
            for _ in range(40):
                t0 = float(rng.uniform(0, analysed_s - 5))
                if all(t0 + 5 <= a or t0 >= b for a, b in busy):
                    baseline = (round(t0, 2), round(t0 + 5, 2))
                    break
        return segs, {"baseline": baseline}

    def _encoder(self, out: Path, w: int, h: int, fps: float):
        return subprocess.Popen(["ffmpeg", "-y", "-loglevel", "error", "-f", "rawvideo", "-pix_fmt", "bgr24", "-s", f"{w}x{h}",
                                 "-r", f"{fps:.3f}", "-i", "-", "-c:v", "libx264", "-preset", "veryfast", "-crf", "26",
                                 "-pix_fmt", "yuv420p", "-movflags", "+faststart", "-an", str(out)], stdin=subprocess.PIPE)

    def _cut(self, path, fps, frames, segs, props, sample_dt, on_progress=None):
        """Read the video once more and write each segment as an anonymised H.264 clip with key frames."""
        aw, ah = frames[0]["w"], frames[0]["h"]
        ow = min(CLIP_W, aw)
        oh = int(round(ah * ow / aw)) // 2 * 2
        s = ow / aw
        ftimes = np.array([f["t"] for f in frames])
        peaks = {}  # event index -> segment it belongs to
        for si, sg in enumerate(segs):
            sg["id"] = uuid.uuid4().hex[:16]
            sg["file"] = f"clips/{sg['id']}.mp4"
            sg["keyframes"] = []
            for i in sg["events"]:
                peaks[i] = si
        want_peak = {i: props[i].t_peak for i in range(len(props))}
        thumbs: dict[int, dict] = {}
        if not segs and not props:
            return thumbs
        last_t = max([sg["t1"] for sg in segs] + [p.t_peak for p in props]) + 0.1
        cap = cv2.VideoCapture(str(path))
        enc, cur, fi = None, None, 0
        have_ffmpeg = ffmpeg_available()
        while True:
            t = fi / fps
            if t > last_t or not cap.grab():
                break
            seg = next((k for k, sg in enumerate(segs) if sg["t0"] <= t <= sg["t1"]), None)
            need_peak = [i for i, tp in want_peak.items() if i not in thumbs and abs(t - tp) <= 0.5 / fps]
            if seg is None and not need_peak:
                if enc is not None:
                    enc.stdin.close()
                    enc.wait()
                    enc, cur = None, None
                fi += 1
                continue
            ok, img = cap.retrieve()
            if not ok:
                break
            img = cv2.resize(_resize(img), (ow, oh), interpolation=cv2.INTER_AREA)
            # blur: detections of the nearest analysed frames on both sides, padded for motion in between
            j = int(np.searchsorted(ftimes, t))
            near = [frames[k] for k in (j - 1, j) if 0 <= k < len(frames) and abs(frames[k]["t"] - t) <= 1.5 * sample_dt + 1e-6]
            for fr in near:
                for cls, (x1, y1, x2, y2) in fr["_blur"]:
                    x1, y1, x2, y2 = x1 * s, y1 * s, x2 * s, y2 * s
                    bw, bh = x2 - x1, y2 - y1
                    if cls == "person":
                        _blur(img, x1 - 0.15 * bw, y1 - 0.06 * bh, x2 + 0.15 * bw, y1 + 0.32 * bh)
                    elif cls in ("car", "truck", "bus"):
                        _blur(img, x1 - 0.03 * bw, y1 + 0.55 * bh, x2 + 0.03 * bw, y2 + 0.04 * bh)
            for i in need_peak:
                thumbs[i] = self._thumb(img, props[i], s)
            if seg is not None:
                if cur != seg:
                    if enc is not None:
                        enc.stdin.close()
                        enc.wait()
                    enc = self._encoder(self.media_dir / segs[seg]["file"], ow, oh, fps) if have_ffmpeg else None
                    cur = seg
                if enc is not None:
                    enc.stdin.write(img.tobytes())
                # key frames: the analysed frames inside the clip, with the model's boxes (pre-annotations)
                k = int(np.argmin(np.abs(ftimes - t)))
                if abs(ftimes[k] - t) <= 0.5 / fps and not any(kf["t"] == frames[k]["t"] for kf in segs[seg]["keyframes"]):
                    name = f"frames/{segs[seg]['id']}_{len(segs[seg]['keyframes']):03d}.jpg"
                    cv2.imwrite(str(self.media_dir / name), img, [cv2.IMWRITE_JPEG_QUALITY, 85])
                    fr = frames[k]
                    boxes = [{"cls": u["cls"], "bbox": [round(v * s, 1) for v in u["bbox"]], "conf": u["conf"], "track": u["id"]} for u in fr["users"]]
                    boxes += [{"cls": d["cls"], "bbox": [round(v * s, 1) for v in d["bbox"]], "conf": d["conf"], "track": d["id"]} for d in fr["damage"]]
                    segs[seg]["keyframes"].append({"t": fr["t"], "file": name, "boxes": boxes})
            if on_progress and last_t > 0:
                on_progress(min(1.0, t / last_t))
            fi += 1
        if enc is not None:
            enc.stdin.close()
            enc.wait()
        cap.release()
        for sg in segs:
            sg["size"] = [ow, oh]
            if not have_ffmpeg or not (self.media_dir / sg["file"]).exists():
                sg["file"] = None
        return thumbs

    def _thumb(self, img, p: Proposal, s: float) -> dict:
        out = img.copy()
        if p.bbox:
            x1, y1, x2, y2 = [int(v * s) for v in p.bbox]
            cv2.rectangle(out, (x1, y1), (x2, y2), (48, 160, 240), 3)
        name = f"thumbs/{uuid.uuid4().hex[:16]}.jpg"
        cv2.imwrite(str(self.media_dir / name), out, [cv2.IMWRITE_JPEG_QUALITY, 82])
        gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
        sharp = float(cv2.Laplacian(gray, cv2.CV_64F).var())
        bright = float(gray.mean())
        q = min(1.0, sharp / 300.0) * (1.0 if 40 <= bright <= 220 else 0.6)
        emb = cv2.resize(gray, (16, 9), interpolation=cv2.INTER_AREA).astype(np.float32).ravel()
        emb = (emb - emb.mean()) / (np.linalg.norm(emb - emb.mean()) + 1e-6)
        return {"file": name, "quality": round(q, 3), "sharpness": round(sharp, 1), "brightness": round(bright, 1),
                "embedding": [round(float(v), 4) for v in emb]}

    # ------------------------------------------------------------------------------------------- run
    def mine(self, path, trip_id: str, track: Track | None = None, sample_fps: float = 5.0, max_seconds: float = 120.0,
             on_frame=None, on_progress=None, should_stop=None) -> dict:
        t_wall = time.perf_counter()
        frames, info, labels = self._analyse(path, sample_fps, max_seconds, on_frame, should_stop)
        t_analysis = time.perf_counter() - t_wall
        props = self.propose(frames, track)
        segs, extra = self._segments(props, info["analysed_s"], trip_id)
        if extra["baseline"]:
            b0, b1 = extra["baseline"]
            props.append(Proposal("baseline_drive", b0, b1, (b0 + b1) / 2, 1.0, 0.0, None, [], {"selection": "seeded random, away from events"}))
            segs.append({"t0": b0, "t1": b1, "events": [len(props) - 1]})
            segs.sort(key=lambda sg: sg["t0"])
        t1 = time.perf_counter()
        thumbs = self._cut(path, info["fps"], frames, segs, props, 1.0 / info["sample_fps"], on_progress)
        t_clips = time.perf_counter() - t1
        seg_of = {i: sg for sg in segs for i in sg["events"]}
        events = []
        for i, p in enumerate(props):
            sg = seg_of.get(i)
            loc = track.at(p.t_peak) if track is not None else None
            th = thumbs.get(i, {})
            events.append({
                "local_id": i, "kind": p.kind, "type": p.type, "t_start": round(p.t_start, 2), "t_end": round(p.t_end, 2),
                "t_peak": round(p.t_peak, 2), "conf": round(float(p.conf), 3), "severity": float(p.severity),
                "uncertainty": round(1 - abs(2 * float(p.conf) - 1), 3) if p.kind != "baseline" else None,
                "bbox": [round(float(v), 1) for v in p.bbox] if p.bbox else None, "frame_size": [info["width"], info["height"]],
                "track_ids": p.track_ids, "evidence": p.evidence,
                "clip_id": sg["id"] if sg else None, "clip_offset_s": round(p.t_peak - sg["t0"], 2) if sg else None,
                "thumb": th.get("file"), "quality": th.get("quality"), "embedding": th.get("embedding"),
                "image_stats": {k: th.get(k) for k in ("sharpness", "brightness")} if th else None,
                "location": ({**loc, "source": track.source} if loc else None),
            })
        clips = [{"id": sg["id"], "t0": round(sg["t0"], 2), "t1": round(sg["t1"], 2), "file": sg["file"], "size": sg.get("size"),
                  "keyframes": sg["keyframes"], "events": sg["events"]} for sg in segs]
        kept = sum(c["t1"] - c["t0"] for c in clips)
        counts = Counter(labels[k].most_common(1)[0][0] for k in labels if labels[k])
        return {
            "info": {**info, "model_version": self.model_version,
                     "provider": getattr(self.users, "provider", "CPUExecutionProvider") if self.users else None},
            "events": events, "clips": clips,
            "reduction": {"analysed_s": info["analysed_s"], "kept_s": round(kept, 2),
                          "kept_ratio": round(kept / info["analysed_s"], 4) if info["analysed_s"] else None,
                          "n_clips": len(clips), "baseline_s": 5.0 if extra["baseline"] else 0.0},
            "road_users": dict(counts),
            "perf": {"frames": len(frames), "analysis_s": round(t_analysis, 2), "clips_s": round(t_clips, 2),
                     "wall_s": round(time.perf_counter() - t_wall, 2),
                     "ms_per_frame_p50": info["ms_per_frame_p50"], "ms_per_frame_p95": info["ms_per_frame_p95"]},
            "track": track.path() if track is not None else None,
        }


def mine_photo(miner: "EventMiner", img: np.ndarray, trip_id: str, location: dict | None) -> dict:
    """A single road photo (a phone report): road damage only, one observation per damage type, no clip."""
    t0 = time.perf_counter()
    img = _resize(img)
    h, w = img.shape[:2]
    u = miner.users(img) if miner.users else Detections.empty()
    d = miner.damage(img) if miner.damage else Detections.empty()
    ms = (time.perf_counter() - t0) * 1e3
    safe = img.copy()
    for i in range(len(u)):
        x1, y1, x2, y2 = [float(v) for v in u.xyxy[i]]
        bw, bh = x2 - x1, y2 - y1
        if u.label(i) == "person":
            _blur(safe, x1 - 0.15 * bw, y1 - 0.06 * bh, x2 + 0.15 * bw, y1 + 0.32 * bh)
        elif u.label(i) in ("car", "truck", "bus"):
            _blur(safe, x1 - 0.03 * bw, y1 + 0.55 * bh, x2 + 0.03 * bw, y2 + 0.04 * bh)
    s = min(1.0, CLIP_W / w)
    small = cv2.resize(safe, (int(w * s), int(h * s)), interpolation=cv2.INTER_AREA) if s < 1 else safe
    clip_id = uuid.uuid4().hex[:16]
    frame = f"frames/{clip_id}_000.jpg"
    cv2.imwrite(str(miner.media_dir / frame), small, [cv2.IMWRITE_JPEG_QUALITY, 85])
    boxes = [{"cls": d.label(i), "bbox": [round(float(v) * s, 1) for v in d.xyxy[i]], "conf": round(float(d.conf[i]), 2), "track": i}
             for i in range(len(d))]
    best: dict[str, tuple] = {}
    for i in range(len(d)):
        cls = d.label(i)
        sev = damage_severity(cls, d.xyxy[i], w, h, float(d.conf[i]))
        if cls not in best or float(d.conf[i]) * (0.5 + sev) > best[cls][0]:
            best[cls] = (float(d.conf[i]) * (0.5 + sev), i, sev, sum(1 for j in range(len(d)) if d.label(j) == cls))
    events = []
    for k, (cls, (_, i, sev, n)) in enumerate(best.items()):
        p = Proposal(cls, 0.0, 0.0, 0.0, float(d.conf[i]), sev, [float(v) for v in d.xyxy[i]], [], {"instances": n, "input": "photo"})
        th = miner._thumb(small, p, s)
        events.append({"local_id": k, "kind": "road", "type": cls, "t_start": 0.0, "t_end": 0.0, "t_peak": 0.0,
                       "conf": round(p.conf, 3), "severity": sev, "uncertainty": round(1 - abs(2 * p.conf - 1), 3),
                       "bbox": [round(v, 1) for v in p.bbox], "frame_size": [w, h], "track_ids": [], "evidence": p.evidence,
                       "clip_id": clip_id, "clip_offset_s": 0.0, "thumb": th["file"], "quality": th["quality"],
                       "embedding": th["embedding"], "image_stats": {"sharpness": th["sharpness"], "brightness": th["brightness"]},
                       "location": location})
    return {"info": {"fps": None, "sample_fps": None, "analysed_s": 0.0, "duration_s": 0.0, "width": w, "height": h, "input": "photo",
                     "model_version": miner.model_version, "provider": getattr(miner.users, "provider", None) if miner.users else None},
            "events": events,
            "clips": [{"id": clip_id, "t0": 0.0, "t1": 0.0, "file": None, "size": list(small.shape[1::-1]),
                       "keyframes": [{"t": 0.0, "file": frame, "boxes": boxes}], "events": list(range(len(events)))}],
            "reduction": {"analysed_s": 0.0, "kept_s": 0.0, "kept_ratio": None, "n_clips": 0, "baseline_s": 0.0},
            "road_users": dict(Counter(u.label(i) for i in range(len(u)))),
            "perf": {"frames": 1, "wall_s": round(time.perf_counter() - t0, 2), "ms_per_frame_p50": round(ms, 1), "ms_per_frame_p95": round(ms, 1)},
            "track": None, "image": frame}


def _dedupe_safety(props: list[Proposal]) -> list[Proposal]:
    """One episode, one event: overlapping safety proposals on the same road user keep the most specific type."""
    safety = sorted([p for p in props if p.kind == "safety"], key=lambda p: -SAFETY_PRIORITY.get(p.type, 0))
    kept: list[Proposal] = []
    for p in safety:
        dup = next((k for k in kept if set(k.track_ids) & set(p.track_ids) and p.t_start <= k.t_end + 1.0 and k.t_start <= p.t_end + 1.0), None)
        if dup is None:
            kept.append(p)
        else:
            dup.evidence.setdefault("also", []).append({"type": p.type, **{k: v for k, v in p.evidence.items() if k in ("min_ttc_s",)}})
            dup.t_start, dup.t_end = min(dup.t_start, p.t_start), max(dup.t_end, p.t_end)
            dup.severity = max(dup.severity, p.severity)
    return [p for p in props if p.kind != "safety"] + kept
