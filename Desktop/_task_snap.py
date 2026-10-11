"""Snapshot task + companion + marker."""
from __future__ import annotations

import json
import sqlite3
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
tid = "c80797b8-d197-4582-8fb3-e30c8207ac7d"
con = sqlite3.connect(ROOT / "data" / "jarvis.db")
print(
    "task",
    con.execute(
        "select status,stage,current_tool,tool_call_count,model_calls,"
        "substr(current_action,1,90),substr(error,1,140) from tasks where id=?",
        (tid,),
    ).fetchone(),
)
print(
    "ev",
    con.execute(
        "select kind,title,substr(detail,1,120) from task_events "
        "where task_id=? order by id desc limit 8",
        (tid,),
    ).fetchall(),
)
con.close()
cdb = sqlite3.connect(ROOT / "data" / "mobile" / "companion.db")
row = cdb.execute(
    "select payload from records where kind='network' and id='config'"
).fetchone()
print("companion", json.loads(row[0]) if row else None)
cdb.close()
m = ROOT / "Desktop" / "_ufo_marker.txt"
print("marker", m.read_text(encoding="utf-8") if m.exists() else None)
for u in ("http://127.0.0.1:4780/api/health", "http://127.0.0.1:8088/health"):
    try:
        print(u, urllib.request.urlopen(u, timeout=5).read()[:160])
    except Exception as e:
        print(u, type(e).__name__, e)
