"""Trip telemetry: a GPS track (GPX or CSV) on the video's time axis.

CSV columns (header required): t (seconds from the start of the video) or time (ISO 8601), lat, lon, and optionally
speed_kmh or speed_ms, and accel_long_ms2 (longitudinal acceleration, negative = braking, from an IMU).
GPX: track points with <time>; t = 0 is the first point, shifted by `offset_s` (the track time at the video's start).

Nothing is invented: outside the track (beyond `GAP_S` from the nearest point) a position is unknown.
"""
from __future__ import annotations

import csv
import io
import math
import re
from dataclasses import dataclass
from datetime import datetime

import numpy as np

GAP_S = 2.0
HARD_BRAKE_MS2 = 3.0  # deceleration a fleet safety team would review (about 0.3 g)
MAX_PLAUSIBLE_MS2 = 9.5  # beyond about 1 g a car cannot brake: such a value is a GPS glitch, not an event
MIN_SPEED_KMH = 15.0


def haversine_m(lat1, lon1, lat2, lon2) -> float:
    R = 6371000.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp, dl = p2 - p1, math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * R * math.asin(math.sqrt(min(1.0, a)))


def _iso(s: str) -> float:
    return datetime.fromisoformat(s.strip().replace("Z", "+00:00")).timestamp()


@dataclass
class Track:
    t: np.ndarray
    lat: np.ndarray
    lon: np.ndarray
    speed: np.ndarray  # m/s
    accel: np.ndarray | None  # m/s2 from an IMU, if given
    source: str
    accuracy_m: float = 10.0

    def __len__(self) -> int:
        return len(self.t)

    def at(self, t: float) -> dict | None:
        if not len(self) or t < self.t[0] - GAP_S or t > self.t[-1] + GAP_S:
            return None
        i = int(np.searchsorted(self.t, t))
        if 0 < i < len(self) and self.t[i] - self.t[i - 1] > 2 * GAP_S + 1 and min(t - self.t[i - 1], self.t[i] - t) > GAP_S:
            # a long gap between fixes: interpolate only if the car hardly moved (standing at a light), else unknown
            if haversine_m(self.lat[i - 1], self.lon[i - 1], self.lat[i], self.lon[i]) > 30.0:
                return None
        tt = float(np.clip(t, self.t[0], self.t[-1]))
        lat = float(np.interp(tt, self.t, self.lat))
        lon = float(np.interp(tt, self.t, self.lon))
        v = float(np.interp(tt, self.t, self.speed))
        # position error: GPS accuracy plus distance driven during an assumed 0.5 s video-to-GPS sync error
        return {"lat": lat, "lon": lon, "speed_ms": v, "uncertainty_m": round(self.accuracy_m + 0.5 * v, 1)}

    def path(self, step_s: float = 1.0) -> list[list[float]]:
        out, last = [], -1e9
        for t, la, lo in zip(self.t, self.lat, self.lon):
            if t - last >= step_s:
                out.append([round(float(t), 2), round(float(la), 6), round(float(lo), 6)])
                last = t
        return out

    def braking(self, threshold: float = HARD_BRAKE_MS2) -> list[dict]:
        """Intervals where the car decelerates harder than `threshold` (IMU if present, else GPS speed)."""
        if len(self) < 3:
            return []
        if self.accel is not None:
            dec, ts = -self.accel, self.t
        else:
            ts = (self.t[1:] + self.t[:-1]) / 2
            dec = -(np.diff(self.speed) / np.maximum(np.diff(self.t), 1e-3))
        out, cur = [], None
        for t, d in zip(ts, dec):
            if d >= threshold:
                if cur is None:
                    cur = {"t_start": float(t), "t_end": float(t), "t_peak": float(t), "peak_decel_ms2": float(d)}
                cur["t_end"] = float(t)
                if d > cur["peak_decel_ms2"]:
                    cur.update(t_peak=float(t), peak_decel_ms2=float(d))
            elif cur is not None:
                out.append(cur)
                cur = None
        if cur is not None:
            out.append(cur)
        out = [b for b in out if b["peak_decel_ms2"] <= MAX_PLAUSIBLE_MS2
               and float(np.interp(b["t_start"] - 1.0, self.t, self.speed)) * 3.6 >= MIN_SPEED_KMH]
        for b in out:
            b["speed_before_kmh"] = round(float(np.interp(b["t_start"] - 1.0, self.t, self.speed)) * 3.6, 1)
            b["speed_after_kmh"] = round(float(np.interp(b["t_end"] + 1.0, self.t, self.speed)) * 3.6, 1)
            b["peak_decel_ms2"] = round(b["peak_decel_ms2"], 2)
            b["signal"] = "imu" if self.accel is not None else "gps_speed"
        return out


