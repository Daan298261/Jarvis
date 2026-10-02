from __future__ import annotations

import difflib
import hashlib
import os
import shutil
import tarfile
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from ..config import LOCAL_NETWORK_SCOPE, live_workspace_roots_from_context
from .base import RiskLevel, Tool, ToolResult
from .owner_paths import resolve_owner_file_path
from .safety import resolve_allowed_path
from .snapshots import create_snapshot, list_snapshots, restore_snapshot


_TEXT_SAMPLE = 4096
_DIFF_LINE_LIMIT = 200
_ARCHIVE_SUFFIXES = (".tar.gz", ".tar.bz2", ".tar.xz", ".tgz", ".tar", ".zip")
_EXTRACT_MAX_FILES = 20_000
_EXTRACT_MAX_BYTES = 8 * 1024 * 1024 * 1024


def archive_folder_name(path: Path) -> str:
    name = path.name
    lower = name.lower()
    for suffix in _ARCHIVE_SUFFIXES:
        if lower.endswith(suffix):
            stem = name[: -len(suffix)]
            return stem or "archive"
    return path.stem or "archive"


def looks_like_archive(path: Path) -> bool:
    lower = path.name.lower()
    return any(lower.endswith(suffix) for suffix in _ARCHIVE_SUFFIXES)


def safe_extract_target(dest: Path, member_name: str) -> Path:
    """Join an archive member under dest; refuse zip-slip and absolute names."""
    dest_root = dest.resolve()
    cleaned = str(member_name or "").replace("\\", "/")
    if cleaned.startswith("/") or cleaned.startswith("\\\\") or (len(cleaned) >= 2 and cleaned[1] == ":"):
        raise ValueError(f"refusing absolute archive member {member_name!r}")
    parts: list[str] = []
    for part in cleaned.split("/"):
        if part in ("", "."):
            continue
        if part == "..":
            raise ValueError(f"refusing path traversal: {member_name}")
        parts.append(part)
    if not parts:
        raise ValueError(f"invalid archive member {member_name!r}")
    target = dest_root.joinpath(*parts)
    try:
        target.resolve().relative_to(dest_root)
    except ValueError as exc:
        raise ValueError(f"refusing path traversal: {member_name}") from exc
    return target


def extract_archive(archive: Path, dest: Path) -> list[str]:
    """Extract a zip/tar archive into dest. Returns written file paths."""
    dest.mkdir(parents=True, exist_ok=True)
    written: list[str] = []
    total = 0
    lower = archive.name.lower()
    if lower.endswith(".zip"):
        if not zipfile.is_zipfile(archive):
            raise ValueError(f"{archive} is not a zip archive")
        with zipfile.ZipFile(archive) as zf:
            for info in zf.infolist():
                name = info.filename.replace("\\", "/")
                if name.endswith("/") or info.is_dir():
                    safe_extract_target(dest, name.rstrip("/")).mkdir(parents=True, exist_ok=True)
                    continue
                target = safe_extract_target(dest, name)
                if info.file_size < 0:
                    raise ValueError(f"invalid zip member size: {name}")
                total += int(info.file_size or 0)
                if total > _EXTRACT_MAX_BYTES:
                    raise ValueError("archive is larger than the 8 GiB extract limit")
                if len(written) >= _EXTRACT_MAX_FILES:
                    raise ValueError("archive has more than 20000 files")
                target.parent.mkdir(parents=True, exist_ok=True)
                with zf.open(info, "r") as src, target.open("wb") as out:
                    shutil.copyfileobj(src, out)
                written.append(str(target))
        return written
    if not tarfile.is_tarfile(archive):
        raise ValueError(f"{archive.name} is not a zip or tar archive")
    with tarfile.open(archive, "r:*") as tf:
        for member in tf.getmembers():
            if member.issym() or member.islnk() or member.isdev() or member.isfifo():
                continue
            if member.isdir():
                safe_extract_target(dest, member.name).mkdir(parents=True, exist_ok=True)
                continue
            if not member.isfile():
                continue
            target = safe_extract_target(dest, member.name)
            size = int(member.size or 0)
            if size < 0:
                raise ValueError(f"invalid tar member size: {member.name}")
            total += size
            if total > _EXTRACT_MAX_BYTES:
                raise ValueError("archive is larger than the 8 GiB extract limit")
            if len(written) >= _EXTRACT_MAX_FILES:
                raise ValueError("archive has more than 20000 files")
            handle = tf.extractfile(member)
            if handle is None:
                continue
            target.parent.mkdir(parents=True, exist_ok=True)
            with handle, target.open("wb") as out:
                shutil.copyfileobj(handle, out)
            written.append(str(target))
    return written


def _allowed(context: dict[str, Any]) -> list[str]:
    return live_workspace_roots_from_context(context)


def _root_key(path: Path) -> str:
    return os.path.normcase(str(path).replace("\\", "/")).rstrip("/") or "/"


