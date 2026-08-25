from __future__ import annotations

import difflib
import hashlib
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .base import RiskLevel, Tool, ToolResult
from .safety import resolve_allowed_path


_TEXT_SAMPLE = 4096
_DIFF_LINE_LIMIT = 200


def _allowed(context: dict[str, Any]) -> list[str]:
    return list(context.get("allowed_directories") or [])


def _is_probably_text(path: Path) -> bool:
    if not path.is_file():
        return False
    sample = path.read_bytes()[:_TEXT_SAMPLE]
    if b"\x00" in sample:
        return False
    try:
        sample.decode("utf-8")
        return True
    except UnicodeDecodeError:
        return False


def _file_digest(path: Path) -> str:
    hasher = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            hasher.update(chunk)
    return hasher.hexdigest()


def _mtime_iso(path: Path) -> str:
    return datetime.fromtimestamp(path.stat().st_mtime, timezone.utc).isoformat()


def compare_paths(left: Path, right: Path) -> str:
    """Compare two files or directories. Text files get a unified diff; binaries get hashes."""
    if not left.exists():
        raise FileNotFoundError(f"Missing {left}")
    if not right.exists():
        raise FileNotFoundError(f"Missing {right}")
    if left.is_dir() or right.is_dir():
        if not left.is_dir() or not right.is_dir():
            return f"Type mismatch: {left} is {'dir' if left.is_dir() else 'file'}, {right} is {'dir' if right.is_dir() else 'file'}"
        left_names = {p.name for p in left.iterdir()}
        right_names = {p.name for p in right.iterdir()}
        only_left = sorted(left_names - right_names)
        only_right = sorted(right_names - left_names)
        shared = sorted(left_names & right_names)
        lines = [
            f"Directory compare\n{left}\n{right}",
            f"shared={len(shared)} only_left={len(only_left)} only_right={len(only_right)}",
        ]
        if only_left:
            lines.append("Only in left: " + ", ".join(only_left[:40]))
        if only_right:
            lines.append("Only in right: " + ", ".join(only_right[:40]))
        return "\n".join(lines)
    left_hash = _file_digest(left)
    right_hash = _file_digest(right)
    left_size = left.stat().st_size
    right_size = right.stat().st_size
    header = (
        f"left={left} size={left_size} mtime={_mtime_iso(left)} sha256={left_hash}\n"
        f"right={right} size={right_size} mtime={_mtime_iso(right)} sha256={right_hash}"
    )
    if left_hash == right_hash:
        return header + "\nidentical=true"
    if not _is_probably_text(left) or not _is_probably_text(right):
        return header + "\nidentical=false\nbinary_or_non_utf8=true"
    left_lines = left.read_text(encoding="utf-8", errors="replace").splitlines(keepends=True)
    right_lines = right.read_text(encoding="utf-8", errors="replace").splitlines(keepends=True)
    diff = list(
        difflib.unified_diff(
            left_lines,
            right_lines,
            fromfile=str(left),
            tofile=str(right),
            n=3,
        )
    )
    if len(diff) > _DIFF_LINE_LIMIT:
        omitted = len(diff) - _DIFF_LINE_LIMIT
        diff = diff[:_DIFF_LINE_LIMIT] + [f"...[{omitted} more diff lines omitted]...\n"]
    return header + "\nidentical=false\n" + "".join(diff)


def recent_versions(path: Path, limit: int = 40) -> list[dict[str, Any]]:
    """Find backup copies and recently modified siblings of a file."""
    if path.exists() and path.is_dir():
        entries = [item for item in path.iterdir() if item.is_file()]
        entries.sort(key=lambda item: item.stat().st_mtime, reverse=True)
        return [
            {
                "path": str(item),
                "size": item.stat().st_size,
                "mtime": _mtime_iso(item),
                "kind": "recent_in_directory",
            }
            for item in entries[:limit]
        ]

    parent = path.parent if path.name else path
    if not parent.exists() or not parent.is_dir():
        return []
    name = path.name
    stem = path.stem
    suffix = path.suffix
    found: list[dict[str, Any]] = []
    seen: set[str] = set()
    if path.exists() and path.is_file():
        found.append(
            {
                "path": str(path),
                "size": path.stat().st_size,
                "mtime": _mtime_iso(path),
                "kind": "current",
            }
        )
        seen.add(str(path.resolve()))

    for item in parent.iterdir():
        if not item.is_file():
            continue
        key = str(item.resolve())
        if key in seen:
            continue
        n = item.name
        is_backup = (
            n == f"{name}.bak"
            or n.startswith(f"{name}.bak-")
            or n.startswith(f"{name}.bak.")
            or n == f"{stem}.bak{suffix}"
            or (n.startswith(f"{stem}.bak-") and n.endswith(suffix))
        )
        if not is_backup:
            continue
        seen.add(key)
        found.append(
            {
                "path": str(item),
                "size": item.stat().st_size,
                "mtime": _mtime_iso(item),
                "kind": "backup",
            }
        )
    found.sort(key=lambda row: row["mtime"], reverse=True)
    return found[:limit]


