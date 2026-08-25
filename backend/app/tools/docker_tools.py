from __future__ import annotations

import asyncio
import shutil
from typing import Any

from .base import RiskLevel, Tool, ToolResult


class DockerTool(Tool):
    name = "docker"
    description = (
        "Inspect and run Docker containers when Docker is installed. Actions: ps, images, build, run, logs, inspect. "
        "run requires image; logs requires container; inspect requires container or image."
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
        image = (kwargs.get("image") or "").strip()
        container = (kwargs.get("container") or "").strip()
        if action == "run" and not image:
            return ToolResult(False, "", error="image is required for docker run")
        if action == "logs" and not container:
            return ToolResult(False, "", error="container is required for docker logs")
        if action == "inspect" and not (container or image):
            return ToolResult(False, "", error="container or image is required for docker inspect")
        if not shutil.which("docker"):
            return ToolResult(False, "", error="Docker is not installed on this machine")
        mapping = {
            "ps": ["ps", "-a"],
            "images": ["images"],
            "build": ["build", kwargs.get("path") or "."],
            "run": ["run", "--rm", *(kwargs.get("args") or "").split(), image],
            "logs": ["logs", container],
            "inspect": ["inspect", container or image],
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
