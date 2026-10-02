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
    visited_urls_from_history,
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
    assert permission_ids_for_tool("browser_use", {"url": "file:///home/owner/Documents/notes.html", "goal": "read"}) == []


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


@pytest.mark.asyncio
async def test_browser_use_opens_local_file_on_extra_drive(tmp_path, monkeypatch, permission_store):
    from app.tools.browser import resolve_browser_open_url
    from app.tools.browser_use import BrowserUseTool
    from app.tools import browser_use as browser_use_mod

    html = tmp_path / "E" / "notes.html"
    html.parent.mkdir(parents=True)
    html.write_text("<html><body>usb</body></html>", encoding="utf-8")
    expected = resolve_browser_open_url(str(html), [str(tmp_path)])
    seen: dict[str, str | None] = {}

    async def fake_run(goal, url, settings):
        seen["url"] = url
        seen["goal"] = goal
        return ToolResult(True, f"opened {url}", data={"url": url})

    monkeypatch.setattr(browser_use_mod._BACKEND, "run", fake_run)
    apply_grant("network.internet", "deny")
    tool = BrowserUseTool(lambda: {"allowed_directories": [str(tmp_path)]})
    result = await tool.execute(goal="summarize this page", url=str(html))
    assert result.success, result.error
    assert seen["url"] == expected
    blocked = await tool.execute(goal="read passwd", url="file:///etc/passwd")
    assert blocked.success is False
    assert "outside allowed" in (blocked.error or "").lower() or "workspace" in (blocked.error or "").lower()


@pytest.mark.asyncio
async def test_browser_use_blocks_lan_to_wan_history_hops(permission_store, monkeypatch):
    apply_grant("network.internet", "deny")
    apply_grant("network.local", "always")
    backend = BrowserUseBackend()
    monkeypatch.setattr(backend, "available", lambda: True)

    state = SimpleNamespace(url="https://example.test/leaked", title="Leaked", to_dict=lambda: {})
    history = SimpleNamespace(
        final_result=lambda: "should not leak",
        history=[SimpleNamespace(state=state, model_output=None, result=[])],
        structured_output=None,
        agent_steps=lambda: [],
    )

    async def fake_invoke(task, settings, *, start_url=None):
        assert start_url == "http://nas.local/status"
        return history

    monkeypatch.setattr(backend, "_invoke", fake_invoke)
    reset = {"called": False}

    async def fake_reset():
        reset["called"] = True

    monkeypatch.setattr("app.workers.browser.reset_browser_use_session_async", fake_reset)
    result = await backend.run("read status", "http://nas.local/status")
    assert result.success is False
    assert "don't allow" in (result.error or "").lower()
    assert "should not leak" not in (result.output or "")
    assert reset["called"] is True


def test_visited_urls_from_history_includes_navigate_actions():
    action = SimpleNamespace(model_dump=lambda **_: {"navigate": {"url": "https://example.test/next"}})
    item = SimpleNamespace(
        state=SimpleNamespace(url="http://nas.local/a", title="", to_dict=lambda: {}),
        model_output=SimpleNamespace(action=[action]),
    )
    history = SimpleNamespace(history=[item])
    assert visited_urls_from_history(history, start_url="http://nas.local/") == [
        "http://nas.local/",
        "http://nas.local/a",
        "https://example.test/next",
    ]


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


def test_browser_use_session_kwargs_download_to_owner_downloads(tmp_path, monkeypatch):
    from app.workers.browser import browser_use_session_kwargs, _browser_profile_with_downloads

    downloads = tmp_path / "Downloads"
    downloads.mkdir()
    profile_dir = tmp_path / "browser-use-profile"
    monkeypatch.setattr("app.tools.owner_paths.Path.home", classmethod(lambda cls: tmp_path))
    kwargs = browser_use_session_kwargs(True, profile_dir)
    assert kwargs["downloads_path"] == str(downloads)
    assert kwargs["user_data_dir"] == str(profile_dir)
    assert kwargs["keep_alive"] is True
    assert kwargs["headless"] is True

    captured: dict[str, object] = {}

    class AcceptingProfile:
        def __init__(self, **inner):
            captured.update(inner)

    profile = _browser_profile_with_downloads(AcceptingProfile, kwargs)
    assert isinstance(profile, AcceptingProfile)
    assert captured["downloads_path"] == str(downloads)

    class StrictProfile:
        def __init__(self, *, headless, keep_alive, user_data_dir):
            captured.clear()
            captured.update(headless=headless, keep_alive=keep_alive, user_data_dir=user_data_dir)

    slim = _browser_profile_with_downloads(StrictProfile, kwargs)
    assert isinstance(slim, StrictProfile)
    assert "downloads_path" not in captured
