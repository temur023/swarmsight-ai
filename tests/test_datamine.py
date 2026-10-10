"""DataMine: split by trip, data value, versioned export with rights and review filters."""
import json
import time
import zipfile
from collections import Counter

import pytest

from swarmsight.datamine import CLASSES, WEIGHTS, data_value, export, split_of, summary
from swarmsight.store import Store


def test_split_is_deterministic_and_balanced():
    ids = [f"trip-{i}" for i in range(2000)]
    first = [split_of(t) for t in ids]
    assert first == [split_of(t) for t in ids]
    c = Counter(first)
    assert set(c) == {"train", "val", "test"}
    assert 0.65 < c["train"] / 2000 < 0.75 and 0.11 < c["val"] / 2000 < 0.19 and 0.11 < c["test"] / 2000 < 0.19


@pytest.fixture
def ds(tmp_path):
    """Two trips with dataset rights, one road-only trip; observations at every review level."""
    st = Store(tmp_path / "db.sqlite")
    media = tmp_path / "media"
    for sub in ("clips", "frames"):
        (media / sub).mkdir(parents=True)
    now = time.time()
    trips = {"tripA": "road_and_dataset", "tripB": "road_and_dataset", "tripC": "road_only"}
    for tid, rights in trips.items():
        st.insert("trips", {"id": tid, "device_id": "dev-x", "filename": f"{tid}.mp4", "created_at": now, "status": "done",
                            "rights_scope": rights, "analysed_s": 20.0, "kept_s": 8.0})
        clip = f"clips/{tid}.mp4"
        (media / clip).write_bytes(b"\x00\x00\x00\x18ftypmp42")
        kfs = []
        for k, t in enumerate((1.0, 1.5, 9.0)):
            f = f"frames/{tid}_{k:03d}.jpg"
            (media / f).write_bytes(b"\xff\xd8\xff\xd9")
            kfs.append({"t": t, "file": f, "boxes": [{"cls": "pothole", "bbox": [100, 200, 300, 260], "conf": 0.7, "track": 1},
                                                     {"cls": "traffic light", "bbox": [0, 0, 10, 10], "conf": 0.5, "track": 2}]})
        st.insert("clips", {"id": f"clip-{tid}", "trip_id": tid, "t0": 0.0, "t1": 10.0, "file": clip, "size": [960, 540],
                            "keyframes": kfs})
    ids = {}

    def add(name, trip, status, label="pothole", model_label="pothole", kind="road"):
        ids[name] = st.insert("observations", {
            "trip_id": trip, "device_id": "dev-x", "kind": kind, "type": model_label, "label": label, "t_start": 1.0,
            "t_end": 2.0, "t_peak": 1.5, "conf": 0.6, "uncertainty": 0.8, "severity": 0.7, "clip_id": f"clip-{trip}",
            "clip_offset_s": 1.5, "lat": 41.3, "lon": 69.2, "loc_source": "csv", "loc_uncertainty_m": 9.0,
            "review_status": status, "quality": 0.9, "data_value": 0.5, "value_parts": {"novelty": 1.0},
            "embedding": [0.1] * 144, "model_version": "test", "observed_at": now, "created_at": now})

    add("a_confirmed", "tripA", "confirmed")
    add("a_corrected", "tripA", "corrected", label="alligator_crack")
    add("a_open", "tripA", "needs_review")
    add("a_rejected", "tripA", "rejected")
    add("b_confirmed", "tripB", "confirmed")
    add("c_confirmed", "tripC", "confirmed")  # road_only: never in a dataset
    return st, media, tmp_path / "exports", ids


def _read(path):
    with zipfile.ZipFile(path) as z:
        return z.namelist(), json.loads(z.read("manifest.json"))


