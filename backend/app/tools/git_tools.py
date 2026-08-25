from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .base import RiskLevel, Tool, ToolResult


class GitTool(Tool):
    name = "git"
    description = (
        "Inspect and checkpoint git repositories. Actions: status, diff, branch, log, search, "
        "checkpoint. checkpoint creates a recoverable backup branch named jarvis-checkpoint-* "
        "and stores uncommitted work as a stash commit object without changing the working tree."
    )
    risk = RiskLevel.MEDIUM
    parameters = {
        "type": "object",
        "properties": {
            "action": {"type": "string", "enum": ["status", "diff", "branch", "log", "search", "checkpoint"]},
            "path": {"type": "string"},
            "query": {"type": "string"},
            "ref": {"type": "string"},
        },
        "required": ["action"],
    }

    async def _git(self, args: list[str], cwd: str) -> ToolResult:
        proc = await asyncio.create_subprocess_exec(
            "git",
            *args,
            cwd=cwd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await proc.communicate()
        out = stdout.decode("utf-8", errors="replace")
        err = stderr.decode("utf-8", errors="replace")
        code = proc.returncode or 0
        return ToolResult(code == 0, out or err, error="" if code == 0 else err)

    async def execute(self, **kwargs: Any) -> ToolResult:
        cwd = kwargs.get("path") or str(Path.cwd())
        action = kwargs.get("action")
        try:
            if action == "status":
                return await self._git(["status", "--porcelain=v1", "-b"], cwd)
            if action == "diff":
                return await self._git(["diff", kwargs.get("ref") or "HEAD"], cwd)
            if action == "branch":
                return await self._git(["branch", "-vv"], cwd)
            if action == "log":
                return await self._git(["log", "-n", "20", "--oneline", "--decorate"], cwd)
            if action == "search":
                query = kwargs.get("query") or ""
                return await self._git(["grep", "-n", query], cwd)
            if action == "checkpoint":
                stamp = datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S")
                branch = f"jarvis-checkpoint-{stamp}"
                created = await self._git(["branch", branch], cwd)
                if not created.success:
                    return created
                stash = await self._git(["stash", "create", f"jarvis-checkpoint-{stamp}"], cwd)
                extra = ""
                digest = (stash.output or "").strip().splitlines()
                commit = digest[-1].strip() if digest else ""
                if commit and len(commit) >= 7 and all(ch in "0123456789abcdef" for ch in commit.lower()):
                    stored = await self._git(["update-ref", f"refs/jarvis-checkpoints/{branch}", commit], cwd)
                    if stored.success:
                        extra = f" Uncommitted work stored at refs/jarvis-checkpoints/{branch} without changing the working tree."
                return ToolResult(
                    True,
                    f"Created backup branch {branch} at HEAD. Working tree left unchanged.{extra}",
                    data={"branch": branch, "stash_commit": commit or None},
                )
            return ToolResult(False, "", error=f"Unknown action {action}")
        except Exception as exc:
            return ToolResult(False, "", error=str(exc))
