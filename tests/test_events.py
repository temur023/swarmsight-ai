"""Fusion of road observations into events, trust, review and manual location (SQLite in memory)."""
import time

import pytest

from swarmsight.events import Fusion
from swarmsight.store import Store

LAT, LON = 41.3111, 69.2797
M_LAT = 1 / 111_320  # degrees of latitude per metre


@pytest.fixture
def fx():
    st = Store(":memory:")
    return st, Fusion(st)


def add_obs(st, device="dev-a", lat=LAT, lon=LON, label="pothole", conf=0.9, unc=8.0, kind="road", trip="trip-1"):
    now = time.time()
    return st.insert("observations", {
        "trip_id": trip, "device_id": device, "kind": kind, "type": label, "label": label, "t_start": 1.0, "t_end": 2.0,
        "t_peak": 1.5, "conf": conf, "uncertainty": 0.2, "severity": 0.8, "lat": lat, "lon": lon,
        "loc_source": "csv" if lat is not None else None, "loc_uncertainty_m": unc if lat is not None else None,
        "review_status": "needs_review", "observed_at": now, "created_at": now})


def obs(st, oid):
    return st.one("SELECT * FROM observations WHERE id=?", (oid,))


def event(st, eid):
    return st.one("SELECT * FROM events WHERE id=?", (eid,))


def test_two_devices_5m_apart_merge_and_corroborate(fx):
    st, fu = fx
    a = add_obs(st, "dev-a")
    e1 = fu.attach(a)
    assert e1["status"] == "candidate" and e1["n_sources"] == 1
    b = add_obs(st, "dev-b", lat=LAT + 5 * M_LAT)
    e2 = fu.attach(b)
    assert e2["id"] == e1["id"]
    assert e2["n_obs"] == 2 and e2["n_sources"] == 2
    # noisy-OR over devices: 1 - (1 - 0.9 * 2/3)^2 = 0.84
    assert e2["confidence"] == pytest.approx(0.84, abs=1e-3)
    assert e2["status"] == "corroborated"
    assert LAT < e2["lat"] < LAT + 5 * M_LAT
    assert st.one("SELECT COUNT(*) AS n FROM events")["n"] == 1


def test_two_weak_observations_stay_candidate(fx):
    st, fu = fx
    fu.attach(add_obs(st, "dev-a", conf=0.3))
    e = fu.attach(add_obs(st, "dev-b", conf=0.3, lat=LAT + 5 * M_LAT))
    assert e["n_sources"] == 2 and e["confidence"] < 0.6 and e["status"] == "candidate"


def test_same_device_twice_is_not_corroboration(fx):
    st, fu = fx
    fu.attach(add_obs(st, "dev-a"))
    e = fu.attach(add_obs(st, "dev-a", lat=LAT + 3 * M_LAT))
    assert e["n_obs"] == 2 and e["n_sources"] == 1 and e["status"] == "candidate"


def test_far_apart_or_other_type_are_separate_events(fx):
    st, fu = fx
    e1 = fu.attach(add_obs(st, "dev-a"))
    e2 = fu.attach(add_obs(st, "dev-b", lat=LAT + 200 * M_LAT))
    e3 = fu.attach(add_obs(st, "dev-c", label="alligator_crack"))
    assert len({e1["id"], e2["id"], e3["id"]}) == 3


def test_confirm_verifies_and_raises_reliability(fx):
    st, fu = fx
    a = add_obs(st, "dev-a")
    eid = fu.attach(a)["id"]
    before = st.reliability("dev-a")
    o = fu.review(a, "confirm", "alice", "clearly a pothole")
    assert o["review_status"] == "confirmed" and o["event_id"] == eid
    assert event(st, eid)["status"] == "verified"
    assert st.reliability("dev-a") > before
    r = st.query("SELECT * FROM reviews WHERE observation_id=?", (a,))
    assert r[0]["reviewer"] == "alice" and r[0]["action"] == "confirm"
    assert any(h["action"] == "verified" for h in event(st, eid)["history"])
    feed = fu.cifs()["incidents"]
    assert [i["id"] for i in feed] == [f"swarmsight-{eid}"] and feed[0]["subtype"] == "HAZARD_ON_ROAD_POT_HOLE"


