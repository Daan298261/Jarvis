"""Poll DB/queue for coding live proof without blocking on /api/health."""
from __future__ import annotations

import sqlite3
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DB = ROOT / "data" / "jarvis.db"
REPO_FILE = ROOT / "Desktop" / "jarvis-coding-live.py"
USER_FILE = Path.home() / "Desktop" / "jarvis-coding-live.py"
PENDING = ROOT / "data" / "queue" / "pending"
PROCESSED = ROOT / "data" / "queue" / "processed"


def snap() -> None:
    pending = list(PENDING.glob("coding_*.json")) if PENDING.exists() else []
    processed = sorted(PROCESSED.glob("*CODINGLIVE*"), key=lambda p: p.stat().st_mtime, reverse=True)[:3]
    con = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
    row = con.execute(
        "select id,status,substr(result,1,80),substr(error,1,80),updated_at "
        "from tasks where prompt like '%jarvis-coding-live%' "
        "and created_at > datetime('now', '-15 minutes') "
        "order by created_at desc limit 1"
    ).fetchone()
    con.close()
    print(
        time.strftime("%H:%M:%S"),
        "pending=",
        len(pending),
        "repo=",
        REPO_FILE.exists(),
        "user=",
        USER_FILE.exists(),
        "task=",
        row,
        "proc=",
        [p.name for p in processed],
        flush=True,
    )


def main() -> None:
    deadline = time.time() + 240
    while time.time() < deadline:
        snap()
        if REPO_FILE.exists() or USER_FILE.exists():
            target = REPO_FILE if REPO_FILE.exists() else USER_FILE
            print("CONTENT:", target.read_text(encoding="utf-8"), flush=True)
            return
        if row_done():
            return
        time.sleep(8)
    snap()
    print("TIMEOUT", flush=True)


def row_done() -> bool:
    con = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
    row = con.execute(
        "select status from tasks where prompt like '%jarvis-coding-live%' "
        "and status not in ('cancelled') "
        "order by created_at desc limit 1"
    ).fetchone()
    con.close()
    return bool(row and row[0] in {"completed", "failed"})


if __name__ == "__main__":
    main()
