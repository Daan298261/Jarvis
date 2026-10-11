"""Poll coding write then enqueue UFO2 once coding completes or times out."""
from __future__ import annotations

import json
import sqlite3
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DB = ROOT / "data" / "jarvis.db"
FILE = ROOT / "Desktop" / "jarvis-coding-live.py"
PENDING = ROOT / "data" / "queue" / "pending"
B = "http://127.0.0.1:4780"


def health(timeout: float = 8.0) -> bool:
    try:
        with urllib.request.urlopen(B + "/api/health", timeout=timeout) as resp:
            return resp.status == 200
    except Exception:
        return False


def snap_coding() -> tuple:
    con = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
    row = con.execute(
        "select id,status,stage,current_tool,tool_call_count,substr(result,1,100) "
        "from tasks where prompt like '%jarvis-coding-live%' "
        "order by created_at desc limit 1"
    ).fetchone()
    con.close()
    return row


def main() -> None:
    deadline = time.time() + 180
    while time.time() < deadline:
        pending = list(PENDING.glob("coding_*.json"))
        exists = FILE.exists()
        row = snap_coding()
        print(
            time.strftime("%H:%M:%S"),
            "pending=",
            len(pending),
            "file=",
            exists,
            "task=",
            row,
            "health=",
            health(),
            flush=True,
        )
        if exists and row and row[1] == "completed":
            print("CONTENT", FILE.read_text(encoding="utf-8"), flush=True)
            break
        if exists and row and row[4] and int(row[4]) > 0:
            print("CONTENT", FILE.read_text(encoding="utf-8"), flush=True)
            break
        if not pending and row and row[1] in {"completed", "failed", "cancelled"}:
            break
        time.sleep(6)
    else:
        print("CODING TIMEOUT", flush=True)

    # UFO2 task via queue
    PENDING.mkdir(parents=True, exist_ok=True)
    for old in PENDING.glob("ufo_*.json"):
        old.unlink()
    prompt = (
        "Use the Microsoft UFO2 Windows worker (not native UI Automation alone) "
        "to open Calculator, confirm the window is visible, then stop. "
        "Do not install anything."
    )
    path = PENDING / f"ufo_LIVE-{datetime.now(timezone.utc).strftime('%H%M%S')}.json"
    path.write_text(
        json.dumps(
            {
                "prompt": prompt,
                "autonomy": "autonomous",
                "execution_mode": "fast",
                "enqueued_at": datetime.now(timezone.utc).isoformat(),
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    print("queued", path.name, flush=True)

    ufo_deadline = time.time() + 240
    tid = None
    while time.time() < ufo_deadline:
        con = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
        row = con.execute(
            "select id,status,stage,current_tool,exposed_tools,substr(result,1,200) "
            "from tasks where prompt like '%UFO2%' order by created_at desc limit 1"
        ).fetchone()
        con.close()
        print(time.strftime("%H:%M:%S"), "ufo=", row, flush=True)
        if row:
            tid = row[0]
            if row[1] in {"completed", "failed", "cancelled"}:
                print("UFO_DONE", row, flush=True)
                return
        time.sleep(8)
    print("UFO TIMEOUT", tid, flush=True)


if __name__ == "__main__":
    main()
