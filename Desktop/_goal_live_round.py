"""Coding agent write + UFO2 live round with unique markers."""
from __future__ import annotations

import json
import sqlite3
import time
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DB = ROOT / "data" / "jarvis.db"
PENDING = ROOT / "data" / "queue" / "pending"
FILE = ROOT / "Desktop" / "jarvis-coding-live.py"
B = "http://127.0.0.1:4780"
MARKER = datetime.now(timezone.utc).strftime("%H%M%S")


def health(timeout: float = 10.0) -> dict | None:
    try:
        with urllib.request.urlopen(B + "/api/health", timeout=timeout) as resp:
            return json.loads(resp.read().decode())
    except Exception as exc:
        print("health_err", exc, flush=True)
        return None


def enqueue(name: str, prompt: str) -> Path:
    PENDING.mkdir(parents=True, exist_ok=True)
    path = PENDING / f"{name}_{MARKER}.json"
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
    return path


def latest_task(needle: str):
    con = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
    row = con.execute(
        "select id,status,stage,current_tool,tool_call_count,exposed_tools,"
        "substr(result,1,220),substr(error,1,160),created_at "
        "from tasks where prompt like ? order by created_at desc limit 1",
        (f"%{needle}%",),
    ).fetchone()
    con.close()
    return row


def wait_task(needle: str, seconds: int = 240):
    deadline = time.time() + seconds
    seen = None
    while time.time() < deadline:
        row = latest_task(needle)
        h = health()
        print(
            time.strftime("%H:%M:%S"),
            "task=",
            row,
            "elev=",
            (h or {}).get("elevated"),
            "file=",
            FILE.exists(),
            flush=True,
        )
        if row:
            seen = row
            if row[1] in {"completed", "failed", "cancelled"}:
                return row
        time.sleep(6)
    return seen


def main() -> None:
    for old in PENDING.glob("*.json"):
        old.unlink()
    if FILE.exists():
        FILE.unlink()
        print("removed proof file", flush=True)

    print("health0", health(), flush=True)
    coding_prompt = (
        f'write "print(\'hello from elevated coding live probe {MARKER}\')" '
        f"to Desktop/jarvis-coding-live.py"
    )
    enqueue("coding_LIVE", coding_prompt)
    coding = wait_task(MARKER, 240)
    print("CODING_DONE", coding, flush=True)
    print("FILE", FILE.exists(), FILE.read_text(encoding="utf-8") if FILE.exists() else None, flush=True)

    ufo_marker = f"UFO2CALC-{MARKER}"
    ufo_prompt = (
        f"[{ufo_marker}] Use the Microsoft UFO2 Windows worker "
        "(not native UI Automation alone) to open Calculator, confirm the window "
        "is visible, then stop. Do not install anything."
    )
    enqueue("ufo_LIVE", ufo_prompt)
    ufo = wait_task(ufo_marker, 300)
    print("UFO_DONE", ufo, flush=True)


if __name__ == "__main__":
    main()
