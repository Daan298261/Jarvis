"""Cancel stuck tasks and enqueue a solo UFO2 Calculator live task."""
from __future__ import annotations

import json
import sqlite3
import time
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

con = sqlite3.connect(ROOT / "data" / "jarvis.db")
con.execute(
    "update tasks set status='cancelled', error='operator_cancel', updated_at=? "
    "where status in ('running','queued')",
    (datetime.utcnow().isoformat(),),
)
print("cancelled", con.total_changes)
con.commit()
con.close()

pending = ROOT / "data" / "queue" / "pending"
pending.mkdir(parents=True, exist_ok=True)
for old in pending.glob("*.json"):
    old.unlink()

marker = ROOT / "Desktop" / "_ufo_marker.txt"
marker.write_text("ready", encoding="utf-8")

prompt = (
    "Use the UFO2 Windows UI automation tool to open the Calculator app, "
    "compute 7+5, and write the result as a single number into Desktop/_ufo_marker.txt. "
    "Do not only describe the steps; call the ufo tool."
)
stamp = datetime.now(timezone.utc).strftime("%H%M%S")
path = pending / f"ufo_UFO2CALC-{stamp}.json"
payload = {
    "prompt": prompt,
    "autonomy": "autonomous",
    "execution_mode": "fast",
    "enqueued_at": datetime.now(timezone.utc).isoformat(),
}
path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
print("queued", path.name)

deadline = time.time() + 60
while time.time() < deadline:
    pend = list(pending.glob("*.json"))
    claiming = list((ROOT / "data" / "queue" / "claiming").glob("*.json"))
    processed = sorted(
        (ROOT / "data" / "queue" / "processed").glob("*UFO2*"),
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )[:3]
    print(
        time.strftime("%H:%M:%S"),
        "pending",
        len(pend),
        "claiming",
        len(claiming),
        "processed",
        [p.name for p in processed],
        flush=True,
    )
    if not pend and not claiming:
        break
    time.sleep(5)

con = sqlite3.connect(ROOT / "data" / "jarvis.db")
rows = con.execute(
    "select id,status,stage,substr(prompt,1,70),substr(current_action,1,70),"
    "tool_call_count from tasks order by created_at desc limit 5"
).fetchall()
for r in rows:
    print(r)
con.close()
