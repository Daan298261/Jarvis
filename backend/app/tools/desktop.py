from __future__ import annotations

import asyncio
import os
import subprocess
import time
from pathlib import Path
from typing import Any

from .base import RiskLevel, Tool, ToolResult
from .safety import resolve_allowed_path

_lock = asyncio.Lock()


def _escape_keys(text: str) -> str:
    special = set("{}!^%+~()")
    return "".join("{" + ch + "}" if ch in special else ch for ch in text)


def _coinit():
    try:
        import pythoncom

        pythoncom.CoInitialize()
        return pythoncom
    except Exception:
        return None


def _window_matches(title: str, needle: str) -> bool:
    needle = (needle or "").strip()
    if len(needle) < 2:
        return False
    return needle.lower() in (title or "").lower()


def _find_window(desktop, needle: str, timeout: float = 15):
    needle = (needle or "").strip()
    if len(needle) < 2:
        raise ValueError("A window title or file name is required")
    deadline = time.time() + timeout
    last = None
    while time.time() < deadline:
        try:
            for window in desktop.windows():
                title = window.window_text() or ""
                if _window_matches(title, needle):
                    return window
        except Exception as exc:
            last = exc
        time.sleep(0.25)
    raise TimeoutError(f"Timed out waiting for window matching {needle!r}: {last or 'not found'}")


def _editor(window):
    specs = [
        {"control_type": "Document"},
        {"auto_id": "RichEditBox"},
        {"class_name": "RichEditD2DPT"},
        {"control_type": "Edit"},
        {"class_name": "Edit"},
    ]
    for spec in specs:
        try:
            child = window.child_window(**spec)
            if child.exists(timeout=1):
                return child
        except Exception:
            continue
    return window


def _set_text(control, text: str) -> None:
    try:
        control.set_edit_text(text)
        return
    except Exception:
        pass
    try:
        control.iface_value.SetValue(text)
        return
    except Exception:
        pass
    from pywinauto.keyboard import send_keys

    try:
        control.click_input()
    except Exception:
        control.set_focus()
    time.sleep(0.15)
    send_keys("^a", pause=0.05)
    time.sleep(0.1)
    send_keys(_escape_keys(text), with_spaces=True, pause=0.01)


def notepad_write_file(path: Path, text: str, timeout: float = 25) -> str:
    """Drive Notepad via UI Automation: open the file, type, Ctrl+S, close the tab."""
    com = _coinit()
    from pywinauto import Desktop
    from pywinauto.keyboard import send_keys

    path = path.expanduser().resolve()
    path.parent.mkdir(parents=True, exist_ok=True)
    if not path.exists():
        path.write_text("", encoding="utf-8")
    needle = path.name
    proc = subprocess.Popen(["notepad.exe", str(path)], close_fds=True)
    desktop = Desktop(backend="uia")
    try:
        window = _find_window(desktop, needle, timeout=timeout)
        window.set_focus()
        editor = _editor(window)
        _set_text(editor, text)
        time.sleep(0.2)
        send_keys("^s", pause=0.05)
        time.sleep(0.6)
        send_keys("^w", pause=0.05)
        time.sleep(0.4)
        try:
            if window.exists(timeout=0.5) and _window_matches(window.window_text(), needle):
                send_keys("{ENTER}", pause=0.05)
                time.sleep(0.3)
                send_keys("^w", pause=0.05)
        except Exception:
            pass
    finally:
        if com is not None:
            try:
                com.CoUninitialize()
            except Exception:
                pass
        if proc.poll() is None:
            time.sleep(0.2)

    disk = path.read_text(encoding="utf-8", errors="replace")
    if text not in disk:
        raise RuntimeError(
            f"Notepad UI save did not persist {text!r} to {path}. File contains {disk[:200]!r}"
        )
    return f"Wrote {path} via Notepad UI Automation ({len(text)} chars)"


