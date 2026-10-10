"""SwarmSight AI web service (FastAPI): Event Mining API, review center, road-event feed, DataMine, web UI.

Run: uvicorn swarmsight.server:app --host 0.0.0.0 --port 7860
"""
from __future__ import annotations

import asyncio
import hashlib
import io
import json
import os
import platform
import re
import threading
import time
import uuid
from collections import deque
from concurrent.futures import ThreadPoolExecutor
from contextlib import asynccontextmanager
from pathlib import Path

import numpy as np
from fastapi import FastAPI, File, Form, HTTPException, UploadFile, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from PIL import Image, ImageOps
from pydantic import BaseModel, Field

import cv2

from . import __version__
from .datamine import RIGHTS, data_value, export as export_dataset, summary as dataset_summary
from .detector import load_default_detectors
from .events import ACTIONS, LABELS, Fusion
from .mining import EventMiner, ffmpeg_available, mine_photo
from .store import Store
from .telemetry import parse_track, single_point

ROOT = Path(__file__).resolve().parent.parent
WEB_DIR = ROOT / "web"
SAMPLES_DIR = ROOT / "samples"
BENCH_DIR = ROOT / "benchmarks" / "results"
RUNTIME = Path(os.environ.get("SWARMSIGHT_RUNTIME", ROOT / "runtime"))
MEDIA_DIR = RUNTIME / "media"
UPLOAD_DIR = RUNTIME / "uploads"
EXPORT_DIR = RUNTIME / "exports"
MAX_VIDEO_BYTES = int(os.environ.get("SWARMSIGHT_MAX_VIDEO_MB", "300")) * 1024 * 1024
MAX_TRACK_BYTES = 10 * 1024 * 1024
for d in (MEDIA_DIR, UPLOAD_DIR, EXPORT_DIR):
    d.mkdir(parents=True, exist_ok=True)


class State:
    def __init__(self):
        self.detectors = {}
        self.miner: EventMiner | None = None
        self.store = Store(RUNTIME / "swarmsight.db")
        self.fusion = Fusion(self.store)
        self.jobs: dict[str, "Job"] = {}
        self.pool = ThreadPoolExecutor(max_workers=int(os.environ.get("SWARMSIGHT_JOB_WORKERS", "1")))
        self.latency = deque(maxlen=2000)
        self.started = time.time()
        self.lock = threading.Lock()

    def load(self):
        with self.lock:
            if not self.detectors:
                self.detectors = load_default_detectors(threads=int(os.environ.get("SWARMSIGHT_THREADS", "0") or 0) or None)
                self.miner = EventMiner(self.detectors, MEDIA_DIR)

    @property
    def gpu(self) -> bool:
        return any(getattr(d, "provider", "") == "CUDAExecutionProvider" for d in self.detectors.values())


S = State()


@asynccontextmanager
async def lifespan(_app):
    S.load()
    yield


app = FastAPI(title="SwarmSight AI", version=__version__, lifespan=lifespan,
              description="Taxi fleet intelligence network: trip video -> Event Mining -> clips -> review -> "
                          "verified road events (map, partner API) and a regional dataset (DataMine).")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])
app.add_middleware(GZipMiddleware, minimum_size=2048)


@app.middleware("http")
async def revalidate_web_assets(request, call_next):
    resp = await call_next(request)
    p = request.url.path
    if p == "/" or p.endswith((".html", ".js", ".css")):
        resp.headers["Cache-Control"] = "no-cache"
    return resp


# ----------------------------------------------------------------------------- helpers
async def _read_upload(f: UploadFile, limit: int) -> bytes:
    buf = bytearray()
    while chunk := await f.read(1 << 20):
        buf.extend(chunk)
        if len(buf) > limit:
            raise HTTPException(413, f"file too large (limit {limit // (1 << 20)} MB)")
    return bytes(buf)


IMAGE_EXT = (".jpg", ".jpeg", ".png", ".webp", ".heic", ".bmp")