def test_export_only_dataset_rights_and_reviewed(ds):
    st, media, out, ids = ds
    res = export(st, media, out, include_unreviewed=False)
    assert res["n_samples"] == 3 and res["version"].startswith("v1-")
    names, man = _read(out / res["file"])
    got = {s["sample_id"] for s in man["samples"]}
    assert got == {f"obs-{ids['a_confirmed']}", f"obs-{ids['a_corrected']}", f"obs-{ids['b_confirmed']}"}
    assert all(s["rights_scope"] == "road_and_dataset" and s["quality_level"] == "reviewed" for s in man["samples"])
    corrected = next(s for s in man["samples"] if s["sample_id"] == f"obs-{ids['a_corrected']}")
    assert corrected["label"] == "alligator_crack" and corrected["model_label"] == "pothole"
    # split by trip: every sample of a trip in that trip's split, and the raw trip id is not exported
    for s in man["samples"]:
        trip = "tripA" if s["sample_id"] != f"obs-{ids['b_confirmed']}" else "tripB"
        assert s["split"] == split_of(trip) and s["trip"] != trip
    assert {"manifest.json", "annotations.json", "classes.txt", "README.md", "clips/tripA.mp4", "clips/tripB.mp4"} <= set(names)
    assert "clips/tripC.mp4" not in names
    # key frames inside the event interval (+-1 s) with YOLO labels; boxes of classes outside CLASSES are dropped
    img = f"images/{split_of('tripA')}/tripA_000.jpg"
    assert img in names and f"images/{split_of('tripA')}/tripA_002.jpg" not in names
    with zipfile.ZipFile(out / res["file"]) as z:
        label = z.read(f"labels/{split_of('tripA')}/tripA_000.txt").decode().split()
    assert int(label[0]) == CLASSES.index("pothole") and len(label) == 5
    assert all(0 <= float(v) <= 1 for v in label[1:])


def test_export_with_unreviewed(ds):
    st, media, out, ids = ds
    res = export(st, media, out, include_unreviewed=True)
    _, man = _read(out / res["file"])
    levels = {s["sample_id"]: s["quality_level"] for s in man["samples"]}
    assert levels[f"obs-{ids['a_open']}"] == "raw_candidate"
    assert f"obs-{ids['a_rejected']}" not in levels and f"obs-{ids['c_confirmed']}" not in levels
    assert res["n_samples"] == 4 and res["summary"]["include_unreviewed"] is True


def test_manifest_fields_and_versioning(ds):
    st, media, out, _ = ds
    r1 = export(st, media, out)
    r2 = export(st, media, out)
    assert r1["version"].startswith("v1-") and r2["version"].startswith("v2-")
    _, man = _read(out / r2["file"])
    for k in ("name", "version", "created", "samples", "classes", "n_samples", "counts", "split_rule", "rights",
              "data_value_weights", "annotations"):
        assert k in man, k
    assert man["n_samples"] == len(man["samples"]) == 3
    assert set(man["counts"]) == {"by_label", "by_split", "by_level"}
    assert man["counts"]["by_level"] == {"reviewed": 3}
    assert man["data_value_weights"] == WEIGHTS
    s = man["samples"][0]
    for k in ("sample_id", "trip", "split", "label", "model_label", "kind", "quality_level", "review_status", "interval_s",
              "peak_s", "clip", "clip_interval_s", "frames", "location", "model_confidence", "data_value", "value_parts",
              "image_quality", "rights_scope", "model_version", "privacy"):
        assert k in s, k
    assert s["location"]["source"] == "csv"
    rows = st.query("SELECT version, n_samples FROM dataset_exports ORDER BY created_at")
    assert [r["version"] for r in rows] == [r1["version"], r2["version"]]
    summ = summary(st)
    assert summ["with_dataset_rights"] == 5 and len(summ["exports"]) == 2


def test_data_value_parts():
    st = Store(":memory:")
    now = time.time()
    oid = st.insert("observations", {"trip_id": "t1", "device_id": "d", "kind": "road", "type": "pothole", "label": "pothole",
                                     "conf": 0.5, "uncertainty": 1.0, "quality": 0.8, "embedding": [1.0, 0.0],
                                     "review_status": "needs_review", "observed_at": now, "created_at": now})
    o = st.one("SELECT * FROM observations WHERE id=?", (oid,))
    v, parts = data_value(st, o)
    assert set(parts) == set(WEIGHTS)
    assert parts["novelty"] == 1.0 and parts["coverage_gap"] == 1.0  # nothing collected yet
    assert v == pytest.approx(0.35 + 0.25 + 0.2 * 0.8 + 0.2, abs=1e-3)
