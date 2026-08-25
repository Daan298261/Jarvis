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
        argv, err = docker_argv(str(action or ""), kwargs)
        if err:
            return ToolResult(False, "", error=err)
        if not shutil.which("docker"):
            return ToolResult(False, "", error="Docker is not installed on this machine")
        if not argv:
            return ToolResult(False, "", error=f"Unknown action {action}")
        proc = await asyncio.create_subprocess_exec(
            "docker",
            *argv,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await proc.communicate()
        out = stdout.decode("utf-8", errors="replace")
        err_out = stderr.decode("utf-8", errors="replace")
        code = proc.returncode or 0
        return ToolResult(code == 0, out or err_out, error="" if code == 0 else err_out)