def _decode_image(data: bytes) -> tuple[np.ndarray, dict]:
    """Decode a photo, apply EXIF orientation, read its GPS position if the camera recorded one."""
    meta: dict = {}
    try:
        im = Image.open(io.BytesIO(data))
        exif = im.getexif()
        gps = exif.get_ifd(0x8825) if exif else None
        if gps and 2 in gps and 4 in gps:
            deg = lambda v: float(v[0]) + float(v[1]) / 60 + float(v[2]) / 3600  # noqa: E731
            lat, lon = deg(gps[2]) * (-1 if gps.get(1) == "S" else 1), deg(gps[4]) * (-1 if gps.get(3) == "W" else 1)
            meta = {"lat": lat, "lon": lon, "uncertainty_m": 15.0, "source": "exif"}
        im = ImageOps.exif_transpose(im).convert("RGB")
        return cv2.cvtColor(np.asarray(im), cv2.COLOR_RGB2BGR), meta
    except Exception:
        arr = cv2.imdecode(np.frombuffer(data, np.uint8), cv2.IMREAD_COLOR)
        if arr is None:
            raise HTTPException(400, "could not decode the image")
        return arr, meta


def _device_id(raw: str | None) -> str:
    """Pseudonymous device id: we never store what the client sent."""
    return "dev-" + hashlib.sha1((raw or "anonymous-web").encode()).hexdigest()[:10]


def _json_default(o):
    if isinstance(o, np.bool_):
        return bool(o)
    if isinstance(o, np.floating):
        return float(o)
    if isinstance(o, np.integer):
        return int(o)
    if isinstance(o, np.ndarray):
        return o.tolist()
    raise TypeError(type(o))


# ----------------------------------------------------------------------------- jobs
class Job:
    def __init__(self, kind: str):
        self.id = uuid.uuid4().hex[:12]
        self.kind = kind
        self.status = "queued"
        self.progress = 0.0
        self.stage = "queued"
        self.messages: list[dict] = []
        self.result = None
        self.error = None
        self.created = time.time()
        self.cancelled = False
        self.lock = threading.Lock()

    def emit(self, msg: dict):
        with self.lock:
            self.messages.append(msg)

    def info(self) -> dict:
        return {"id": self.id, "kind": self.kind, "status": self.status, "stage": self.stage,
                "progress": round(self.progress, 3), "error": self.error}


def _submit(kind: str, fn) -> Job:
    job = Job(kind)
    S.jobs[job.id] = job
    if len(S.jobs) > 100:
        for jid in sorted(S.jobs, key=lambda k: S.jobs[k].created)[:-100]:
            S.jobs.pop(jid, None)

    def run():
        job.status = "running"
        try:
            job.result = fn(job)
            job.status, job.progress = "done", 1.0
            job.emit({"type": "done", "result": job.result})
        except Exception as e:  # surfaced to the client
            job.status = "error"
            job.error = f"{type(e).__name__}: {e}"
            job.emit({"type": "error", "error": job.error})

    S.pool.submit(run)
    return job


@app.get("/api/v1/jobs/{job_id}")
def job_status(job_id: str):
    job = S.jobs.get(job_id)
    if not job:
        raise HTTPException(404, "unknown job")
    d = job.info()
    if job.status == "done":
        d["result"] = job.result
    return d


@app.delete("/api/v1/jobs/{job_id}")
def job_cancel(job_id: str):
    if job_id in S.jobs:
        S.jobs[job_id].cancelled = True
    return {"ok": True}


@app.websocket("/ws/jobs/{job_id}")
async def job_ws(ws: WebSocket, job_id: str):
    await ws.accept()
    job = S.jobs.get(job_id)
    if not job:
        await ws.send_json({"type": "error", "error": "unknown job"})
        await ws.close()
        return
    sent = 0
    try:
        while True:
            with job.lock:
                new = job.messages[sent:]
            for m in new:
                await ws.send_text(json.dumps(m, default=_json_default))
            sent += len(new)
            if job.status in ("done", "error") and sent >= len(job.messages):
                break
            if not new:
                await ws.send_json({"type": "progress", "progress": round(job.progress, 3), "stage": job.stage})
                await asyncio.sleep(0.2)
        await ws.close()
    except WebSocketDisconnect:
        pass


