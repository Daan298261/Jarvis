import asyncio
import base64
import importlib.util
import io
import json
import os
from pathlib import Path
import struct
import subprocess
import sys
import time

import pytest

from app.tools import chrome_connector as connector
from app.tools.browser import BrowserTool
from app.policy.reversibility import resolve_action_effect

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("anzu_native_host", ROOT / "extensions/chrome/native_host.py")
native = importlib.util.module_from_spec(spec)
spec.loader.exec_module(native)


@pytest.fixture
def bridge(tmp_path, monkeypatch):
    monkeypatch.setattr(connector, "connector_dir", lambda: tmp_path)
    connector.atomic_json(tmp_path / "connection.json", {"session": "test", "heartbeat": time.time()})
    from app.policy.computer_permissions import reset_computer_permission_state
    monkeypatch.setattr("app.policy.computer_permissions.data_dir", lambda: tmp_path)
    reset_computer_permission_state()
    return tmp_path


async def test_disconnected_status_without_launching_playwright(tmp_path, monkeypatch):
    monkeypatch.setattr(connector, "connector_dir", lambda: tmp_path)
    result = await BrowserTool(lambda: {}).execute(action="chrome_status")
    assert result.success and result.data["connected"] is False
    result = await connector.execute_connector("chrome_snapshot", url="https://example.test/")
    assert not result.success and "disconnected" in result.error


@pytest.mark.parametrize("url", ["", "file:///secret", "javascript:alert(1)", "https://user:secret@example.test/", "https://"])
async def test_invalid_urls_never_dispatch(bridge, url):
    result = await connector.execute_connector("chrome_snapshot", url=url)
    assert not result.success
    assert not list(bridge.glob("*.request.json"))


async def test_network_denial_never_dispatches(bridge):
    from app.policy.computer_permissions import apply_grant
    apply_grant("network.internet", "deny")
    result = await connector.execute_connector("chrome_snapshot", url="https://example.test/")
    assert not result.success
    assert not list(bridge.glob("*.request.json"))


async def test_response_roundtrip_and_cleanup(bridge):
    async def extension():
        while not list(bridge.glob("*.request.json")):
            await asyncio.sleep(0.01)
        request = list(bridge.glob("*.request.json"))[0]
        value = connector.read_json(request)
        assert value["session"] == "test" and value["expires"] > time.time()
        connector.atomic_json(bridge / f'{value["id"]}.response.json', {"id": value["id"], "success": True, "data": {"matches": ["shipping"]}})
    task = asyncio.create_task(extension())
    result = await connector.execute_connector("chrome_find", url="https://example.test/", text="shipping")
    await task
    assert result.success and result.data["matches"] == ["shipping"]
    assert not list(bridge.glob("*.request.json")) and not list(bridge.glob("*.response.json"))


async def test_disconnect_cancels_pending_request(bridge):
    async def disconnect():
        await asyncio.sleep(0.08)
        (bridge / "connection.json").unlink()
    task = asyncio.create_task(disconnect())
    result = await connector.execute_connector("chrome_snapshot", url="https://example.test/")
    await task
    assert not result.success and "disconnected during" in result.error
    assert not list(bridge.glob("*.request.json"))


async def test_timeout_is_ambiguous_and_cleans_request(bridge):
    result = await connector.execute_connector("chrome_click", url="https://example.test/", target_id="observed", timeout_seconds=1)
    assert not result.success and "may have completed" in result.error
    assert not list(bridge.glob("*.request.json"))


async def test_malformed_heartbeat_and_oversize_commands_fail_closed(bridge):
    result = await connector.execute_connector("chrome_fill", url="https://example.test/", target_id="observed", text="x" * 16001)
    assert not result.success and "limit" in result.error
    result = await connector.execute_connector("chrome_snapshot", url="https://example.test/", timeout_seconds=float("nan"))
    assert not result.success and "finite" in result.error
    connector.atomic_json(bridge / "connection.json", {"session": "test", "heartbeat": "invalid"})
    assert not (await connector.execute_connector("chrome_status")).data["connected"]


