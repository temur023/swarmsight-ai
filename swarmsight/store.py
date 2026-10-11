"""SQLite persistence.

devices        a camera / phone in a fleet; reliability (Beta posterior) learnt from moderator decisions
trips          one uploaded drive: video facts, telemetry source, rights scope, data reduction, timings
telemetry      the trip's GPS track (internal only, never in the partner API)
clips          anonymised clip segments with key frames and model pre-annotations
observations   mined event candidates (one per proposal): type, time interval, clip, location, review state, data value
events         unique road events after fusion of observations (map and partner API)
reviews        audit log of every moderator decision
dataset_exports  versioned DataMine exports
"""
from __future__ import annotations

import json
import os
import sqlite3
import threading
import time
from pathlib import Path

SCHEMA = """
CREATE TABLE IF NOT EXISTS devices (
    id TEXT PRIMARY KEY, kind TEXT NOT NULL DEFAULT 'phone', fleet TEXT,
    alpha REAL NOT NULL DEFAULT 2.0, beta REAL NOT NULL DEFAULT 1.0, created_at REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS trips (
    id TEXT PRIMARY KEY, device_id TEXT NOT NULL, filename TEXT, created_at REAL NOT NULL, status TEXT NOT NULL,
    rights_scope TEXT NOT NULL, gps_source TEXT, duration_s REAL, analysed_s REAL, kept_s REAL, n_events INTEGER,
    info TEXT, perf TEXT, reduction TEXT, road_users TEXT, error TEXT
);
CREATE TABLE IF NOT EXISTS telemetry (
    trip_id TEXT NOT NULL, t REAL NOT NULL, lat REAL NOT NULL, lon REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS clips (
    id TEXT PRIMARY KEY, trip_id TEXT NOT NULL, t0 REAL NOT NULL, t1 REAL NOT NULL, file TEXT, size TEXT, keyframes TEXT
);
CREATE TABLE IF NOT EXISTS observations (
    id INTEGER PRIMARY KEY AUTOINCREMENT, trip_id TEXT NOT NULL, device_id TEXT NOT NULL,
    kind TEXT NOT NULL, type TEXT NOT NULL, label TEXT NOT NULL,
    t_start REAL, t_end REAL, t_peak REAL, conf REAL, uncertainty REAL, severity REAL,
    bbox TEXT, frame_size TEXT, evidence TEXT, clip_id TEXT, clip_offset_s REAL, thumb TEXT,
    lat REAL, lon REAL, loc_source TEXT, loc_uncertainty_m REAL,
    review_status TEXT NOT NULL, event_id INTEGER,
    quality REAL, data_value REAL, value_parts TEXT, embedding TEXT,
    model_version TEXT, observed_at REAL NOT NULL, created_at REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS events (
    id INTEGER PRIMARY KEY AUTOINCREMENT, type TEXT NOT NULL, lat REAL NOT NULL, lon REAL NOT NULL,
    radius_m REAL NOT NULL, status TEXT NOT NULL, confidence REAL NOT NULL, severity REAL NOT NULL,
    first_seen REAL NOT NULL, last_seen REAL NOT NULL, expires_at REAL NOT NULL,
    n_obs INTEGER NOT NULL DEFAULT 0, n_sources INTEGER NOT NULL DEFAULT 0, evidence_obs INTEGER,
    validity_reason TEXT, history TEXT NOT NULL DEFAULT '[]'
);
CREATE TABLE IF NOT EXISTS reviews (
    id INTEGER PRIMARY KEY AUTOINCREMENT, observation_id INTEGER, event_id INTEGER, reviewer TEXT NOT NULL,
    action TEXT NOT NULL, old_label TEXT, new_label TEXT, note TEXT, t REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS dataset_exports (
    version TEXT PRIMARY KEY, created_at REAL NOT NULL, n_samples INTEGER NOT NULL, summary TEXT NOT NULL, file TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_obs_trip ON observations(trip_id);
CREATE INDEX IF NOT EXISTS idx_obs_review ON observations(review_status, kind);
CREATE INDEX IF NOT EXISTS idx_obs_event ON observations(event_id);
CREATE INDEX IF NOT EXISTS idx_tel_trip ON telemetry(trip_id);
"""

JSON_COLS = {"info", "perf", "reduction", "road_users", "size", "keyframes", "bbox", "frame_size", "evidence",
             "value_parts", "embedding", "history", "summary"}


def _row(r: sqlite3.Row) -> dict:
    d = dict(r)
    for k in JSON_COLS & d.keys():
        if isinstance(d[k], str):
            d[k] = json.loads(d[k])
    return d


class Store:
    def __init__(self, path: str | Path | None = None):
        path = str(path or os.environ.get("SWARMSIGHT_DB", "runtime/swarmsight.db"))
        if path != ":memory:":
            Path(path).parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(path, check_same_thread=False)
        self.conn.row_factory = sqlite3.Row
        self.conn.executescript(SCHEMA)
        self.lock = threading.RLock()

    def backup_to(self, path: str | Path):
        """A consistent copy of the database (SQLite online backup), written atomically."""
        path = Path(path)
        tmp = path.with_suffix(".tmp")
        dst = sqlite3.connect(str(tmp))
        with self.lock:
            self.conn.backup(dst)
        dst.close()
        tmp.replace(path)

    def execute(self, sql: str, args=()):
        with self.lock:
            cur = self.conn.execute(sql, [json.dumps(a) if isinstance(a, (dict, list)) else a for a in args])
            self.conn.commit()
            return cur

    def query(self, sql: str, args=()) -> list[dict]:
        with self.lock:
            return [_row(r) for r in self.conn.execute(sql, args).fetchall()]

    def one(self, sql: str, args=()) -> dict | None:
        rows = self.query(sql, args)
        return rows[0] if rows else None

    def insert(self, table: str, row: dict) -> int:
        cols = list(row)
        cur = self.execute(f"INSERT INTO {table}({','.join(cols)}) VALUES ({','.join('?' * len(cols))})", [row[c] for c in cols])
        return cur.lastrowid

    def update(self, table: str, key, row: dict, key_col: str = "id"):
        cols = list(row)
        self.execute(f"UPDATE {table} SET {','.join(f'{c}=?' for c in cols)} WHERE {key_col}=?", [row[c] for c in cols] + [key])

    # --- devices --------------------------------------------------------------------------------------
    def device(self, device_id: str, kind: str = "phone") -> dict:
        d = self.one("SELECT * FROM devices WHERE id=?", (device_id,))
        if d:
            return d
        self.execute("INSERT OR IGNORE INTO devices(id, kind, created_at) VALUES (?,?,?)", (device_id, kind, time.time()))
        return self.one("SELECT * FROM devices WHERE id=?", (device_id,))

    def reliability(self, device_id: str) -> float:
        d = self.device(device_id)
        return d["alpha"] / (d["alpha"] + d["beta"])

    def credit(self, device_id: str, d_alpha: float = 0.0, d_beta: float = 0.0):
        self.device(device_id)
        self.execute("UPDATE devices SET alpha=alpha+?, beta=beta+? WHERE id=?", (d_alpha, d_beta, device_id))