# ----------------------------------------------------------------------------- trips (Event Mining)
def _process_trip(job: Job, trip_id: str, path: Path, track, device: str, sample_fps: float, max_seconds: float,
                  keep_upload: bool = False) -> dict:
    try:
        job.stage = "analysing"

        def on_frame(fr, idx, total):
            S.latency.append(("frame", fr["ms"]))
            job.progress = 0.8 * min(0.999, (idx + 1) / total) if total else 0.4
            job.emit({"type": "frame", "frame": fr})

        def on_clip(p):
            job.stage = "cutting clips"
            job.progress = 0.8 + 0.18 * p

        res = S.miner.mine(path, trip_id, track, sample_fps, max_seconds, on_frame, on_clip, lambda: job.cancelled)
        job.stage = "saving"
        _persist(trip_id, device, res, track)
        return trip_report(trip_id)
    except Exception as e:
        S.store.update("trips", trip_id, {"status": "error", "error": f"{type(e).__name__}: {e}"})
        raise
    finally:
        if not keep_upload:
            path.unlink(missing_ok=True)


def _persist(trip_id: str, device: str, res: dict, track):
    st = S.store
    now = time.time()
    trip = st.one("SELECT * FROM trips WHERE id=?", (trip_id,))
    for c in res["clips"]:
        st.insert("clips", {"id": c["id"], "trip_id": trip_id, "t0": c["t0"], "t1": c["t1"], "file": c["file"],
                            "size": c["size"], "keyframes": c["keyframes"]})
    if res["track"]:
        with st.lock:
            st.conn.executemany("INSERT INTO telemetry(trip_id, t, lat, lon) VALUES (?,?,?,?)",
                                [(trip_id, t, la, lo) for t, la, lo in res["track"]])
            st.conn.commit()
    ids = []
    for e in res["events"]:
        loc = e["location"] or {}
        ids.append(st.insert("observations", {
            "trip_id": trip_id, "device_id": device, "kind": e["kind"], "type": e["type"], "label": e["type"],
            "t_start": e["t_start"], "t_end": e["t_end"], "t_peak": e["t_peak"], "conf": e["conf"], "uncertainty": e["uncertainty"],
            "severity": e["severity"], "bbox": e["bbox"], "frame_size": e["frame_size"], "evidence": e["evidence"],
            "clip_id": e["clip_id"], "clip_offset_s": e["clip_offset_s"], "thumb": e["thumb"],
            "lat": loc.get("lat"), "lon": loc.get("lon"), "loc_source": loc.get("source"), "loc_uncertainty_m": loc.get("uncertainty_m"),
            "review_status": "needs_review", "quality": e["quality"], "embedding": e["embedding"],
            "model_version": res["info"]["model_version"], "observed_at": trip["created_at"] + e["t_peak"], "created_at": now}))
    for oid in ids:
        o = st.one("SELECT * FROM observations WHERE id=?", (oid,))
        v, parts = data_value(st, o)
        st.update("observations", oid, {"data_value": v, "value_parts": parts})
        if o["kind"] == "road" and o["lat"] is not None:
            S.fusion.attach(oid)
    st.update("trips", trip_id, {"status": "done", "duration_s": res["info"]["duration_s"], "analysed_s": res["info"]["analysed_s"],
                                 "kept_s": res["reduction"]["kept_s"], "n_events": sum(1 for e in res["events"] if e["kind"] != "baseline"),
                                 "info": res["info"], "perf": res["perf"], "reduction": res["reduction"], "road_users": res["road_users"],
                                 "gps_source": track.source if track is not None else None})


