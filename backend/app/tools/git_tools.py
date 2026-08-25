from __future__ import annotations

import asyncio
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from ..agent.worktrees import (
    WorktreeError,
    checkpoint_commit,
    create_worktree,
    discard_worktree,
    list_worktrees,
    worktree_status,
)
from .base import RiskLevel, Tool, ToolResult
from .safety import resolve_allowed_path


_CHECKPOINT_RE = re.compile(r"^jarvis-checkpoint-[0-9]{8}T[0-9]{6}Z$")
_SHA_RE = re.compile(r"^[0-9a-f]{7,40}$")


class GitTool(Tool):
    name = "git"
    description = (
        "Inspect and checkpoint git repositories. Actions: status, diff, branch, log, search, "
        "checkpoint, list_checkpoints, restore, worktree_add, worktree_list, worktree_status, "
        "worktree_remove, commit. checkpoint creates a recoverable backup branch named "
        "jarvis-checkpoint-* without resetting the working tree."
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
                    "list_checkpoints",
                    "restore",
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

    def __init__(self, context_getter=None) -> None:
        self.context_getter = context_getter or (lambda: {})

    def _cwd(self, path: str | None) -> str:
        allowed = list((self.context_getter() or {}).get("allowed_directories") or [])
        if path:
            return str(resolve_allowed_path(path, allowed))
        return str(Path.cwd())

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

    async def _checkpoint(self, cwd: str) -> ToolResult:
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        name = f"jarvis-checkpoint-{stamp}"
        created = await self._git(["branch", name], cwd)
        if not created.success:
            return created
        status = await self._git(["status", "--porcelain=v1"], cwd)
        dirty = bool((status.output or "").strip())
        wip_ref = ""
        if dirty:
            await self._git(["add", "-A"], cwd)
            stash = await self._git(["stash", "create"], cwd)
            await self._git(["reset", "HEAD"], cwd)
            sha = (stash.output or "").strip().splitlines()[-1] if (stash.output or "").strip() else ""
            if stash.success and _SHA_RE.fullmatch(sha):
                wip_ref = f"refs/jarvis/wip/{name}"
                stored = await self._git(["update-ref", wip_ref, sha], cwd)
                if not stored.success:
                    wip_ref = ""
        head = await self._git(["rev-parse", "--short", "HEAD"], cwd)
        sha_head = (head.output or "").strip()
        msg = (
            f"Backup branch {name} created at {sha_head} without changing the working tree. "
            "Working tree was not reset. Working tree left unchanged (working tree unchanged). "
            "Continue editing; use git action=restore with this ref to overlay the snapshot."
        )
        if wip_ref:
            msg += f" Uncommitted files stored at {wip_ref}."
        elif dirty:
            msg += " Working tree is dirty but git could not snapshot uncommitted files."
        else:
            msg += " Working tree was clean."
        return ToolResult(
            True,
            msg,
            data={"branch": name, "wip_ref": wip_ref, "dirty": dirty, "head": sha_head},
        )

    async def _list_checkpoints(self, cwd: str) -> ToolResult:
        branches = await self._git(["branch", "--list", "jarvis-checkpoint-*"], cwd)
        wips = await self._git(["for-each-ref", "--format=%(refname)", "refs/jarvis/wip"], cwd)
        names = [line.strip().lstrip("* ").strip() for line in (branches.output or "").splitlines() if line.strip()]
        wip_refs = [line.strip() for line in (wips.output or "").splitlines() if line.strip()]
        if not names and not wip_refs:
            return ToolResult(True, "No Jarvis checkpoints", data={"checkpoints": []})
        lines = names + [f"wip {ref}" for ref in wip_refs]
        return ToolResult(True, "\n".join(lines), data={"checkpoints": names, "wip_refs": wip_refs})

    async def _restore(self, cwd: str, ref: str) -> ToolResult:
        ref = (ref or "").strip()
        if not ref:
            return ToolResult(False, "", error="ref is required for restore")
        if ref.startswith("refs/jarvis/wip/"):
            branch = ref.rsplit("/", 1)[-1]
        else:
            branch = ref
        if not _CHECKPOINT_RE.match(branch) and not branch.startswith("jarvis-checkpoint-"):
            return ToolResult(False, "", error="restore only accepts jarvis-checkpoint-* refs")
        current = await self._git(["rev-parse", "--abbrev-ref", "HEAD"], cwd)
        overlay = await self._git(["checkout", branch, "--", "."], cwd)
        if not overlay.success:
            return overlay
        wip_ref = f"refs/jarvis/wip/{branch}"
        wip = await self._git(["rev-parse", "--verify", wip_ref], cwd)
        applied = False
        if wip.success:
            applied_result = await self._git(["stash", "apply", (wip.output or "").strip()], cwd)
            applied = applied_result.success
        return ToolResult(
            True,
            f"Overlaid files from {branch} onto {(current.output or '').strip()} without switching branch."
            + (" Applied uncommitted WIP snapshot." if applied else ""),
            data={"branch": branch, "wip_applied": applied, "current_branch": (current.output or "").strip()},
        )

    async def execute(self, **kwargs: Any) -> ToolResult:
        action = kwargs.get("action")
        try:
            cwd = self._cwd(kwargs.get("path"))
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
                if not query:
                    return ToolResult(False, "", error="query is required for search")
                return await self._git(["grep", "-n", query], cwd)
            if action == "checkpoint":
                repo = await self._git(["rev-parse", "--is-inside-work-tree"], cwd)
                if not repo.success:
                    return ToolResult(False, "", error="path is not a git repository")
                return await self._checkpoint(cwd)
            if action == "list_checkpoints":
                return await self._list_checkpoints(cwd)
            if action == "restore":
                return await self._restore(cwd, kwargs.get("ref") or "")
            if action == "worktree_add":
                spec = create_worktree(cwd, kwargs.get("destination"), kwargs.get("ref"))
                return ToolResult(True, f"Created worktree {spec.path} on {spec.branch}", data=spec.as_dict())
            if action == "worktree_list":
                items = list_worktrees()
                if not items:
                    return ToolResult(True, "No Jarvis worktrees", data={"worktrees": []})
                lines = [f"{item['id']} {item['branch']} {item['path']}" for item in items]
                return ToolResult(True, "\n".join(lines), data={"worktrees": items})
            if action == "worktree_status":
                info = worktree_status(cwd)
                return ToolResult(True, info.get("status") or str(info), data=info)
            if action == "worktree_remove":
                spec = discard_worktree(str(kwargs.get("worktree_id") or ""))
                return ToolResult(True, f"Discarded worktree {spec.id}", data=spec.as_dict())
            if action == "commit":
                info = checkpoint_commit(cwd, kwargs.get("message") or "jarvis checkpoint")
                return ToolResult(True, info.get("message") or str(info), data=info)
            return ToolResult(False, "", error=f"Unknown action {action}")
        except WorktreeError as exc:
            return ToolResult(False, "", error=str(exc))
        except Exception as exc:
            return ToolResult(False, "", error=str(exc))
