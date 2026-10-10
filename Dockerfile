# SwarmSight AI: web service on any container host (CPU). GPU deployment: modal_app.py / docs/DEPLOY_MODAL.md
FROM python:3.13-slim

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1 \
    SWARMSIGHT_RUNTIME=/data/runtime SWARMSIGHT_DEVICE=cpu SWARMSIGHT_THREADS=2 SWARMSIGHT_JOB_WORKERS=1
# ffmpeg writes the H.264 clips; libglib is needed by OpenCV
RUN apt-get update && apt-get install -y --no-install-recommends ffmpeg libglib2.0-0 && rm -rf /var/lib/apt/lists/*

# many hosts (e.g. Hugging Face Spaces) run the container as uid 1000
RUN useradd -m -u 1000 app && mkdir -p /data/runtime && chown -R app /data
WORKDIR /app
COPY requirements.txt .
RUN pip install -r requirements.txt

COPY --chown=app swarmsight swarmsight
COPY --chown=app web web
COPY --chown=app models models
COPY --chown=app samples samples
COPY --chown=app docs docs
COPY --chown=app datasets/tashkent datasets/tashkent
COPY --chown=app benchmarks/results benchmarks/results

USER app
# keep the database, clips and exports across restarts: docker run -v swarmsight-data:/data -p 7860:7860 swarmsight-ai
EXPOSE 7860
HEALTHCHECK --interval=30s --timeout=5s --start-period=60s CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:7860/api/v1/health', timeout=4)"
CMD ["uvicorn", "swarmsight.server:app", "--host", "0.0.0.0", "--port", "7860", "--proxy-headers", "--forwarded-allow-ips", "*"]
