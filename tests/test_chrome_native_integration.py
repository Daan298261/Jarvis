"""Desktop-only smoke: Chromium -> compiled host -> ANZU browser tool -> page."""
import asyncio
import json
import os
from pathlib import Path
import shutil
import sys
import time

import pytest

from app.tools import chrome_connector, chrome_setup


async def test_registered_native_host_roundtrip_with_real_extension(tmp_path, monkeypatch):
    if sys.platform != "win32" or not chrome_setup.setup_status()["registered"]:
        pytest.skip("Registered Windows native host required for desktop connector smoke")
    from playwright.async_api import async_playwright
    from app.config import apply_playwright_browsers_path
    apply_playwright_browsers_path()
    source = chrome_setup.source_dir()
    extension = tmp_path / "extension"
    for name in chrome_setup.FILES:
        target = extension / name
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source / name, target)
    manifest = json.loads((extension / "manifest.json").read_text())
    # Only synthetic fixture websites are pre-granted in this temporary profile.
    manifest["host_permissions"] = ["https://example.test/*", "https://frame.test/*"]
    (extension / "manifest.json").write_text(json.dumps(manifest))
    local_app_data = tmp_path / "native-user"
    queue = local_app_data / "ANZU" / "chrome-connector"
    monkeypatch.setattr(chrome_connector, "connector_dir", lambda: queue)
    monkeypatch.setattr("app.policy.computer_permissions.data_dir", lambda: tmp_path / "permissions")
    from app.policy.computer_permissions import reset_computer_permission_state
    reset_computer_permission_state()
    async with async_playwright() as pw:
        if not Path(pw.chromium.executable_path).is_file():
            pytest.skip("Chromium runtime required for native connector smoke")
        context = await pw.chromium.launch_persistent_context(str(tmp_path / "profile"), channel="chromium", headless=True, env={**os.environ,"LOCALAPPDATA":str(local_app_data)}, args=[f"--disable-extensions-except={extension}",f"--load-extension={extension}"])
        try:
            worker = context.service_workers[0] if context.service_workers else await context.wait_for_event("serviceworker")
            identity = worker.url.split("/")[2]
            assert identity == chrome_setup.extension_id()
            page = await context.new_page()
            await page.route("https://example.test/**", lambda route: route.fulfill(body='<h1>Native bridge verified</h1><input type="file" aria-label="Document"><iframe src="https://frame.test/"></iframe>'))
            await page.route("https://frame.test/**", lambda route: route.fulfill(body='<h1>Embedded information</h1><button>Frame control</button>'))
            await page.goto("https://example.test/")
            tab_id = await worker.evaluate("async () => (await chrome.tabs.query({})).find(tab => tab.url === 'https://example.test/').id")
            popup = await context.new_page()
            await popup.goto(f"chrome-extension://{identity}/popup.html")
            reply = await popup.evaluate("id => chrome.runtime.sendMessage({action:'share',tabId:id,include_frames:true})", tab_id)
            assert reply.get("connected"), reply
            deadline = time.time() + 10
            while not chrome_connector.read_json(queue / "connection.json").get("url") and time.time() < deadline:
                await asyncio.sleep(0.05)
            snapshot = await chrome_connector.execute_connector("chrome_snapshot", url=page.url)
            assert snapshot.success, snapshot.error
            assert "Native bridge verified" in snapshot.data["text"]
            frames = await chrome_connector.execute_connector("chrome_frames", url=page.url)
            assert frames.success
            frame = next(frame for frame in frames.data["frames"] if frame.get("url") == "https://frame.test/")
            embedded = await chrome_connector.execute_connector("chrome_find", url=page.url, frame_id=frame["frame_id"], frame_url=frame["url"], text="Embedded information")
            assert embedded.success and embedded.data["matches"]
            path = tmp_path / "approved" / "document.txt"
            path.parent.mkdir()
            path.write_bytes(b"native upload " * 30000)
            target_id = next(control["target_id"] for control in snapshot.data["controls"] if control.get("input_type") == "file")
            upload = await chrome_connector.execute_connector("chrome_upload", url=page.url, target_id=target_id, path=str(path), _allowed=[str(path.parent)])
            assert upload.success, upload.error
            assert await page.locator('input[type=file]').evaluate("el => el.files[0].size") == path.stat().st_size
            await popup.evaluate("() => chrome.runtime.sendMessage({action:'revoke'})")
            await asyncio.sleep(0.1)
            assert not (await chrome_connector.execute_connector("chrome_status")).data["connected"]
        finally:
            await context.close()
