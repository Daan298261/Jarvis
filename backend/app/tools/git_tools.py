from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .base import RiskLevel, Tool, ToolResult


class GitTool(Tool):
    name = "git"
    description = (
        "Inspect and recover git repositories. Actions: status, diff, branch, log, search, "
        "checkpoints, checkpoint, restore. checkpoint creates a jarvis-checkpoint-* branch "
        "without changing the working tree. restore reverts files from that checkpoint."
    )
    risk = RiskLevel.MEDIUM
    parameters = {
        "type": "object",
        "properties": {
            "action": {
                "type": "string",
                "enum": ["status", "diff", "branch", "log", "search", "checkpoints", "checkpoint", "restore"],
            },
            "path": {"type": "string"},
            "query": {"type": "string"},
            "ref": {"type": "string"},
            "target": {"type": "string", "description": "Optional file to restore from a checkpoint"},
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

    async def _repo(self, cwd: str) -> str | None:
        result = await self._git(["rev-parse", "--show-toplevel"], cwd)
        if not result.success:
            return None
        root = (result.output or "").strip()
        return root or None

    async def execute(self, **kwargs: Any) -> ToolResult:
        cwd = kwargs.get("path") or str(Path.cwd())
        action = kwargs.get("action")
        try:
            repo = await self._repo(cwd)
            if repo is None:
                return ToolResult(False, "", error=f"Not a git repository: {cwd}")
            if action == "status":
                return await self._git(["status", "--porcelain=v1", "-b"], repo)
            if action == "diff":
                return await self._git(["diff", kwargs.get("ref") or "HEAD"], repo)
            if action == "branch":
                return await self._git(["branch", "-vv"], repo)
            if action == "log":
                return await self._git(["log", "-n", "20", "--oneline", "--decorate"], repo)
            if action == "search":
                query = kwargs.get("query") or ""
                return await self._git(["grep", "-n", query], repo)
            if action == "checkpoints":
                listed = await self._git(["branch", "--list", "jarvis-checkpoint-*"], repo)
                if listed.success and not (listed.output or "").strip():
                    return ToolResult(True, "No jarvis-checkpoint-* branches yet.")
                return listed
            if action == "checkpoint":
                return await self._checkpoint(repo)
            if action == "restore":
                return await self._restore(repo, kwargs.get("ref") or "", kwargs.get("target") or "")
            return ToolResult(False, "", error=f"Unknown action {action}")
        except Exception as exc:
            return ToolResult(False, "", error=str(exc))

    async def _checkpoint(self, repo: str) -> ToolResult:
        head = await self._git(["rev-parse", "--verify", "HEAD"], repo)
        if not head.success:
            return ToolResult(False, "", error="Repository has no commits to checkpoint")
        stamp = datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S")
        name = f"jarvis-checkpoint-{stamp}"
        dirty = await self._git(["status", "--porcelain"], repo)
        sha = (head.output or "").strip()
        if (dirty.output or "").strip():
            created = await self._git(["stash", "create"], repo)
            blob = (created.output or "").strip()
            if created.success and blob:
                sha = blob.splitlines()[-1].strip()
        branched = await self._git(["branch", name, sha], repo)
        if not branched.success:
            return ToolResult(False, "", error=branched.error or branched.output)
        return ToolResult(
            True,
            f"Created checkpoint branch {name} without changing the working tree. "
            f"Inspect with git diff {name} or git restore --source={name}.",
        )

    async def _restore(self, repo: str, ref: str, target: str) -> ToolResult:
        name = (ref or "").strip()
        if not name:
            listed = await self._git(["branch", "--list", "jarvis-checkpoint-*"], repo)
            lines = [line.strip().lstrip("* ") for line in (listed.output or "").splitlines() if line.strip()]
            if not lines:
                return ToolResult(False, "", error="No checkpoint ref given and no jarvis-checkpoint-* branches exist")
            name = lines[-1]
        if name != "HEAD" and not name.startswith("jarvis-checkpoint-"):
            return ToolResult(False, "", error="Restore only accepts jarvis-checkpoint-* refs")
        restore_path = "."
        if target.strip():
            candidate = Path(target.strip())
            root = Path(repo).resolve()
            if candidate.is_absolute():
                try:
                    restore_path = candidate.resolve().relative_to(root).as_posix()
                except ValueError:
                    return ToolResult(False, "", error="Restore target is outside the repository")
            else:
                restore_path = candidate.as_posix()
            if ".." in Path(restore_path).parts:
                return ToolResult(False, "", error="Restore target is outside the repository")
        args = ["restore", "--source", name, "--worktree", "--staged", "--", restore_path]
        restored = await self._git(args, repo)
        if restored.success:
            return ToolResult(True, f"Restored {restore_path} from {name}. Inspect with git status / git diff.")
        checkout = ["checkout", name, "--", restore_path]
        fallback = await self._git(checkout, repo)
        if fallback.success:
            return ToolResult(True, f"Restored {restore_path} from {name}. Inspect with git status / git diff.")
        return ToolResult(False, "", error=restored.error or fallback.error or "Restore failed")
