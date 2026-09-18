from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.agent.recovery import UNAVAILABLE, alternatives_for
from app.ingest.fallbacks import extract_with_browser_use
from app.ingest.adapters.base import IngestContext
from app.policy.computer_permissions import (
    apply_grant,
    permission_ids_for_tool,
    reset_computer_permission_state,
)
from app.tools.base import ToolResult
from app.tools.capabilities import optional_workers
from app.workers.browser_structured import browser_use_ingest_payload, browser_use_tool_result_data
from app.workers.browser import (
    BrowserUseBackend,
    DEFAULT_BROWSER_BACKEND,
    format_browser_use_output,
    playwright_is_default,
    reset_browser_use_session,
    structured_payload_from_history,
)
from app.workers.local_llm import local_browser_use_model
from app.config import AppSettings


@pytest.fixture
def permission_store(tmp_path, monkeypatch):
    monkeypatch.setattr("app.policy.computer_permissions.data_dir", lambda: tmp_path)
    reset_computer_permission_state()
    return tmp_path


def test_playwright_stays_default_backend():
    assert DEFAULT_BROWSER_BACKEND == "playwright"
    assert playwright_is_default() is True


def test_browser_use_maps_to_internet_permission(permission_store):
    assert permission_ids_for_tool("browser_use", {"url": "https://example.com", "goal": "read"}) == [
        "network.internet"
    ]
    assert permission_ids_for_tool("browser_use", {"url": "http://192.168.0.10", "goal": "read"}) == [
        "network.local"
    ]


@pytest.mark.asyncio
async def test_browser_use_permission_ask_blocks_backend_async(permission_store):
    backend = BrowserUseBackend()
    result = await backend.run("read the page", "https://example.com")
    assert result.success is False
    assert result.error


@pytest.mark.asyncio
async def test_browser_use_runs_when_network_allowed(permission_store, monkeypatch):
    apply_grant("network.internet", "always")
    backend = BrowserUseBackend()
    monkeypatch.setattr(backend, "available", lambda: True)

    history = MagicMock()
    history.final_result.return_value = "done reading"
    history.history = []
    history.structured_output = None
    history.agent_steps.return_value = []

    async def fake_invoke(task, settings, *, start_url=None):
        assert "example.com" in task
        assert start_url == "https://example.com"
        return history

    monkeypatch.setattr(backend, "_invoke", fake_invoke)
    result = await backend.run("read", "https://example.com")
    assert result.success is True
    assert result.data["extracted_text"] == "done reading"
    assert result.data["backend"] == "browser-use"
    assert result.data["url"] == "https://example.com"
    assert "done reading" in result.output


def test_structured_payload_from_history_collects_trace():
    action = SimpleNamespace(model_dump=lambda **_: {"click": {"index": 1}})
    model_output = SimpleNamespace(action=[action], next_goal="click submit")
    result_item = SimpleNamespace(extracted_content="caption text", error=None)
    state = SimpleNamespace(url="https://example.com/post", title="Post title", to_dict=lambda: {})
    history_item = SimpleNamespace(model_output=model_output, result=[result_item], state=state)
    history = SimpleNamespace(
        final_result=lambda: "final answer",
        history=[history_item],
        structured_output=None,
        agent_steps=lambda: [],
    )

    payload = structured_payload_from_history(history, start_url="https://example.com")
    assert payload["url"] == "https://example.com/post"
    assert payload["title"] == "Post title"
    assert payload["extracted_text"] == "final answer"
    assert payload["action_trace"][0]["step"] == 1
    assert payload["action_trace"][0]["actions"]
    assert payload["action_trace"][0]["next_goal"] == "click submit"


def test_structured_payload_uses_agent_steps_when_no_actions():
    history = SimpleNamespace(
        final_result=lambda: "",
        history=[],
        structured_output=None,
        agent_steps=lambda: ["Step 1:\nActions: []"],
    )
    payload = structured_payload_from_history(history)
    assert payload["action_trace"][0]["summary"].startswith("Step 1")


def test_format_browser_use_output_includes_title_and_body():
    text = format_browser_use_output(
        {"title": "Hello", "url": "https://example.com", "extracted_text": "Body copy", "action_trace": [{}]}
    )
    assert "Hello" in text
    assert "Body copy" in text
    assert "Action trace" in text


def test_browser_use_tool_result_data_shape():
    structured = {
        "url": "https://example.com/p",
        "title": "T",
        "extracted_text": "body",
        "action_trace": [{"step": 1}],
        "steps": 3,
    }
    data = browser_use_tool_result_data(
        goal="g",
        structured=structured,
        start_url="https://example.com",
        session_reused=True,
    )
    assert data["goal"] == "g"
    assert data["extracted_text"] == "body"
    assert data["session_reused"] is True
    assert data["action_trace"]


