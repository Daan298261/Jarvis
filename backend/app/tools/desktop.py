from __future__ import annotations

import asyncio
import os
from typing import Any

from .base import RiskLevel, Tool, ToolResult


class DesktopTool(Tool):
    name = "desktop"
    description = (
        "Interact with native Windows applications using UI Automation / pywinauto when possible. "
        "Actions: screenshot, apps, windows, focus, click, type, keys. Prefer named UI controls "
        "over coordinates. Use screenshot and then vision when semantic UI lookup fails."
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
            from pywinauto import Desktop

            desktop = Desktop(backend="uia")
            if action == "windows":
                titles = [w.window_text() for w in desktop.windows() if w.window_text()]
                return ToolResult(True, "\n".join(titles[:200]) or "No windows")
            if action == "focus":
                spec = desktop.window(title_re=f".*{kwargs.get('title') or ''}.*")
                spec.set_focus()
                return ToolResult(True, f"Focused {spec.window_text()}")
            if action == "click":
                if kwargs.get("name"):
                    spec = desktop.window(title_re=f".*{kwargs.get('title') or ''}.*")
                    spec.child_window(title=kwargs["name"]).click_input()
                    return ToolResult(True, f"Clicked control {kwargs['name']}")
                if kwargs.get("x") is not None:
                    import ctypes

                    ctypes.windll.user32.SetCursorPos(int(kwargs["x"]), int(kwargs["y"]))
                    ctypes.windll.user32.mouse_event(2, 0, 0, 0, 0)
                    ctypes.windll.user32.mouse_event(4, 0, 0, 0, 0)
                    return ToolResult(True, f"Clicked {kwargs['x']},{kwargs['y']} (coordinate fallback)")
                return ToolResult(False, "", error="Provide name or x/y")
            if action == "type":
                spec = desktop.window(title_re=f".*{kwargs.get('title') or ''}.*")
                spec.type_keys(kwargs.get("text") or "", with_spaces=True)
                return ToolResult(True, "Typed text")
            if action == "keys":
                spec = desktop.window(title_re=f".*{kwargs.get('title') or ''}.*")
                spec.type_keys(kwargs.get("text") or "")
                return ToolResult(True, f"Sent keys {kwargs.get('text')}")
            return ToolResult(False, "", error=f"Unknown action {action}")
        except Exception as exc:
            return ToolResult(False, "", error=str(exc))
