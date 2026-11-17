"""Exercise a real Manager on an ephemeral port without touching live workloads."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import socket
import shutil
import subprocess
import sys
import tempfile
import time
from urllib.error import URLError
from urllib.request import urlopen

ROOT = Path(__file__).resolve().parents[2]


def read(base: str, path: str, *, timeout: float = 5):
    with urlopen(base + path, timeout=timeout) as response:
        assert response.status == 200
        return response.read()


def serve(port: int) -> None:
    """Bind the unchanged application to one disposable test origin only."""
    sys.path.insert(0, str(ROOT / "backend"))
    import uvicorn
    from app.manager import main as manager

    manager.MANAGER_ORIGINS = frozenset({f"http://127.0.0.1:{port}"})
    uvicorn.run(manager.app, host="127.0.0.1", port=port)


def exercise_child(page, panel, base: str, scratch: str) -> None:
    """The only kill target is this test's own disposable, non-model child."""
    node = shutil.which("node")
    if not node:
        raise RuntimeError("Node is required for the disposable-process E2E test")
    executable = Path(scratch) / ("llama-server.exe" if os.name == "nt" else "llama-server")
    shutil.copy2(node, executable)
    child = subprocess.Popen([str(executable), "-e", "setInterval(() => {}, 1000)"], creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    try:
        with page.expect_response(lambda response: response.url == base + "/api/manager/v1/model-processes" and response.status == 200):
            panel.get_by_role("button", name="Refresh processes").click()
        kill = panel.get_by_role("button", name=f"Hard kill llama.cpp PID {child.pid}", exact=True)
        kill.wait_for()
        page.once("dialog", lambda dialog: dialog.dismiss())
        kill.click()
        assert child.poll() is None, "Cancel unexpectedly killed the disposable child"
        page.once("dialog", lambda dialog: dialog.accept())
        with page.expect_response(lambda response: response.url.endswith("/kill") and response.status == 200):
            kill.click()
        child.wait(timeout=10)
        assert all(row["pid"] != child.pid for row in json.loads(read(base, "/api/manager/v1/model-processes"))["processes"])
        events = json.loads(read(base, "/api/manager/v1/debug-log?tail=200"))["lines"]
        assert any(event.get("action") == "model_hard_kill" and event.get("ok") is True and event.get("detail", {}).get("pid") == child.pid for event in events), "Successful kill audit record missing"
    finally:
        if child.poll() is None:
            child.kill()
            child.wait(timeout=10)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("check", choices=["startup", "health", "e2e"])
    check = parser.parse_args().check
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        port = listener.getsockname()[1]
    base = f"http://127.0.0.1:{port}"
    evidence = ROOT / ".verify"
    evidence.mkdir(exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="anzu-manager-gate-") as scratch:
        env = dict(os.environ, JARVIS_ROOT=scratch, JARVIS_SKIP_MODEL="1", JARVIS_MANAGER_WATCHDOG="0", PYTHONPATH=str(ROOT / "backend"))
        with (evidence / f"manager-{check}-{os.getpid()}.log").open("wb") as log:
            process = subprocess.Popen(
                [sys.executable, str(Path(__file__).resolve()), "serve", str(port)],
                cwd=ROOT, env=env, stdout=log, stderr=subprocess.STDOUT,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
            try:
                deadline = time.monotonic() + 45
                while time.monotonic() < deadline and process.poll() is None:
                    try:
                        read(base, "/admin")
                        break
                    except (OSError, URLError):
                        time.sleep(0.1)  # Bounded readiness polling, never a test retry.
                else:
                    raise RuntimeError("Manager did not become ready; inspect its smoke log")
                if check in {"health", "e2e"}:
                    # Status includes serialized 2s/3s core probes plus OS/GPU
                    # inspection; its composed budget exceeds an individual GET.
                    assert json.loads(read(base, "/api/manager/v1/status", timeout=30))["manager"]["healthy"] is True
                    payload = json.loads(read(base, "/api/manager/v1/model-processes"))
                    assert isinstance(payload["processes"], list)
                    read(base, "/assets/processes.js")
                if check == "e2e":
                    os.environ["PLAYWRIGHT_BROWSERS_PATH"] = str(ROOT / ".verify" / "browsers")
                    from playwright.sync_api import sync_playwright

                    with sync_playwright() as playwright:
                        browser = playwright.chromium.launch()
                        try:
                            page = browser.new_page(viewport={"width": 390, "height": 844})
                            errors = []
                            page.on("pageerror", lambda error: errors.append(str(error)))
                            model_response = lambda response: response.url == base + "/api/manager/v1/model-processes" and response.status == 200
                            with page.expect_response(model_response):
                                page.goto(base + "/admin", wait_until="domcontentloaded")
                            panel = page.get_by_role("region", name="Running AI model processes")
                            panel.get_by_role("heading", name="Running AI models").wait_for()
                            page.wait_for_function("document.querySelector('#model-processes .process-list').children.length > 0")
                            with page.expect_response(model_response):
                                panel.get_by_role("button", name="Refresh processes").click()
                            page.wait_for_function("document.querySelector('#model-processes .process-list').children.length > 0")
                            assert page.evaluate("document.documentElement.scrollWidth <= innerWidth"), "Manager overflows a narrow window"
                            assert not errors, errors
                            page.screenshot(path=str(evidence / "manager-mobile.png"), full_page=True)
                            exercise_child(page, panel, base, scratch)
                        finally:
                            browser.close()
                print(f"Manager {check} passed on disposable port {port}.")
            finally:
                process.terminate()
                try:
                    process.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait(timeout=10)


if __name__ == "__main__":
    if len(sys.argv) == 3 and sys.argv[1] == "serve":
        serve(int(sys.argv[2]))
    else:
        main()
