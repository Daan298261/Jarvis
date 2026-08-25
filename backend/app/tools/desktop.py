from __future__ import annotations

import platform
from typing import Any

from .base import RiskLevel, Tool, ToolResult

UNAVAILABLE = (
    "Windows UI Automation is unavailable on this machine. "
    "Use the screenshot tool and vision, or the browser tool for web apps."
)


def windows_ui_available() -> bool:
    return platform.system() == "Windows"


def resolve_named_control(window: Any, name: str) -> Any:
    """Prefer a named control over coordinates. Try several UIA lookup keys."""
    if not name:
        return None
    lookups = (
        {"title": name},
        {"auto_id": name},
        {"best_match": name},
        {"title_re": f".*{name}.*"},
        {"control_type": "Button", "title": name},
        {"control_type": "Edit", "title": name},
    )
    for kwargs in lookups:
        try:
            child = window.child_window(**kwargs)
        except Exception:
            continue
        exists = getattr(child, "exists", None)
        try:
            if callable(exists) and not exists(timeout=1):
                continue
        except Exception:
            continue
        return child
    return None


class DesktopTool(Tool):
    name = "desktop"
    description = (
        "Interact with native Windows applications using UI Automation / pywinauto when possible. "
        "Actions: screenshot, apps, windows, focus, click, type, keys. Prefer named UI controls "
        "over coordinates. Coordinate click is last resort after named lookup fails. "
        "Use screenshot and then vision when semantic UI lookup fails."
    )
    risk = RiskLevel.HIGH
    parameters = {
        "type": "object",
        "properties": {
            "action": {"type": "string", "enum": ["screenshot", "apps", "windows", "focus", "click", "type", "keys"]},
            "title": {"type": "string"},
            "name": {"type": "string"},
            "text": {"type": "string"},
            "x": {"type": "integer"},
            "y": {"type": "integer"},
            "path": {"type": "string"},
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
            if action not in {"windows", "focus", "click", "type", "keys"}:
                return ToolResult(False, "", error=f"Unknown action {action}")
            if not windows_ui_available():
                return ToolResult(False, "", error=UNAVAILABLE)
            try:
                from pywinauto import Desktop
            except Exception as exc:
                return ToolResult(False, "", error=f"{UNAVAILABLE} ({exc})")

            desktop = Desktop(backend="uia")
            if action == "windows":
                titles = [w.window_text() for w in desktop.windows() if w.window_text()]
                return ToolResult(True, "\n".join(titles[:200]) or "No windows")
            spec = desktop.window(title_re=f".*{kwargs.get('title') or ''}.*")
            if action == "focus":
                spec.set_focus()
                return ToolResult(True, f"Focused {spec.window_text()}")
            if action == "click":
                if kwargs.get("name"):
                    control = resolve_named_control(spec, kwargs["name"])
                    if control is None:
                        return ToolResult(
                            False,
                            "",
                            error=f"Named control {kwargs['name']!r} was not found. "
                            "Do not use coordinates yet; take a screenshot and retry with the visible name.",
                        )
                    control.click_input()
                    return ToolResult(True, f"Clicked control {kwargs['name']}")
                if kwargs.get("x") is not None and kwargs.get("y") is not None:
                    import ctypes

                    ctypes.windll.user32.SetCursorPos(int(kwargs["x"]), int(kwargs["y"]))
                    ctypes.windll.user32.mouse_event(2, 0, 0, 0, 0)
                    ctypes.windll.user32.mouse_event(4, 0, 0, 0, 0)
                    return ToolResult(True, f"Clicked {kwargs['x']},{kwargs['y']} (coordinate fallback)")
                return ToolResult(False, "", error="Provide name or x/y")
            if action == "type":
                if kwargs.get("name"):
                    control = resolve_named_control(spec, kwargs["name"])
                    if control is None:
                        return ToolResult(False, "", error=f"Named control {kwargs['name']!r} was not found")
                    control.type_keys(kwargs.get("text") or "", with_spaces=True)
                    return ToolResult(True, f"Typed into {kwargs['name']}")
                spec.type_keys(kwargs.get("text") or "", with_spaces=True)
                return ToolResult(True, "Typed text")
            if action == "keys":
                spec.type_keys(kwargs.get("text") or "")
                return ToolResult(True, f"Sent keys {kwargs.get('text')}")
            return ToolResult(False, "", error=f"Unknown action {action}")
        except Exception as exc:
            return ToolResult(False, "", error=str(exc))