@app.post("/api/v1/trips")
async def create_trip(video: UploadFile = File(...), track: UploadFile | None = File(None), track_offset_s: float = Form(0.0),
                      lat: float | None = Form(None), lon: float | None = Form(None), gps_accuracy_m: float = Form(15.0),
                      rights_scope: str = Form("road_only"), device_id: str | None = Form(None),
                      sample_fps: float | None = Form(None), max_seconds: float = Form(120.0)):
    """Upload a trip: a video and, optionally, its GPS track (GPX/CSV) or one position. Returns a job to follow."""
    S.load()
    if rights_scope not in RIGHTS:
        raise HTTPException(400, f"rights_scope must be one of {', '.join(RIGHTS)}")
    data = await _read_upload(video, MAX_VIDEO_BYTES)
    if (video.content_type or "").startswith("image/") or (video.filename or "").lower().endswith(IMAGE_EXT):
        img, meta = _decode_image(data)
        loc = meta or ({"lat": lat, "lon": lon, "uncertainty_m": gps_accuracy_m, "source": "pin"} if lat is not None and lon is not None else None)
        return _start_photo(img, video.filename, loc, device_id, rights_scope)
    suffix = (Path(video.filename or "trip.mp4").suffix or ".mp4")[:6]
    path = UPLOAD_DIR / f"{uuid.uuid4().hex}{suffix}"
    path.write_bytes(data)
    tr = None
    if track is not None and track.filename:
        try:
            tr = parse_track(await _read_upload(track, MAX_TRACK_BYTES), track.filename, track_offset_s)
        except (ValueError, KeyError) as e:
            path.unlink(missing_ok=True)
            raise HTTPException(400, f"track: {e}")
    elif lat is not None and lon is not None:
        tr = single_point(lat, lon, gps_accuracy_m, max_seconds)
    return _start_trip(path, video.filename, tr, device_id, rights_scope, sample_fps, max_seconds)


def _start_trip(path: Path, filename: str | None, tr, device_id, rights_scope, sample_fps, max_seconds, keep_upload=False):
    device = _device_id(device_id)
    S.store.device(device)
    fps = float(np.clip(sample_fps or (10.0 if S.gpu else 5.0), 1.0, 15.0))
    max_s = float(np.clip(max_seconds, 5.0, 300.0))
    trip_id = uuid.uuid4().hex[:12]
    S.store.insert("trips", {"id": trip_id, "device_id": device, "filename": (filename or "")[:120], "created_at": time.time(),
                             "status": "processing", "rights_scope": rights_scope, "gps_source": tr.source if tr is not None else None})
    job = _submit("trip", lambda j: _process_trip(j, trip_id, path, tr, device, fps, max_s, keep_upload))
    return {"trip_id": trip_id, "job_id": job.id, "sample_fps": fps}


def _start_photo(img, filename, loc, device_id, rights_scope):
    device = _device_id(device_id)
    S.store.device(device)
    trip_id = uuid.uuid4().hex[:12]
    S.store.insert("trips", {"id": trip_id, "device_id": device, "filename": (filename or "")[:120], "created_at": time.time(),
                             "status": "processing", "rights_scope": rights_scope, "gps_source": loc["source"] if loc else None})

    def work(job):
        try:
            res = mine_photo(S.miner, img, trip_id, loc)
            S.latency.append(("frame", res["perf"]["ms_per_frame_p50"]))
            _persist(trip_id, device, res, None)
            S.store.update("trips", trip_id, {"gps_source": loc["source"] if loc else None})
            return trip_report(trip_id)
        except Exception as e:
            S.store.update("trips", trip_id, {"status": "error", "error": f"{type(e).__name__}: {e}"})
            raise
    job = _submit("photo", work)
    return {"trip_id": trip_id, "job_id": job.id, "input": "photo"}


TASHKENT_DIR = ROOT / "datasets" / "tashkent"


@app.get("/api/v1/samples")
def samples():
    """Bundled inputs for visitors without their own: our anonymised trip, and Tashkent street photos (Mapillary, CC BY-SA)
    chosen by our image-level label only (never by model output)."""
    out = json.loads((SAMPLES_DIR / "samples.json").read_text()) if (SAMPLES_DIR / "samples.json").exists() else {"samples": []}
    if (TASHKENT_DIR / "labels_test.json").exists():
        labels = json.loads((TASHKENT_DIR / "labels_test.json").read_text())["labels"]
        man = {m["id"]: m for m in json.loads((TASHKENT_DIR / "manifest.json").read_text())["images"]}
        ok = [l for l in labels if not l["uncertain"] and not l["not_road"] and l["id"] in man]
        pick, seen = [], set()
        for t in ("pothole", "alligator_crack", "transverse_crack", "longitudinal_crack"):
            for l in ok:
                if l["damage"] and t in l["types"] and l["id"] not in seen:
                    pick.append(l)
                    seen.add(l["id"])
                    break
        pick += [l for l in ok if not l["damage"]][:2]
        out["photos"] = [{"id": l["id"], "image": f"/datasets/tashkent/{man[l['id']]['file']}", "lat": man[l["id"]]["lat"],
                          "lon": man[l["id"]]["lon"], "our_label": l["types"] if l["damage"] else [], "source": man[l["id"]]["source"]}
                         for l in pick]
    return out


