from __future__ import annotations

import asyncio
import json
import subprocess
import time
from pathlib import Path
from types import SimpleNamespace

import pytest

from app.agent import development_scheduler as ds
from app.agent.development_worker import OllamaDevelopmentProvider
from app.providers.base import ChatMessage


@pytest.fixture
def scheduler(tmp_path, monkeypatch):
    monkeypatch.setattr(ds, "root", lambda: tmp_path)
    monkeypatch.setattr(ds, "kill_switch_active", lambda: False)
    return ds.DevelopmentScheduler()


def item(content="Status: accepted\nImplement a small fix"):
    return ds.source_item("drive:document1", "RFC: small fix", content)


def test_revision_changes_revoke_queue_approval():
    state = ds.default_state()
    first = item()
    ds.upsert(state, first)
    state["items"][first["id"]].update(status="queued", approved_revision=first["revision"])
    ds.upsert(state, first)
    assert state["items"][first["id"]]["status"] == "queued"
    ds.upsert(state, item("Different requirement"))
    assert state["items"][first["id"]]["approved_revision"] == ""
    assert state["items"][first["id"]]["status"] == "available"
    assert len(state["items"]) == 1


@pytest.mark.parametrize("url", ["https://example.com", "http://10.0.0.2:11434", "http://127.0.0.1:11434/evil", "http://user@localhost:11434", "http://localhost:11434?key=abc"])
def test_remote_or_ambiguous_endpoint_rejected(url):
    with pytest.raises(ValueError):
        ds.DevelopmentConfig(ollama_url=url)


@pytest.mark.asyncio
async def test_selection_requires_current_revision(scheduler):
    await scheduler.import_drive("document1", "RFC: small fix", "original")
    old = scheduler.public()["items"][0]
    await scheduler.import_drive("document1", "RFC: small fix", "changed")
    with pytest.raises(ValueError, match="changed"):
        await scheduler.select(old["id"], old["revision"], True)
    current = scheduler.public()["items"][0]
    await scheduler.select(current["id"], current["revision"], True)
    assert scheduler.public()["items"][0]["status"] == "queued"
    assert "content" not in current


@pytest.mark.asyncio
async def test_no_automatic_replay_after_worker_loss(scheduler, monkeypatch):
    state = ds.default_state()
    i = item()
    ds.upsert(state, i)
    state["items"][i["id"]].update(status="running", approved_revision=i["revision"])
    state["runs"] = [{"id": "lost", "task_id": "task", "item_id": i["id"], "revision": i["revision"], "status": "running", "started_at": time.time(), "pid": 1, "created": 1}]
    scheduler.save(state)
    monkeypatch.setattr(scheduler, "owned_process", lambda run: None)
    await scheduler.tick()
    after = scheduler.state()
    assert after["runs"][0]["status"] == "interrupted"
    assert after["items"][i["id"]]["approved_revision"] == ""
    assert after["failures"] == 1


@pytest.mark.asyncio
async def test_concurrent_start_and_failure_breaker(scheduler):
    state = ds.default_state()
    state["runs"] = [{"id": "active", "status": "running"}]
    scheduler.save(state)
    with pytest.raises(ValueError, match="already running"):
        await scheduler.launch()
    state["runs"] = []
    state["failures"] = 3
    scheduler.save(state)
    with pytest.raises(ValueError, match="Failure limit"):
        await scheduler.launch()


@pytest.mark.asyncio
async def test_schedule_scan_then_launch_once(scheduler, monkeypatch):
    state = ds.default_state()
    state["config"]["enabled"] = True
    state["next_run"] = 0
    scheduler.save(state)
    calls = []
    async def scan(): calls.append("scan")
    async def launch(): calls.append("launch")
    monkeypatch.setattr(scheduler, "scan", scan)
    monkeypatch.setattr(scheduler, "launch", launch)
    await scheduler.tick()
    await scheduler.tick()
    assert calls == ["scan", "launch"]


@pytest.mark.asyncio
async def test_image_turns_go_only_to_vision_model():
    calls = []
    class Provider:
        def __init__(self, name): self.name = name
        async def chat(self, messages, **kwargs):
            calls.append((self.name, kwargs.get("tools")))
            return self.name
        async def chat_stream(self, messages, **kwargs):
            calls.append((self.name, None))
            yield self.name
    provider = OllamaDevelopmentProvider(Provider("coder"), Provider("vision"))
    text = [ChatMessage("user", "Implement fix")]
    image = [ChatMessage("user", [{"type": "image_url", "image_url": {"url": "data:image/png;base64,abc"}}])]
    assert await provider.chat(text, tools=[{"function": {"name": "filesystem"}}]) == "coder"
    assert await provider.chat(image, tools=[{"function": {"name": "desktop"}}]) == "vision"
    assert [c async for c in provider.chat_stream(image)] == ["vision"]
    assert calls[0][1][0]["function"]["name"] == "filesystem"
    assert calls[1][1][0]["function"]["name"] == "desktop"


