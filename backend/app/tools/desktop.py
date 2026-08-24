from __future__ import annotations

import asyncio
import platform
import time
from typing import Any

from .base import RiskLevel, Tool, ToolResult
from .semantic_ui import UiControl, click_backend, format_control_list, resolve_control


def desktop_automation_available() -> bool:
    return platform.system() == "Windows"


def _unavailable(action: str) -> ToolResult:
    return ToolResult(
        False,
        "",
        error=(
            f"desktop {action} needs Windows UI Automation (pywinauto). "
            "This environment has no native desktop session. "
            "Use screenshot/apps here, or run Jarvis on the Windows PC."
        ),
    )


def _collect_controls(window: Any) -> list[UiControl]:
    controls: list[UiControl] = []
    try:
        descendants = window.descendants()
    except Exception:
        descendants = []
    for child in descendants:
        try:
            text = (child.window_text() or "").strip()
            info = getattr(child, "element_info", None)
            auto_id = str(getattr(info, "automation_id", "") or "")
            ctype = str(getattr(info, "control_type", "") or "")
            enabled = bool(getattr(info, "enabled", True))
            if not text and not auto_id:
                continue
            controls.append(
                UiControl(
                    name=text or auto_id,
                    automation_id=auto_id,
                    control_type=ctype,
                    enabled=enabled,
                    handle=child,
                )
            )
        except Exception:
            continue
    return controls


def _find_window(desktop: Any, title: str | None) -> Any:
    needle = (title or "").strip()
    if needle:
        return desktop.window(title_re=f".*{needle}.*")
    windows = [w for w in desktop.windows() if w.window_text()]
    if not windows:
        raise RuntimeError("No visible windows")
    return windows[0]


def _coordinate_click(x: int, y: int) -> None:
    import ctypes

    ctypes.windll.user32.SetCursorPos(int(x), int(y))
    ctypes.windll.user32.mouse_event(2, 0, 0, 0, 0)
    ctypes.windll.user32.mouse_event(4, 0, 0, 0, 0)


