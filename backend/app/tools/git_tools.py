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
        "checkpoint. checkpoint creates a recoverable stash or commit-less backup branch named "
        "jarvis-checkpoint-* before large autonomous edits."
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
                created = await self._git(["branch", branch, "HEAD"], cwd)
                extra = ""
                status = await self._git(["status", "--porcelain"], cwd)
                dirty = bool((status.output or "").strip())
                if dirty:
                    stash = await self._git(["stash", "create", f"jarvis-checkpoint-{stamp}"], cwd)
                    hash_id = (stash.output or "").strip().splitlines()[-1].strip() if stash.success else ""
                    if hash_id and len(hash_id) >= 7:
                        wip = f"{branch}-wip"
                        await self._git(["update-ref", f"refs/heads/{wip}", hash_id], cwd)
                        extra = f" Uncommitted work saved on {wip} via stash create (working tree unchanged)."
                    else:
                        extra = " Working tree has uncommitted files; HEAD branch still points at the last commit."
                if created.success:
                    return ToolResult(
                        True,
                        f"Created backup branch {branch}. Working tree was not modified.{extra}",
                        data={"branch": branch, "working_tree_unchanged": True},
                    )
                return created
            return ToolResult(False, "", error=f"Unknown action {action}")
        except Exception as exc:
            return ToolResult(False, "", error=str(exc))
