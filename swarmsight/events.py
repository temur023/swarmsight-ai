"""Event fusion, trust and review.

* One pothole seen by five taxis is one event with five observations: a located road observation joins a live event of
  the same type within the type's radius (widened by the observation's position uncertainty), else it starts one.
* Independent corroboration: repeated sightings by one device are not independent; event confidence is a noisy-OR over
  devices, each weighted by that device's reliability (a Beta posterior updated by moderator decisions).
* Lifecycle: candidate -> corroborated (two independent devices) -> verified (a moderator confirmed an observation)
  | rejected (every observation rejected), and expired when not re-observed within the type's lifetime.
* Safety episodes and ordinary-driving samples never become public road events: they stay in their own review queues.
* Every decision is written to the reviews table (who, when, old and new label, note).
"""
from __future__ import annotations

import math
import time

from .store import Store
from .telemetry import haversine_m

# family, merge radius (m), lifetime (s), base severity
EVENT_TYPES = {
    "pothole": ("surface", 12.0, 30 * 86400, 0.9),
    "alligator_crack": ("surface", 15.0, 90 * 86400, 0.6),
    "transverse_crack": ("surface", 15.0, 90 * 86400, 0.35),
    "longitudinal_crack": ("surface", 15.0, 90 * 86400, 0.3),
}
LABELS = {
    "road": list(EVENT_TYPES),
    "safety": ["forward_collision_risk", "vru_near_path", "cut_in", "hard_braking"],
    "baseline": ["baseline_drive"],
}
CORROBORATE_SOURCES = 2
CORROBORATE_CONF = 0.6
ACTIONS = ("confirm", "reject", "correct")


def severity_label(s: float) -> str:
    return "high" if s >= 0.6 else "medium" if s >= 0.35 else "low"


