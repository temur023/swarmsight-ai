"""Build a sample "trip" from one Mapillary capture sequence in Tashkent: a phone in a car taking a photo about
every second with GPS, which is exactly the phone-on-a-mount scenario of a taxi pilot.

Output: samples/<name>.mp4 (one video frame per photo, at the capture rate; Mapillary has already blurred faces
and plates), samples/<name>.csv (t, lat, lon from Mapillary's computed positions) and samples/<name>.json
(attribution: image ids, contributor, licence CC BY-SA 4.0).

Usage: MAPILLARY_TOKEN=MLY|... python scripts/build_mapillary_trip.py --sequence <id> --start 60 --count 120 --name tashkent_redmi
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import urllib.request
from pathlib import Path

import cv2
import numpy as np

API = "https://graph.mapillary.com"


def get(url):
    return json.load(urllib.request.urlopen(url, timeout=60))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--sequence", required=True)
    ap.add_argument("--start", type=int, default=0)
    ap.add_argument("--count", type=int, default=120)
    ap.add_argument("--name", required=True)
    ap.add_argument("--out", default="samples")
    a = ap.parse_args()
    tok = os.environ["MAPILLARY_TOKEN"]
    rows = get(f"{API}/images?sequence_ids={a.sequence}&fields=id,captured_at,computed_geometry,geometry,creator&limit=2000&access_token={tok}")["data"]
    rows = sorted(rows, key=lambda r: r["captured_at"])[a.start:a.start + a.count]
    t0 = rows[0]["captured_at"] / 1000
    dts = np.diff([r["captured_at"] / 1000 for r in rows])
    fps = round(1.0 / float(np.median(dts)), 3)
    out = Path(a.out)
    frames, track = [], []
    for k, r in enumerate(rows):
        info = get(f"{API}/{r['id']}?fields=thumb_1024_url&access_token={tok}")
        data = urllib.request.urlopen(info["thumb_1024_url"], timeout=60).read()
        img = cv2.imdecode(np.frombuffer(data, np.uint8), cv2.IMREAD_COLOR)
        frames.append(img)
        g = (r.get("computed_geometry") or r["geometry"])["coordinates"]
        # video time of this frame: frames are written at a constant rate, so use the frame index
        track.append((round(k / fps, 3), g[1], g[0]))
    h, w = frames[0].shape[:2]
    w2, h2 = 960, int(round(h * 960 / w)) // 2 * 2
    enc = subprocess.Popen(["ffmpeg", "-y", "-loglevel", "error", "-f", "rawvideo", "-pix_fmt", "bgr24", "-s", f"{w2}x{h2}", "-r", str(fps),
                            "-i", "-", "-c:v", "libx264", "-preset", "slow", "-crf", "26", "-pix_fmt", "yuv420p", "-movflags", "+faststart",
                            "-an", str(out / f"{a.name}.mp4")], stdin=subprocess.PIPE)
    for img in frames:
        enc.stdin.write(cv2.resize(img, (w2, h2), interpolation=cv2.INTER_AREA).tobytes())
    enc.stdin.close()
    enc.wait()
    cv2.imwrite(str(out / f"{a.name}.jpg"), cv2.resize(frames[0], (w2, h2)), [cv2.IMWRITE_JPEG_QUALITY, 80])
    # speed from the real capture times (photos are not exactly 1 s apart), 5-point running median against GPS noise
    import math
    real = [r["captured_at"] / 1000 for r in rows]
    def dist(i, j):
        (la1, lo1), (la2, lo2) = track[i][1:], track[j][1:]
        x = math.radians(lo2 - lo1) * math.cos(math.radians((la1 + la2) / 2)) * 6371000
        return math.hypot(x, math.radians(la2 - la1) * 6371000)
    v = [dist(i, i + 1) / max(real[i + 1] - real[i], 0.2) for i in range(len(rows) - 1)]
    v = [v[0]] + [(v[i - 1] + v[i]) / 2 for i in range(1, len(v))] + [v[-1]]
    pad = v[:2] + v + v[-2:]
    v = [sorted(pad[i:i + 5])[2] for i in range(len(v))]
    (out / f"{a.name}.csv").write_text("t,lat,lon,speed_kmh\n" + "\n".join(f"{t},{la:.7f},{lo:.7f},{vk * 3.6:.1f}" for (t, la, lo), vk in zip(track, v)) + "\n")
    creator = (rows[0].get("creator") or {}).get("username")
    (out / f"{a.name}.json").write_text(json.dumps({
        "source": "Mapillary", "license": "CC BY-SA 4.0", "sequence": a.sequence, "contributor": creator,
        "captured": [rows[0]["captured_at"], rows[-1]["captured_at"]], "fps": fps,
        "images": [r["id"] for r in rows], "note": "faces and plates blurred by Mapillary; one video frame per photo",
    }, indent=1))
    print(a.name, len(frames), "frames at", fps, "fps", "contributor", creator)


if __name__ == "__main__":
    main()
