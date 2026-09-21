import pytest

from app.config import is_ephemeral_workspace_path, sanitize_allowed_directories
from app.systems.health_notify import issue_fingerprint, spoken_health_summary
from app.tools.desktop import parse_desktop_goal
from app.workers.computer import NativeWindowsBackend


def test_ephemeral_pytest_paths_are_stripped(tmp_path, monkeypatch):
    monkeypatch.delenv("PYTEST_CURRENT_TEST", raising=False)
    leaked = r"C:\Users\daanv\AppData\Local\Temp\pytest-of-daanv\pytest-235\test_existing_windows_default_0"
    assert is_ephemeral_workspace_path(leaked)
    cleaned = sanitize_allowed_directories([leaked])
    assert leaked not in cleaned
    assert any(path.lower().endswith("\\documents") or path.lower().endswith("/documents") for path in cleaned)


def test_parse_desktop_goal_click_and_type():
    steps = parse_desktop_goal('Click Save and type "hello" into Search', app="Notepad")
    actions = [step["action"] for step in steps]
    assert "type" in actions
    assert "click" in actions
    click = next(step for step in steps if step["action"] == "click")
    assert click["name"].lower().startswith("save")
    assert click["title"] == "Notepad"


def test_parse_desktop_goal_matches_inspected_control():
    steps = parse_desktop_goal("Open File", controls=[{"name": "File"}, {"name": "Edit"}])
    assert steps == [{"action": "click", "name": "File"}]


@pytest.mark.asyncio
async def test_native_backend_executes_named_click(monkeypatch):
    backend = NativeWindowsBackend()
    monkeypatch.setattr(backend, "available", lambda: True)

    calls: list[dict] = []

    class FakeDesktop:
        async def execute(self, **kwargs):
            calls.append(kwargs)
            action = kwargs.get("action")
            if action == "inspect":
                from app.tools.base import ToolResult

                return ToolResult(True, "controls", data={"controls": [{"name": "Save"}]})
            from app.tools.base import ToolResult

            return ToolResult(True, f"{action} ok")

    monkeypatch.setattr("app.tools.desktop.DesktopTool", FakeDesktop)
    result = await backend.run("click Save", app="Notepad")
    assert result.success is True
    assert any(item.get("action") == "click" and item.get("name") == "Save" for item in calls)


def test_health_summary_lists_problems():
    checks = [
        {"id": "core", "label": "Core", "status": "ready", "detail": "ok"},
        {"id": "workspace", "label": "Owner workspace", "status": "degraded", "detail": "test leftovers"},
    ]
    assert "Owner workspace" in spoken_health_summary(checks)
    assert "workspace:degraded" in issue_fingerprint(checks)
