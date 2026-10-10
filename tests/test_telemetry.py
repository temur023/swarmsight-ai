import numpy as np
import pytest

from swarmsight.telemetry import GAP_S, parse_track, single_point

CSV_T = b"t,lat,lon,speed_kmh\n0,41.3000,69.2000,36\n1,41.3001,69.2000,36\n2,41.3002,69.2000,36\n3,41.3003,69.2000,36\n"


def _speed_csv(speeds_kmh, dt=1.0) -> bytes:
    rows = ["t,lat,lon,speed_kmh"] + [f"{i * dt:g},{41.3 + i * 1e-4:.6f},69.2,{v}" for i, v in enumerate(speeds_kmh)]
    return ("\n".join(rows) + "\n").encode()


def test_csv_with_t_column():
    tr = parse_track(CSV_T, "trip.csv")
    assert tr.source == "csv" and len(tr) == 4
    assert np.allclose(tr.t, [0, 1, 2, 3])
    assert np.allclose(tr.speed, 10.0)  # 36 km/h in m/s
    assert tr.accel is None


def test_csv_offset_shifts_time():
    tr = parse_track(CSV_T, "trip.csv", offset_s=1.0)
    assert np.allclose(tr.t, [-1, 0, 1, 2])


def test_csv_with_iso_time_and_derived_speed():
    data = (b"time,lat,lon\n"
            b"2026-07-16T18:28:00Z,41.3000,69.2000\n"
            b"2026-07-16T18:28:02Z,41.3001,69.2000\n"
            b"2026-07-16T18:28:04+00:00,41.3002,69.2000\n")
    tr = parse_track(data, "trip.csv")
    assert np.allclose(tr.t, [0, 2, 4])
    # 0.0001 deg of latitude is about 11.1 m, every 2 s -> about 5.6 m/s
    assert np.allclose(tr.speed, 5.56, atol=0.1)


def test_gpx_lat_lon_in_any_order():
    gpx = b"""<?xml version="1.0"?><gpx version="1.1"><trk><trkseg>
      <trkpt lat="41.3000" lon="69.2000"><time>2026-07-16T18:28:00Z</time></trkpt>
      <trkpt lon="69.2000" lat="41.3001"><time>2026-07-16T18:28:01Z</time></trkpt>
      <trkpt lat="41.3002" lon="69.2000"><ele>400</ele><time>2026-07-16T18:28:02Z</time></trkpt>
    </trkseg></trk></gpx>"""
    tr = parse_track(gpx, "trip.gpx")
    assert tr.source == "gpx" and len(tr) == 3
    assert np.allclose(tr.t, [0, 1, 2])
    assert np.allclose(tr.lat, [41.3, 41.3001, 41.3002])


def test_gpx_without_time_is_rejected():
    with pytest.raises(ValueError):
        parse_track(b'<gpx><trk><trkseg><trkpt lat="41.3" lon="69.2"></trkpt></trkseg></trk></gpx>', "x.gpx")


@pytest.mark.parametrize("data", [b"", b"foo,bar\n1,2\n", b"t,lat,lon\n0,41.3,69.2\n"])
def test_bad_csv_is_rejected(data):
    with pytest.raises(ValueError):
        parse_track(data, "x.csv")


def test_at_inside_and_outside_the_track():
    tr = parse_track(CSV_T, "trip.csv")
    p = tr.at(1.5)
    assert p is not None and p["lat"] == pytest.approx(41.30015) and p["speed_ms"] == pytest.approx(10.0)
    assert p["uncertainty_m"] > 0
    assert tr.at(-GAP_S - 0.1) is None
    assert tr.at(3 + GAP_S + 0.1) is None
    assert tr.at(3 + GAP_S - 0.1) is not None  # near the end: clamped to the last point


def test_at_inside_a_long_gap_is_unknown_if_the_car_moved():
    data = b"t,lat,lon\n0,41.30,69.2\n1,41.30,69.2\n20,41.31,69.2\n21,41.31,69.2\n"  # 1.1 km in 19 s without fixes
    tr = parse_track(data, "trip.csv")
    assert tr.at(10) is None
    assert tr.at(1.5) is not None and tr.at(19.5) is not None


def test_at_inside_a_long_gap_while_standing_is_known():
    tr = parse_track(b"t,lat,lon\n0,41.30,69.2\n1,41.30,69.2\n20,41.30001,69.2\n21,41.30001,69.2\n", "trip.csv")
    assert tr.at(10) is not None


def test_braking_finds_a_hard_brake():
    # 50 km/h -> 10 km/h in 2 s: about 5.6 m/s2
    tr = parse_track(_speed_csv([50, 50, 50, 50, 50, 30, 10, 10, 10, 10]), "trip.csv")
    br = tr.braking()
    assert len(br) == 1
    b = br[0]
    assert 4.0 <= b["t_start"] <= b["t_peak"] <= b["t_end"] <= 6.0
    assert b["peak_decel_ms2"] == pytest.approx(5.56, abs=0.05)
    assert b["speed_before_kmh"] == pytest.approx(50, abs=1) and b["speed_after_kmh"] == pytest.approx(10, abs=1)
    assert b["signal"] == "gps_speed"


def test_braking_ignores_a_gentle_slowdown():
    tr = parse_track(_speed_csv([50, 48, 46, 44, 42, 40, 38, 36, 34, 32]), "trip.csv")  # 0.56 m/s2
    assert tr.braking() == []


def test_braking_from_imu():
    data = b"t,lat,lon,speed_kmh,accel_long_ms2\n0,41.3,69.2,40,0\n1,41.3001,69.2,40,-0.5\n2,41.3002,69.2,30,-4.5\n3,41.3003,69.2,20,-0.2\n"
    br = parse_track(data, "trip.csv").braking()
    assert len(br) == 1 and br[0]["signal"] == "imu" and br[0]["t_peak"] == 2.0


def test_single_point_covers_the_video():
    tr = single_point(41.3, 69.2, 25.0, 60.0)
    assert tr.source == "single_point"
    p = tr.at(30.0)
    assert p["lat"] == 41.3 and p["uncertainty_m"] == 25.0
    assert tr.braking() == []