class DesktopTool(Tool):
    name = "desktop"
    description = (
        "Interact with native Windows applications using UI Automation / pywinauto. "
        "Actions: write (Notepad type+save to a file — preferred for text documents), "
        "launch, screenshot, apps, windows, focus, click, type, keys, close. "
        "Prefer named UI controls over coordinates. Use screenshot + vision when lookup fails."
    )
    risk = RiskLevel.MEDIUM
    parameters = {
        "type": "object",
        "properties": {
            "action": {
                "type": "string",
                "enum": [
                    "write",
                    "launch",
                    "screenshot",
                    "apps",
                    "windows",
                    "focus",
                    "click",
                    "type",
                    "keys",
                    "close",
                ],
            },
            "title": {"type": "string"},
            "name": {"type": "string"},
            "text": {"type": "string"},
            "x": {"type": "integer"},
            "y": {"type": "integer"},
            "path": {"type": "string"},
        },
        "required": ["action"],
    }

    def __init__(self, context_getter=None) -> None:
        self.context_getter = context_getter or (lambda: {})

    def _allowed(self) -> list[str]:
        return list((self.context_getter() or {}).get("allowed_directories") or [])

    async def execute(self, **kwargs: Any) -> ToolResult:
        action = kwargs.get("action")
        async with _lock:
            try:
                if action == "screenshot":
                    from .screenshot import capture_screen

                    path = capture_screen(kwargs.get("path"))
                    return ToolResult(True, f"Saved screenshot to {path}", data={"path": path, "attach_image": path})
                if action == "apps":
                    import psutil

                    names = sorted({p.info["name"] for p in psutil.process_iter(["name"]) if p.info["name"]})
                    return ToolResult(True, "\n".join(names[:400]))
                if action == "write":
                    dest = kwargs.get("path")
                    text = kwargs.get("text") or ""
                    if not dest:
                        return ToolResult(False, "", error="path is required")
                    if not text:
                        return ToolResult(False, "", error="text is required")
                    out = resolve_allowed_path(dest, self._allowed())
                    message = await asyncio.to_thread(notepad_write_file, out, text)
                    return ToolResult(True, message, data={"path": str(out)})
                if action == "launch":
                    target = kwargs.get("path") or kwargs.get("name") or "notepad.exe"
                    subprocess.Popen(target if os.path.sep in target else [target], close_fds=True)
                    return ToolResult(True, f"Launched {target}")
                return await asyncio.to_thread(self._uia_action, action, kwargs)
            except Exception as exc:
                return ToolResult(False, "", error=str(exc))

    def _uia_action(self, action: str | None, kwargs: dict[str, Any]) -> ToolResult:
        com = _coinit()
        try:
            from pywinauto import Desktop

            desktop = Desktop(backend="uia")
            title = kwargs.get("title") or ""
            if action == "windows":
                titles = [w.window_text() for w in desktop.windows() if w.window_text()]
                return ToolResult(True, "\n".join(titles[:200]) or "No windows")
            if action == "focus":
                spec = _find_window(desktop, title, timeout=8)
                spec.set_focus()
                return ToolResult(True, f"Focused {spec.window_text()}")
            if action == "close":
                spec = _find_window(desktop, title, timeout=8)
                spec.set_focus()
                from pywinauto.keyboard import send_keys

                send_keys("^w", pause=0.05)
                return ToolResult(True, f"Closed tab/window matching {title}")
            if action == "click":
                if kwargs.get("name"):
                    spec = _find_window(desktop, title, timeout=8)
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
                spec = _find_window(desktop, title, timeout=8)
                spec.set_focus()
                editor = _editor(spec)
                _set_text(editor, kwargs.get("text") or "")
                return ToolResult(True, "Typed text")
            if action == "keys":
                spec = _find_window(desktop, title, timeout=8)
                spec.set_focus()
                from pywinauto.keyboard import send_keys

                send_keys(kwargs.get("text") or "", pause=0.02)
                return ToolResult(True, f"Sent keys {kwargs.get('text')}")
            return ToolResult(False, "", error=f"Unknown action {action}")
        finally:
            if com is not None:
                try:
                    com.CoUninitialize()
                except Exception:
                    pass