@pytest.mark.parametrize("action", ["chrome_click", "chrome_fill", "chrome_block_ads"])
def test_mutations_keep_consequential_policy(action):
    effect = resolve_action_effect("browser", action=action, arguments={"url": "https://example.test/"})
    assert effect.high_consequence and effect.external_side_effect


@pytest.mark.parametrize("action", ["chrome_status", "chrome_snapshot", "chrome_find"])
def test_observations_are_readonly(action):
    effect = resolve_action_effect("browser", action=action)
    assert not effect.side_effecting


def test_native_framing_and_limits():
    stream = io.BytesIO()
    native.write_message(stream, {"text": "é\nhello"})
    stream.seek(0)
    assert native.read_message(stream) == {"text": "é\nhello"}
    with pytest.raises(ValueError):
        native.read_message(io.BytesIO(struct.pack("<I", native.MAX_MESSAGE + 1)))
    with pytest.raises(ValueError):
        native.read_message(io.BytesIO(b"\x01"))
    assert native.read_message(io.BytesIO()) is None


def test_real_native_process_roundtrip(tmp_path):
    env = {**os.environ, "LOCALAPPDATA": str(tmp_path)}
    process = subprocess.Popen([sys.executable, "-u", str(ROOT / "extensions/chrome/native_host.py")], stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=env)
    root = tmp_path / "ANZU" / "chrome-connector"
    try:
        deadline = time.time() + 5
        while not (root / "connection.json").exists() and time.time() < deadline:
            time.sleep(0.02)
        state = connector.read_json(root / "connection.json")
        assert state.get("session")
        native.write_message(process.stdin, {"type": "shared", "url": "https://example.test/"})
        request_id = "a" * 32
        connector.atomic_json(root / f"{request_id}.request.json", {"id": request_id, "session": state["session"], "expires": time.time() + 4, "action": "chrome_find", "url": "https://example.test/", "text": "hello"})
        # Read off-thread to keep a broken host from hanging the suite.
        from concurrent.futures import ThreadPoolExecutor
        reader = ThreadPoolExecutor(max_workers=1)
        try:
            request = reader.submit(native.read_message, process.stdout).result(timeout=5)
        finally:
            reader.shutdown(wait=False)
        assert request["id"] == request_id
        native.write_message(process.stdin, {"id": request_id, "success": True, "data": {"matches": ["hello"]}})
        deadline = time.time() + 3
        response = root / f"{request_id}.response.json"
        while not response.exists() and time.time() < deadline:
            time.sleep(0.02)
        assert connector.read_json(response)["data"]["matches"] == ["hello"]
        process.stdin.close()
        assert process.wait(timeout=5) == 0
        assert not (root / "connection.json").exists()
    finally:
        if process.poll() is None:
            process.kill()
        process.wait(timeout=5)


async def test_page_operations_in_real_chromium():
    from playwright.async_api import async_playwright
    from app.config import apply_playwright_browsers_path
    apply_playwright_browsers_path()
    source = (ROOT / "extensions/chrome/page.js").read_text(encoding="utf-8").replace("export function", "function", 1)
    async with async_playwright() as pw:
        if not Path(pw.chromium.executable_path).is_file():
            pytest.skip("Chromium runtime required for desktop browser smoke; run python -m playwright install chromium")
        browser = await pw.chromium.launch(headless=True)
        try:
            page = await browser.new_page()
            await page.route("https://example.test/**", lambda route: route.fulfill(body='<h1>Shipping details</h1><input aria-label="Search"><input type="password"><button onclick="document.querySelector(\'h1\').textContent=\'Clicked\'">Confirm</button><a href="https://other.test/">External</a>'))
            await page.goto("https://example.test/")
            async def run(action, **kwargs):
                return await page.evaluate(f"request => {{ {source}; return pageOperation(request); }}", {"action": action, "url": page.url, "expires": time.time() + 5, **kwargs})
            snapshot = await run("chrome_snapshot")
            assert snapshot["untrusted_page_content"]
            assert len(snapshot["controls"]) == 3
            assert (await run("chrome_find", text="shipping"))["matches"]
            field = snapshot["controls"][0]["target_id"]
            await run("chrome_fill", target_id=field, text="ANZU")
            assert await page.locator("input").first.input_value() == "ANZU"
            with pytest.raises(Exception, match="Stale"):
                await run("chrome_fill", target_id=field, text="old snapshot")
            snapshot = await run("chrome_snapshot")
            with pytest.raises(Exception, match="manually"):
                await run("chrome_click", target_id=snapshot["controls"][2]["target_id"])
            button = snapshot["controls"][1]["target_id"]
            await run("chrome_click", target_id=button)
            assert await page.locator("h1").inner_text() == "Clicked"
            with pytest.raises(Exception, match="expired"):
                await page.evaluate(f"request => {{ {source}; return pageOperation(request); }}", {"action": "chrome_snapshot", "expires": 0, "url": page.url})
        finally:
            await browser.close()