class DesktopTool(Tool):
    name = "desktop"
    description = (
        "Interact with native Windows applications using UI Automation / pywinauto. "
        "Actions: screenshot, apps, windows, inspect, focus, click, type, keys, wait. "
        "Always inspect or use a named control (name / automation_id) before coordinates. "
        "Coordinate click is last resort only."
    )
    risk = RiskLevel.HIGH
    parameters = {
        "type": "object",
        "properties": {
            "action": {
                "type": "string",
                "enum": ["screenshot", "apps", "windows", "inspect", "focus", "click", "type", "keys", "wait"],
            },
            "title": {"type": "string", "description": "Window title or substring"},
            "name": {"type": "string", "description": "Visible control name"},
            "automation_id": {"type": "string"},
            "control_type": {"type": "string", "description": "Button, Edit, MenuItem, ..."},
            "text": {"type": "string"},
            "x": {"type": "integer"},
            "y": {"type": "integer"},
            "path": {"type": "string"},
            "timeout_seconds": {"type": "integer", "default": 10},
        },
        "required": ["action"],
    }

    async def execute(self, **kwargs: Any) -> ToolResult:
        action = kwargs.get("action")
        try:
            if action == "screenshot":
                from .screenshot import capture_screen

                path = capture_screen(kwargs.get("path"))
                return ToolResult(True, f"Saved screenshot to {path}", data={"path": path})
            if action == "apps":
                import psutil

                names = sorted({p.info["name"] for p in psutil.process_iter(["name"]) if p.info["name"]})
                return ToolResult(True, "\n".join(names[:400]))
            if action not in {"windows", "inspect", "focus", "click", "type", "keys", "wait"}:
                return ToolResult(False, "", error=f"Unknown action {action}")
            if not desktop_automation_available():
                return _unavailable(str(action))
            return await asyncio.to_thread(self._uia_action, action, kwargs)
        except Exception as exc:
            return ToolResult(False, "", error=str(exc))

    def _uia_action(self, action: str, kwargs: dict[str, Any]) -> ToolResult:
        try:
            from pywinauto import Desktop
        except Exception as exc:
            return ToolResult(False, "", error=f"pywinauto is unavailable: {exc}")

        desktop = Desktop(backend="uia")
        if action == "windows":
            titles = [w.window_text() for w in desktop.windows() if w.window_text()]
            return ToolResult(True, "\n".join(titles[:200]) or "No windows", data={"windows": titles[:200]})

        if action == "wait":
            deadline = time.time() + int(kwargs.get("timeout_seconds") or 10)
            last_error = "timed out"
            while time.time() < deadline:
                try:
                    spec = _find_window(desktop, kwargs.get("title"))
                    if spec.exists(timeout=1):
                        if kwargs.get("name") or kwargs.get("automation_id"):
                            control, method = resolve_control(
                                _collect_controls(spec),
                                name=kwargs.get("name"),
                                automation_id=kwargs.get("automation_id"),
                                control_type=kwargs.get("control_type"),
                            )
                            if control:
                                return ToolResult(
                                    True,
                                    f"Found control {control.name} via {method}",
                                    data={"method": method, "control": control.as_dict()},
                                )
                            last_error = "window found but control not yet visible"
                        else:
                            return ToolResult(True, f"Found window {spec.window_text()}")
                except Exception as exc:
                    last_error = str(exc)
                time.sleep(0.4)
            return ToolResult(False, "", error=f"wait failed: {last_error}")

        spec = _find_window(desktop, kwargs.get("title"))
        if action == "inspect":
            controls = _collect_controls(spec)
            listing = format_control_list(controls)
            return ToolResult(
                True,
                f"Window: {spec.window_text()}\n{listing}",
                data={"title": spec.window_text(), "controls": [c.as_dict() for c in controls[:80]]},
            )
        if action == "focus":
            spec.set_focus()
            return ToolResult(True, f"Focused {spec.window_text()}")
        if action == "click":
            backend = click_backend(
                name=kwargs.get("name"),
                automation_id=kwargs.get("automation_id"),
                control_type=kwargs.get("control_type"),
                x=kwargs.get("x"),
                y=kwargs.get("y"),
            )
            if backend == "semantic":
                control, method = resolve_control(
                    _collect_controls(spec),
                    name=kwargs.get("name"),
                    automation_id=kwargs.get("automation_id"),
                    control_type=kwargs.get("control_type"),
                )
                if control and control.handle is not None:
                    control.handle.click_input()
                    return ToolResult(
                        True,
                        f"Clicked control {control.name} via {method}",
                        data={"method": method, "fallback": False, "control": control.as_dict()},
                    )
                if kwargs.get("x") is not None and kwargs.get("y") is not None:
                    _coordinate_click(int(kwargs["x"]), int(kwargs["y"]))
                    return ToolResult(
                        True,
                        f"Named control not found; clicked {kwargs['x']},{kwargs['y']} (coordinate fallback)",
                        data={"method": "coordinate", "fallback": True},
                    )
                available = format_control_list(_collect_controls(spec), limit=20)
                return ToolResult(False, "", error=f"No matching named control. Visible controls:\n{available}")
            if backend == "coordinate":
                _coordinate_click(int(kwargs["x"]), int(kwargs["y"]))
                return ToolResult(
                    True,
                    f"Clicked {kwargs['x']},{kwargs['y']} (coordinate fallback)",
                    data={"method": "coordinate", "fallback": True},
                )
            return ToolResult(False, "", error="Provide name, automation_id, or x/y. Prefer a named control.")
        if action == "type":
            text = kwargs.get("text") or ""
            if kwargs.get("name") or kwargs.get("automation_id"):
                control, method = resolve_control(
                    _collect_controls(spec),
                    name=kwargs.get("name"),
                    automation_id=kwargs.get("automation_id"),
                    control_type=kwargs.get("control_type"),
                )
                if not control or control.handle is None:
                    return ToolResult(False, "", error="Named edit control not found; inspect the window first")
                try:
                    control.handle.set_focus()
                except Exception:
                    pass
                control.handle.type_keys(text, with_spaces=True)
                return ToolResult(True, f"Typed into {control.name} via {method}", data={"method": method})
            spec.type_keys(text, with_spaces=True)
            return ToolResult(True, "Typed text into focused window")
        if action == "keys":
            spec.type_keys(kwargs.get("text") or "")
            return ToolResult(True, f"Sent keys {kwargs.get('text')}")
        return ToolResult(False, "", error=f"Unknown action {action}")
