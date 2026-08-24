from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

from ..agent.worktrees import (
    WorktreeError,
    checkpoint_commit,
    create_worktree,
    discard_worktree,
    is_production_checkout,
    list_worktrees,
    worktree_status,
)
from .base import RiskLevel, Tool, ToolResult


class GitTool(Tool):
    name = "git"
    description = (
        "Inspect and checkpoint git repositories. Actions: status, diff, branch, log, search, "
        "checkpoint, worktree_add, worktree_list, worktree_status, worktree_remove, commit. "
        "checkpoint creates a recoverable stash on the current checkout. Isolated self-development "
        "uses worktree_add (never the trusted production tree) and commit only inside that worktree."
    )
    risk = RiskLevel.MEDIUM
    parameters = {
        "type": "object",
        "properties": {
            "action": {
                "type": "string",
                "enum": [
                    "status",
                    "diff",
                    "branch",
                    "log",
                    "search",
                    "checkpoint",
                    "worktree_add",
                    "worktree_list",
                    "worktree_status",
                    "worktree_remove",
                    "commit",
                ],
            },
            "path": {"type": "string"},
            "query": {"type": "string"},
            "ref": {"type": "string"},
            "message": {"type": "string"},
            "worktree_id": {"type": "string"},
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
                if is_production_checkout(cwd):
                    stamp = Path(cwd).name
                    result = await self._git(["stash", "push", "-u", "-m", f"jarvis-checkpoint-{stamp}"], cwd)
                    if result.success:
                        return ToolResult(True, "Created git stash checkpoint on the trusted checkout. Use git stash list / pop to recover.")
                    return await self._git(["status"], cwd)
                try:
                    payload = checkpoint_commit(cwd, kwargs.get("message") or "jarvis checkpoint")
                    return ToolResult(True, f"Committed isolated checkpoint {payload['commit']}", data=payload)
                except WorktreeError as exc:
                    return ToolResult(False, "", error=str(exc))
            if action == "worktree_add":
                spec = create_worktree(cwd)
                return ToolResult(
                    True,
                    f"Created isolated worktree {spec.branch} at {spec.path} from {spec.start_commit[:12]}",
                    data=spec.as_dict(),
                )
            if action == "worktree_list":
                rows = list_worktrees()
                text = "\n".join(f"{item['id']} {item['status']} {item['branch']} {item['path']}" for item in rows) or "No isolated worktrees."
                return ToolResult(True, text, data={"worktrees": rows})
            if action == "worktree_status":
                return ToolResult(True, "", data=worktree_status(cwd))
            if action == "worktree_remove":
                worktree_id = kwargs.get("worktree_id")
                if not worktree_id:
                    return ToolResult(False, "", error="worktree_id is required")
                spec = discard_worktree(worktree_id)
                return ToolResult(True, f"Discarded isolated worktree {spec.branch}", data=spec.as_dict())
            if action == "commit":
                payload = checkpoint_commit(cwd, kwargs.get("message") or "jarvis checkpoint")
                return ToolResult(True, f"commit={payload['commit']} created={payload['created']}", data=payload)
            return ToolResult(False, "", error=f"Unknown action {action}")
        except WorktreeError as exc:
            return ToolResult(False, "", error=str(exc))
        except Exception as exc:
            return ToolResult(False, "", error=str(exc))