@app.post("/api/v1/samples/{name}/run")
def run_sample(name: str, device_id: str | None = None, rights_scope: str = "road_and_dataset"):
    """Run a bundled sample trip through exactly the same pipeline as an upload (for visitors without a video).

    The sample was filmed by one camera, so every run of it counts as that one device, whoever clicks: re-running
    the same footage must never look like independent corroboration."""
    S.load()
    s = next((x for x in samples()["samples"] if x["id"] == name), None)
    if not s:
        raise HTTPException(404, "unknown sample")
    tr = parse_track((SAMPLES_DIR / s["track"]).read_bytes(), s["track"], s.get("track_offset_s", 0.0)) if s.get("track") else None
    return _start_trip(SAMPLES_DIR / s["video"], s["video"], tr, f"sample:{name}", rights_scope, None, 120.0, keep_upload=True)


def trip_report(trip_id: str) -> dict:
    t = S.store.one("SELECT * FROM trips WHERE id=?", (trip_id,))
    if not t:
        raise HTTPException(404, "unknown trip")
    obs = S.store.query("SELECT * FROM observations WHERE trip_id=? ORDER BY t_peak", (trip_id,))
    clips = {c["id"]: c for c in S.store.query("SELECT id, t0, t1, file, size FROM clips WHERE trip_id=?", (trip_id,))}
    events = {e["id"]: e for e in S.store.query("SELECT id, status, n_sources, confidence FROM events WHERE id IN "
                                                "(SELECT event_id FROM observations WHERE trip_id=?)", (trip_id,))}
    for o in obs:
        o.pop("embedding", None)
        o["clip"] = clips.get(o["clip_id"])
        o["event"] = events.get(o["event_id"])
    track = [[r["t"], r["lat"], r["lon"]] for r in S.store.query("SELECT t, lat, lon FROM telemetry WHERE trip_id=? ORDER BY t", (trip_id,))]
    t["device_id"] = t["device_id"][:8] + "…"
    return {"trip": t, "observations": obs, "clips": list(clips.values()), "track": track}


@app.get("/api/v1/trips")
def list_trips(limit: int = 30):
    rows = S.store.query("SELECT id, filename, created_at, status, rights_scope, gps_source, duration_s, analysed_s, kept_s, n_events "
                         "FROM trips ORDER BY created_at DESC LIMIT ?", (max(1, min(limit, 200)),))
    return {"trips": rows}


@app.get("/api/v1/trips/{trip_id}")
def get_trip(trip_id: str):
    return trip_report(trip_id)


# ----------------------------------------------------------------------------- review center
@app.get("/api/v1/observations")
def list_observations(status: str = "needs_review", kind: str = "all", limit: int = 100):
    st = [s for s in status.split(",") if s in ("needs_review", "confirmed", "corrected", "rejected")] or ["needs_review"]
    q = f"SELECT o.*, t.filename, t.rights_scope FROM observations o JOIN trips t ON t.id=o.trip_id WHERE o.review_status IN ({','.join('?' * len(st))})"
    args = list(st)
    if kind in ("road", "safety", "baseline"):
        q += " AND o.kind=?"
        args.append(kind)
    rows = S.store.query(q + " ORDER BY o.created_at DESC, o.t_peak LIMIT ?", args + [max(1, min(limit, 500))])
    clips = {c["id"]: c for c in S.store.query("SELECT id, t0, t1, file, size FROM clips")}
    for o in rows:
        o.pop("embedding", None)
        o["clip"] = clips.get(o["clip_id"])
        o["device_id"] = o["device_id"][:8] + "…"
    counts = {r["kind"]: r["n"] for r in S.store.query("SELECT kind, COUNT(*) AS n FROM observations WHERE review_status='needs_review' GROUP BY kind")}
    return {"observations": rows, "queue": counts, "labels": LABELS, "actions": ACTIONS}


