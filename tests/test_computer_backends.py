from types import SimpleNamespace

from app.tools.base import ToolResult
from app.workers.computer import ComputerUseBackend, NativeWindowsBackend, preferred_computer_backend


def test_base_computer_backend_does_not_raise():
    backend = ComputerUseBackend()
    probe = backend.probe()
    assert probe["available"] is False
    assert probe["status"] == "unavailable"
    assert backend.build_command("open notepad") == []


async def test_base_computer_backend_run_requires_goal_and_availability():
    backend = ComputerUseBackend()
    missing = await backend.run("")
    assert missing.success is False
    assert "goal is required" in missing.error
    unavailable = await backend.run("open notepad")
    assert unavailable.success is False
    assert "not available" in unavailable.error.lower()


async def test_native_backend_run_focuses_and_inspects(monkeypatch):
    backend = NativeWindowsBackend()
    monkeypatch.setattr(backend, "available", lambda: True)
    calls: list[dict] = []

    async def fake_execute(self, **kwargs):
        calls.append(kwargs)
        action = kwargs.get("action")
        if action == "focus":
            return ToolResult(True, "Focused Notepad")
        if action == "inspect":
            return ToolResult(
                True,
                "Window: Notepad\n- Save (Button id=saveBtn)",
                data={"controls": [{"name": "Save", "automation_id": "saveBtn"}]},
            )
        return ToolResult(False, "", error=f"unexpected {action}")

    monkeypatch.setattr("app.tools.desktop.DesktopTool.execute", fake_execute)
    result = await backend.run("save the file", app="Notepad")
    assert result.success is True
    assert result.data["backend"] == "windows_ui"
    assert result.data["inspect_ok"] is True
    assert "Focused Notepad" in result.output
    assert "named desktop controls" in result.output.lower()
    assert [item["action"] for item in calls] == ["focus", "inspect"]


async def test_native_backend_run_lists_windows_when_focus_fails(monkeypatch):
    backend = NativeWindowsBackend()
    monkeypatch.setattr(backend, "available", lambda: True)

    async def fake_execute(self, **kwargs):
        if kwargs.get("action") == "focus":
            return ToolResult(False, "", error="window not found")
        if kwargs.get("action") == "windows":
            return ToolResult(True, "Calculator\nSettings")
        return ToolResult(False, "", error="unexpected")

    monkeypatch.setattr("app.tools.desktop.DesktopTool.execute", fake_execute)
    result = await backend.run("click OK", app="Notepad")
    assert result.success is False
    assert "Calculator" in result.output
    assert "window not found" in result.error


def test_preferred_backend_never_crashes():
    chosen = preferred_computer_backend()
    assert chosen.probe()["id"] in {"windows_ui", "ufo", "cua"}
    assert isinstance(chosen, NativeWindowsBackend) or chosen.available()


async def test_desktop_inspect_is_dispatched(monkeypatch):
    from app.tools.desktop import DesktopTool

    seen: dict[str, object] = {}

    def fake_uia(self, action, kwargs):
        seen["action"] = action
        seen["title"] = kwargs.get("title")
        return ToolResult(True, "inspected", data={"controls": []})

    monkeypatch.setattr("app.tools.desktop.windows_ui_available", lambda: True)
    monkeypatch.setattr(DesktopTool, "_uia_action", fake_uia)

    class _Desktop:
        def __init__(self, backend=None):
            pass

        def windows(self):
            return []

        def window(self, **kwargs):
            return SimpleNamespace(window_text=lambda: "Notepad")

    import sys
    import types

    fake = types.ModuleType("pywinauto")
    fake.Desktop = _Desktop
    monkeypatch.setitem(sys.modules, "pywinauto", fake)
    result = await DesktopTool().execute(action="inspect", title="Notepad")
    assert result.success is True
    assert seen["action"] == "inspect"
    assert seen["title"] == "Notepad"
