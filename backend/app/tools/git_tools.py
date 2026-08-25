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
        "without resetting the working tree."
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
                repo = await self._git(["rev-parse", "--is-inside-work-tree"], cwd)
                if not repo.success:
                    return ToolResult(False, "", error="path is not a git repository")
                stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
                branch = f"jarvis-checkpoint-{stamp}"
                created = await self._git(["stash", "create"], cwd)
                sha = (created.output or "").strip().split()[0] if created.success else ""
                if sha and len(sha) >= 7 and all(ch in "0123456789abcdefABCDEF" for ch in sha):
                    labeled = await self._git(["branch", branch, sha], cwd)
                else:
                    labeled = await self._git(["branch", branch], cwd)
                if labeled.success:
                    return ToolResult(
                        True,
                        f"Created recoverable backup branch {branch} without changing the working tree. "
                        f"Restore with: git checkout {branch}",
                        data={"branch": branch, "sha": sha},
                    )
                return labeled
            return ToolResult(False, "", error=f"Unknown action {action}")
        except Exception as exc:
            return ToolResult(False, "", error=str(exc))