def _finish(t, lat, lon, speed, accel, source) -> Track:
    t, lat, lon = np.asarray(t, float), np.asarray(lat, float), np.asarray(lon, float)
    order = np.argsort(t, kind="stable")
    t, lat, lon = t[order], lat[order], lon[order]
    ok = np.isfinite(t) & np.isfinite(lat) & np.isfinite(lon) & (np.abs(lat) <= 90) & (np.abs(lon) <= 180)
    if speed is not None:
        speed = np.asarray(speed, float)[order]
        ok &= np.isfinite(speed)
    if accel is not None:
        accel = np.asarray(accel, float)[order]
    t, lat, lon = t[ok], lat[ok], lon[ok]
    speed = speed[ok] if speed is not None else None
    accel = accel[ok] if accel is not None else None
    if len(t) < 2:
        raise ValueError("the track needs at least two valid points")
    if speed is None:  # from consecutive positions, lightly smoothed
        d = np.array([haversine_m(lat[i], lon[i], lat[i + 1], lon[i + 1]) for i in range(len(t) - 1)])
        v = d / np.maximum(np.diff(t), 1e-3)
        speed = np.r_[v[0], (v[1:] + v[:-1]) / 2, v[-1]] if len(v) > 1 else np.r_[v, v]
        if len(speed) >= 5:  # GPS positions are noisy: a 5-point running median before any braking test
            pad = np.r_[speed[:2], speed, speed[-2:]]
            speed = np.array([np.median(pad[i:i + 5]) for i in range(len(speed))])
    # drop GPS jumps (faster than 70 m/s between points)
    return Track(t, lat, lon, np.clip(speed, 0, 70), accel, source)


def parse_track(data: bytes, filename: str = "", offset_s: float = 0.0) -> Track:
    text = data.decode("utf-8-sig", errors="replace")
    if filename.lower().endswith(".gpx") or "<gpx" in text[:500]:
        pts = re.findall(r"<trkpt[^>]*lat=\"([-0-9.]+)\"[^>]*lon=\"([-0-9.]+)\"[^>]*>(.*?)</trkpt>", text, re.S)
        pts += [(la, lo, body) for lo, la, body in re.findall(r"<trkpt[^>]*lon=\"([-0-9.]+)\"[^>]*lat=\"([-0-9.]+)\"[^>]*>(.*?)</trkpt>", text, re.S)]
        rows = []
        for la, lo, body in pts:
            m = re.search(r"<time>([^<]+)</time>", body)
            if m:
                sp = re.search(r"<(?:\w+:)?speed>([-0-9.]+)</", body)
                rows.append((_iso(m.group(1)), float(la), float(lo), float(sp.group(1)) if sp else None))
        if len(rows) < 2:
            raise ValueError("GPX: no track points with <time>")
        rows.sort()
        t0 = rows[0][0]
        speed = [r[3] for r in rows] if all(r[3] is not None for r in rows) else None
        return _finish([r[0] - t0 - offset_s for r in rows], [r[1] for r in rows], [r[2] for r in rows], speed, None, "gpx")
    rd = csv.DictReader(io.StringIO(text))
    if not rd.fieldnames:
        raise ValueError("CSV: header row required (t,lat,lon[,speed_kmh][,accel_long_ms2])")
    cols = {c.strip().lower(): c for c in rd.fieldnames}
    if "lat" not in cols or "lon" not in cols or not ({"t", "time", "timestamp"} & cols.keys()):
        raise ValueError("CSV: columns t (or time), lat, lon are required")
    rows = list(rd)
    if "t" in cols:
        t = [float(r[cols["t"]]) - offset_s for r in rows]
    else:
        tc = cols.get("time") or cols["timestamp"]
        raw = [_iso(r[tc]) for r in rows]
        t = [x - raw[0] - offset_s for x in raw]
    speed = None
    if "speed_kmh" in cols:
        speed = [float(r[cols["speed_kmh"]]) / 3.6 for r in rows]
    elif "speed_ms" in cols:
        speed = [float(r[cols["speed_ms"]]) for r in rows]
    accel = [float(r[cols["accel_long_ms2"]]) for r in rows] if "accel_long_ms2" in cols else None
    return _finish(t, [float(r[cols["lat"]]) for r in rows], [float(r[cols["lon"]]) for r in rows], speed, accel, "csv")


def single_point(lat: float, lon: float, accuracy_m: float, duration_s: float) -> Track:
    """One position for the whole video (a pin or the device's location): every event gets it, with a wider radius."""
    return Track(np.array([0.0, max(duration_s, 0.1)]), np.array([lat, lat]), np.array([lon, lon]), np.zeros(2), None,
                 "single_point", accuracy_m)
