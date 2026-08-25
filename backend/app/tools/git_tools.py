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
    is_production_checkout,
    list_worktrees,
    worktree_status,
)
from .base import RiskLevel, Tool, ToolResult
from .safety import resolve_allowed_path


_CHECKPOINT_RE = re.compile(r"^jarvis-checkpoint-[0-9]{8}T[0-9]{6}Z$")
_SHA_RE = re.compile(r"^[0-9a-f]{7,40}$")

_HASH = re.compile(r"^[0-9a-f]{40,64}$")


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
            "action": {
                "type": "string",
                "enum": [
                    "status",
                    "diff",
                    "branch",
                    "log",
                    "search",
                    "checkpoint",
                    "restore",
                    "list_checkpoints",
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
        stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
        branch = f"jarvis-checkpoint-{stamp}"
        created = await self._git(["branch", branch], cwd)
        if not created.success:
            return created
        stash = await self._git(["stash", "create"], cwd)
        blob = ""
        if stash.success:
            parts = (stash.output or "").strip().split()
            blob = parts[0] if parts else ""
        notes = [f"Backup branch {branch} created at HEAD. Working tree was not reset."]
        wip_ref = ""
        if blob and _HASH.match(blob):
            wip_ref = f"refs/jarvis-wip/{stamp}"
            stored = await self._git(["update-ref", wip_ref, blob], cwd)
            if stored.success:
                notes.append(f"Dirty work stored at {wip_ref} ({blob[:12]}). Use action=restore with that ref.")
            else:
                notes.append("stash create produced an object but the WIP ref could not be stored.")
        elif stash.success:
            notes.append("Working tree was clean; no WIP object was created.")
        else:
            notes.append(stash.error or "stash create skipped.")
        return ToolResult(
            True,
            "\n".join(notes),
            data={"branch": branch, "wip_ref": wip_ref, "stash_object": blob if _HASH.match(blob) else ""},
        )

    async def _restore(self, cwd: str, ref: str) -> ToolResult:
        if not ref:
            return ToolResult(False, "", error="ref is required for restore")
        allowed = ref.startswith("jarvis-checkpoint-") or ref.startswith("refs/jarvis-wip/") or bool(_HASH.match(ref))
        if not allowed:
            return ToolResult(False, "", error="restore only accepts jarvis-checkpoint-* branches, refs/jarvis-wip/*, or a stash object hash")
        checkout = await self._git(["checkout", ref, "--", "."], cwd)
        if not checkout.success:
            return checkout
        return ToolResult(True, f"Overlaid files from {ref} onto the current branch. Did not switch branches.")

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
            if action == "restore":
                return await self._restore(cwd, kwargs.get("ref") or "")
            if action == "list_checkpoints":
                return await self._list_checkpoints(cwd)
            if action == "worktree_add":
                spec = create_worktree(cwd, kwargs.get("path"))
                return ToolResult(True, f"Created worktree {spec.id}", data=spec.__dict__)
            if action == "worktree_list":
                return ToolResult(True, "\n".join(item.get("id", "") for item in list_worktrees()), data={"worktrees": list_worktrees()})
            if action == "worktree_status":
                return ToolResult(True, str(worktree_status(kwargs.get("path") or cwd)), data=worktree_status(kwargs.get("path") or cwd))
            if action == "worktree_remove":
                spec = discard_worktree(kwargs.get("worktree_id") or "")
                return ToolResult(True, f"Removed worktree {spec.id}")
            if action == "commit":
                result = checkpoint_commit(cwd, kwargs.get("message") or "jarvis checkpoint")
                return ToolResult(True, str(result), data=result)
            return ToolResult(False, "", error=f"Unknown action {action}")
        except WorktreeError as exc:
            return ToolResult(False, "", error=str(exc))
        except Exception as exc:
            return ToolResult(False, "", error=str(exc))

    async def _checkpoint(self, cwd: str) -> ToolResult:
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        branch = f"jarvis-checkpoint-{stamp}"
        created = await self._git(["branch", branch], cwd)
        if not created.success:
            return created
        status = await self._git(["status", "--porcelain=v1"], cwd)
        dirty = bool((status.output or "").strip())
        stash = await self._git(["stash", "create"], cwd)
        blob = ""
        if stash.success:
            parts = (stash.output or "").strip().split()
            blob = parts[0] if parts else ""
        wip_ref = ""
        notes = [
            f"Backup branch {branch} created at HEAD. Working tree was not reset. "
            "Working tree left unchanged (working tree unchanged)."
        ]
        if blob and (_HASH.match(blob) or _SHA_RE.fullmatch(blob)):
            wip_ref = f"refs/jarvis-wip/{stamp}"
            stored = await self._git(["update-ref", wip_ref, blob], cwd)
            if stored.success:
                notes.append(f"Dirty work stored at {wip_ref} ({blob[:12]}). Use action=restore with that ref.")
            else:
                notes.append("stash create produced an object but the WIP ref could not be stored.")
        elif stash.success:
            notes.append("Working tree was clean; no WIP object was created.")
        else:
            notes.append(stash.error or "stash create skipped.")
        return ToolResult(
            True,
            "\n".join(notes),
            data={
                "branch": branch,
                "wip_ref": wip_ref,
                "stash_object": blob if (_HASH.match(blob) or _SHA_RE.fullmatch(blob)) else "",
                "dirty": dirty,
            },
        )

    async def _list_checkpoints(self, cwd: str) -> ToolResult:
        branches = await self._git(["branch", "--list", "jarvis-checkpoint-*"], cwd)
        names = [line.strip().lstrip("* ").strip() for line in (branches.output or "").splitlines() if line.strip()]
        if not names:
            return ToolResult(True, "No Jarvis checkpoints", data={"checkpoints": []})
        return ToolResult(True, "\n".join(names), data={"checkpoints": names})

    async def _restore(self, cwd: str, ref: str) -> ToolResult:
        ref = (ref or "").strip()
        if not ref:
            return ToolResult(False, "", error="ref is required for restore")
        allowed = (
            ref.startswith("jarvis-checkpoint-")
            or ref.startswith("refs/jarvis-wip/")
            or ref.startswith("refs/jarvis/wip/")
            or bool(_HASH.match(ref))
        )
        if not allowed:
            return ToolResult(False, "", error="restore only accepts jarvis-checkpoint-* branches, refs/jarvis-wip/*, or a stash object hash")
        current = await self._git(["rev-parse", "--abbrev-ref", "HEAD"], cwd)
        overlay = await self._git(["checkout", ref, "--", "."], cwd)
        if not overlay.success:
            return overlay
        return ToolResult(
            True,
            f"Overlaid files from {ref} onto the current branch. Did not switch branches.",
            data={"branch": ref, "current_branch": (current.output or "").strip(), "wip_applied": False},
        )
