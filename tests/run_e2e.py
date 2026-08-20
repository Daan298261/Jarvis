"""End-to-end tests against a running Jarvis API."""

from __future__ import annotations

import json
import os
import time
from pathlib import Path

import httpx
from PIL import Image, ImageDraw, ImageFont

from broken_project import create_broken_project

ROOT = Path(__file__).resolve().parents[1]
DESKTOP = Path.home() / "Desktop"
BASE = os.environ.get("JARVIS_URL", "http://127.0.0.1:4780")
TIMEOUT = int(os.environ.get("JARVIS_TEST_TIMEOUT", "900"))


def wait_task(client: httpx.Client, task_id: str, timeout: int = TIMEOUT) -> dict:
    deadline = time.time() + timeout
    last = {}
    while time.time() < deadline:
        last = client.get(f"/api/tasks/{task_id}").json()
        if last.get("status") in {"completed", "failed", "cancelled"}:
            return last
        time.sleep(3)
    raise TimeoutError(f"Task {task_id} did not finish: {last.get('status')} {last.get('current_action')}")


def submit(client: httpx.Client, prompt: str, autonomy: str = "autonomous") -> dict:
    task = client.post("/api/tasks", json={"prompt": prompt, "autonomy": autonomy, "profile": "fast"}).json()
    return wait_task(client, task["id"])


def main() -> None:
    results = {}
    with httpx.Client(base_url=BASE, timeout=60) as client:
        health = client.get("/api/health").json()
        assert health.get("ok"), health
        model = client.get("/api/model").json()
        if not model.get("loaded"):
            print("Loading model...")
            client.post("/api/model/load", json={"profile": "balanced"}, timeout=400)
            model = client.get("/api/model").json()
        print("Model:", json.dumps({k: model.get(k) for k in ("active_model", "quantization", "loaded", "tokens_per_second", "vram_used_mib")}, indent=2))

        # TEST 1
        folder = DESKTOP / "Jarvis-Test"
        prompt1 = (
            "Create a folder on the desktop named Jarvis-Test and write a text file named system-specs.txt "
            "containing the current system specifications (OS, CPU, RAM, GPU, VRAM). Then verify the file exists and is non-empty."
        )
        t1 = submit(client, prompt1)
        spec_file = folder / "system-specs.txt"
        results["test1"] = {
            "status": t1["status"],
            "file_exists": spec_file.exists(),
            "size": spec_file.stat().st_size if spec_file.exists() else 0,
        }

        # TEST 2
        prompt2 = (
            f"Create a small Python program that calculates the first 100 prime numbers, run it, and save the result "
            f"to {folder / 'primes.txt'}. Verify the file contains 100 numbers and that 2 and 97 are present."
        )
        t2 = submit(client, prompt2)
        primes_file = folder / "primes.txt"
        primes_ok = False
        if primes_file.exists():
            text = primes_file.read_text(encoding="utf-8", errors="replace")
            primes_ok = "2" in text and "97" in text
        results["test2"] = {"status": t2["status"], "ok": primes_ok, "exists": primes_file.exists()}

        # TEST 3
        title_file = folder / "page-title.txt"
        prompt3 = (
            f"Open a browser, visit https://example.com, read the page title, and save that title to {title_file}. Verify the file."
        )
        t3 = submit(client, prompt3)
        title_ok = title_file.exists() and "example" in title_file.read_text(encoding="utf-8", errors="replace").lower()
        results["test3"] = {"status": t3["status"], "ok": title_ok}

        # TEST 4
        broken = create_broken_project(ROOT / "tests" / "output")
        prompt4 = (
            f"Find out why the Python project at {broken} fails, fix it, and verify the fix by running python main.py. "
            "The program should write 100 primes to output.txt. Do not stop until it runs successfully."
        )
        t4 = submit(client, prompt4)
        out = broken / "output.txt"
        results["test4"] = {"status": t4["status"], "output_exists": out.exists(), "lines": len(out.read_text(encoding='utf-8').splitlines()) if out.exists() else 0}

        # TEST 5
        image = ROOT / "tests" / "output" / "vision-target.png"
        image.parent.mkdir(parents=True, exist_ok=True)
        im = Image.new("RGB", (640, 360), (16, 22, 30))
        draw = ImageDraw.Draw(im)
        draw.ellipse((420, 80, 580, 240), fill=(200, 40, 40))
        draw.text((40, 150), "JARVIS-VISION-OK", fill=(230, 200, 80))
        im.save(image)
        vision_out = folder / "vision-result.txt"
        prompt5 = (
            f"Look at this image: {image}. Identify the visible text and the color of the circle. "
            f"Save your answer to {vision_out}."
        )
        t5 = submit(client, prompt5)
        vision_text = vision_out.read_text(encoding="utf-8", errors="replace").lower() if vision_out.exists() else ""
        results["test5"] = {
            "status": t5["status"],
            "mentions_text": "jarvis-vision-ok" in vision_text or "jarvis" in (t5.get("result") or "").lower(),
            "file": vision_out.exists(),
        }

        # TEST 6 recovery
        prompt6 = (
            f"Use the terminal tool to run the PowerShell command Get-Item C:\\this-path-does-not-exist-jarvis-xyz. "
            f"It will fail. You must inspect the error, recover with a different strategy, and still write a file "
            f"{folder / 'recovery.txt'} containing the word RECOVERED and the current date. Do not stop after the first failure."
        )
        t6 = submit(client, prompt6)
        rec = folder / "recovery.txt"
        results["test6"] = {"status": t6["status"], "ok": rec.exists() and "RECOVERED" in rec.read_text(encoding="utf-8", errors="replace")}

        # TEST 7 persistence — recreate client after listing
        tasks = client.get("/api/tasks").json()
        results["test7"] = {"history_count": len(tasks), "ok": len(tasks) >= 6}

    (ROOT / "tests" / "output" / "e2e-results.json").write_text(json.dumps(results, indent=2), encoding="utf-8")
    print(json.dumps(results, indent=2))
    failed = []
    if not (results["test1"]["file_exists"] and results["test1"]["size"] > 20):
        failed.append("test1")
    if not results["test2"]["ok"]:
        failed.append("test2")
    if not results["test3"]["ok"]:
        failed.append("test3")
    if not (results["test4"]["output_exists"] and results["test4"]["lines"] >= 90):
        failed.append("test4")
    if not results["test5"]["mentions_text"]:
        failed.append("test5")
    if not results["test6"]["ok"]:
        failed.append("test6")
    if not results["test7"]["ok"]:
        failed.append("test7")
    if failed:
        raise SystemExit(f"Failed: {failed}")
    print("All end-to-end tests passed.")


if __name__ == "__main__":
    main()
