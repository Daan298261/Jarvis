from __future__ import annotations

import asyncio
import shutil
from typing import Any

from .base import RiskLevel, Tool, ToolResult


class DockerTool(Tool):
    name = "docker"
    description = (
        "Inspect and run Docker containers when Docker is installed. Actions: ps, images, build, run, logs, inspect."
    )
    risk = RiskLevel.HIGH
    parameters = {
        "type": "object",
        "properties": {
            "action": {"type": "string", "enum": ["ps", "images", "build", "run", "logs", "inspect"]},
            "args": {"type": "string"},
            "path": {"type": "string"},
            "image": {"type": "string"},
            "container": {"type": "string"},
        },
        "required": ["action"],
    }

    async def execute(self, **kwargs: Any) -> ToolResult:
        action = kwargs.get("action")
        if action == "run" and not str(kwargs.get("image") or "").strip():
            return ToolResult(False, "", error="docker run requires an image")
        if not shutil.which("docker"):
            return ToolResult(False, "", error="Docker is not installed on this machine")
        mapping = {
            "ps": ["ps", "-a"],
            "images": ["images"],
            "build": ["build", kwargs.get("path") or "."],
            "run": ["run", "--rm", *(kwargs.get("args") or "").split(), kwargs.get("image") or ""],
            "logs": ["logs", kwargs.get("container") or ""],
            "inspect": ["inspect", kwargs.get("container") or kwargs.get("image") or ""],
        }
        args = mapping.get(action)
        if not args:
            return ToolResult(False, "", error=f"Unknown action {action}")
        args = [a for a in args if a]
        proc = await asyncio.create_subprocess_exec(
            "docker",
            *args,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await proc.communicate()
        out = stdout.decode("utf-8", errors="replace")
        err = stderr.decode("utf-8", errors="replace")
        code = proc.returncode or 0
        return ToolResult(code == 0, out or err, error="" if code == 0 else err)
