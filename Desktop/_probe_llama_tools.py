"""Direct llama tool-call probe + task snap."""
from __future__ import annotations

import json
import sqlite3
import time
import urllib.request

body = json.dumps(
    {
        "model": "Qwen3.5-9B",
        "messages": [{"role": "user", "content": "Reply with a tool call only."}],
        "tools": [
            {
                "type": "function",
                "function": {
                    "name": "filesystem",
                    "description": "fs",
                    "parameters": {"type": "object", "properties": {}},
                },
            }
        ],
        "tool_choice": "auto",
        "max_tokens": 64,
    }
).encode()
req = urllib.request.Request(
    "http://127.0.0.1:8088/v1/chat/completions",
    data=body,
    headers={"Content-Type": "application/json"},
)
t0 = time.time()
try:
    with urllib.request.urlopen(req, timeout=60) as r:
        print("ok", round(time.time() - t0, 2), r.read()[:500])
except Exception as e:
    print("fail", round(time.time() - t0, 2), e)

for u in ("http://127.0.0.1:4780/api/health", "http://127.0.0.1:8088/health"):
    try:
        print(u, urllib.request.urlopen(u, timeout=5).read()[:120])
    except Exception as e:
        print(u, e)

con = sqlite3.connect("data/jarvis.db")
print(
    "task",
    con.execute(
        "select status,stage,substr(error,1,160),tool_call_count,model_calls "
        "from tasks where id=?",
        ("01689000-5c9e-42c6-9e2d-02371f7b5c84",),
    ).fetchone(),
)
con.close()
