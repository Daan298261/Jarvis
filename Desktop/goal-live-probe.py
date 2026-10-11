"""Live leftover probes: TTS speech_safe, Laya enable, steam/file tasks."""
from __future__ import annotations

import json
import time
import urllib.error
import urllib.request

BASE = "http://127.0.0.1:4780"


def get(path: str, timeout: float = 20) -> dict | bytes | int:
    with urllib.request.urlopen(BASE + path, timeout=timeout) as r:
        raw = r.read()
        ctype = r.headers.get("Content-Type", "")
        if "json" in ctype:
            return json.loads(raw.decode())
        return raw


def post(path: str, payload: dict | None = None, timeout: float = 60):
    data = None if payload is None else json.dumps(payload).encode()
    req = urllib.request.Request(
        BASE + path,
        data=data,
        headers={"Content-Type": "application/json"} if data else {},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            body = r.read()
            headers = {k: r.headers.get(k) for k in ("X-Jarvis-TTS-Engine", "X-Jarvis-Voice-Profile", "Content-Length")}
            if not body:
                return r.status, headers, None
            if not body:
                return r.status, headers, None
            ctype = (r.headers.get("Content-Type") or "").lower()
            if "json" in ctype:
                return r.status, headers, json.loads(body.decode())
            return r.status, headers, body
    except urllib.error.HTTPError as e:
        return e.code, {}, e.read()[:400]


def speak(label: str, text: str) -> None:
    status, headers, body = post("/api/voice/speak", {"text": text})
    engine = headers.get("X-Jarvis-TTS-Engine")
    nbytes = headers.get("Content-Length") or (len(body) if isinstance(body, (bytes, bytearray)) else None)
    print(f"speak[{label}] status={status} engine={engine} bytes={nbytes}")


print("=== health ===")
h = get("/api/health")
assert isinstance(h, dict)
print(
    f"pid={h.get('pid')} elevated={h.get('elevated')} logon={h.get('logon_task_registered')} "
    f"ufo={((h.get('computer_use') or {}).get('ufo') or {}).get('status')}"
)

print("=== voice ===")
v = get("/api/voice/status")
assert isinstance(v, dict)
tts = v.get("tts") or {}
print(f"tts_ready={v.get('tts_ready')} backend={tts.get('actual_engine') or tts.get('backend')} fallback={tts.get('fallback_active')}")

speak("plain", "That's done.")
speak("progress", "Saving that now.")
speak("markdown", "**bold** and `code` plus C:\\Program Files (x86)\\Steam\\steam.exe")
speak("dump", "Error rendering prompt: no user query found. Traceback (most recent call last)")

print("=== laya enable ===")
status, _, body = post("/api/decision/laya/enable", {"warm": True}, timeout=180)
print(f"enable status={status} body_keys={list(body) if isinstance(body, dict) else type(body)}")
if isinstance(body, dict):
    print(f"enabled={body.get('enabled')} warm={body.get('warm')} err={body.get('load_error')} pkg={body.get('package_version')}")

# wait warm briefly
deadline = time.time() + 120
while time.time() < deadline:
    laya = get("/api/decision/laya", timeout=30)
    assert isinstance(laya, dict)
    if laya.get("warm") and laya.get("enabled"):
        print(f"laya warm ok last_ms={laya.get('last_infer_ms')}")
        break
    if laya.get("load_error"):
        print(f"laya load_error={laya.get('load_error')}")
        break
    time.sleep(3)
else:
    laya = get("/api/decision/laya", timeout=30)
    print(f"laya still not warm: {laya}")

print("=== tasks ===")
file_status, _, file_task = post(
    "/api/tasks",
    {
        "prompt": 'Write a one-line text file at Desktop/jarvis-progress-check.txt saying live-verify-ok. Then stop.',
        "autonomy": "autonomous",
        "execution_mode": "fast",
    },
)
steam_status, _, steam_task = post(
    "/api/tasks",
    {
        "prompt": "Open Steam. If it is already running, say so and stop. Do not install anything.",
        "autonomy": "autonomous",
        "execution_mode": "fast",
    },
)
print(f"file_create={file_status} id={(file_task or {}).get('id')} class={(file_task or {}).get('task_class')}")
print(f"steam_create={steam_status} id={(steam_task or {}).get('id')} class={(steam_task or {}).get('task_class')} tools={(steam_task or {}).get('exposed_tools')}")

ids = [t["id"] for t in (file_task, steam_task) if isinstance(t, dict) and t.get("id")]
done: dict[str, dict] = {}
deadline = time.time() + 180
while time.time() < deadline and len(done) < len(ids):
    for tid in ids:
        if tid in done:
            continue
        row = get(f"/api/tasks/{tid}", timeout=20)
        assert isinstance(row, dict)
        print(f"{tid[:8]} status={row.get('status')} stage={row.get('stage')} action={row.get('current_action')} class={row.get('task_class')}")
        if row.get("status") in {"completed", "failed", "cancelled"}:
            done[tid] = row
    if len(done) < len(ids):
        time.sleep(4)

for tid, row in done.items():
    print("---", tid)
    print("status", row.get("status"), "class", row.get("task_class"))
    print("result", (row.get("result") or "")[:300])
    print("error", (row.get("error") or "")[:200])