class Fusion:
    def __init__(self, store: Store):
        self.store = store

    # ------------------------------------------------------------------------------------------- fusion
    def attach(self, obs_id: int) -> dict | None:
        o = self.store.one("SELECT * FROM observations WHERE id=?", (obs_id,))
        if not o or o["kind"] != "road" or o["lat"] is None or o["review_status"] == "rejected":
            return None
        _, radius, ttl, _ = EVENT_TYPES.get(o["label"], ("other", 15.0, 86400, 0.5))
        now = time.time()
        best, best_d = None, 1e9
        for e in self.store.query("SELECT * FROM events WHERE type=? AND status NOT IN ('rejected','expired')", (o["label"],)):
            if e["expires_at"] < now:
                continue
            d = haversine_m(o["lat"], o["lon"], e["lat"], e["lon"])
            if d <= max(radius, o["loc_uncertainty_m"] or 10.0) and d < best_d:
                best, best_d = e, d
        if best is None:
            eid = self.store.insert("events", {
                "type": o["label"], "lat": o["lat"], "lon": o["lon"], "radius_m": max(radius, o["loc_uncertainty_m"] or 10.0),
                "status": "candidate", "confidence": 0.0, "severity": o["severity"], "first_seen": o["observed_at"],
                "last_seen": o["observed_at"], "expires_at": o["observed_at"] + ttl, "evidence_obs": obs_id,
                "validity_reason": "one observation", "history": [{"t": now, "action": "created", "by": "fusion",
                                                                   "note": f"first observation #{obs_id}"}]})
        else:
            eid = best["id"]
            self._log(eid, "merged", "fusion", f"observation #{obs_id} at {best_d:.0f} m")
        self.store.update("observations", obs_id, {"event_id": eid})
        return self.refresh(eid)

    def _log(self, eid: int, action: str, by: str, note: str = ""):
        e = self.store.one("SELECT history FROM events WHERE id=?", (eid,))
        self.store.update("events", eid, {"history": e["history"] + [{"t": time.time(), "action": action, "by": by, "note": note}]})

    def refresh(self, eid: int) -> dict:
        e = self.store.one("SELECT * FROM events WHERE id=?", (eid,))
        obs = self.store.query("SELECT * FROM observations WHERE event_id=? AND review_status!='rejected'", (eid,))
        all_obs = self.store.query("SELECT id FROM observations WHERE event_id=?", (eid,))
        best: dict[str, float] = {}
        for o in obs:
            best[o["device_id"]] = max(best.get(o["device_id"], 0.0), o["conf"])
        p_none = 1.0
        for dev, c in best.items():
            p_none *= 1.0 - c * self.store.reliability(dev)
        conf, n_src = (1.0 - p_none) if best else 0.0, len(best)
        if obs:
            w = [o["conf"] / max(o["loc_uncertainty_m"] or 10.0, 1.0) ** 2 for o in obs]  # inverse-variance weights
            lat = sum(o["lat"] * wi for o, wi in zip(obs, w)) / sum(w)
            lon = sum(o["lon"] * wi for o, wi in zip(obs, w)) / sum(w)
            sigma = 1.0 / math.sqrt(sum(1.0 / max(o["loc_uncertainty_m"] or 10.0, 1.0) ** 2 for o in obs))
        else:
            lat, lon, sigma = e["lat"], e["lon"], e["radius_m"]
        reviewed = [o for o in obs if o["review_status"] in ("confirmed", "corrected")]
        if not obs:
            status, why = (("rejected", "every observation rejected by a moderator") if all_obs else
                           ("expired", "no observations left: moved to another event by a moderator"))
        elif reviewed:
            status, why = "verified", f"confirmed by a moderator; {n_src} device(s)"
        elif n_src >= CORROBORATE_SOURCES and conf >= CORROBORATE_CONF:
            status, why = "corroborated", f"{n_src} independent devices, confidence {conf:.2f}"
        else:
            status, why = "candidate", f"{n_src} device(s), confidence {conf:.2f}"
        ttl = EVENT_TYPES.get(e["type"], ("", 0, 86400, 0))[2]
        last_seen = max([o["observed_at"] for o in obs] or [e["last_seen"]])
        ev = max(obs, key=lambda o: o["conf"] * (0.5 + o["severity"]))["id"] if obs else e["evidence_obs"]
        upd = {"lat": lat, "lon": lon, "status": status, "confidence": round(conf, 4), "n_obs": len(obs), "n_sources": n_src,
               "last_seen": last_seen, "expires_at": last_seen + ttl, "severity": max([o["severity"] for o in obs] or [e["severity"]]),
               "evidence_obs": ev, "radius_m": round(max(sigma, 3.0), 1), "validity_reason": why}
        self.store.update("events", eid, upd)
        if status != e["status"]:
            self._log(eid, status, "fusion", why)
        return self.store.one("SELECT * FROM events WHERE id=?", (eid,))

    # ------------------------------------------------------------------------------------------- review
    def review(self, obs_id: int, action: str, reviewer: str = "moderator", note: str = "", label: str | None = None) -> dict:
        if action not in ACTIONS:
            raise ValueError(f"action must be one of {', '.join(ACTIONS)}")
        o = self.store.one("SELECT * FROM observations WHERE id=?", (obs_id,))
        if o is None:
            raise KeyError(obs_id)
        new_label = o["label"]
        if action == "correct":
            if label not in sum(LABELS.values(), []):
                raise ValueError(f"unknown label {label!r}")
            new_label = label
        status = {"confirm": "confirmed", "reject": "rejected", "correct": "corrected"}[action]
        new_kind = next(k for k, v in LABELS.items() if new_label in v)
        self.store.insert("reviews", {"observation_id": obs_id, "event_id": o["event_id"], "reviewer": reviewer[:64],
                                      "action": action, "old_label": o["label"], "new_label": new_label, "note": note[:500],
                                      "t": time.time()})
        old_event = o["event_id"]
        self.store.update("observations", obs_id, {"review_status": status, "label": new_label, "kind": new_kind,
                                                   "event_id": None if (action == "correct" and new_label != o["label"]) or new_kind != "road" else old_event})
        # device reliability: a confirmed report raises it, a rejected one lowers it, a corrected type counts half
        self.store.credit(o["device_id"], d_alpha={"confirm": 1.0, "correct": 0.5, "reject": 0.0}[action],
                          d_beta={"confirm": 0.0, "correct": 0.5, "reject": 1.0}[action])
        if old_event:
            change = f": {o['label']} -> {new_label}" if new_label != o["label"] else ""
            self._log(old_event, f"review:{action}", reviewer, f"observation #{obs_id}{change}. {note}".strip().rstrip("."))
            self.refresh(old_event)
        cur = self.store.one("SELECT * FROM observations WHERE id=?", (obs_id,))
        if cur["kind"] == "road" and cur["event_id"] is None and action != "reject":
            self.attach(obs_id)
        return self.store.one("SELECT * FROM observations WHERE id=?", (obs_id,))

    def locate(self, obs_id: int, lat: float, lon: float, uncertainty_m: float, reviewer: str = "moderator") -> dict:
        """Manual geotag by a moderator (a video without GPS): recorded as such, never presented as GPS."""
        o = self.store.one("SELECT * FROM observations WHERE id=?", (obs_id,))
        if o is None:
            raise KeyError(obs_id)
        if not (-90 <= lat <= 90 and -180 <= lon <= 180):
            raise ValueError("invalid coordinates")
        self.store.update("observations", obs_id, {"lat": lat, "lon": lon, "loc_source": "manual",
                                                   "loc_uncertainty_m": float(max(3.0, min(uncertainty_m, 500.0)))})
        self.store.insert("reviews", {"observation_id": obs_id, "event_id": o["event_id"], "reviewer": reviewer[:64],
                                      "action": "locate", "old_label": o["label"], "new_label": o["label"],
                                      "note": f"{lat:.6f},{lon:.6f} ±{uncertainty_m:.0f} m", "t": time.time()})
        if o["event_id"]:
            self.store.update("observations", obs_id, {"event_id": None})
            self.refresh(o["event_id"])
        self.attach(obs_id)
        return self.store.one("SELECT * FROM observations WHERE id=?", (obs_id,))

    def expire(self) -> int:
        now = time.time()
        rows = self.store.query("SELECT id FROM events WHERE status IN ('candidate','corroborated','verified') AND expires_at < ?", (now,))
        for e in rows:
            self.store.update("events", e["id"], {"status": "expired", "validity_reason": "not re-observed within its lifetime"})
            self._log(e["id"], "expired", "fusion", "not re-observed within its lifetime")
        return len(rows)

    # ------------------------------------------------------------------------------------------- partner feeds
    def events(self, statuses=("verified",), bbox=None) -> list[dict]:
        self.expire()
        rows = self.store.query(f"SELECT * FROM events WHERE status IN ({','.join('?' * len(statuses))}) ORDER BY last_seen DESC",
                                tuple(statuses))
        if bbox:
            rows = [e for e in rows if bbox[0] <= e["lon"] <= bbox[2] and bbox[1] <= e["lat"] <= bbox[3]]
        return rows

    def geojson(self, statuses=("verified",), bbox=None) -> dict:
        """Partner feed: no device identities, no tracks, no clips of people; evidence on request."""
        return {"type": "FeatureCollection", "features": [{
            "type": "Feature", "geometry": {"type": "Point", "coordinates": [round(e["lon"], 6), round(e["lat"], 6)]},
            "properties": {"id": e["id"], "event_type": e["type"], "status": e["status"], "confidence": round(e["confidence"], 3),
                           "severity": severity_label(e["severity"]), "location_uncertainty_m": e["radius_m"],
                           "first_seen": e["first_seen"], "last_seen": e["last_seen"], "expires_at": e["expires_at"],
                           "independent_sources": e["n_sources"], "observations": e["n_obs"], "validity_reason": e["validity_reason"]},
        } for e in self.events(statuses, bbox)]}

    def cifs(self) -> dict:
        """Verified hazards in a CIFS-style JSON (the incident format Waze for Cities ingests). Not a certified feed."""
        sub = {"pothole": "HAZARD_ON_ROAD_POT_HOLE"}
        iso = lambda t: time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(t))  # noqa: E731
        return {"incidents": [{
            "id": f"swarmsight-{e['id']}", "type": "HAZARD", "subtype": sub.get(e["type"], "HAZARD_ON_ROAD"),
            "polyline": f"{e['lat']:.6f} {e['lon']:.6f}", "direction": "BOTH_DIRECTIONS",
            "description": f"{e['type'].replace('_', ' ')} · verified · {e['n_sources']} source(s)",
            "starttime": iso(e["first_seen"]), "endtime": iso(e["expires_at"]),
        } for e in self.events(("verified",))]}
