from app.tools.desktop import DesktopTool, desktop_automation_available
from app.tools.semantic_ui import UiControl, click_backend, format_control_list, resolve_control


CONTROLS = [
    UiControl(name="File", control_type="MenuItem", automation_id="FileMenu"),
    UiControl(name="Save", control_type="Button", automation_id="saveBtn"),
    UiControl(name="Untitled - Notepad", control_type="Window"),
    UiControl(name="Text Editor", control_type="Edit", automation_id="editor"),
]


def test_resolve_prefers_automation_id_then_name():
    control, method = resolve_control(CONTROLS, automation_id="saveBtn")
    assert control is not None
    assert control.name == "Save"
    assert method == "automation_id"

    control, method = resolve_control(CONTROLS, name="Save")
    assert method == "name"
    assert control.automation_id == "saveBtn"

    control, method = resolve_control(CONTROLS, name="Save", control_type="Button")
    assert method == "control_type+name"


def test_resolve_fuzzy_and_unresolved():
    control, method = resolve_control(CONTROLS, name="note")
    assert method == "fuzzy_name"
    assert "Notepad" in control.name

    missing, method = resolve_control(CONTROLS, name="Print")
    assert missing is None
    assert method == "unresolved"


def test_click_backend_uses_coordinates_only_as_fallback():
    assert click_backend(name="Save") == "semantic"
    assert click_backend(automation_id="saveBtn") == "semantic"
    assert click_backend(x=10, y=20) == "coordinate"
    assert click_backend() == "missing"
    assert click_backend(name="Save", x=1, y=2) == "semantic"


def test_format_control_list_includes_type_and_id():
    text = format_control_list(CONTROLS, limit=2)
    assert "Save" in text
    assert "id=saveBtn" in text


async def test_desktop_uia_actions_are_unavailable_off_windows():
    if desktop_automation_available():
        return
    tool = DesktopTool()
    for action in ("windows", "inspect", "focus", "click", "type", "keys", "wait"):
        result = await tool.execute(action=action, title="Notepad", name="File")
        assert result.success is False
        assert "Windows UI Automation" in (result.error or "")


async def test_desktop_apps_still_works_without_uia():
    tool = DesktopTool()
    result = await tool.execute(action="apps")
    assert result.success
    assert result.output
