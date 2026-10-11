"""Package a stretch of an openly licensed driving video (Wikimedia Commons) as a bundled sample trip (samples/).

The stretch is decoded with ffmpeg, scaled to 960 px wide at 15 fps, and anonymised like scripts/build_sample.py:
faces (top of every person box) and plate bands (lower part of every vehicle box) are blurred using the detections
of each frame and its two neighbours on either side, so one missed detection does not leak a face or a plate.
There is no GPS track: the trip report then says so, and locations come only from a pin or a moderator.

Output: samples/<name>.mp4, samples/<name>.jpg (poster), samples/<name>.json (source, licence, author, stretch).

Usage: python scripts/build_commons_sample.py --video src.webm --start 100 --duration 90 --name stcroix_taxi \
           --file "File:....webm" --license "CC BY 3.0" --author "John Edwards"
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from collections import deque
from pathlib import Path

import cv2
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from swarmsight.detector import MODELS_DIR, YoloOnnxDetector  # noqa: E402
from swarmsight.privacy import _blur  # noqa: E402

OUT_W, FPS, WIN = 960, 15.0, 2


def probe_size(video: str) -> tuple[int, int]:
    cap = cv2.VideoCapture(video)
    w, h = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH)), int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    cap.release()
    if not w or not h:
        raise SystemExit(f"cannot read the frame size of {video}")
    return w, h


def is_own_vehicle(x1, y1, x2, y2, fw: int, fh: int) -> bool:
    """Our own hood or dashboard, which the low-threshold detector reads as a huge car at the bottom of the frame."""
    return (x2 - x1) > 0.45 * fw and y2 > 0.85 * fh


def anonymise(img: np.ndarray, boxes: list) -> np.ndarray:
    safe = img.copy()
    fh, fw = img.shape[:2]
    for cls, (x1, y1, x2, y2) in boxes:
        w, h = x2 - x1, y2 - y1
        if cls == "person":
            _blur(safe, x1 - 0.12 * w, y1 - 0.06 * h, x2 + 0.12 * w, y1 + 0.3 * h)
        elif cls in ("car", "truck", "bus") and not is_own_vehicle(x1, y1, x2, y2, fw, fh):
            _blur(safe, x1, y1 + 0.35 * h, x2, y2 + 0.04 * h)  # SUV and van plates sit higher than a sedan's
    return safe


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--video", required=True)
    ap.add_argument("--start", type=float, required=True)
    ap.add_argument("--duration", type=float, required=True)
    ap.add_argument("--name", required=True)
    ap.add_argument("--file", required=True, help="Wikimedia Commons file title")
    ap.add_argument("--license", required=True)
    ap.add_argument("--author", required=True)
    ap.add_argument("--out", default="samples")
    a = ap.parse_args()
    out = Path(a.out)
    w0, h0 = probe_size(a.video)
    oh = int(round(h0 * OUT_W / w0)) // 2 * 2
    dec = subprocess.Popen(["ffmpeg", "-loglevel", "error", "-ss", str(a.start), "-t", str(a.duration), "-i", a.video,
                            "-vf", f"fps={FPS},scale={OUT_W}:{oh}", "-f", "rawvideo", "-pix_fmt", "bgr24", "-"], stdout=subprocess.PIPE)
    enc = subprocess.Popen(["ffmpeg", "-y", "-loglevel", "error", "-f", "rawvideo", "-pix_fmt", "bgr24", "-s", f"{OUT_W}x{oh}",
                            "-r", str(FPS), "-i", "-", "-c:v", "libx264", "-preset", "slow", "-crf", "27", "-pix_fmt", "yuv420p",
                            "-movflags", "+faststart", "-an", str(out / f"{a.name}.mp4")], stdin=subprocess.PIPE)
    det = YoloOnnxDetector(str(MODELS_DIR / "yolo11n_coco.onnx"), conf=0.1)
    boxes: list[list] = []  # detections of every frame read so far (small), by frame index
    pending: deque = deque()  # images not yet written: frame `written` .. the last frame read
    written, n = 0, OUT_W * oh * 3

    def flush():
        nonlocal written
        k = written
        near = [b for j in range(max(0, k - WIN), min(len(boxes), k + WIN + 1)) for b in boxes[j]]
        safe = anonymise(pending.popleft(), near)
        if k == 0:
            cv2.imwrite(str(out / f"{a.name}.jpg"), safe, [cv2.IMWRITE_JPEG_QUALITY, 80])
        enc.stdin.write(safe.tobytes())
        written += 1

    while True:
        buf = dec.stdout.read(n)
        if len(buf) < n:
            break
        img = np.frombuffer(buf, np.uint8).reshape(oh, OUT_W, 3).copy()
        d = det(img)
        boxes.append([(d.label(i), d.xyxy[i]) for i in range(len(d))])
        pending.append(img)
        if len(boxes) - 1 - written >= WIN:  # frame `written` now has its WIN later neighbours
            flush()
    while pending:
        flush()
    dec.wait()
    enc.stdin.close()
    enc.wait()
    meta = {"source": "Wikimedia Commons", "file": a.file, "url": "https://commons.wikimedia.org/wiki/" + a.file.replace(" ", "_"),
            "license": a.license, "author": a.author, "start_s": a.start, "duration_s": round(written / FPS, 2), "fps": FPS,
            "anonymised": "faces and plates blurred by us (scripts/build_commons_sample.py)"}
    (out / f"{a.name}.json").write_text(json.dumps(meta, indent=1) + "\n")
    print(a.name, written, "frames", f"{written / FPS:.1f} s")


if __name__ == "__main__":
    main()
