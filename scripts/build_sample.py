"""Package the team's Tashkent dashcam trip as a labelled benchmark trip (benchmarks/trips/): anonymised video + telemetry CSV.
It is not a public sample on the site (it ends at a crash).

Faces (top of every person box) and plate bands (lower part of every vehicle box, full width) are blurred using the
detections of each frame and its four neighbours, so one missed detection does not leak a face or a plate.  The
sample stops at the moment of impact in the crossing ahead (we show the conflict, not its outcome).
The telemetry was read by us from the dashcam's on-screen overlay (GPS and speed, once a second).

Usage: python scripts/build_sample.py --video trip.mp4   (the original video is not part of the repository)
"""
from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

import cv2

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from swarmsight.detector import MODELS_DIR, YoloOnnxDetector  # noqa: E402
from swarmsight.privacy import _blur  # noqa: E402

FPS = 24.0
START_S, IMPACT_FRAME = 6.0, 714
OUT_W = 960
# video time (s), lat, lon, km/h; video time 0 = 18:27:53 on the overlay clock
TELEMETRY = [
    (0, 41.32853, 69.35432, 0), (6, 41.32853, 69.35432, 0), (14, 41.32853, 69.35432, 0), (15, 41.32851, 69.35432, 0), (19, 41.32851, 69.35430, 0),
    (25, 41.32851, 69.35430, 0), (26, 41.32851, 69.35430, 3), (27, 41.32851, 69.35430, 6), (28, 41.32853, 69.35433, 9),
    (29, 41.32857, 69.35436, 16), (30, 41.32862, 69.35441, 22), (31, 41.32866, 69.35445, 27),
]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--video", required=True)
    ap.add_argument("--out", default="benchmarks/trips")
    a = ap.parse_args()
    out = Path(a.out)
    out.mkdir(exist_ok=True)
    det = YoloOnnxDetector(str(MODELS_DIR / "yolo11n_coco.onnx"), conf=0.1)
    cap = cv2.VideoCapture(a.video)
    f0, f1 = int(START_S * FPS), IMPACT_FRAME
    cap.set(cv2.CAP_PROP_POS_FRAMES, max(0, f0 - 2))
    raw, boxes = {}, {}
    for fi in range(max(0, f0 - 2), f1 + 3):
        ok, img = cap.read()
        if not ok:
            break
        d = det(img)
        boxes[fi] = [(d.label(i), d.xyxy[i]) for i in range(len(d))]
        if f0 <= fi <= f1:
            raw[fi] = img
    h0, w0 = raw[f0].shape[:2]
    oh = int(round(h0 * OUT_W / w0)) // 2 * 2
    enc = subprocess.Popen(["ffmpeg", "-y", "-loglevel", "error", "-f", "rawvideo", "-pix_fmt", "bgr24", "-s", f"{OUT_W}x{oh}",
                            "-r", str(FPS), "-i", "-", "-c:v", "libx264", "-preset", "slow", "-crf", "23", "-pix_fmt", "yuv420p",
                            "-movflags", "+faststart", "-an", str(out / "tashkent_crossing.mp4")], stdin=subprocess.PIPE)
    for fi in range(f0, f1 + 1):
        safe = raw[fi].copy()
        for g in range(fi - 2, fi + 3):
            for cls, (x1, y1, x2, y2) in boxes.get(g, []):
                w, h = x2 - x1, y2 - y1
                if cls == "person":
                    _blur(safe, x1 - 0.12 * w, y1 - 0.06 * h, x2 + 0.12 * w, y1 + 0.3 * h)
                elif cls in ("car", "truck", "bus"):
                    _blur(safe, x1, y1 + 0.55 * h, x2, y2 + 0.04 * h)
        small = cv2.resize(safe, (OUT_W, oh), interpolation=cv2.INTER_AREA)
        if fi == f0:
            cv2.imwrite(str(out / "tashkent_crossing.jpg"), small, [cv2.IMWRITE_JPEG_QUALITY, 80])
        enc.stdin.write(small.tobytes())
    enc.stdin.close()
    enc.wait()
    lines = ["t,lat,lon,speed_kmh"] + [f"{t - START_S:g},{la},{lo},{v}" for t, la, lo, v in TELEMETRY if t >= START_S - 1]
    (out / "tashkent_crossing.csv").write_text("\n".join(lines) + "\n")
    print("sample:", f1 - f0 + 1, "frames")


if __name__ == "__main__":
    main()
