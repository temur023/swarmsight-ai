"""Smoke test of a deployed SwarmSight AI service through its public URL.

    python scripts/smoke_deploy.py https://<workspace>--swarmsight-ai-web.modal.run [--expect-gpu]

1. GET  /api/v1/health                       (the first call may include a cold start)
2. POST /api/v1/samples/stcroix-taxi/run and poll /api/v1/jobs/{id}
3. POST /api/v1/trips with samples/tashkent_redmi.mp4 (multipart `video` + `track`) and poll the job
4. GET  /media/<clip>: 200 + video/mp4, and a Range request answers 206
5. WebSocket /ws/jobs/{id} replays the job to "done" (only if the `websockets` package is installed)

Standard library only; uses `requests` when it is installed. Exit code 1 on any failure.
"""
from __future__ import annotations

import argparse
import json
import sys
import time
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
VIDEO = ROOT / "samples" / "tashkent_redmi.mp4"  # a public sample: never put the crash trip on the live site
TRACK = ROOT / "samples" / "tashkent_redmi.csv"

try:
    import requests
except ImportError:  # fallback: urllib
    requests = None
    import urllib.error
    import urllib.request


class Resp:
    def __init__(self, status: int, headers: dict, body: bytes):
        self.status, self.headers, self.body = status, {k.lower(): v for k, v in headers.items()}, body

    def json(self):
        return json.loads(self.body)


