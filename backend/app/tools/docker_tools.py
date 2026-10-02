from __future__ import annotations

import asyncio
import shutil
from typing import Any

from ..config import live_workspace_roots_from_context
from .base import RiskLevel, Tool, ToolResult
from .owner_paths import default_workspace_dir, resolve_workspace_dir


def looks_like_host_path(host: str) -> bool:
    text = str(host or "").strip()
    if not text:
        return False
    if text.startswith(("/", ".", "~")) or "\\" in text:
        return True
    return len(text) >= 2 and text[1] == ":"


def split_bind_spec(spec: str) -> tuple[str, str] | None:
    """Split `host:container[:mode]` so Windows drive letters stay in the host side."""
    text = str(spec or "").strip()
    if not text:
        return None
    if text.startswith(("/", ".", "~")):
        idx = text.find(":")
        if idx <= 0:
            return None
        return text[:idx], text[idx:]
    if len(text) >= 3 and text[1] == ":" and text[2] in "\\/":
        rest = text[2:]
        idx = rest.find(":")
        if idx < 0:
            return None
        return text[: 2 + idx], rest[idx:]
    idx = text.find(":")
    if idx <= 0:
        return None
    host, rest = text[:idx], text[idx:]
    if looks_like_host_path(host):
        return host, rest
    return None


def rewrite_volume_spec(spec: str, allowed: list[str]) -> str:
    split = split_bind_spec(spec)
    if split is None:
        return spec
    host, rest = split
    if not looks_like_host_path(host):
        return spec
    resolved = resolve_workspace_dir(host, allowed)
    return f"{resolved}{rest}" if resolved else spec


def rewrite_mount_spec(spec: str, allowed: list[str]) -> str:
    parts: list[str] = []
    for part in str(spec or "").split(","):
        if part.startswith("source=") or part.startswith("src="):
            key, host = part.split("=", 1)
            if looks_like_host_path(host):
                resolved = resolve_workspace_dir(host, allowed)
                parts.append(f"{key}={resolved or host}")
            else:
                parts.append(part)
        else:
            parts.append(part)
    return ",".join(parts)


def rewrite_docker_run_args(args: str, allowed: list[str]) -> str:
    """Rewrite -v/--volume/--mount host paths onto the allowed workspace."""
    parts = [part for part in str(args or "").split() if part]
    out: list[str] = []
    i = 0
    while i < len(parts):
        part = parts[i]
        if part in {"-v", "--volume"} and i + 1 < len(parts):
            out.append(part)
            out.append(rewrite_volume_spec(parts[i + 1], allowed))
            i += 2
            continue
        if part.startswith("--volume="):
            out.append("--volume=" + rewrite_volume_spec(part.split("=", 1)[1], allowed))
            i += 1
            continue
        if part.startswith("-v") and len(part) > 2 and not part.startswith("--"):
            out.append("-v" + rewrite_volume_spec(part[2:], allowed))
            i += 1
            continue
        if part in {"--mount"} and i + 1 < len(parts):
            out.append(part)
            out.append(rewrite_mount_spec(parts[i + 1], allowed))
            i += 2
            continue
        if part.startswith("--mount="):
            out.append("--mount=" + rewrite_mount_spec(part.split("=", 1)[1], allowed))
            i += 1
            continue
        out.append(part)
        i += 1
    return " ".join(out)


def docker_argv(action: str, kwargs: dict[str, Any]) -> tuple[list[str] | None, str]:
    """Build `docker …` arguments or return a user-visible error."""
    if action == "ps":
        return ["ps", "-a"], ""
    if action == "images":
        return ["images"], ""
    if action == "build":
        path = str(kwargs.get("path") or "").strip() or "."
        return ["build", path], ""
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
        "build path is the folder with a Dockerfile (USB/`D:` extra drives included). "
        "Omit path to build in Documents. "
        "run -v/--volume/--mount host paths must be inside the allowed workspace. "
        "run requires image; logs requires container; inspect requires container or image."
    )
    risk = RiskLevel.HIGH
    parameters = {
        "type": "object",
        "properties": {
            "action": {"type": "string", "enum": ["ps", "images", "build", "run", "logs", "inspect"]},
            "args": {"type": "string"},
            "path": {
                "type": "string",
                "description": "docker build context folder. Extra drives are allowed. Omit to use Documents.",
            },
            "image": {"type": "string"},
            "container": {"type": "string"},
        },
        "required": ["action"],
    }

    def __init__(self, context_getter=None) -> None:
        self.context_getter = context_getter or (lambda: {})

    def _allowed(self) -> list[str]:
        return live_workspace_roots_from_context(self.context_getter() if callable(self.context_getter) else {})

    def _build_path(self, raw: str | None) -> str:
        allowed = self._allowed()
        text = str(raw or "").strip()
        if not text:
            if not allowed:
                return "."
            try:
                return str(default_workspace_dir(allowed, media_only=True))
            except PermissionError:
                raise ValueError(
                    "path is required for docker build (folder with a Dockerfile, including extra drives)"
                ) from None
        resolved = resolve_workspace_dir(text, allowed)
        if not resolved:
            raise ValueError("path is required for docker build (folder with a Dockerfile, including extra drives)")
        return resolved

    async def execute(self, **kwargs: Any) -> ToolResult:
        action = kwargs.get("action")
        payload = dict(kwargs)
        try:
            if str(action or "") == "build":
                payload["path"] = self._build_path(kwargs.get("path"))
            if str(action or "") == "run":
                payload["args"] = rewrite_docker_run_args(str(kwargs.get("args") or ""), self._allowed())
        except (PermissionError, ValueError) as exc:
            return ToolResult(False, "", error=str(exc))
        argv, err = docker_argv(str(action or ""), payload)
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
