from __future__ import annotations

import asyncio
import shutil
import subprocess
from typing import Any

from .base import RiskLevel, Tool, ToolResult

_TIMEOUT = 180


def docker_available() -> bool:
    return shutil.which("docker") is not None


def docker_daemon_ok() -> tuple[bool, str]:
    if not docker_available():
        return False, "Docker is not installed on this machine"
    try:
        completed = subprocess.run(
            ["docker", "info"],
            capture_output=True,
            text=True,
            timeout=20,
            check=False,
        )
    except Exception as exc:
        return False, f"Docker daemon is not reachable ({exc})"
    if completed.returncode != 0:
        err = (completed.stderr or completed.stdout or "docker info failed").strip()
        return False, err[:400]
    return True, "Docker daemon is running"


class DockerTool(Tool):
    name = "docker"
    description = (
        "Inspect and run Docker containers when Docker Desktop is installed. "
        "Actions: ps, images, build, run, logs, inspect. `run` uses --rm and needs an image."
    )
    risk = RiskLevel.HIGH
    parameters = {
        "type": "object",
        "properties": {
            "action": {"type": "string", "enum": ["ps", "images", "build", "run", "logs", "inspect"]},
            "args": {"type": "string", "description": "Command after the image for run, or extra docker args."},
            "path": {"type": "string"},
            "image": {"type": "string"},
            "container": {"type": "string"},
        },
        "required": ["action"],
    }

    async def execute(self, **kwargs: Any) -> ToolResult:
        ok, reason = docker_daemon_ok()
        if not ok:
            return ToolResult(False, "", error=reason)
        action = (kwargs.get("action") or "").strip()
        argv = _argv(action, kwargs)
        if argv is None:
            return ToolResult(False, "", error=f"Unknown action {action}")
        if isinstance(argv, str):
            return ToolResult(False, "", error=argv)
        proc = await asyncio.create_subprocess_exec(
            "docker",
            *argv,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        try:
            stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=_TIMEOUT)
        except TimeoutError:
            proc.kill()
            await proc.wait()
            return ToolResult(False, "", error=f"Docker {action} timed out after {_TIMEOUT}s")
        out = stdout.decode("utf-8", errors="replace")
        err = stderr.decode("utf-8", errors="replace")
        code = proc.returncode or 0
        return ToolResult(
            code == 0,
            out or err,
            error="" if code == 0 else (err or out),
            data={"exit_code": code, "command": ["docker", *argv]},
        )


def _argv(action: str, kwargs: dict[str, Any]) -> list[str] | str | None:
    extra = [part for part in str(kwargs.get("args") or "").split() if part]
    if action == "ps":
        return ["ps", "-a"]
    if action == "images":
        return ["images"]
    if action == "build":
        return ["build", kwargs.get("path") or "."]
    if action == "run":
        image = str(kwargs.get("image") or "").strip()
        if not image:
            return "image is required for docker run"
        return ["run", "--rm", image, *extra]
    if action == "logs":
        container = str(kwargs.get("container") or "").strip()
        if not container:
            return "container is required for docker logs"
        return ["logs", container]
    if action == "inspect":
        target = str(kwargs.get("container") or kwargs.get("image") or "").strip()
        if not target:
            return "container or image is required for docker inspect"
        return ["inspect", target]
    return None


DockerTool = DockerTool
