"""End to end through the HTTP API: the bundled sample trip, review, partner feed, DataMine export, error paths."""
import io
import json
import os
import zipfile
from pathlib import Path

from conftest import ROOT, wait_job

RUNTIME = Path(os.environ["SWARMSIGHT_RUNTIME"])
VIDEO = ROOT / "benchmarks" / "trips" / "tashkent_crossing.mp4"


def test_health(client):
    h = client.get("/api/v1/health").json()
    assert h["ok"] is True
    assert h["inference"] == "CPU · ONNX Runtime"
    assert {"road_users", "road_damage"} <= set(h["models"])
    assert h["clips"] == "ffmpeg H.264"


def test_web_and_samples(client):
    assert client.get("/").status_code == 200
    s = client.get("/api/v1/samples").json()["samples"]
    ids = [x["id"] for x in s]
    assert {"stcroix-taxi", "tashkent-redmi"} <= set(ids)
    assert "tashkent-crossing" not in ids
    for x in s:
        assert client.get(f"/samples/{x['poster']}").status_code == 200
        assert (ROOT / "samples" / x["video"]).is_file()


def test_sample_trip_report(client, sample_run):
    rep = sample_run["report"]
    assert rep["trip"]["id"] == sample_run["trip_id"] and rep["trip"]["status"] == "done"
    assert rep["trip"]["rights_scope"] == "road_and_dataset" and rep["trip"]["gps_source"] == "csv"
    assert rep["track"], "telemetry from the sample CSV"
    assert rep["observations"], "the sample has at least the baseline stretch"
    assert rep["clips"]
    for c in rep["clips"]:
        assert c["file"] and (RUNTIME / "media" / c["file"]).is_file()
        r = client.get(f"/media/{c['file']}")
        assert r.status_code == 200 and r.headers["content-type"] == "video/mp4" and r.content[4:8] == b"ftyp"
    clip_ids = {c["id"] for c in rep["clips"]}
    assert all(o["clip_id"] in clip_ids for o in rep["observations"] if o["clip_id"])
    assert client.get(f"/api/v1/trips/{sample_run['trip_id']}").json()["trip"]["id"] == sample_run["trip_id"]
    assert any(t["id"] == sample_run["trip_id"] for t in client.get("/api/v1/trips").json()["trips"])


def test_job_websocket_replays_progress(client, sample_run):
    types = []
    with client.websocket_connect(f"/ws/jobs/{sample_run['job_id']}") as ws:
        while True:
            m = ws.receive_json()
            types.append(m["type"])
            if m["type"] in ("done", "error"):
                break
    assert types[-1] == "done" and "frame" in types


def test_unknown_ids(client):
    assert client.get("/api/v1/jobs/nope").status_code == 404
    assert client.get("/api/v1/trips/nope").status_code == 404
    assert client.get("/api/v1/observations/999999").status_code == 404
    assert client.get("/api/v1/events/999999").status_code == 404
    assert client.post("/api/v1/samples/nope/run").status_code == 404
    assert client.get("/api/v1/datasets/exports/v999").status_code == 404


def test_review_flow_feed_and_export(client, sample_run):
    obs = client.get("/api/v1/observations?status=needs_review&kind=all").json()["observations"]
    mine = [o for o in obs if o["trip_id"] == sample_run["trip_id"]]
    assert mine
    target = next((o for o in mine if o["kind"] == "safety"), mine[0])
    assert target["lat"] is not None, "located from the sample telemetry"
    oid = target["id"]

    # bad input
    assert client.post(f"/api/v1/observations/{oid}/review", json={"action": "approve"}).status_code == 400
    assert client.post(f"/api/v1/observations/{oid}/review", json={"action": "correct", "label": "unicorn"}).status_code == 400
    assert client.post("/api/v1/observations/999999/review", json={"action": "confirm"}).status_code == 404

    # confirm, then reject: decisions are logged
    r = client.post(f"/api/v1/observations/{oid}/review", json={"action": "confirm", "reviewer": "jury"})
    assert r.status_code == 200 and r.json()["review_status"] == "confirmed"
    r = client.post(f"/api/v1/observations/{oid}/review", json={"action": "reject", "note": "changed my mind"})
    assert r.json()["review_status"] == "rejected"

    # correct to a road type: it becomes a verified road event on the map and in the partner feeds
    r = client.post(f"/api/v1/observations/{oid}/review", json={"action": "correct", "label": "pothole"}).json()
    assert r["review_status"] == "corrected" and r["label"] == "pothole" and r["kind"] == "road"
    assert [x["action"] for x in r["reviews"]] == ["confirm", "reject", "correct"]
    ev = r["event"]
    assert ev and ev["type"] == "pothole" and ev["status"] == "verified"
    assert client.get(f"/api/v1/events/{ev['id']}").json()["observations"][0]["id"] == oid

    cifs = client.get("/api/v1/partners/road-feed?format=cifs").json()
    assert set(cifs) == {"incidents"} and isinstance(cifs["incidents"], list)
    inc = next(i for i in cifs["incidents"] if i["id"] == f"swarmsight-{ev['id']}")
    assert inc["type"] == "HAZARD" and inc["subtype"] == "HAZARD_ON_ROAD_POT_HOLE"
    geo = client.get("/api/v1/partners/road-feed").json()
    assert any(f["properties"]["id"] == ev["id"] for f in geo["features"])
    assert all("device" not in k for f in geo["features"] for k in f["properties"])

    # manual location
    r = client.post(f"/api/v1/observations/{oid}/location", json={"lat": 41.3285, "lon": 69.3543, "uncertainty_m": 20})
    assert r.status_code == 200 and r.json()["loc_source"] == "manual"
    assert client.post(f"/api/v1/observations/{oid}/location", json={"lat": 41.3, "lon": 69.3, "uncertainty_m": 5000}).status_code == 422
    assert client.post("/api/v1/observations/999999/location", json={"lat": 41.3, "lon": 69.3}).status_code == 404

    # DataMine: the reviewed sample (dataset rights) is exported; the ZIP downloads
    summ = client.get("/api/v1/datasets/summary").json()
    assert summ["with_dataset_rights"] >= 1
    exp = client.post("/api/v1/datasets/exports", json={"include_unreviewed": False})
    assert exp.status_code == 200
    exp = exp.json()
    assert exp["n_samples"] >= 1
    dl = client.get(f"/api/v1/datasets/exports/{exp['version']}")
    assert dl.status_code == 200 and dl.headers["content-type"] == "application/zip"
    with zipfile.ZipFile(io.BytesIO(dl.content)) as z:
        names = z.namelist()
        man = json.loads(z.read("manifest.json"))
    assert man["n_samples"] == exp["n_samples"]
    assert any(s["sample_id"] == f"obs-{oid}" and s["label"] == "pothole" for s in man["samples"])
    assert any(n.startswith("clips/") and n.endswith(".mp4") for n in names)

    m = client.get("/api/v1/metrics").json()
    assert m["live"]["trips"] >= 1 and "road_damage_eval" in m


