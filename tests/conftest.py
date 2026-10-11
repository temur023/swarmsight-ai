"""Test setup. The runtime directory must be set before swarmsight.server is imported (it is read at import time)."""
import os
import sys
import tempfile
import time
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
os.environ["SWARMSIGHT_RUNTIME"] = tempfile.mkdtemp(prefix="swarmsight_test_")
os.environ.setdefault("SWARMSIGHT_DEVICE", "cpu")


def wait_job(client, job_id: str, timeout: float = 240.0) -> dict:
    t0 = time.time()
    while time.time() - t0 < timeout:
        j = client.get(f"/api/v1/jobs/{job_id}").json()
        if j["status"] in ("done", "error"):
            return j
        time.sleep(0.25)
    raise AssertionError(f"job {job_id} did not finish in {timeout} s: {j}")


@pytest.fixture(scope="session")
def client():
    from fastapi.testclient import TestClient

    from swarmsight.server import app

    with TestClient(app) as c:
        yield c


@pytest.fixture(scope="session")
def sample_run(client) -> dict:
    """Our Tashkent benchmark trip with its telemetry, uploaded once through the full pipeline (about 15-25 s on a CPU)."""
    trip = ROOT / "benchmarks" / "trips"
    with open(trip / "tashkent_crossing.mp4", "rb") as v, open(trip / "tashkent_crossing.csv", "rb") as t:
        r = client.post("/api/v1/trips", files={"video": ("tashkent_crossing.mp4", v, "video/mp4"), "track": ("tashkent_crossing.csv", t, "text/csv")},
                        data={"rights_scope": "road_and_dataset"})
    assert r.status_code == 200, r.text
    started = r.json()
    job = wait_job(client, started["job_id"])
    assert job["status"] == "done", job
    return {**started, "job": job, "report": job["result"]}
