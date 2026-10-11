"""Cancel stuck tasks and enqueue simple .py write for coding live proof."""
from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
import sys

sys.path.insert(0, str(ROOT / "backend"))
from app.agent.planning import simple_file_control  # noqa: E402

prompt = 'write "print(\'hello from elevated coding live probe\')" to Desktop/jarvis-coding-live.py'
print("match", simple_file_control(prompt))

con = sqlite3.connect(ROOT / "data" / "jarvis.db")
con.execute(
    "update tasks set status='cancelled', error='operator_cancel', updated_at=? "
    "where status in ('running','queued')",
    (datetime.utcnow().isoformat(),),
)
print("cancelled", con.total_changes)
con.commit()
con.close()

for p in (ROOT / "Desktop" / "jarvis-coding-live.py", Path.home() / "Desktop" / "jarvis-coding-live.py"):
    if p.exists():
        p.unlink()
        print("removed", p)

pending = ROOT / "data" / "queue" / "pending"
pending.mkdir(parents=True, exist_ok=True)
for old in pending.glob("*.json"):
    old.unlink()

path = pending / f"coding_CODINGLIVE-{datetime.now(timezone.utc).strftime('%H%M%S')}.json"
payload = {
    "prompt": prompt,
    "autonomy": "autonomous",
    "execution_mode": "fast",
    "enqueued_at": datetime.now(timezone.utc).isoformat(),
}
path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
print("queued", path.name, "bytes", path.stat().st_size)