@app.get("/api/v1/observations/{oid}")
def get_observation(oid: int):
    o = S.store.one("SELECT * FROM observations WHERE id=?", (oid,))
    if not o:
        raise HTTPException(404, "unknown observation")
    o.pop("embedding", None)
    o["clip"] = S.store.one("SELECT id, t0, t1, file, size FROM clips WHERE id=?", (o["clip_id"],)) if o["clip_id"] else None
    o["reviews"] = S.store.query("SELECT reviewer, action, old_label, new_label, note, t FROM reviews WHERE observation_id=? ORDER BY t", (oid,))
    o["event"] = S.store.one("SELECT * FROM events WHERE id=?", (o["event_id"],)) if o["event_id"] else None
    o["device_reliability"] = round(S.store.reliability(o["device_id"]), 3)
    o["device_id"] = o["device_id"][:8] + "…"
    return o


class ReviewIn(BaseModel):
    action: str
    label: str | None = None
    note: str = ""
    reviewer: str = "moderator"


@app.post("/api/v1/observations/{oid}/review")
def review_observation(oid: int, r: ReviewIn):
    try:
        S.fusion.review(oid, r.action, r.reviewer or "moderator", r.note, r.label)
    except KeyError:
        raise HTTPException(404, "unknown observation")
    except ValueError as e:
        raise HTTPException(400, str(e))
    return get_observation(oid)


class LocateIn(BaseModel):
    lat: float
    lon: float
    uncertainty_m: float = Field(25.0, ge=1, le=500)
    reviewer: str = "moderator"


@app.post("/api/v1/observations/{oid}/location")
def locate_observation(oid: int, b: LocateIn):
    try:
        S.fusion.locate(oid, b.lat, b.lon, b.uncertainty_m, b.reviewer)
    except KeyError:
        raise HTTPException(404, "unknown observation")
    except ValueError as e:
        raise HTTPException(400, str(e))
    return get_observation(oid)


@app.get("/api/v1/safety/reviews")
def safety_reviews(limit: int = 100):
    """Safety episodes for the fleet's safety team (in production: a separate role; never in the partner feed)."""
    return list_observations("needs_review,confirmed,corrected,rejected", "safety", limit)


# ----------------------------------------------------------------------------- road events (map + partner API)
@app.get("/api/v1/events")
def list_events(status: str = "verified", bbox: str | None = None):
    st = tuple(s for s in status.split(",") if s in ("candidate", "corroborated", "verified", "rejected", "expired")) or ("verified",)
    return S.fusion.geojson(st, _bbox(bbox))


def _bbox(raw: str | None) -> list[float] | None:
    """min_lon,min_lat,max_lon,max_lat"""
    if not raw:
        return None
    try:
        bb = [float(x) for x in raw.split(",")]
    except ValueError:
        bb = []
    if len(bb) != 4:
        raise HTTPException(400, "bbox: four numbers, min_lon,min_lat,max_lon,max_lat")
    return bb


@app.get("/api/v1/events/{eid}")
def get_event(eid: int):
    e = S.store.one("SELECT * FROM events WHERE id=?", (eid,))
    if not e:
        raise HTTPException(404, "unknown event")
    obs = S.store.query("SELECT id, trip_id, device_id, label, type, conf, severity, t_peak, thumb, clip_id, clip_offset_s, lat, lon, "
                        "loc_source, loc_uncertainty_m, review_status, observed_at FROM observations WHERE event_id=? ORDER BY observed_at", (eid,))
    clips = {c["id"]: c for c in S.store.query("SELECT id, t0, t1, file FROM clips WHERE id IN (SELECT clip_id FROM observations WHERE event_id=?)", (eid,))}
    for o in obs:
        o["device_reliability"] = round(S.store.reliability(o["device_id"]), 3)
        o["device_id"] = o["device_id"][:8] + "…"
        o["clip"] = clips.get(o["clip_id"])
    e["observations"] = obs
    return e