def test_upload_non_video_fails_cleanly(client):
    r = client.post("/api/v1/trips", files={"video": ("notes.mp4", b"this is not a video", "video/mp4")})
    if r.status_code >= 400:
        assert r.status_code < 500
        return
    started = r.json()
    job = wait_job(client, started["job_id"], timeout=30)
    assert job["status"] == "error" and job["error"]
    trip = client.get(f"/api/v1/trips/{started['trip_id']}").json()["trip"]
    assert trip["status"] == "error"


def test_bad_track_and_rights_are_rejected(client):
    video = VIDEO.read_bytes()
    r = client.post("/api/v1/trips", files={"video": ("a.mp4", video, "video/mp4"), "track": ("t.csv", b"foo,bar\n1,2\n", "text/csv")})
    assert r.status_code == 400 and "track" in r.json()["detail"]
    r = client.post("/api/v1/trips", files={"video": ("a.mp4", video, "video/mp4"),
                                            "track": ("t.gpx", b"<gpx><trk></trk></gpx>", "application/gpx+xml")})
    assert r.status_code == 400
    r = client.post("/api/v1/trips", files={"video": ("a.mp4", video, "video/mp4")}, data={"rights_scope": "everything"})
    assert r.status_code == 400
    assert not any((RUNTIME / "uploads").iterdir()), "rejected uploads are not kept"


def test_upload_short_trip_with_a_pinned_location(client):
    with open(VIDEO, "rb") as f:
        r = client.post("/api/v1/trips", files={"video": ("dashcam.mp4", f, "video/mp4")},
                        data={"lat": "41.3285", "lon": "69.3543", "max_seconds": "5", "rights_scope": "road_only",
                              "device_id": "test-phone"})
    assert r.status_code == 200, r.text
    started = r.json()
    job = wait_job(client, started["job_id"], timeout=120)
    assert job["status"] == "done", job
    rep = job["result"]
    assert rep["trip"]["gps_source"] == "single_point" and rep["trip"]["analysed_s"] <= 5.5
    assert rep["trip"]["device_id"].endswith("…") and "test-phone" not in rep["trip"]["device_id"]
    assert not any((RUNTIME / "uploads").iterdir()), "the upload is deleted after processing"


def test_moderator_token_protects_writes_when_set(client, monkeypatch):
    monkeypatch.setenv("SWARMSIGHT_MODERATOR_TOKEN", "s3cret")
    assert client.post("/api/v1/observations/1/review", json={"action": "confirm"}).status_code == 401
    assert client.post("/api/v1/datasets/exports", json={}).status_code == 401
    r = client.post("/api/v1/observations/999999/review", json={"action": "confirm"}, headers={"X-Moderator-Token": "s3cret"})
    assert r.status_code == 404
    assert client.get("/api/v1/health").json()["moderation"] == "token required"


def test_store_backup_is_a_consistent_copy(tmp_path):
    import sqlite3
    from swarmsight.store import Store
    st = Store(tmp_path / "live.db")
    st.device("dev-x")
    st.backup_to(tmp_path / "copy.db")
    assert sqlite3.connect(tmp_path / "copy.db").execute("SELECT COUNT(*) FROM devices").fetchone()[0] == 1
