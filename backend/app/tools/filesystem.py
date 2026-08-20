from __future__ import annotations

import hashlib
import os
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .base import RiskLevel, Tool, ToolResult
from .safety import resolve_allowed_path


def _allowed(context: dict[str, Any]) -> list[str]:
    return list(context.get("allowed_directories") or [])


class FilesystemTool(Tool):
    name = "filesystem"
    description = (
        "Inspect and modify files and directories. Actions: list, search, read, write, edit, "
        "copy, move, rename, mkdir, delete, hash, stat. Use this for organizing files, creating "
        "documents, and inspecting project trees. Prefer write/edit over delete. Binary files "
        "are supported via hash/stat/copy; read returns a note for large binaries."
    )
    risk = RiskLevel.MEDIUM
    parameters = {
        "type": "object",
        "properties": {
            "action": {
                "type": "string",
                "enum": ["list", "search", "read", "write", "edit", "copy", "move", "rename", "mkdir", "delete", "hash", "stat"],
            },
            "path": {"type": "string", "description": "Primary path"},
            "destination": {"type": "string"},
            "content": {"type": "string"},
            "pattern": {"type": "string", "description": "Glob or substring for search"},
            "recursive": {"type": "boolean", "default": True},
            "old_text": {"type": "string", "description": "Exact text to replace for edit"},
            "new_text": {"type": "string"},
            "create_backup": {"type": "boolean", "default": True},
        },
        "required": ["action", "path"],
    }

    def __init__(self, context_getter) -> None:
        self.context_getter = context_getter

    def _path(self, raw: str) -> Path:
        return resolve_allowed_path(raw, _allowed(self.context_getter()))

    async def execute(self, **kwargs: Any) -> ToolResult:
        action = kwargs.get("action")
        try:
            path = self._path(kwargs["path"])
            if action == "list":
                if not path.exists():
                    return ToolResult(False, "", error="Path does not exist")
                entries = []
                for item in sorted(path.iterdir(), key=lambda p: p.name.lower()):
                    entries.append(
                        f"{'DIR' if item.is_dir() else 'FILE':4} {item.stat().st_size:10} {item}"
                    )
                return ToolResult(True, "\n".join(entries) or "(empty)")
            if action == "search":
                pattern = kwargs.get("pattern") or "*"
                matches = list(path.rglob(pattern))[:400] if kwargs.get("recursive", True) else list(path.glob(pattern))[:400]
                return ToolResult(True, "\n".join(str(m) for m in matches) or "No matches")
            if action == "read":
                if not path.exists():
                    return ToolResult(False, "", error="File not found")
                if path.stat().st_size > 2_000_000:
                    return ToolResult(True, f"File is {path.stat().st_size} bytes. Too large to inline; use search/hash or read a smaller slice.")
                try:
                    return ToolResult(True, path.read_text(encoding="utf-8"))
                except UnicodeDecodeError:
                    digest = hashlib.sha256(path.read_bytes()).hexdigest()
                    return ToolResult(True, f"Binary file ({path.stat().st_size} bytes). sha256={digest}")
            if action == "write":
                path.parent.mkdir(parents=True, exist_ok=True)
                if path.exists() and kwargs.get("create_backup", True):
                    backup = path.with_suffix(path.suffix + f".bak-{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S')}")
                    shutil.copy2(path, backup)
                path.write_text(kwargs.get("content") or "", encoding="utf-8")
                return ToolResult(True, f"Wrote {path} ({path.stat().st_size} bytes)")
            if action == "edit":
                if not path.exists():
                    return ToolResult(False, "", error="File not found")
                text = path.read_text(encoding="utf-8")
                old = kwargs.get("old_text") or ""
                new = kwargs.get("new_text") or ""
                if old not in text:
                    return ToolResult(False, "", error="old_text not found in file")
                if kwargs.get("create_backup", True):
                    shutil.copy2(path, path.with_suffix(path.suffix + ".bak"))
                path.write_text(text.replace(old, new, 1), encoding="utf-8")
                return ToolResult(True, f"Edited {path}")
            if action in {"copy", "move", "rename"}:
                dest = self._path(kwargs.get("destination") or "")
                dest.parent.mkdir(parents=True, exist_ok=True)
                if action == "copy":
                    if path.is_dir():
                        shutil.copytree(path, dest, dirs_exist_ok=True)
                    else:
                        shutil.copy2(path, dest)
                else:
                    shutil.move(str(path), str(dest))
                return ToolResult(True, f"{action} {path} -> {dest}")
            if action == "mkdir":
                path.mkdir(parents=True, exist_ok=True)
                return ToolResult(True, f"Created directory {path}")
            if action == "delete":
                if not path.exists():
                    return ToolResult(False, "", error="Path does not exist")
                if path.is_dir():
                    shutil.rmtree(path)
                else:
                    path.unlink()
                return ToolResult(True, f"Deleted {path}")
            if action == "hash":
                digest = hashlib.sha256(path.read_bytes()).hexdigest()
                return ToolResult(True, f"sha256 {digest}  {path}")
            if action == "stat":
                st = path.stat()
                info = (
                    f"path={path}\nexists={path.exists()}\nis_dir={path.is_dir()}\n"
                    f"size={st.st_size}\nmtime={datetime.fromtimestamp(st.st_mtime, timezone.utc).isoformat()}\n"
                    f"mode={oct(st.st_mode)}"
                )
                return ToolResult(True, info)
            return ToolResult(False, "", error=f"Unknown action {action}")
        except Exception as exc:
            return ToolResult(False, "", error=str(exc))
