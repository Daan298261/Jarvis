from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from ..config import data_dir
from .base import RiskLevel, Tool, ToolResult


def capture_screen(path: str | None = None) -> str:
    import mss
    from PIL import Image

    out = Path(path) if path else data_dir() / "screenshots" / f"screen-{datetime.now(timezone.utc).strftime('%Y%m%d-%H%M%S')}.png"
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
        "Actions: capture, describe_path. After capture, the agent should send the image in the next model turn."
    )
    risk = RiskLevel.LOW
    parameters = {
        "type": "object",
        "properties": {
            "action": {"type": "string", "enum": ["capture", "describe_path"]},
            "path": {"type": "string"},
        },
        "required": ["action"],
    }

    async def execute(self, **kwargs: Any) -> ToolResult:
        action = kwargs.get("action")
        if action == "capture":
            path = capture_screen(kwargs.get("path"))
            return ToolResult(True, f"Captured screen to {path}", data={"path": path, "attach_image": path})
        if action == "describe_path":
            path = kwargs.get("path")
            if not path or not Path(path).exists():
                return ToolResult(False, "", error="Image path not found")
            return ToolResult(True, f"Image ready at {path}", data={"path": path, "attach_image": path})
        return ToolResult(False, "", error="Unknown action")