def test_repository_intake_reads_base_not_dirty_checkout(tmp_path):
    def git(*args):
        return subprocess.run(["git", *args], cwd=tmp_path, check=True, capture_output=True, text=True).stdout
    git("init")
    git("config", "user.email", "test@local")
    git("config", "user.name", "test")
    (tmp_path / "docs/rfcs").mkdir(parents=True)
    accepted = tmp_path / "docs/rfcs/0001-fix.md"
    accepted.write_text("# Fix\nStatus: accepted\nOriginal requirement", encoding="utf-8")
    (tmp_path / "docs/rfcs/0002-done.md").write_text("Status: implemented", encoding="utf-8")
    git("add", ".")
    git("commit", "-m", "baseline")
    git("branch", "development")
    accepted.write_text("Status: accepted\nDirty replacement", encoding="utf-8")
    rows = ds.repo_items(ds.DevelopmentConfig(repo=str(tmp_path)))
    assert len(rows) == 1
    assert "Original requirement" in rows[0]["content"]


@pytest.mark.asyncio
async def test_stale_action_cannot_receive_confirmation(scheduler):
    state = ds.default_state()
    state["runs"] = [{"id": "active", "task_id": "task1", "status": "running"}]
    scheduler.save(state)
    ds.write_json(ds.root() / "active/status.json", {"waiting_for_confirmation": True, "confirmation_payload": "current"})
    with pytest.raises(ValueError, match="changed"):
        await scheduler.command("active", "task1", "old", True)
    assert not (ds.root() / "active/command.json").exists()
    await scheduler.command("active", "task1", "current", False)
    assert ds.read_json(ds.root() / "active/command.json")["approved"] is False


@pytest.mark.asyncio
async def test_drive_refresh_failure_revokes_cached_approval(scheduler, monkeypatch):
    from app.tools.mcp_runtime import MCP
    from app.tools.base import ToolResult
    await scheduler.import_drive("document1", "RFC small fix", "requirements")
    state = scheduler.state()
    state["config"].update(drive_folder_id="folder", drive_search_tool="search", drive_fetch_tool="fetch")
    i = next(iter(state["items"].values()))
    i.update(status="queued", approved_revision=i["revision"])
    scheduler.save(state)
    monkeypatch.setattr(ds, "repo_items", lambda config: [])
    async def broken(*args): return ToolResult(False, "", error="Disconnected")
    monkeypatch.setattr(MCP, "call", broken)
    await scheduler.scan()
    i = scheduler.public()["items"][0]
    assert i["status"] == "needs_refresh"
    assert i["approved_revision"] == ""


@pytest.mark.asyncio
async def test_close_keeps_schedule_preference(scheduler):
    state = ds.default_state()
    state["config"]["enabled"] = True
    scheduler.save(state)
    await scheduler.close()
    assert scheduler.state()["config"]["enabled"] is True


def test_lease_prevents_another_scheduler(scheduler):
    scheduler.claim()
    with pytest.raises(ValueError, match="owns"):
        ds.DevelopmentScheduler().claim()
    scheduler.release()


@pytest.mark.asyncio
async def test_priority_reservation_skips_all_inference(scheduler, monkeypatch):
    state = ds.default_state()
    state["config"].update(enabled=True, resource_hold="Grokbot priority reverse-engineering tickets")
    state["next_run"] = 0
    scheduler.save(state)
    async def unexpected(*args): raise AssertionError("Reserved models must not be probed or called")
    monkeypatch.setattr(ds, "model_capabilities", unexpected)
    monkeypatch.setattr(scheduler, "scan", unexpected)
    await scheduler.tick()
    with pytest.raises(ValueError, match="Grokbot"):
        await scheduler.launch()
    assert scheduler.state()["runs"] == []


@pytest.mark.asyncio
async def test_native_ollama_uses_real_tool_protocol_and_thinking_flag():
    import httpx
    from app.agent.development_worker import NativeOllamaProvider
    captured = []
    def handler(request):
        body = json.loads(request.content)
        captured.append(body)
        return httpx.Response(200, json={"message": {"role": "assistant", "content": "", "tool_calls": [{"function": {"name": "filesystem", "arguments": {"action": "read", "path": "test.py"}}}]}, "eval_count": 20})
    provider = NativeOllamaProvider("http://127.0.0.1:11434", "coder")
    await provider.native.aclose()
    provider.native = httpx.AsyncClient(base_url="http://127.0.0.1:11434", transport=httpx.MockTransport(handler))
    try:
        result = await provider.chat([ChatMessage("user", "Read file")], tools=[{"type": "function", "function": {"name": "filesystem", "parameters": {"type": "object"}}}], thinking=True, max_tokens=256)
        assert captured[0]["think"] is False
        assert captured[0]["options"]["num_predict"] == 256
        assert result.tool_calls[0]["id"]
        assert json.loads(result.tool_calls[0]["function"]["arguments"])["path"] == "test.py"
    finally:
        await provider.close()


