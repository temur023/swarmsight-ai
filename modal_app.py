"""SwarmSight AI on Modal (GPU): `modal deploy modal_app.py`.

Modal API as documented (checked 2026-10-10, modal client 1.6.1):
  https://modal.com/docs/guide/webhooks            @modal.asgi_app, @modal.concurrent on web functions, WebSockets, ASGI lifespan
  https://modal.com/docs/guide/concurrent-inputs   @modal.concurrent(max_inputs=...) goes directly below @app.function()
  https://modal.com/docs/sdk/py/latest/App         App.function(gpu, timeout, min_containers, max_containers, scaledown_window, ...)
  https://modal.com/docs/sdk/py/latest/Image       debian_slim / apt_install / uv_pip_install / env / add_local_dir (copy=False must be last)
  https://modal.com/docs/guide/images              Image builders
  https://modal.com/docs/guide/gpu                 gpu="T4" | "L4" | list of fallbacks
  https://modal.com/docs/guide/cuda                NVIDIA driver (CUDA 13.0 driver API) on every GPU host; CUDA libs via pip on debian_slim
  https://modal.com/docs/guide/volumes             Volume.from_name(create_if_missing=True); attached Volumes are committed
                                                   automatically every few seconds and on container shutdown -> no commit thread
  https://modal.com/docs/guide/cold-start          min_containers, scaledown_window (2 s .. 20 min)
  https://modal.com/docs/guide/timeouts            timeout 1 s .. 24 h (default 300 s)
  https://modal.com/docs/guide/webhook-timeouts    one HTTP request is capped at 150 s (then 303 redirect); jobs here run in a
                                                   background thread, so every API call returns quickly
ONNX Runtime GPU:
  https://onnxruntime.ai/docs/execution-providers/CUDA-ExecutionProvider.html
      onnxruntime-gpu >= 1.27 on PyPI is built for CUDA 13.0 + cuDNN 9; `pip install onnxruntime-gpu[cuda,cudnn]` installs the
      CUDA/cuDNN runtime wheels and `onnxruntime.preload_dlls()` (called in swarmsight/detector.py) loads them: no CUDA base image.
      Default GPU is L4 (sm_89): the onnxruntime-gpu 1.31.0 CUDA provider ships sm_89 machine code for all its kernels, but
      sm_75 (T4) code for only ~70% of them and no PTX fallback (counted from the wheel's fatbins). The YOLO ops most likely
      run on a T4 too; check /api/v1/health and scripts/smoke_deploy.py after deploying with MODAL_GPU=T4.

Deploy-time settings (read on the machine that runs `modal deploy`):
  MODAL_GPU             GPU type, or a comma-separated fallback list (default "L4"; "T4" is cheaper, see the note above)
  MODAL_MIN_CONTAINERS  warm containers kept running (default 0; 1 during the jury window). Never more than 1.
  MODAL_SCALEDOWN_S     idle seconds before the container stops (default 600, Modal allows 2..1200)
  MODAL_APP_NAME        Modal app name (default "swarmsight-ai")
  MODAL_VOLUME          Volume name (default "swarmsight-data")
  SWARMSIGHT_JOB_WORKERS, SWARMSIGHT_MAX_VIDEO_MB, SWARMSIGHT_THREADS, SWARMSIGHT_DEVICE  passed through to the app

The FastAPI app (swarmsight.server:app) knows nothing about Modal. It keeps jobs and WebSocket progress in memory and
SQLite on disk, so it runs in exactly one container (max_containers=1) that takes many concurrent requests.
"""
from __future__ import annotations

import os
from pathlib import Path

import modal

HERE = Path(__file__).resolve().parent
APP_DIR = "/app"  # project root inside the container: swarmsight/, web/, models/, samples/, ...
DATA_DIR = "/data"  # Modal Volume mount: SQLite DB, clips, key frames, thumbnails, dataset exports

APP_NAME = os.environ.get("MODAL_APP_NAME", "swarmsight-ai")
VOLUME_NAME = os.environ.get("MODAL_VOLUME", "swarmsight-data")
_gpu = [g.strip() for g in os.environ.get("MODAL_GPU", "L4").split(",") if g.strip()] or ["L4"]
GPU = _gpu[0] if len(_gpu) == 1 else _gpu
MIN_CONTAINERS = min(1, max(0, int(os.environ.get("MODAL_MIN_CONTAINERS", "0"))))
SCALEDOWN_S = max(2, min(1200, int(os.environ.get("MODAL_SCALEDOWN_S", "600"))))
CPU_CORES = 2.0  # physical cores (= 4 vCPU): video decode, ffmpeg H.264 encode, tracking
MEMORY_MB = 4096


