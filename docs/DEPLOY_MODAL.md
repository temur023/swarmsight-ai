# Deploy on Modal (GPU)

## From the browser (GitHub Actions)

1. modal.com → Settings → API Tokens → **New token**: copy the token id (`ak-…`) and secret (`as-…`).
2. github.com/temur023/swarmsight-ai → Settings → Secrets and variables → Actions → **New repository secret**:
   `MODAL_TOKEN_ID` and `MODAL_TOKEN_SECRET`.
3. Actions → **Deploy to Modal (GPU)** → Run workflow (warm containers: 0 now, 1 for the jury window; GPU: L4).
   The workflow runs the tests, deploys with `--strategy recreate --tag <commit>`, prints the public URL in the run
   summary and smoke-tests it (GPU health, sample trip, upload, clip streaming).


`modal_app.py` serves the unchanged FastAPI app (`swarmsight.server:app`) from one Modal container with an NVIDIA L4 (or T4)
GPU, ONNX Runtime GPU (CUDA 13 + cuDNN 9 from pip, no CUDA base image) and ffmpeg. The SQLite database, clips and dataset
exports go to the Modal Volume `swarmsight-data` (mounted at `/data`, `SWARMSIGHT_RUNTIME=/data/runtime`), so they survive
restarts and redeploys.

## First deploy

```bash
pip install modal            # client 1.6.x
modal setup                  # opens the browser and stores a token in ~/.modal.toml
modal deploy modal_app.py    # prints the URL: https://<workspace>--swarmsight-ai-web.modal.run
```

The first build installs the Python packages and the CUDA wheels, which takes a few minutes. Later deploys reuse the image
and only upload the project files.

## Check it

```bash
URL=https://<workspace>--swarmsight-ai-web.modal.run
curl -s $URL/api/v1/health | python -m json.tool     # "inference": "GPU · ONNX Runtime", provider CUDAExecutionProvider
python scripts/smoke_deploy.py $URL --expect-gpu     # health, sample trip, upload, clip + Range 206, WebSocket, timings
modal app logs swarmsight-ai                         # add -f to follow
```

The first request after an idle period starts the container and loads the models (a cold start of some seconds to tens of seconds).
If health says `CPU · ONNX Runtime`, the CUDA provider did not load: look for ONNX Runtime errors in the logs. The service
still works on the CPU, only slower.

## Settings

Read from your shell when you run `modal deploy`:

| Variable | Default | Meaning |
|---|---|---|
| `MODAL_GPU` | `L4` | GPU type, or a fallback list such as `L4,T4`. A T4 is cheaper but onnxruntime-gpu 1.31 has T4 (sm_75) machine code for only part of its CUDA kernels: check health and the smoke test if you pick it. |
| `MODAL_MIN_CONTAINERS` | `0` | `1` keeps the container warm (no cold starts). Never more than 1. |
| `MODAL_SCALEDOWN_S` | `600` | Idle seconds before the container stops (2 to 1200). |
| `SWARMSIGHT_JOB_WORKERS` | `2` | Trips analysed in parallel. |
| `SWARMSIGHT_MAX_VIDEO_MB` | `300` | Upload limit. |
| `SWARMSIGHT_THREADS` | `4` | CPU threads per ONNX Runtime session (the container has 2 physical cores = 4 vCPU). |
| `SWARMSIGHT_DEVICE` | `auto` | `cpu` forces CPU inference. |
| `MODAL_APP_NAME`, `MODAL_VOLUME` | `swarmsight-ai`, `swarmsight-data` | Names, e.g. for a separate test deployment. |

Why one container (`max_containers=1`): jobs and WebSocket progress live in memory and SQLite has one writer. The container
accepts up to 200 concurrent requests (`@modal.concurrent`), uploads are processed in a background thread and the browser
follows progress over the WebSocket, so no request comes near Modal's 150 s HTTP limit. Function timeout: 1 h per request.

## Jury window

```bash
MODAL_MIN_CONTAINERS=1 modal deploy modal_app.py --strategy recreate     # before: one container always warm
python scripts/smoke_deploy.py $URL --expect-gpu                         # warm it and check it
modal deploy modal_app.py --strategy recreate                            # after: back to scale-to-zero
```

## Cost (modal.com/pricing, October 2026)

L4 $0.000222/s (about $0.80/h), T4 $0.000164/s (about $0.59/h), plus 2 CPU cores (about $0.09/h) and 4 GiB of memory
(about $0.03/h). Billing is per second while the container runs: with `MODAL_MIN_CONTAINERS=0` you pay only while it is
busy and for 10 idle minutes after the last request; a warm L4 for a 24 h jury window costs about $22 (T4 about $17). The
Starter plan includes $30 of credits per month.

## Redeploy the code-freeze commit

Modal uploads the files of your working tree, not a git commit, so deploy from a clean checkout of the frozen commit:

```bash
git fetch && git worktree add ../swarmsight-freeze <freeze-tag-or-sha>
cd ../swarmsight-freeze
MODAL_MIN_CONTAINERS=1 modal deploy modal_app.py --strategy recreate --tag "$(git rev-parse --short HEAD)"
modal app history swarmsight-ai          # versions with their tags
modal app rollover swarmsight-ai         # restart the container with the same code
```

Same app name, same URL, same Volume: data from earlier deploys stays. `--strategy recreate` stops the old container when
the new one goes live, so two containers never write the database at once. Redeploy when nobody is uploading: a trip
being analysed at that moment is lost, and writes from its last few seconds may be too.

Backup of the data: `modal volume get swarmsight-data runtime/swarmsight.db ./swarmsight-backup.db` (or `runtime` for
everything). Look at it: `modal volume ls swarmsight-data runtime`.