@pytest.mark.asyncio
async def test_shared_browser_session_reuses_single_instance(permission_store, monkeypatch):
    import app.workers.browser as browser_mod

    await browser_mod.reset_browser_use_session_async()
    apply_grant("network.internet", "always")
    backend = BrowserUseBackend()
    monkeypatch.setattr(backend, "available", lambda: True)

    created: list[Any] = []

    class FakeSession:
        async def start(self):
            return None

    def fake_build(settings):
        session = FakeSession()
        created.append(session)
        return session

    monkeypatch.setattr(backend, "_build_browser_session", fake_build)

    first = await backend._shared_browser_session(AppSettings())
    second = await backend._shared_browser_session(AppSettings())
    assert first is second
    assert len(created) == 1
    assert browser_mod._SESSION_REUSED is True


@pytest.mark.asyncio
async def test_run_marks_session_reused_on_second_invoke(permission_store, monkeypatch):
    import app.workers.browser as browser_mod

    await browser_mod.reset_browser_use_session_async()
    apply_grant("network.internet", "always")
    backend = BrowserUseBackend()
    monkeypatch.setattr(backend, "available", lambda: True)

    history = SimpleNamespace(
        final_result=lambda: "ok",
        history=[],
        structured_output=None,
        agent_steps=lambda: [],
    )

    class FakeSession:
        async def start(self):
            return None

    monkeypatch.setattr(backend, "_build_browser_session", lambda _settings: FakeSession())

    async def fake_invoke(task, settings, *, start_url=None):
        await backend._shared_browser_session(settings)
        return history

    monkeypatch.setattr(backend, "_invoke", fake_invoke)

    first = await backend.run("one", "https://a.test")
    second = await backend.run("two", "https://b.test")
    assert first.success and second.success
    assert first.data["session_reused"] is False
    assert second.data["session_reused"] is True


def test_alternatives_for_missing_package_unchanged():
    tools = [item.tool for item in alternatives_for("browser_use", UNAVAILABLE)]
    assert tools[0] == "browser"
    assert "web_fetch" in tools


def test_browser_use_ingest_payload_prefers_structured_data():
    payload = browser_use_ingest_payload(
        data={
            "extracted_text": "structured body",
            "title": "Hello",
            "url": "https://example.com/x",
            "action_trace": [{"step": 1}],
            "steps": 2,
            "session_reused": True,
        },
        output="Title: Hello\nBody",
    )
    assert payload["text"] == "structured body"
    assert payload["title"] == "Hello"
    assert payload["url"] == "https://example.com/x"
    assert payload["action_trace"]
    assert payload["session_reused"] is True


@pytest.mark.asyncio
async def test_ingest_uses_structured_browser_use_fields():
    ctx = IngestContext(url="https://example.com/post", platform="web", provider_url="", headless=True)
    tool = AsyncMock()
    tool.execute = AsyncMock(
        return_value=ToolResult(
            True,
            "ignored",
            data={
                "extracted_text": "See https://cdn.example/use.jpg",
                "title": "Use title",
                "url": "https://example.com/post",
                "action_trace": [{"step": 1, "actions": [{"go": "url"}]}],
                "steps": 1,
            },
        )
    )
    artifact = await extract_with_browser_use(ctx, tool)
    assert artifact is not None
    assert artifact.title == "Use title"
    assert artifact.metadata["tier"] == "browser_use"
    assert artifact.metadata["action_trace"]
    assert "https://cdn.example/use.jpg" in artifact.images


def test_probe_missing_mentions_install_now_and_installable():
    backend = BrowserUseBackend()
    if backend.available():
        pytest.skip("browser-use package is installed in this environment")
    probe = backend.probe()
    assert probe["status"] == "missing"
    assert probe.get("installable") is True
    assert "install now" in probe["detail"].lower()
    assert probe.get("install_worker_id") == "browser-use"


def test_optional_worker_catalog_installable_for_missing_browser_use():
    backend = BrowserUseBackend()
    if backend.available():
        pytest.skip("browser-use package is installed in this environment")
    workers = {item["id"]: item for item in optional_workers()}
    item = workers["browser-use"]
    assert item["installable"] is True
    assert item["status"] == "missing"


def test_local_browser_use_model_prefers_settings():
    settings = AppSettings(browser={"browser_use_model": "Qwen3.5-27B", "headless": True})
    assert local_browser_use_model(settings) == "Qwen3.5-27B"
