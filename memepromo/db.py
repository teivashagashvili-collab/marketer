"""SQLite storage for campaigns and the post log."""
from __future__ import annotations

import json
import sqlite3
import time
from contextlib import contextmanager

SCHEMA = """
CREATE TABLE IF NOT EXISTS campaigns (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    address TEXT NOT NULL,
    symbol TEXT DEFAULT '',
    channels TEXT NOT NULL,
    interval_minutes INTEGER NOT NULL,
    dry_run INTEGER NOT NULL,
    status TEXT NOT NULL DEFAULT 'running',
    snapshot TEXT,
    created_at REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS posts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    campaign_id INTEGER NOT NULL REFERENCES campaigns(id),
    channel TEXT NOT NULL,
    occasion TEXT NOT NULL,
    text TEXT NOT NULL,
    status TEXT NOT NULL,
    result TEXT DEFAULT '',
    created_at REAL NOT NULL
);
"""


class DB:
    def __init__(self, path: str):
        self.path = path
        with self._conn() as c:
            c.executescript(SCHEMA)

    @contextmanager
    def _conn(self):
        conn = sqlite3.connect(self.path)
        conn.row_factory = sqlite3.Row
        try:
            yield conn
            conn.commit()
        finally:
            conn.close()

    def create_campaign(self, address: str, symbol: str, channels: list[str], interval_minutes: int, dry_run: bool) -> int:
        with self._conn() as c:
            cur = c.execute(
                "INSERT INTO campaigns (address, symbol, channels, interval_minutes, dry_run, created_at) VALUES (?,?,?,?,?,?)",
                (address, symbol, json.dumps(channels), interval_minutes, int(dry_run), time.time()),
            )
            return cur.lastrowid

    def campaign(self, cid: int) -> dict | None:
        with self._conn() as c:
            row = c.execute("SELECT * FROM campaigns WHERE id=?", (cid,)).fetchone()
        return _campaign(row) if row else None

    def campaigns(self, status: str | None = None) -> list[dict]:
        with self._conn() as c:
            if status:
                rows = c.execute("SELECT * FROM campaigns WHERE status=? ORDER BY id DESC", (status,)).fetchall()
            else:
                rows = c.execute("SELECT * FROM campaigns ORDER BY id DESC").fetchall()
        return [_campaign(r) for r in rows]

    def set_status(self, cid: int, status: str) -> None:
        with self._conn() as c:
            c.execute("UPDATE campaigns SET status=? WHERE id=?", (status, cid))

    def save_snapshot(self, cid: int, snapshot: dict, symbol: str) -> None:
        with self._conn() as c:
            c.execute("UPDATE campaigns SET snapshot=?, symbol=? WHERE id=?", (json.dumps(snapshot), symbol, cid))

    def log_post(self, cid: int, channel: str, occasion: str, text: str, status: str, result: str = "") -> None:
        with self._conn() as c:
            c.execute(
                "INSERT INTO posts (campaign_id, channel, occasion, text, status, result, created_at) VALUES (?,?,?,?,?,?,?)",
                (cid, channel, occasion, text, status, result, time.time()),
            )

    def posts(self, cid: int | None = None, limit: int = 100) -> list[dict]:
        with self._conn() as c:
            if cid is None:
                rows = c.execute("SELECT * FROM posts ORDER BY id DESC LIMIT ?", (limit,)).fetchall()
            else:
                rows = c.execute("SELECT * FROM posts WHERE campaign_id=? ORDER BY id DESC LIMIT ?", (cid, limit)).fetchall()
        return [dict(r) for r in rows]

    def last_post_time(self, cid: int, channel: str) -> float | None:
        with self._conn() as c:
            row = c.execute(
                "SELECT MAX(created_at) FROM posts WHERE campaign_id=? AND channel=? AND status IN ('sent','dry_run')",
                (cid, channel),
            ).fetchone()
        return row[0]

    def posts_since(self, cid: int, channel: str, since: float) -> int:
        with self._conn() as c:
            row = c.execute(
                "SELECT COUNT(*) FROM posts WHERE campaign_id=? AND channel=? AND status IN ('sent','dry_run') AND created_at>=?",
                (cid, channel, since),
            ).fetchone()
        return row[0]


def _campaign(row: sqlite3.Row) -> dict:
    d = dict(row)
    d["channels"] = json.loads(d["channels"])
    d["dry_run"] = bool(d["dry_run"])
    d["snapshot"] = json.loads(d["snapshot"]) if d["snapshot"] else None
    return d
