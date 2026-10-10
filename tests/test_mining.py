"""EventMiner.propose on synthetic per-frame records (no video, no model)."""
from swarmsight.mining import EventMiner, Proposal, _dedupe_safety, kind_of
from swarmsight.telemetry import parse_track

W, H = 1280, 720


def frames(n=5, dt=0.2, users=None, damage=None):
    """n frames; users/damage: callables frame index -> list of records."""
    return [{"t": round(i * dt, 3), "w": W, "h": H, "users": users(i) if users else [], "damage": damage(i) if damage else []}
            for i in range(n)]


def pothole(i, tid=1):
    return [{"id": tid, "cls": "pothole", "bbox": [600, 500 + 10 * i, 700, 560 + 10 * i], "conf": 0.6 + 0.05 * i,
             "severity": 0.7}] if i < 3 else []


def car_ttc(i, tid=7, ttc=1.8):
    # in our path (centre, lower half), growing, time to contact under 3 s
    return [{"id": tid, "cls": "car", "bbox": [560 - 10 * i, 380, 720 + 10 * i, 520 + 10 * i], "conf": 0.8, "corridor": True,
             "ttc": round(ttc - 0.2 * i, 2)}] if i < 3 else []


def test_damage_track_in_three_frames_gives_one_pothole():
    props = EventMiner.propose(frames(damage=pothole))
    assert len(props) == 1
    p = props[0]
    assert p.type == "pothole" and p.kind == "road"
    assert p.evidence["frames_seen"] == 3 and p.track_ids == [1]
    assert p.t_start == 0.0 and p.t_end == 0.4
    assert p.conf == max(0.6, 0.65, 0.7) and p.severity == 0.7


def test_damage_seen_once_is_ignored():
    assert EventMiner.propose(frames(damage=lambda i: pothole(i) if i == 0 else [])) == []


def test_two_tracks_of_one_pothole_are_joined():
    # an id switch while driving over it: track 1 in frames 0-2, track 2 in frames 3-4
    props = EventMiner.propose(frames(damage=lambda i: pothole(i) if i < 3 else pothole(i - 3, tid=2)))
    assert [p.type for p in props] == ["pothole"]
    assert sorted(props[0].track_ids) == [1, 2]


def test_vehicle_with_low_ttc_in_corridor_gives_forward_collision_risk():
    props = EventMiner.propose(frames(users=car_ttc))
    assert [p.type for p in props] == ["forward_collision_risk"]
    p = props[0]
    assert p.kind == "safety" and p.track_ids == [7]
    assert p.evidence["min_ttc_s"] == 1.4 and p.evidence["road_user"] == "car" and p.evidence["frames_seen"] == 3
    assert 0.2 <= p.severity <= 1.0


def test_high_ttc_gives_nothing():
    assert EventMiner.propose(frames(users=lambda i: car_ttc(i, ttc=6.0))) == []


def test_overlapping_safety_proposals_on_one_track_are_deduplicated():
    # a pedestrian in our path, large in the frame, with a low time to contact: vru_near_path + forward_collision_risk
    def person(i):
        return [{"id": 3, "cls": "person", "bbox": [600, 300, 680, 600], "conf": 0.7, "corridor": True, "ttc": 2.0}] if i < 4 else []

    props = EventMiner.propose(frames(users=person))
    safety = [p for p in props if p.kind == "safety"]
    assert len(safety) == 1
    assert safety[0].type == "forward_collision_risk"  # the more specific type wins
    assert [a["type"] for a in safety[0].evidence["also"]] == ["vru_near_path"]


def test_dedupe_keeps_separate_road_users_apart():
    a = Proposal("forward_collision_risk", 1.0, 2.0, 1.5, 0.8, 0.6, [0, 0, 1, 1], [1])
    b = Proposal("vru_near_path", 1.2, 2.2, 1.7, 0.8, 0.5, [0, 0, 1, 1], [2])
    c = Proposal("cut_in", 1.1, 1.9, 1.9, 0.8, 0.7, [0, 0, 1, 1], [1])
    road = Proposal("pothole", 1.0, 1.5, 1.2, 0.5, 0.9, [0, 0, 1, 1], [9])
    out = _dedupe_safety([a, b, c, road])
    assert sorted(p.type for p in out) == ["cut_in", "pothole", "vru_near_path"]
    cut = next(p for p in out if p.type == "cut_in")
    assert cut.t_start == 1.0 and cut.t_end == 2.0 and cut.severity == 0.7
    assert cut.evidence["also"][0]["type"] == "forward_collision_risk"


def test_hard_braking_from_telemetry_is_linked_to_visual_context():
    fr = frames(n=20, users=car_ttc)  # 0..3.8 s, collision risk at 0-0.4 s
    track = parse_track(b"t,lat,lon,speed_kmh\n0,41.3,69.2,50\n1,41.3001,69.2,50\n2,41.3002,69.2,30\n3,41.3003,69.2,10\n4,41.3003,69.2,10\n")
    props = EventMiner.propose(fr, track)
    hb = [p for p in props if p.type == "hard_braking"]
    assert len(hb) == 1
    ev = hb[0].evidence
    assert ev["causal_claim"] == "not_established" and ev["driver_fault"] == "not_determined"
    assert [c["type"] for c in ev["visual_context"]] == ["forward_collision_risk"]
    assert [p.t_peak for p in props] == sorted(p.t_peak for p in props)


def test_kind_of():
    assert kind_of("pothole") == "road" and kind_of("cut_in") == "safety" and kind_of("baseline_drive") == "baseline"


def test_no_frames():
    assert EventMiner.propose([]) == []
