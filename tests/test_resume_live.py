"""Live check: create a task, restart the Jarvis API, history remains, continue works.

Restarts only the API process (keeps llama-server). stop-jarvis.ps1 also kills llama
and uses WMI; this helper uses the pid file plus netstat so the test cannot hang.
"""

from __future__ import annotations

import os
import subprocess
import sys
import time
import unittest
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parents[1]
BASE = os.environ.get("JARVIS_URL", "http://127.0.0.1:4780")
DESKTOP = Path.home() / "Desktop" / "Jarvis-Test"
PID_FILE = ROOT / "data" / "jarvis.pids"
CREATE_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)


def _wait_task(client: httpx.Client, task_id: str, timeout: int = 300) -> dict:
    deadline = time.time() + timeout
    last = {}
    while time.time() < deadline:
        last = client.get(f"/api/tasks/{task_id}").json()
        if last.get("status") in {"completed", "failed", "cancelled", "interrupted"}:
            return last
        time.sleep(2)
    raise TimeoutError(f"task {task_id} still {last.get('status')}")


def _pids_listening(port: int) -> set[int]:
    completed = subprocess.run(
        ["netstat", "-ano"],
        capture_output=True,
        text=True,
        timeout=20,
        check=False,
    )
    pids: set[int] = set()
    needle = f":{port}"
    for line in completed.stdout.splitlines():
        parts = line.split()
        if len(parts) < 5:
            continue
        if needle not in parts[1]:
            continue
        if parts[3].upper() != "LISTENING":
            continue
        try:
            pids.add(int(parts[-1]))
        except ValueError:
            continue
    return pids


def _kill_pid(pid: int) -> None:
    if pid <= 0 or pid == os.getpid():
        return
    subprocess.run(
        ["taskkill", "/PID", str(pid), "/F"],
        capture_output=True,
        text=True,
        timeout=20,
        check=False,
        creationflags=CREATE_NO_WINDOW,
    )


def restart_api(port: int = 4780) -> int:
    (ROOT / "logs").mkdir(parents=True, exist_ok=True)
    (ROOT / "data").mkdir(parents=True, exist_ok=True)
    pids = set()
    if PID_FILE.exists():
        for line in PID_FILE.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line.isdigit():
                pids.add(int(line))
    pids |= _pids_listening(port)
    for pid in pids:
        _kill_pid(pid)
    deadline = time.time() + 20
    while time.time() < deadline and _pids_listening(port):
        time.sleep(0.5)
    if _pids_listening(port):
        raise RuntimeError(f"port {port} still in use after kill")

    env = os.environ.copy()
    env["JARVIS_SKIP_MODEL"] = "1"
    env["PYTHONUNBUFFERED"] = "1"
    log_out = open(ROOT / "logs" / "backend.log", "a", encoding="utf-8")
    log_err = open(ROOT / "logs" / "backend.err.log", "a", encoding="utf-8")
    proc = subprocess.Popen(
        [
            sys.executable,
            "-m",
            "uvicorn",
            "app.main:app",
            "--host",
            "127.0.0.1",
            "--port",
            str(port),
            "--app-dir",
            "backend",
        ],
        cwd=str(ROOT),
        env=env,
        stdout=log_out,
        stderr=log_err,
        creationflags=CREATE_NO_WINDOW | subprocess.CREATE_NEW_PROCESS_GROUP,
    )
    PID_FILE.write_text(str(proc.pid), encoding="utf-8")
    health_deadline = time.time() + 40
    last_error = ""
    while time.time() < health_deadline:
        try:
            response = httpx.get(f"http://127.0.0.1:{port}/api/health", timeout=2)
            if response.status_code == 200 and response.json().get("ok"):
                return proc.pid
        except Exception as exc:
            last_error = str(exc)
        if proc.poll() is not None:
            raise RuntimeError(f"API process exited {proc.returncode}; {last_error}")
        time.sleep(0.5)
    raise RuntimeError(f"API did not return after restart: {last_error}")


class LiveResumeTests(unittest.TestCase):
    def test_create_stop_start_history_continue(self) -> None:
        if not os.environ.get("JARVIS_LIVE_RESUME"):
            self.skipTest("Set JARVIS_LIVE_RESUME=1 to run the live restart test")
        marker = f"T06-{int(time.time())}"
        path = DESKTOP / "t06-resume.txt"
        DESKTOP.mkdir(parents=True, exist_ok=True)
        prompt = f"Write the token {marker} into {path} and verify the file exists."
        try:
            with httpx.Client(base_url=BASE, timeout=30) as client:
                health = client.get("/api/health").json()
                if not health.get("ok"):
                    self.skipTest("Jarvis API is not healthy")
                created = client.post(
                    "/api/tasks",
                    json={
                        "prompt": prompt,
                        "autonomy": "autonomous",
                        "profile": "fast",
                        "execution_mode": "balanced",
                    },
                ).json()
                task_id = created["id"]
                first = _wait_task(client, task_id)
                self.assertTrue(path.exists(), first.get("result"))
                self.assertIn(marker, path.read_text(encoding="utf-8", errors="replace"))
                before = client.get(f"/api/tasks/{task_id}").json()
                self.assertGreaterEqual(len(before.get("events") or []), 1)
        except httpx.ConnectError:
            self.skipTest("Jarvis API is not running")

        restart_api()

        with httpx.Client(base_url=BASE, timeout=30) as client:
            listed = client.get("/api/tasks").json()
            ids = [row["id"] for row in listed]
            self.assertIn(task_id, ids)
            stored = client.get(f"/api/tasks/{task_id}").json()
            self.assertEqual(stored["id"], task_id)
            self.assertIn(marker, stored.get("prompt") or "")
            self.assertGreaterEqual(len(stored.get("events") or []), 1)
            follow = f"Append the word RESUMED to {path}. Keep the original token."
            continued = client.post(
                f"/api/tasks/{task_id}/continue",
                json={"prompt": follow},
            ).json()
            self.assertEqual(continued["id"], task_id)
            after = _wait_task(client, task_id)
            self.assertEqual(after["status"], "completed", after.get("error") or after.get("result"))
            text = path.read_text(encoding="utf-8", errors="replace")
            self.assertIn(marker, text)
            self.assertIn("RESUMED", text)


if __name__ == "__main__":
    unittest.main()