def _gpu_requirements() -> list[str]:
    """requirements.txt with the CPU onnxruntime swapped for onnxruntime-gpu + its CUDA 13 / cuDNN 9 pip extras."""
    req = HERE / "requirements.txt"
    if not req.exists():  # inside the running container: the image is already built, nothing to resolve
        return []
    out = []
    for line in req.read_text().splitlines():
        line = line.split("#", 1)[0].strip()
        if not line:
            continue
        if line.startswith("onnxruntime=="):
            line = "onnxruntime-gpu[cuda,cudnn]==" + line.split("==", 1)[1]
        out.append(line)
    return out


_ignore = ["**/__pycache__", "**/*.pyc", "**/.DS_Store"]
image = (
    modal.Image.debian_slim(python_version="3.13")
    .apt_install("ffmpeg", "libglib2.0-0")
    .uv_pip_install(*_gpu_requirements())
    .env({
        "PYTHONUNBUFFERED": "1",
        "PYTHONDONTWRITEBYTECODE": "1",
        "SWARMSIGHT_RUNTIME": f"{DATA_DIR}/runtime",
        "SWARMSIGHT_DB_LOCAL": "/tmp/swarmsight/swarmsight.db",  # live DB on local disk, consistent copy on the Volume
        "SWARMSIGHT_DEVICE": os.environ.get("SWARMSIGHT_DEVICE", "auto"),
        "SWARMSIGHT_THREADS": os.environ.get("SWARMSIGHT_THREADS", "4"),
        "SWARMSIGHT_JOB_WORKERS": os.environ.get("SWARMSIGHT_JOB_WORKERS", "2"),
        "SWARMSIGHT_MAX_VIDEO_MB": os.environ.get("SWARMSIGHT_MAX_VIDEO_MB", "300"),
        "SWARMSIGHT_ANONYMIZE": os.environ.get("SWARMSIGHT_ANONYMIZE", "1"),  # face/plate blurring; 0 turns it off
        # optional: review, manual location and export then need this token (the site asks for it once)
        "SWARMSIGHT_MODERATOR_TOKEN": os.environ.get("SWARMSIGHT_MODERATOR_TOKEN", ""),
    })
    # project files: added at container start (copy=False), so these steps must stay last
    .add_local_dir(HERE / "swarmsight", f"{APP_DIR}/swarmsight", ignore=_ignore)
    .add_local_dir(HERE / "web", f"{APP_DIR}/web", ignore=_ignore)
    .add_local_dir(HERE / "models", f"{APP_DIR}/models", ignore=_ignore)
    .add_local_dir(HERE / "samples", f"{APP_DIR}/samples", ignore=_ignore)
    .add_local_dir(HERE / "docs", f"{APP_DIR}/docs", ignore=_ignore)
    .add_local_dir(HERE / "benchmarks" / "results", f"{APP_DIR}/benchmarks/results", ignore=_ignore)
    .add_local_file(HERE / "benchmarks" / "event_labels.csv", f"{APP_DIR}/benchmarks/event_labels.csv")  # reference labels
    .add_local_file(HERE / "benchmarks" / "event_labels_ru.csv", f"{APP_DIR}/benchmarks/event_labels_ru.csv")
    .add_local_file(HERE / "benchmarks" / "demo_labels.csv", f"{APP_DIR}/benchmarks/demo_labels.csv")
    .add_local_dir(HERE / "datasets" / "tashkent", f"{APP_DIR}/datasets/tashkent", ignore=_ignore)
)

app = modal.App(APP_NAME)
volume = modal.Volume.from_name(VOLUME_NAME, create_if_missing=True)


@app.function(
    image=image,
    gpu=GPU,
    cpu=CPU_CORES,
    memory=MEMORY_MB,
    volumes={DATA_DIR: volume},
    max_containers=1,  # jobs, WebSockets and the SQLite connection live in this one process
    min_containers=MIN_CONTAINERS,
    scaledown_window=SCALEDOWN_S,
    timeout=60 * 60,  # per input: a WebSocket that follows a long job, a big upload
    startup_timeout=10 * 60,
)
@modal.concurrent(max_inputs=200)
@modal.asgi_app()
def web():
    import sys

    sys.path.insert(0, APP_DIR)
    os.chdir(APP_DIR)
    from swarmsight.server import app as fastapi_app  # env above is set before this import: RUNTIME is on the Volume

    return fastapi_app