async def test_manifest_and_popup_load_in_real_chromium(tmp_path):
    from playwright.async_api import async_playwright
    from app.config import apply_playwright_browsers_path
    apply_playwright_browsers_path()
    extension = ROOT / "extensions/chrome"
    async with async_playwright() as pw:
        if not Path(pw.chromium.executable_path).is_file():
            pytest.skip("Chromium runtime required for extension smoke; run python -m playwright install chromium")
        context = await pw.chromium.launch_persistent_context(str(tmp_path / "profile"), channel="chromium", headless=True, args=[f"--disable-extensions-except={extension}", f"--load-extension={extension}"])
        try:
            worker = context.service_workers[0] if context.service_workers else await context.wait_for_event("serviceworker", timeout=10000)
            extension_id = worker.url.split("/")[2]
            popup = await context.new_page()
            errors = []
            popup.on("pageerror", lambda error: errors.append(str(error)))
            await popup.goto(f"chrome-extension://{extension_id}/popup.html")
            await popup.get_by_role("status").filter(has_text="No tab shared").wait_for()
            assert await popup.get_by_role("button", name="Share this tab", exact=True).is_visible()
            assert not errors
            assert await worker.evaluate("chrome.runtime.getManifest().manifest_version") == 3
            # Exercise Chrome's actual network-rule engine, without global site permissions.
            website = await context.new_page()
            await website.route("https://example.test/**", lambda route: route.fulfill(body="<h1>Test page</h1>"))
            await website.route("https://doubleclick.net/**", lambda route: route.fulfill(body="ok"))
            await website.goto("https://example.test/")
            await website.bring_to_front()
            tab_id = await worker.evaluate("async () => (await chrome.tabs.query({active:true,currentWindow:true}))[0].id")
            await worker.evaluate("async id => chrome.declarativeNetRequest.updateSessionRules({addRules:[{id:99,priority:1,action:{type:'block'},condition:{urlFilter:'||doubleclick.net^',tabIds:[id],resourceTypes:['image']}}]})", tab_id)
            async with website.expect_event("requestfailed") as failed:
                await website.evaluate("() => {const img = new Image(); img.src='https://doubleclick.net/anzu-test.png'; document.body.append(img);}")
            assert "ERR_BLOCKED_BY_CLIENT" in (await failed.value).failure
            await worker.evaluate("async () => chrome.declarativeNetRequest.updateSessionRules({removeRuleIds:[99]})")
            async with website.expect_response("https://doubleclick.net/anzu-test-unblocked.png") as unblocked:
                await website.evaluate("() => {const img = new Image(); img.src='https://doubleclick.net/anzu-test-unblocked.png'; document.body.append(img);}")
            assert (await unblocked.value).status == 200
            ad_source = (ROOT / "extensions/chrome/ad-rules.js").read_text().replace("export async function", "async function", 1)
            filters = await worker.evaluate(f"async id => {{ {ad_source}; const filters=await adRules(id); await chrome.declarativeNetRequest.updateSessionRules({{addRules:filters.rules}}); return {{count:filters.count, rules:filters.rules.length}}; }}", tab_id)
            assert filters["count"] > 40000 and filters["rules"] < 5000
            await worker.evaluate("async () => {const rules=await chrome.declarativeNetRequest.getSessionRules(); await chrome.declarativeNetRequest.updateSessionRules({removeRuleIds:rules.map(rule=>rule.id)});}")
        finally:
            await context.close()