def http(method: str, url: str, *, json_body=None, files=None, data=None, headers=None, timeout=120.0) -> Resp:
    headers = dict(headers or {})
    if requests is not None:
        r = requests.request(method, url, json=json_body, files=files, data=data, headers=headers, timeout=timeout)
        return Resp(r.status_code, dict(r.headers), r.content)
    body = None
    if json_body is not None:
        body = json.dumps(json_body).encode()
        headers["Content-Type"] = "application/json"
    elif files:
        boundary = uuid.uuid4().hex
        parts = []
        for k, v in (data or {}).items():
            parts.append(f'--{boundary}\r\nContent-Disposition: form-data; name="{k}"\r\n\r\n{v}\r\n'.encode())
        for k, (name, content, ctype) in files.items():
            parts.append(f'--{boundary}\r\nContent-Disposition: form-data; name="{k}"; filename="{name}"\r\n'
                         f"Content-Type: {ctype}\r\n\r\n".encode() + content + b"\r\n")
        body = b"".join(parts) + f"--{boundary}--\r\n".encode()
        headers["Content-Type"] = f"multipart/form-data; boundary={boundary}"
    req = urllib.request.Request(url, data=body, method=method, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return Resp(r.status, dict(r.headers), r.read())
    except urllib.error.HTTPError as e:
        return Resp(e.code, dict(e.headers), e.read())


class Smoke:
    def __init__(self, base: str, job_timeout: float):
        self.base = base.rstrip("/")
        self.job_timeout = job_timeout
        self.timings: list[tuple[str, float]] = []
        self.failures: list[str] = []

    def check(self, ok: bool, what: str) -> bool:
        print(("  ok    " if ok else "  FAIL  ") + what)
        if not ok:
            self.failures.append(what)
        return ok

    def timed(self, name: str, fn):
        t0 = time.perf_counter()
        try:
            return fn()
        finally:
            dt = time.perf_counter() - t0
            self.timings.append((name, dt))
            print(f"  {name}: {dt:.2f} s")

    def wait_job(self, job_id: str) -> dict:
        t0 = time.time()
        last = None
        while time.time() - t0 < self.job_timeout:
            j = http("GET", f"{self.base}/api/v1/jobs/{job_id}", timeout=60).json()
            stage = (j["status"], j.get("stage"), round(j.get("progress", 0), 2))
            if stage != last:
                print(f"    job {job_id}: {stage[0]} · {stage[1]} · {stage[2]:.0%}")
                last = stage
            if j["status"] in ("done", "error"):
                return j
            time.sleep(1.0)
        raise TimeoutError(f"job {job_id} not finished after {self.job_timeout:.0f} s")

    # ---------------------------------------------------------------------------------------------------- steps
    def health(self, expect_gpu: bool):
        print("1. health")
        r = self.timed("health (incl. cold start)", lambda: http("GET", f"{self.base}/api/v1/health", timeout=600))
        if not self.check(r.status == 200, f"GET /api/v1/health -> {r.status}"):
            return
        h = r.json()
        print(f"    inference: {h.get('inference')} · clips: {h.get('clips')} · version {h.get('version')}")
        for k, m in (h.get("models") or {}).items():
            print(f"    model {k}: {m.get('file')} on {m.get('provider')}")
        self.check(h.get("ok") is True, "health ok")
        self.check(h.get("clips") == "ffmpeg H.264", "ffmpeg available for clips")
        gpu = h.get("inference", "").startswith("GPU")
        if expect_gpu:
            self.check(gpu, "inference on GPU ('GPU · ONNX Runtime')")
        elif not gpu:
            print("    note: inference runs on the CPU")
        self.timed("health (warm)", lambda: http("GET", f"{self.base}/api/v1/health"))

    def sample(self) -> dict | None:
        print("2. sample trip")
        r = self.timed("POST sample run", lambda: http("POST", f"{self.base}/api/v1/samples/stcroix-taxi/run"))
        if not self.check(r.status == 200, f"POST /api/v1/samples/stcroix-taxi/run -> {r.status}"):
            return None
        started = r.json()
        job = self.timed("sample job", lambda: self.wait_job(started["job_id"]))
        if not self.check(job["status"] == "done", f"sample job done ({job.get('error') or 'no error'})"):
            return None
        self._report(job["result"])
        return {**started, "report": job["result"]}

    def upload(self) -> dict | None:
        print("3. upload a trip")
        files = {"video": (VIDEO.name, VIDEO.read_bytes(), "video/mp4"), "track": (TRACK.name, TRACK.read_bytes(), "text/csv")}
        data = {"rights_scope": "road_only", "device_id": "smoke-test"}
        r = self.timed(f"POST /api/v1/trips ({VIDEO.stat().st_size / 1e6:.1f} MB)",
                       lambda: http("POST", f"{self.base}/api/v1/trips", files=files, data=data, timeout=300))
        if not self.check(r.status == 200, f"POST /api/v1/trips -> {r.status} {r.body[:200]!r}"):
            return None
        started = r.json()
        job = self.timed("upload job", lambda: self.wait_job(started["job_id"]))
        if not self.check(job["status"] == "done", f"upload job done ({job.get('error') or 'no error'})"):
            return None
        self._report(job["result"])
        return {**started, "report": job["result"]}

    def _report(self, rep: dict):
        t = rep["trip"]
        perf = t.get("perf") or {}
        print(f"    trip {t['id']}: {len(rep['observations'])} observations, {len(rep['clips'])} clips, "
              f"{perf.get('frames')} frames, {perf.get('ms_per_frame_p50')} ms/frame p50, analysis {perf.get('analysis_s')} s, "
              f"clips {perf.get('clips_s')} s, wall {perf.get('wall_s')} s")

    def media(self, run: dict | None):
        print("4. clip under /media/")
        clips = [c for c in (run or {}).get("report", {}).get("clips", []) if c.get("file")]
        if not self.check(bool(clips), "trip has a clip file"):
            return
        url = f"{self.base}/media/{clips[0]['file']}"
        r = self.timed("GET clip", lambda: http("GET", url))
        self.check(r.status == 200, f"GET {url} -> {r.status}")
        self.check(r.headers.get("content-type", "").startswith("video/mp4"), f"content-type {r.headers.get('content-type')}")
        self.check(len(r.body) > 1000 and r.body[4:8] == b"ftyp", f"MP4 body ({len(r.body)} bytes)")
        r = self.timed("GET clip, Range", lambda: http("GET", url, headers={"Range": "bytes=0-1023"}))
        self.check(r.status == 206, f"Range request -> {r.status} (206 expected)")
        self.check(len(r.body) == 1024 and "content-range" in r.headers, f"partial body {len(r.body)} bytes, "
                                                                         f"Content-Range {r.headers.get('content-range')}")

    def websocket(self, job_id: str):
        print("5. job WebSocket")
        try:
            from websockets.sync.client import connect
        except ImportError:
            print("    skipped (pip install websockets to check it)")
            return
        url = self.base.replace("https://", "wss://").replace("http://", "ws://") + f"/ws/jobs/{job_id}"

        def run():
            n, last = 0, None
            with connect(url, open_timeout=60, max_size=None) as ws:
                for raw in ws:
                    n += 1
                    last = json.loads(raw)["type"]
                    if last in ("done", "error"):
                        break
            return n, last

        try:
            n, last = self.timed("WebSocket replay", run)
            self.check(last == "done", f"WebSocket replayed {n} messages, last '{last}'")
        except Exception as e:  # noqa: BLE001
            self.check(False, f"WebSocket {url}: {type(e).__name__}: {e}")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("url", help="base URL of the deployment, e.g. https://<workspace>--swarmsight-ai-web.modal.run")
    ap.add_argument("--expect-gpu", action="store_true", help="fail unless /api/v1/health reports GPU inference")
    ap.add_argument("--job-timeout", type=float, default=600.0)
    a = ap.parse_args()
    s = Smoke(a.url, a.job_timeout)
    print(f"SwarmSight smoke test against {s.base} (HTTP via {'requests' if requests else 'urllib'})")
    t0 = time.perf_counter()
    try:
        s.health(a.expect_gpu)
        run = s.sample()
        up = s.upload()
        s.media(up or run)
        if run:
            s.websocket(run["job_id"])
    except Exception as e:  # noqa: BLE001
        s.check(False, f"{type(e).__name__}: {e}")
    print("\ntimings")
    for name, dt in s.timings:
        print(f"  {dt:8.2f} s  {name}")
    print(f"  {time.perf_counter() - t0:8.2f} s  total")
    if s.failures:
        print(f"\nFAILED ({len(s.failures)}):\n  - " + "\n  - ".join(s.failures))
        return 1
    print("\nall checks passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
