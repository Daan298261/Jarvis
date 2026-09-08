from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from pathlib import Path

from ..config import data_dir


def root() -> Path:
    path = data_dir() / "mobile"
    path.mkdir(parents=True, exist_ok=True)
    return path


@contextmanager
def database():
    """Short atomic transactions; no network/model work under a database lock."""
    conn = sqlite3.connect(root() / "companion.db", timeout=10)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.executescript('''
        CREATE TABLE IF NOT EXISTS records (
            kind TEXT NOT NULL, id TEXT NOT NULL, payload TEXT NOT NULL,
            PRIMARY KEY(kind, id)
        );
        CREATE TABLE IF NOT EXISTS events (
            id INTEGER PRIMARY KEY AUTOINCREMENT, device TEXT NOT NULL,
            kind TEXT NOT NULL, payload TEXT NOT NULL, created REAL NOT NULL
        );
        CREATE INDEX IF NOT EXISTS events_device ON events(device, id);
    ''')
    try:
        conn.execute("BEGIN IMMEDIATE")
        yield conn
        conn.commit()
    except BaseException:
        conn.rollback()
        raise
    finally:
        conn.close()


def get(conn, kind: str, key: str):
    row = conn.execute("SELECT payload FROM records WHERE kind=? AND id=?", (kind, key)).fetchone()
    return json.loads(row[0]) if row else None


def put(conn, kind: str, key: str, value: dict):
    conn.execute("INSERT INTO records VALUES(?,?,?) ON CONFLICT(kind,id) DO UPDATE SET payload=excluded.payload",
                 (kind, key, json.dumps(value, ensure_ascii=False)))


def rows(conn, kind: str) -> list[dict]:
    return [json.loads(row[0]) for row in conn.execute("SELECT payload FROM records WHERE kind=?", (kind,))]
