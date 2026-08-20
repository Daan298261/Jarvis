import time
from pathlib import Path

import httpx

desktop = Path.home() / "Desktop" / "Jarvis-Test"
prompt = (
    "Create a folder on the desktop named Jarvis-Test and write a text file named "
    "smoke.txt containing the word READY. Then verify the file exists."
)
last = None
with httpx.Client(base_url="http://127.0.0.1:4780", timeout=60) as client:
    task = client.post("/api/tasks", json={"prompt": prompt, "autonomy": "autonomous", "profile": "fast"}).json()
    print("created", task["id"], flush=True)
    task_id = task["id"]
    deadline = time.time() + 300
    while time.time() < deadline:
        data = client.get(f"/api/tasks/{task_id}").json()
        key = (data["status"], data["stage"], data.get("current_tool"), data.get("current_action"))
        if key != last:
            print(f"{data['status']} | {data['stage']} | {data.get('current_tool') or '-'} | {data.get('current_action')}", flush=True)
            last = key
        if data["status"] in {"completed", "failed", "cancelled"}:
            print("RESULT:", (data.get("result") or "")[:1500], flush=True)
            break
        time.sleep(3)
path = desktop / "smoke.txt"
print("file_exists", path.exists(), "content=", path.read_text(encoding="utf-8") if path.exists() else "", flush=True)
