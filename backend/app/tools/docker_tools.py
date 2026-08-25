from __future__ import annotations

import asyncio
import shutil
from typing import Any

from .base import RiskLevel, Tool, ToolResult


def docker_argv(action: str, kwargs: dict[str, Any]) -> tuple[list[str] | None, str]:
    """Build `docker …` arguments or return a user-visible error."""
    if action == "ps":
        return ["ps", "-a"], ""
    if action == "images":
        return ["images"], ""
    if action == "build":
        return ["build", kwargs.get("path") or "."], ""
    if action == "run":
        image = str(kwargs.get("image") or "").strip()
        if not image:
            return None, "image is required for docker run"
        extra = [part for part in str(kwargs.get("args") or "").split() if part]
        return ["run", "--rm", *extra, image], ""
    if action == "logs":
        container = str(kwargs.get("container") or "").strip()
        if not container:
            return None, "container is required for docker logs"
        return ["logs", container], ""
    if action == "inspect":
        target = str(kwargs.get("container") or kwargs.get("image") or "").strip()
        if not target:
            return None, "container or image is required for docker inspect"
        return ["inspect", target], ""
    return None, f"Unknown action {action}"


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
        if action == "run" and not str(kwargs.get("image") or "").strip():
            return ToolResult(False, "", error="docker run requires an image")
        if action == "logs" and not str(kwargs.get("container") or "").strip():
            return ToolResult(False, "", error="docker logs requires a container")
        if action == "inspect" and not str(kwargs.get("container") or kwargs.get("image") or "").strip():
            return ToolResult(False, "", error="docker inspect requires a container or image")
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
