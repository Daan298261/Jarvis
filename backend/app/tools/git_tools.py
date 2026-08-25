from __future__ import annotations

import asyncio
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .base import RiskLevel, Tool, ToolResult

_HASH = re.compile(r"^[0-9a-f]{40,64}$")


class GitTool(Tool):
    name = "git"
    description = (
        "Inspect and checkpoint git repositories. Actions: status, diff, branch, log, search, "
        "checkpoint, restore. checkpoint creates a jarvis-checkpoint-* backup branch at HEAD and "
        "stores dirty work with stash create so the working tree is not emptied. restore overlays "
        "files from a checkpoint ref without switching branch."
    )
    risk = RiskLevel.MEDIUM
    parameters = {
        "type": "object",
        "properties": {
            "action": {
                "type": "string",
                "enum": ["status", "diff", "branch", "log", "search", "checkpoint", "restore"],
            },
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

    async def _checkpoint(self, cwd: str) -> ToolResult:
        stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
        branch = f"jarvis-checkpoint-{stamp}"
        created = await self._git(["branch", branch], cwd)
        if not created.success:
            return created
        stash = await self._git(["stash", "create"], cwd)
        blob = (stash.output or "").strip().split()[0] if stash.success else ""
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
                return await self._checkpoint(cwd)
            if action == "restore":
                return await self._restore(cwd, kwargs.get("ref") or "")
            return ToolResult(False, "", error=f"Unknown action {action}")
        except Exception as exc:
            return ToolResult(False, "", error=str(exc))