class FilesystemTool(Tool):
    name = "filesystem"
    description = (
        "Inspect and modify files and directories. Actions: list, search, read, write, edit, "
        "copy, move, rename, mkdir, delete, hash, stat, compare, recent, restore. Use this for organizing "
        "files, creating documents, and inspecting project trees. Prefer write/edit over delete. "
        "compare shows a unified diff (or hashes for binaries). recent lists backup copies and "
        "recent versions next to a file. restore copies the newest .bak sidecar back over the file. "
        "Binary files are supported via hash/stat/copy; read returns a note for large binaries."
    )
    risk = RiskLevel.MEDIUM
    parameters = {
        "type": "object",
        "properties": {
            "action": {
                "type": "string",
                "enum": [
                    "list",
                    "search",
                    "read",
                    "write",
                    "edit",
                    "copy",
                    "move",
                    "rename",
                    "mkdir",
                    "delete",
                    "hash",
                    "stat",
                    "compare",
                    "recent",
                    "restore",
                ],
            },
            "path": {"type": "string", "description": "Primary path"},
            "destination": {"type": "string", "description": "Second path for compare, or copy/move/rename target"},
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

    def _want_backup(self, kwargs: dict[str, Any]) -> bool:
        if not self.context_getter().get("backup_enabled", True):
            return False
        return bool(kwargs.get("create_backup", True))

    def _backup_file(self, path: Path) -> Path:
        stamp = datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S")
        dest = path.with_name(path.name + f".bak-{stamp}")
        shutil.copy2(path, dest)
        self._prune_backups(path)
        return dest

    def _prune_backups(self, path: Path, keep: int = 3) -> None:
        matches = sorted(
            path.parent.glob(path.name + ".bak-*"),
            key=lambda item: item.stat().st_mtime,
            reverse=True,
        )
        for stale in matches[keep:]:
            try:
                stale.unlink()
            except OSError:
                pass

    def _latest_backup(self, path: Path) -> Path | None:
        matches = list(path.parent.glob(path.name + ".bak*"))
        if not matches:
            return None
        return max(matches, key=lambda item: item.stat().st_mtime)

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
                if path.exists() and self._want_backup(kwargs):
                    self._backup_file(path)
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
                if self._want_backup(kwargs):
                    self._backup_file(path)
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
                if path.is_file() and self._want_backup(kwargs):
                    self._backup_file(path)
                if path.is_dir():
                    shutil.rmtree(path)
                else:
                    path.unlink()
                return ToolResult(True, f"Deleted {path}")
            if action == "restore":
                backup = self._latest_backup(path)
                if backup is None:
                    return ToolResult(False, "", error=f"No .bak sidecar found for {path}")
                shutil.copy2(backup, path)
                return ToolResult(True, f"Restored {path} from {backup.name}")
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
            if action == "compare":
                other_raw = kwargs.get("destination") or kwargs.get("other") or ""
                if not other_raw:
                    return ToolResult(False, "", error="compare requires destination (the second path)")
                other = self._path(other_raw)
                return ToolResult(True, compare_paths(path, other), data={"left": str(path), "right": str(other)})
            if action == "recent":
                versions = recent_versions(path)
                if not versions:
                    return ToolResult(True, f"No recent versions or backups found next to {path}")
                lines = [
                    f"{row['kind']:18} {row['size']:10} {row['mtime']}  {row['path']}"
                    for row in versions
                ]
                return ToolResult(True, "\n".join(lines), data={"versions": versions})
            return ToolResult(False, "", error=f"Unknown action {action}")
        except Exception as exc:
            return ToolResult(False, "", error=str(exc))