async def test_upload_is_chunked_and_workspace_scoped(bridge, monkeypatch):
    from app.tools.base import ToolResult
    sent = []
    async def transport(root, state, payload, timeout):
        sent.append(payload)
        return ToolResult(True, "", data={"selected_file": payload.get("filename")})
    monkeypatch.setattr(connector, "_send", transport)
    source = bridge / "allowed" / "document.txt"
    source.parent.mkdir()
    source.write_bytes(b"x" * 500000)
    result = await connector.execute_connector("chrome_upload", url="https://example.test/", target_id="observed", path=str(source), _allowed=[str(source.parent)])
    assert result.success
    assert [item["stage"] for item in sent] == ["begin", "chunk", "chunk", "chunk", "finish"]
    assert b"".join(base64.b64decode(item["chunk"]) for item in sent if item["stage"] == "chunk") == source.read_bytes()
    assert all(len(json.dumps(item)) < native.MAX_MESSAGE for item in sent)
    sent.clear()
    result = await connector.execute_connector("chrome_upload", url="https://example.test/", target_id="observed", path=str(source), _allowed=[str(bridge / "elsewhere")])
    assert not result.success and not sent


async def test_frame_and_download_urls_use_network_permissions(bridge):
    from app.policy.computer_permissions import apply_grant
    apply_grant("network.local", "deny")
    for action, extra in [("chrome_snapshot", {"frame_id":2,"frame_url":"http://127.0.0.1/"}), ("chrome_download", {"target_id":"link","download_url":"http://127.0.0.1/file"})]:
        result = await connector.execute_connector(action, url="https://example.test/", **extra)
        assert not result.success
    assert not list(bridge.glob("*.request.json"))


async def test_real_shadow_controls_and_upload_selection():
    from playwright.async_api import async_playwright
    from app.config import apply_playwright_browsers_path
    apply_playwright_browsers_path()
    source = (ROOT / "extensions/chrome/page.js").read_text().replace("export function", "function", 1)
    async with async_playwright() as pw:
        if not Path(pw.chromium.executable_path).is_file():
            pytest.skip("Chromium required for browser smoke")
        browser = await pw.chromium.launch(headless=True)
        try:
            page = await browser.new_page()
            await page.route("https://example.test/**", lambda route: route.fulfill(body='<h1>Embedded information</h1>' if route.request.url.endswith('/frame') else '<div id="host"></div><input type="file" aria-label="Document"><a href="/file.txt">Download</a><iframe src="/frame"></iframe>'))
            await page.goto("https://example.test/")
            await page.evaluate("() => {const root=document.getElementById('host').attachShadow({mode:'open'}); root.innerHTML='<button>Shadow action</button><p>Shadow information</p>'; root.querySelector('button').onclick=()=>root.querySelector('p').textContent='Verified shadow action';}")
            async def run(action, **extra):
                return await page.evaluate(f"request => {{ {source}; return pageOperation(request); }}", {"action":action,"url":page.url,"expires":time.time()+10,**extra})
            snapshot = await run("chrome_snapshot")
            assert snapshot["open_shadow_roots"] == 1 and "Shadow information" in snapshot["text"]
            shadow = next(control for control in snapshot["controls"] if control["name"] == "Shadow action")
            await run("chrome_click", target_id=shadow["target_id"])
            assert "Verified shadow action" in (await run("chrome_snapshot"))["text"]
            snapshot = await run("chrome_snapshot")
            field = next(control for control in snapshot["controls"] if control["input_type"] == "file")
            common = {"target_id":field["target_id"],"upload_id":"test","filename":"document.txt","mime":"text/plain","size":5}
            await run("chrome_upload", stage="begin", **common)
            await run("chrome_upload", stage="chunk", chunk=base64.b64encode(b"hello").decode(), **common)
            await run("chrome_upload", stage="finish", **common)
            assert await page.locator('input[type=file]').evaluate("async el => await el.files[0].text()") == "hello"
            frame = page.frames[1]
            result = await frame.evaluate(f"request => {{ {source}; return pageOperation(request); }}", {"action":"chrome_snapshot","url":page.url,"frame_url":frame.url,"frame_id":2,"expires":time.time()+5})
            assert result["frame_id"] == 2
        finally:
            await browser.close()
