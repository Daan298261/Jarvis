from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.agent.recovery import UNAVAILABLE, alternatives_for
from app.ingest.fallbacks import _browser_use_payload, extract_with_browser_use
from app.ingest.adapters.base import IngestContext
from app.policy.computer_permissions import (
    apply_grant,
    evaluate_tool_permissions,
    permission_ids_for_tool,
    reset_computer_permission_state,
)
from app.tools.base import ToolResult
from app.workers.browser import (
    BrowserUseBackend,
    DEFAULT_BROWSER_BACKEND,
    format_browser_use_output,
    playwright_is_default,
    reset_browser_use_session,
    structured_payload_from_history,
)


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

    async def fake_invoke(task, settings, *, start_url=None):
        assert "example.com" in task
        return history

    monkeypatch.setattr(backend, "_invoke", fake_invoke)
    result = await backend.run("read", "https://example.com")
    assert result.success is True
    assert result.data["extracted_text"] == "done reading"
    assert result.data["backend"] == "browser-use"
    assert "done reading" in result.output


def test_structured_payload_from_history_collects_trace():
    action = SimpleNamespace(model_dump=lambda **_: {"click": {"index": 1}})
    model_output = SimpleNamespace(action=[action])
    result_item = SimpleNamespace(extracted_content="caption text", error=None)
    state = SimpleNamespace(url="https://example.com/post", title="Post title", to_dict=lambda: {})
    history_item = SimpleNamespace(model_output=model_output, result=[result_item], state=state)
    history = SimpleNamespace(final_result=lambda: "final answer", history=[history_item])

    payload = structured_payload_from_history(history, start_url="https://example.com")
    assert payload["url"] == "https://example.com/post"
    assert payload["title"] == "Post title"
    assert payload["extracted_text"] == "final answer"
    assert payload["action_trace"][0]["step"] == 1
    assert payload["action_trace"][0]["actions"]


def test_format_browser_use_output_includes_title_and_body():
    text = format_browser_use_output(
        {"title": "Hello", "url": "https://example.com", "extracted_text": "Body copy"}
    )
    assert "Hello" in text
    assert "Body copy" in text


@pytest.mark.asyncio
async def test_session_reuse_flag(permission_store, monkeypatch):
    import app.workers.browser as browser_mod

    browser_mod.reset_browser_use_session()
    apply_grant("network.internet", "always")
    backend = BrowserUseBackend()
    monkeypatch.setattr(backend, "available", lambda: True)

    history = SimpleNamespace(final_result=lambda: "ok", history=[])

    async def fake_invoke(task, settings, *, start_url=None):
        return history

    monkeypatch.setattr(backend, "_invoke", fake_invoke)

    browser_mod._BROWSER_SESSION = object()
    browser_mod._SESSION_CREATED = False
    first = await backend.run("one", "https://a.test")
    assert first.success is True
    assert first.data["session_reused"] is False

    browser_mod._SESSION_CREATED = True
    second = await backend.run("two", "https://b.test")
    assert second.success is True
    assert second.data["session_reused"] is True


def test_alternatives_for_missing_package_unchanged():
    tools = [item.tool for item in alternatives_for("browser_use", UNAVAILABLE)]
    assert tools[0] == "browser"
    assert "web_fetch" in tools


def test_browser_use_payload_prefers_structured_data():
    result = ToolResult(
        True,
        "Title: Hello\nBody",
        data={
            "extracted_text": "structured body",
            "title": "Hello",
            "url": "https://example.com/x",
            "action_trace": [{"step": 1}],
            "steps": 2,
        },
    )
    payload = _browser_use_payload(result)
    assert payload["text"] == "structured body"
    assert payload["title"] == "Hello"
    assert payload["url"] == "https://example.com/x"
    assert payload["action_trace"]


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


def test_probe_missing_mentions_install_now():
    backend = BrowserUseBackend()
    if backend.available():
        pytest.skip("browser-use package is installed in this environment")
    probe = backend.probe()
    assert probe["status"] == "missing"
    assert "install now" in probe["detail"].lower()