def test_native_ollama_translates_images_and_tool_results():
    from app.agent.development_worker import NativeOllamaProvider
    provider = NativeOllamaProvider.__new__(NativeOllamaProvider)
    provider.model = "vision"
    provider.context_size = 16384
    messages = [ChatMessage("user", [{"type": "text", "text": "Inspect screenshot"}, {"type": "image_url", "image_url": {"url": "data:image/png;base64,abcd"}}]), ChatMessage("assistant", "", tool_calls=[{"id": "call1", "type": "function", "function": {"name": "desktop", "arguments": '{"action":"screenshot"}'}}]), ChatMessage("tool", "Captured", tool_call_id="call1")]
    body = provider.arguments(messages)
    assert body["messages"][0]["images"] == ["abcd"]
    assert body["messages"][1]["tool_calls"][0]["function"]["arguments"] == {"action": "screenshot"}
    assert body["messages"][2]["tool_name"] == "desktop"


@pytest.mark.asyncio
async def test_worker_cannot_recursively_schedule(monkeypatch):
    from app.tools.self_development import SelfDevelopmentTool
    monkeypatch.setenv("ANZU_DEVELOPMENT_MISSION", "test-mission")
    result = await SelfDevelopmentTool().execute("run")
    assert not result.success
    assert "cannot control" in result.error


@pytest.mark.asyncio
async def test_duplicate_repo_and_drive_content_cannot_both_queue(scheduler):
    await scheduler.import_drive("first", "RFC first", "Identical RFC")
    await scheduler.import_drive("second", "RFC second", "Identical RFC")
    first, second = scheduler.public()["items"]
    await scheduler.select(first["id"], first["revision"], True)
    with pytest.raises(ValueError, match="another source"):
        await scheduler.select(second["id"], second["revision"], True)


def test_mcp_native_text_blocks_are_parsed():
    from app.tools.base import ToolResult
    payload = ds.mcp_payload(ToolResult(True, "TextContent repr", data={"mcp_text": '{"files":[{"id":"doc"}]}' }))
    assert payload["files"][0]["id"] == "doc"


def test_development_worker_paths_do_not_expand_to_owner_drives(monkeypatch, tmp_path):
    from app.config import sanitize_allowed_directories
    monkeypatch.setenv("ANZU_DEVELOPMENT_MISSION", "mission")
    monkeypatch.delenv("PYTEST_CURRENT_TEST", raising=False)
    monkeypatch.setattr("app.config.default_allowed_directories", lambda: ["C:/"])
    assert sanitize_allowed_directories([str(tmp_path)]) == [str(tmp_path)]


@pytest.mark.asyncio
async def test_launch_keeps_owner_model_and_uses_trusted_code(scheduler, tmp_path, monkeypatch):
    from app.config import AppSettings
    from app.agent.worktrees import WorktreeSpec
    owner = AppSettings()
    owner.inference.remote_model = "owner-chat-model"
    monkeypatch.setattr(ds, "load_settings", lambda: owner)
    spec = WorktreeSpec("spec", str(tmp_path / "repo"), str(tmp_path / "candidate"), "jarvis/self-dev-test", "a" * 40, "today")
    monkeypatch.setattr(ds, "create_worktree", lambda *args, **kwargs: spec)
    async def capabilities(*args): return {}
    monkeypatch.setattr(ds, "model_capabilities", capabilities)
    monkeypatch.setattr(ds.psutil, "Process", lambda *args: SimpleNamespace(create_time=lambda: 123))
    captured = {}
    def popen(command, **kwargs):
        captured.update(command=command, **kwargs)
        return SimpleNamespace(pid=99999)
    monkeypatch.setattr(ds.subprocess, "Popen", popen)
    await scheduler.import_drive("ticket", "RFC fix", "Implement one fix")
    i = scheduler.public()["items"][0]
    await scheduler.select(i["id"], i["revision"], True)
    state = await scheduler.launch()
    run = state["runs"][0]
    control = ds.root() / run["id"]
    saved = ds.read_json(control / "data/settings.json")
    assert saved["inference"]["remote_model"] == "anzu-coder-27b:latest"
    assert saved["allowed_directories"] == [spec.path]
    assert saved["front_responder"]["enabled"] is False
    assert "code_worker" in saved["disabled_tools"]
    assert "self_development" in saved["disabled_tools"]
    assert owner.inference.remote_model == "owner-chat-model"
    assert captured["env"]["PYTHONPATH"] == str(Path(ds.__file__).resolve().parents[2])
    assert captured["env"]["ANZU_DEVELOPMENT_MISSION"] == run["id"]
    assert captured["cwd"] == str(control)
    assert run["base_sha"] == spec.start_commit
    scheduler.release()