def existing_local_roots(allowed: list[str]) -> list[Path]:
    """Resolved local workspace roots, excluding the LAN-share sentinel."""
    roots: list[Path] = []
    seen: set[str] = set()
    for raw in allowed:
        text = str(raw or "").strip()
        if not text or text == LOCAL_NETWORK_SCOPE:
            continue
        try:
            path = Path(text).expanduser().resolve()
        except OSError:
            continue
        if not path.exists():
            continue
        key = _root_key(path)
        if key in seen:
            continue
        seen.add(key)
        roots.append(path)
    return roots


def _system_volume_keys() -> set[str]:
    """Whole-volume roots that would make an unscoped search walk the OS tree."""
    keys: set[str] = set()
    if os.name == "nt":
        keys.add(_root_key(Path(Path.home().anchor)))
    else:
        keys.add("/")
    return keys


def search_workspace_roots(allowed: list[str]) -> list[Path]:
    """Roots to walk for an unscoped search: extra drives and profile folders, not C:\\ or /."""
    local = existing_local_roots(allowed)
    if not local:
        return []
    skip = _system_volume_keys()
    preferred = [path for path in local if _root_key(path) not in skip]
    return preferred or local


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
        "copy, move, rename, mkdir, delete, hash, stat, compare, recent, extract. Use this for "
        "organizing files, creating documents, and inspecting project trees. Omit path on list to "
        "see every allowed drive, mount, and folder (plus private LAN UNC). Omit path on search to "
        "look across those folders and extra volumes without walking the OS drive root. extract "
        "unpacks zip/tar archives onto an allowed folder (USB/`D:` included); omit destination to "
        "create a folder next to the archive. Omit path on write to save Documents/note.txt; a "
        "folder path (USB/`D:`) gets note.txt appended. copy/move omit destination to save "
        "Documents/<filename>; a folder path (USB/`D:`) gets the source name appended. Prefer write/edit over delete. compare shows a "
        "unified diff (or hashes for binaries). recent lists backup copies and recent versions "
        "next to a file. snapshot copies a directory or file into data/backups before mass edits; "
        "snapshots lists them; restore copies a snapshot back. Identical trees are not snapshotted "
        "again. Binary files are supported via hash/stat/copy; read returns a note for large binaries."
    )
    risk = RiskLevel.MEDIUM
    # Per-action class resolved by RFC-0031; default UNKNOWN until action known.
    reversibility = "UNKNOWN"
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
                    "extract",
                    "snapshot",
                    "snapshots",
                    "restore",
                ],
            },
            "path": {
                "type": "string",
                "description": "Primary path. Omit on list/search to cover the whole allowed workspace. Omit write to save Documents/note.txt.",
            },
            "destination": {
                "type": "string",
                "description": "Second path for compare, copy/move/rename/restore, or extract folder. Omit copy/move to save Documents/<filename>; a folder path (USB/`D:`) gets the source name. Omit extract to unpack next to the archive.",
            },
            "content": {"type": "string"},
            "pattern": {"type": "string", "description": "Glob or substring for search"},
            "recursive": {"type": "boolean", "default": True},
            "old_text": {"type": "string", "description": "Exact text to replace for edit"},
            "new_text": {"type": "string"},
            "create_backup": {"type": "boolean", "default": True},
            "snapshot_id": {"type": "string", "description": "Snapshot id for restore"},
            "note": {"type": "string", "description": "Optional snapshot note"},
        },
        "required": ["action"],
    }

    def __init__(self, context_getter) -> None:
        self.context_getter = context_getter

    def _path(self, raw: str) -> Path:
        return resolve_allowed_path(raw, _allowed(self.context_getter()))

    def _copy_dest(self, source: Path, dest_raw: str, allowed: list[str]) -> Path:
        name = source.name or "copy"
        text = str(dest_raw or "").strip()
        if not text:
            return resolve_owner_file_path(
                None,
                suggested_name=name,
                allowed=allowed,
                fallback_dirs=("Documents", "Desktop", "Downloads"),
            )
        as_dir = text.endswith(("/", "\\"))
        dest = self._path(text.rstrip("/\\") if as_dir else text)
        try:
            as_dir = as_dir or dest.is_dir()
        except OSError:
            pass
        if as_dir:
            dest = dest / name
        return dest

    def _list_workspace(self, allowed: list[str]) -> ToolResult:
        roots = existing_local_roots(allowed)
        entries: list[str] = []
        for item in roots:
            try:
                size = item.stat().st_size
            except OSError:
                size = 0
            kind = "DIR" if item.is_dir() else "FILE"
            entries.append(f"{kind:4} {size:10} {item}")
        if LOCAL_NETWORK_SCOPE in allowed:
            entries.append(
                "SHARE          "
                f"{LOCAL_NETWORK_SCOPE}  (private LAN UNC such as \\\\nas.local\\share)"
            )
        return ToolResult(
            True,
            "\n".join(entries) or "(empty)",
            data={
                "roots": [str(path) for path in roots],
                "lan_shares": LOCAL_NETWORK_SCOPE in allowed,
            },
        )

    def _search_workspace(self, allowed: list[str], pattern: str, *, recursive: bool) -> ToolResult:
        matches: list[str] = []
        for root in search_workspace_roots(allowed):
            try:
                found = root.rglob(pattern) if recursive else root.glob(pattern)
                for item in found:
                    matches.append(str(item))
                    if len(matches) >= 400:
                        return ToolResult(True, "\n".join(matches), data={"matches": matches, "truncated": True})
            except OSError:
                continue
        return ToolResult(True, "\n".join(matches) or "No matches", data={"matches": matches})

    def _guard_coding_write(self, resolved: Path) -> Path:
        ctx = self.context_getter() or {}
        task_id = str(ctx.get("task_id") or "").strip()
        if not task_id:
            return resolved
        from ..agent.worktrees import WorktreeError, assert_task_write_path, get_coding_task

        try:
            get_coding_task(task_id)
        except WorktreeError:
            return resolved
        return assert_task_write_path(task_id, resolved)

    async def execute(self, **kwargs: Any) -> ToolResult:
        action = kwargs.get("action")
        try:
            ctx = self.context_getter()
            if action == "snapshots":
                source = self._path(kwargs["path"]) if kwargs.get("path") else None
                rows = list_snapshots(ctx, source=source)
                if not rows:
                    return ToolResult(True, "No directory snapshots yet.")
                lines = [
                    f"{row['id']}  files={row.get('files')}  {row.get('created_at')}  {row.get('source')}"
                    + ("  [identical skipped]" if row.get("skipped") else "")
                    for row in rows
                ]
                return ToolResult(True, "\n".join(lines), data={"snapshots": rows})
            if action == "restore":
                snapshot_id = kwargs.get("snapshot_id") or ""
                dest_raw = kwargs.get("destination") or kwargs.get("path") or ""
                if not snapshot_id or not dest_raw:
                    return ToolResult(False, "", error="restore requires snapshot_id and destination")
                dest = self._path(dest_raw)
                payload = restore_snapshot(snapshot_id, dest, ctx)
                return ToolResult(True, f"Restored {payload.get('restored')} files to {dest}", data=payload)
            if action == "snapshot":
                if not kwargs.get("path"):
                    return ToolResult(False, "", error="path is required")
                path = self._path(kwargs["path"])
                payload = create_snapshot(path, ctx, note=kwargs.get("note") or "")
                if payload.get("skipped"):
                    return ToolResult(True, f"Skipped extra snapshot; identical to {payload.get('id')}", data=payload)
                return ToolResult(
                    True,
                    f"Created snapshot {payload['id']} ({payload.get('files')} files, {payload.get('bytes')} bytes)",
                    data=payload,
                )
            allowed = _allowed(ctx)
            raw_path = str(kwargs.get("path") or "").strip()
            if action in {"list", "search"} and not raw_path:
                if action == "list":
                    return self._list_workspace(allowed)
                return self._search_workspace(
                    allowed,
                    str(kwargs.get("pattern") or "*"),
                    recursive=bool(kwargs.get("recursive", True)),
                )
            if action == "write":
                path = resolve_owner_file_path(
                    raw_path or None,
                    suggested_name="note.txt",
                    allowed=allowed,
                    fallback_dirs=("Documents", "Desktop", "Downloads"),
                )
                path = self._guard_coding_write(path)
                path.parent.mkdir(parents=True, exist_ok=True)
                if path.exists() and kwargs.get("create_backup", True):
                    backup = path.with_suffix(path.suffix + f".bak-{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S')}")
                    shutil.copy2(path, backup)
                path.write_text(kwargs.get("content") or "", encoding="utf-8")
                return ToolResult(True, f"Wrote {path} ({path.stat().st_size} bytes)")
            path = self._path(raw_path)
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
            if action == "edit":
                path = self._guard_coding_write(path)
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
            if action == "extract":
                if not path.is_file():
                    return ToolResult(False, "", error="extract requires a zip or tar archive file")
                dest_raw = str(kwargs.get("destination") or "").strip()
                if dest_raw:
                    dest = self._path(dest_raw)
                    if dest.exists() and dest.is_file():
                        return ToolResult(False, "", error="extract destination must be a folder")
                else:
                    dest = self._path(str(path.parent / archive_folder_name(path)))
                    if dest.exists() and dest.is_file():
                        return ToolResult(False, "", error="extract destination must be a folder")
                dest = self._guard_coding_write(dest)
                files = extract_archive(path, dest)
                listing = files[:400]
                return ToolResult(
                    True,
                    f"Extracted {len(files)} file(s) to {dest}",
                    data={"destination": str(dest), "files": listing, "truncated": len(files) > 400},
                )
            if action in {"copy", "move", "rename"}:
                dest_raw = str(kwargs.get("destination") or "").strip()
                if action == "rename" and not dest_raw:
                    return ToolResult(False, "", error="destination is required for rename")
                dest = self._copy_dest(path, dest_raw, allowed)
                dest = self._guard_coding_write(dest)
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