@app.get("/api/v1/partners/road-feed")
def road_feed(format: str = "geojson", bbox: str | None = None):
    """Read-only feed of verified road events for map platforms and road services (production: API keys, rate limits)."""
    if format == "cifs":
        return S.fusion.cifs()
    return list_events("verified", bbox)


# ----------------------------------------------------------------------------- DataMine
@app.get("/api/v1/datasets/summary")
def datasets_summary():
    return dataset_summary(S.store)


class ExportIn(BaseModel):
    include_unreviewed: bool = False


@app.post("/api/v1/datasets/exports")
def create_export(b: ExportIn):
    return export_dataset(S.store, MEDIA_DIR, EXPORT_DIR, b.include_unreviewed)


@app.get("/api/v1/datasets/exports/{version}")
def download_export(version: str):
    row = S.store.one("SELECT file FROM dataset_exports WHERE version=?", (version,))
    if not row or not (EXPORT_DIR / row["file"]).exists():
        raise HTTPException(404, "unknown export")
    return FileResponse(EXPORT_DIR / row["file"], media_type="application/zip", filename=row["file"])


# ----------------------------------------------------------------------------- health, metrics, data registry
@app.get("/api/v1/health")
def health():
    S.load()
    v = [ms for _, ms in S.latency]
    return {
        "ok": True, "version": __version__,
        "models": {k: {"file": Path(d.model_path).name, "imgsz": d.imgsz, "classes": len(d.names), "provider": d.provider}
                   for k, d in S.detectors.items()},
        "inference": ("GPU" if S.gpu else "CPU") + " · ONNX Runtime", "clips": "ffmpeg H.264" if ffmpeg_available() else "unavailable (no ffmpeg)",
        "hardware": {"cpu_count": os.cpu_count(), "machine": platform.machine(), "python": platform.python_version()},
        "frame_ms": {"n": len(v), "p50": round(float(np.median(v)), 1), "p95": round(float(np.percentile(v, 95)), 1)} if v else None,
        "uptime_s": round(time.time() - S.started),
    }


@app.get("/api/v1/metrics")
def metrics():
    out = {}
    for f in BENCH_DIR.glob("*.json"):
        try:
            out[f.stem] = json.loads(f.read_text())
        except json.JSONDecodeError:
            pass
    st = S.store
    out["live"] = {
        "trips": st.one("SELECT COUNT(*) AS n FROM trips WHERE status='done'")["n"],
        "observations": {r["review_status"]: r["n"] for r in st.query("SELECT review_status, COUNT(*) AS n FROM observations GROUP BY review_status")},
        "events": {r["status"]: r["n"] for r in st.query("SELECT status, COUNT(*) AS n FROM events GROUP BY status")},
        "review_precision": _review_precision(),
    }
    return out


def _review_precision() -> dict:
    """Of the candidates a moderator has decided on, how many were right (per type): the system's live precision."""
    rows = S.store.query("SELECT type, review_status, label FROM observations WHERE review_status IN ('confirmed','corrected','rejected') AND type!='baseline_drive'")
    out = {}
    for r in rows:
        d = out.setdefault(r["type"], {"decided": 0, "correct": 0})
        d["decided"] += 1
        d["correct"] += r["review_status"] == "confirmed" or (r["review_status"] == "corrected" and r["label"] == r["type"])
    for d in out.values():
        d["precision"] = round(d["correct"] / d["decided"], 3)
    return out


@app.get("/api/v1/data")
def data_registry():
    p = ROOT / "docs" / "data_registry.json"
    return json.loads(p.read_text()) if p.exists() else {}


app.mount("/media", StaticFiles(directory=str(MEDIA_DIR)), name="media")
if (TASHKENT_DIR / "images").exists():
    app.mount("/datasets/tashkent/images", StaticFiles(directory=str(TASHKENT_DIR / "images")), name="tashkent")
if SAMPLES_DIR.exists():
    app.mount("/samples", StaticFiles(directory=str(SAMPLES_DIR)), name="samples")
if WEB_DIR.exists():
    app.mount("/", StaticFiles(directory=str(WEB_DIR), html=True), name="web")