def test_reject_all_rejects_the_event(fx):
    st, fu = fx
    a, b = add_obs(st, "dev-a"), add_obs(st, "dev-b", lat=LAT + 5 * M_LAT)
    fu.attach(a)
    eid = fu.attach(b)["id"]
    fu.review(a, "reject")
    assert event(st, eid)["status"] == "candidate" and event(st, eid)["n_obs"] == 1
    fu.review(b, "reject")
    assert event(st, eid)["status"] == "rejected"
    assert st.reliability("dev-a") < 2 / 3
    assert fu.geojson(("candidate", "corroborated", "verified"))["features"] == []


def test_correct_changes_label_and_moves_to_event_of_new_type(fx):
    st, fu = fx
    a = add_obs(st, "dev-a")
    old = fu.attach(a)["id"]
    o = fu.review(a, "correct", label="alligator_crack")
    assert o["review_status"] == "corrected" and o["label"] == "alligator_crack" and o["type"] == "pothole"
    assert o["event_id"] is not None and o["event_id"] != old
    new = event(st, o["event_id"])
    assert new["type"] == "alligator_crack" and new["status"] == "verified"
    assert event(st, old)["n_obs"] == 0


def test_correct_to_safety_label_leaves_the_map(fx):
    st, fu = fx
    a = add_obs(st, "dev-a")
    fu.attach(a)
    o = fu.review(a, "correct", label="cut_in")
    assert o["kind"] == "safety" and o["event_id"] is None


def test_bad_review_input(fx):
    st, fu = fx
    a = add_obs(st)
    with pytest.raises(ValueError):
        fu.review(a, "approve")
    with pytest.raises(ValueError):
        fu.review(a, "correct", label="unicorn")
    with pytest.raises(KeyError):
        fu.review(99999, "confirm")


def test_locate_sets_manual_location_and_attaches(fx):
    st, fu = fx
    a = add_obs(st, lat=None, lon=None)
    assert fu.attach(a) is None  # no location, no road event
    o = fu.locate(a, LAT, LON, 30.0, "bob")
    assert o["loc_source"] == "manual" and o["lat"] == LAT and o["loc_uncertainty_m"] == 30.0
    assert o["event_id"] is not None and event(st, o["event_id"])["type"] == "pothole"
    assert st.one("SELECT action FROM reviews WHERE observation_id=?", (a,))["action"] == "locate"
    with pytest.raises(ValueError):
        fu.locate(a, 95.0, LON, 30.0)
    with pytest.raises(KeyError):
        fu.locate(99999, LAT, LON, 30.0)


def test_locate_moves_observation_between_events(fx):
    st, fu = fx
    a = add_obs(st, "dev-a")
    e1 = fu.attach(a)["id"]
    o = fu.locate(a, LAT + 500 * M_LAT, LON, 10.0)
    assert o["event_id"] != e1 and o["loc_source"] == "manual"


def test_safety_and_baseline_never_become_road_events(fx):
    st, fu = fx
    assert fu.attach(add_obs(st, label="cut_in", kind="safety")) is None
    assert fu.attach(add_obs(st, label="baseline_drive", kind="baseline")) is None


def test_expired_events_leave_the_feed(fx):
    st, fu = fx
    a = add_obs(st)
    eid = fu.attach(a)["id"]
    fu.review(a, "confirm")
    st.update("events", eid, {"expires_at": time.time() - 1})
    assert fu.cifs()["incidents"] == []
    assert event(st, eid)["status"] == "expired"


def test_event_left_without_observations_leaves_the_map(fx):
    st, fu = fx
    a = add_obs(st, "dev-a")
    old = fu.attach(a)["id"]
    fu.review(a, "correct", label="alligator_crack")
    assert event(st, old)["status"] not in ("candidate", "corroborated", "verified")
