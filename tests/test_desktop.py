from types import SimpleNamespace

from app.tools.desktop import DesktopTool, UNAVAILABLE, resolve_named_control


class _Child:
    def __init__(self, present: bool) -> None:
        self.present = present
        self.clicked = False

    def exists(self, timeout=1):
        return self.present

    def click_input(self):
        self.clicked = True


class _Window:
    def __init__(self) -> None:
        self.lookups: list[dict] = []
        self.children = {
            ("auto_id", "Save"): _Child(True),
        }

    def child_window(self, **kwargs):
        self.lookups.append(kwargs)
        if kwargs.get("auto_id") == "Save":
            return self.children[("auto_id", "Save")]
        return _Child(False)


def test_named_control_prefers_title_then_auto_id():
    window = _Window()
    control = resolve_named_control(window, "Save")
    assert control is not None
    assert any("title" in item for item in window.lookups)
    assert any(item.get("auto_id") == "Save" for item in window.lookups)
    control.click_input()
    assert control.clicked is True


def test_missing_named_control_returns_none():
    assert resolve_named_control(_Window(), "NoSuchControl") is None
    assert resolve_named_control(_Window(), "") is None


async def test_desktop_ui_actions_are_unavailable_off_windows(monkeypatch):
    monkeypatch.setattr("app.tools.desktop.windows_ui_available", lambda: False)
    tool = DesktopTool()
    result = await tool.execute(action="windows")
    assert result.success is False
    assert UNAVAILABLE in result.error
    click = await tool.execute(action="click", name="OK")
    assert click.success is False
    assert "unavailable" in click.error.lower()


async def test_named_click_does_not_use_coordinates(monkeypatch):
    window = _Window()
    desktop = SimpleNamespace(window=lambda **kwargs: window, windows=lambda: [])
    monkeypatch.setattr("app.tools.desktop.windows_ui_available", lambda: True)

    class _Desktop:
        def __init__(self, backend=None):
            pass

        def window(self, **kwargs):
            return window

        def windows(self):
            return []

    import sys
    import types

    fake = types.ModuleType("pywinauto")
    fake.Desktop = _Desktop
    monkeypatch.setitem(sys.modules, "pywinauto", fake)
    tool = DesktopTool()
    result = await tool.execute(action="click", title="Notepad", name="Save")
    assert result.success, result.error
    assert "Clicked control Save" in result.output
    missing = await tool.execute(action="click", title="Notepad", name="Print")
    assert missing.success is False
    assert "Do not use coordinates yet" in missing.error
