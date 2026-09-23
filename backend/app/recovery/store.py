from __future__ import annotations

import sqlite3
import threading
from pathlib import Path

from ..config import data_dir

_lock = threading.RLock()
_DB_PATH: Path | None = None


def recovery_db_path() -> Path:
    global _DB_PATH
    if _DB_PATH is None:
        root = data_dir() / "recovery"
        root.mkdir(parents=True, exist_ok=True)
        _DB_PATH = root / "journal.db"
    return _DB_PATH


def configure_recovery_db(path: Path) -> None:
    global _DB_PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    _DB_PATH = path


def reset_recovery_db() -> None:
    """Test helper: remove recovery database and re-init schema."""
    global _DB_PATH
    with _lock:
        path = recovery_db_path()
        if path.exists():
            path.unlink()
        _DB_PATH = path.parent / "journal.db"
        _init_schema(connect())


def connect() -> sqlite3.Connection:
    with _lock:
        conn = sqlite3.connect(str(recovery_db_path()), timeout=30, isolation_level=None)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA busy_timeout=30000")
        _init_schema(conn)
        return conn


def _init_schema(conn: sqlite3.Connection) -> None:
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS journal_entries (
            seq INTEGER PRIMARY KEY AUTOINCREMENT,
            created_at TEXT NOT NULL,
            actor TEXT NOT NULL,
            source TEXT NOT NULL DEFAULT 'api',
            resource_class TEXT NOT NULL,
            resource_id TEXT NOT NULL,
            operation TEXT NOT NULL,
            schema_version INTEGER NOT NULL,
            correlation_id TEXT,
            payload_json TEXT NOT NULL,
            integrity_hash TEXT NOT NULL,
            chain_hash TEXT NOT NULL,
            replay_safe INTEGER NOT NULL DEFAULT 0,
            commit_state TEXT NOT NULL DEFAULT 'committed',
            risk_tag TEXT
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS checkpoints (
            id TEXT PRIMARY KEY,
            created_at TEXT NOT NULL,
            tag TEXT NOT NULL,
            journal_seq INTEGER NOT NULL,
            snapshot_json TEXT NOT NULL,
            snapshot_hash TEXT NOT NULL,
            verification_json TEXT,
            verified_at TEXT,
            notes TEXT
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS rollback_runs (
            id TEXT PRIMARY KEY,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            phase TEXT NOT NULL,
            terminal_status TEXT,
            target_checkpoint_id TEXT NOT NULL,
            target_seq INTEGER NOT NULL,
            forward_replay INTEGER NOT NULL DEFAULT 0,
            plan_json TEXT,
            evidence_json TEXT,
            stage_log_json TEXT NOT NULL DEFAULT '[]'
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS prune_audit (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            created_at TEXT NOT NULL,
            actor TEXT NOT NULL,
            pruned_through_seq INTEGER NOT NULL,
            retained_checkpoint_id TEXT NOT NULL,
            detail_json TEXT NOT NULL DEFAULT '{}'
        )
        """
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_journal_resource ON journal_entries(resource_class, resource_id)"
    )
    conn.execute("CREATE INDEX IF NOT EXISTS idx_journal_commit ON journal_entries(commit_state)")
