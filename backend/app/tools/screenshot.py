from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .base import RiskLevel, Tool, ToolResult
from .owner_paths import resolve_owner_file_path
from .safety import resolve_allowed_path


def screenshot_dest(path: str | None = None, *, allowed: list[str] | None = None) -> Path:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    return resolve_owner_file_path(
        path,
        suggested_name=f"screen-{stamp}.png",
        allowed=list(allowed or []),
        fallback_dirs=("Pictures", "Desktop", "Downloads"),
    )


def capture_screen(path: str | None = None, *, allowed: list[str] | None = None) -> str:
    import mss
    from PIL import Image

    out = screenshot_dest(path, allowed=allowed)
    out.parent.mkdir(parents=True, exist_ok=True)
    with mss.mss() as sct:
        monitor = sct.monitors[1] if len(sct.monitors) > 1 else sct.monitors[0]
        raw = sct.grab(monitor)
        image = Image.frombytes("RGB", raw.size, raw.bgra, "raw", "BGRX")
        image.save(out)
    return str(out)


class ScreenshotTool(Tool):
    name = "screenshot"
    description = (
        "Capture the desktop or a provided image path so the multimodal model can inspect it. "
        "Actions: capture, describe_path. capture saves to the owner's Pictures folder by default, "
        "or to an allowed extra drive when path is set. After capture, the agent should send the "
        "image in the next model turn."
    )
    risk = RiskLevel.LOW
    parameters = {
        "type": "object",
        "properties": {
            "action": {"type": "string", "enum": ["capture", "describe_path"]},
            "path": {
                "type": "string",
                "description": "Save/open path. Omit capture to use Pictures (or Desktop/Downloads).",
            },
        },
        "required": ["action"],
    }

    def __init__(self, context_getter=None) -> None:
        self.context_getter = context_getter or (lambda: {})

    def _allowed(self) -> list[str]:
        raw = self.context_getter() if callable(self.context_getter) else {}
        if isinstance(raw, dict):
            return list(raw.get("allowed_directories") or [])
        return list(getattr(raw, "allowed_directories", None) or [])

    async def execute(self, **kwargs: Any) -> ToolResult:
        action = kwargs.get("action")
        try:
            if action == "capture":
                path = capture_screen(kwargs.get("path"), allowed=self._allowed())
                return ToolResult(True, f"Captured screen to {path}", data={"path": path, "attach_image": path})
            if action == "describe_path":
                raw = kwargs.get("path")
                if not raw:
                    return ToolResult(False, "", error="Image path not found")
                allowed = self._allowed()
                path = resolve_allowed_path(str(raw), allowed) if allowed else Path(raw)
                if not path.exists():
                    return ToolResult(False, "", error="Image path not found")
                return ToolResult(True, f"Image ready at {path}", data={"path": str(path), "attach_image": str(path)})
            return ToolResult(False, "", error="Unknown action")
        except Exception as exc:
            return ToolResult(False, "", error=str(exc))
