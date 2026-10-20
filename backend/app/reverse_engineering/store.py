from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import stat
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path

from ..config import LOCAL_NETWORK_SCOPE, data_dir
from ..tools.safety import _is_unc_path, reject_unsafe_path_text, resolve_allowed_path
from .privacy import private_directory

_ID = re.compile(r"^[a-f0-9]{32}$")
MAX_FILES = 50000
MAX_BYTES = 8 * 1024**3
# Owner decisions that no background writer may downgrade (RFC-0201 close/cancel).
TERMINAL_STATUSES = frozenset({"closed", "cancelled"})
_ROW_LOCKS: dict[str, threading.Lock] = {}
_ROW_LOCKS_GUARD = threading.Lock()


def root() -> Path:
    p = data_dir() / "investigations"
    private_directory(p)
    return p


def directory(ident: str) -> Path:
    if not _ID.fullmatch(ident or ""):
        raise ValueError("Invalid investigation id")
    p = root() / ident
    if p.is_symlink():
        raise PermissionError("Investigation directory is a symbolic link")
    return p


def atomic_json(path: Path, value: dict) -> None:
    tmp = path.with_name(path.name + "." + uuid.uuid4().hex + ".tmp")
    tmp.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")
    os.chmod(tmp, 0o600)
    os.replace(tmp, path)


def load(ident: str) -> dict:
    return json.loads((directory(ident) / "investigation.json").read_text(encoding="utf-8"))


def save(row: dict) -> dict:
    row["updated_at"] = datetime.now(timezone.utc).isoformat()
    atomic_json(directory(row["id"]) / "investigation.json", row)
    return row


def row_lock(ident: str) -> threading.Lock:
    """Per-investigation lock serializing status read-modify-writes across threads."""
    with _ROW_LOCKS_GUARD:
        return _ROW_LOCKS.setdefault(ident, threading.Lock())


def save_guarded(row: dict) -> bool:
    """Save ``row`` but never downgrade a closed/cancelled status already on disk.

    Background writers (the FFS ingest thread) hold a stale in-memory row; the owner's
    close/cancel wins. Returns True when the stored status is terminal, so the caller stops.
    """
    with row_lock(row["id"]):
        try:
            current = load(row["id"]).get("status")
        except FileNotFoundError:
            current = None
        terminal = current in TERMINAL_STATUSES
        if terminal:
            row["status"] = current
        save(row)
        return terminal


def set_status(ident: str, status: str, unless: frozenset[str] | set[str] = frozenset()) -> dict:
    """Atomically set ``status`` (re-reading the row) unless the stored status is in ``unless``."""
    with row_lock(ident):
        row = load(ident)
        if row.get("status") in unless:
            return row
        row["status"] = status
        return save(row)


def list_rows(task_id: str | None = None) -> list[dict]:
    rows = []
    for p in root().glob("*/investigation.json"):
        try:
            row = load(p.parent.name)
            if task_id is None or row.get("task_id") == task_id:
                rows.append(row)
        except (OSError, ValueError):
            continue
    return sorted(rows, key=lambda r: r["updated_at"], reverse=True)


def _regular_files(source: Path) -> list[tuple[Path, str]]:
    candidates = [(source, source.name)] if source.is_file() else []
    if source.is_dir():
        for parent, dirs, files in os.walk(source, followlinks=False):
            dirs[:] = sorted(d for d in dirs if d not in {".git", "node_modules", ".venv", "__pycache__"})
            for name in dirs + files:
                p = Path(parent) / name
                st = p.lstat()
                if p.is_symlink() or getattr(st, "st_file_attributes", 0) & 0x400:
                    raise PermissionError(f"Linked/reparse target is not admitted: {p}")
            candidates.extend((Path(parent) / name, (Path(parent) / name).relative_to(source).as_posix()) for name in sorted(files))
            if len(candidates) > MAX_FILES:
                raise ValueError("Target exceeds file-count limit; select a narrower target")
    if not candidates:
        raise ValueError("Target has no regular files")
    return candidates


def fingerprint(source: Path) -> tuple[str, list[dict]]:
    digest = hashlib.sha256()
    manifest = []
    total = 0
    for p, name in _regular_files(source):
        st = p.lstat()
        if not stat.S_ISREG(st.st_mode):
            raise PermissionError(f"Target is not a regular file: {p}")
        total += st.st_size
        if total > MAX_BYTES:
            raise ValueError("Target exceeds 8 GiB limit; select a narrower target")
        h = hashlib.sha256()
        with p.open("rb") as f:
            for block in iter(lambda: f.read(1024 * 1024), b""):
                h.update(block)
        after = p.stat()
        if (st.st_size, st.st_mtime_ns, st.st_ino) != (after.st_size, after.st_mtime_ns, after.st_ino):
            raise ValueError("Target changed during hashing")
        item = {"path": name, "sha256": h.hexdigest(), "bytes": st.st_size}
        digest.update(json.dumps(item, sort_keys=True).encode())
        manifest.append(item)
    return (manifest[0]["sha256"] if source.is_file() else digest.hexdigest()), manifest


def classify(path: Path) -> str:
    suffix = path.suffix.lower()
    if path.is_dir():
        return "javascript" if (path / "package.json").exists() else "source"
    if suffix == ".asar":
        return "javascript"
    if suffix in {".apk", ".ipa"}:
        return "mobile"
    if suffix in {".zip", ".msix", ".appx", ".dmg", ".jar"}:
        return "archive"
    if suffix in {".js", ".mjs", ".cjs", ".ts", ".py", ".c", ".cpp", ".rs", ".java", ".cs"}:
        return "source"
    # CLI directory 14 distinguishes managed PE without loading the assembly.
    import struct
    with path.open("rb") as f:
        header = f.read(64)
        if header[:2] == b"MZ" and len(header) == 64:
            offset = struct.unpack_from("<I", header, 60)[0]
            f.seek(offset)
            pe = f.read(264)
            if pe[:4] == b"PE\0\0" and len(pe) >= 240:
                magic = struct.unpack_from("<H", pe, 24)[0]
                dd = 24 + (112 if magic == 0x20B else 96)
                if len(pe) >= dd + 120 and struct.unpack_from("<II", pe, dd + 112) != (0, 0):
                    return "managed"
    return "native"


def prepare(target: str, question: str, allowed: list[str], task_id: str | None) -> dict:
    if not question.strip():
        raise ValueError("A specific investigation question is required")
    ident = uuid.uuid4().hex
    workspace = directory(ident)
    private_directory(workspace)
    row = {"id": ident, "task_id": task_id, "target": target, "question": question,
           "status": "prepared", "evidence": [], "findings": [], "unknowns": [],
           "created_at": datetime.now(timezone.utc).isoformat()}
    try:
        if target.startswith(("http://", "https://")):
            from urllib.parse import urlparse
            parsed = urlparse(target)
            if parsed.scheme != "http" or parsed.hostname not in {"127.0.0.1", "::1", "localhost"} or not parsed.port:
                raise ValueError("Browser target must be an explicit loopback CDP endpoint with a port")
            row.update(kind="browser", sha256=None, snapshot=target, manifest=[])
        else:
            raw = Path(target).expanduser()
            if raw.is_symlink() or (raw.exists() and getattr(raw.lstat(), "st_file_attributes", 0) & 0x400):
                raise PermissionError("Linked/reparse targets are not admitted")
            source = resolve_allowed_path(target, allowed)
            before, manifest = fingerprint(source)
            destination = workspace / "target" / source.name
            destination.parent.mkdir(mode=0o700)
            if source.is_dir():
                shutil.copytree(source, destination, ignore=shutil.ignore_patterns(".git", "node_modules", ".venv", "__pycache__"))
            else:
                shutil.copyfile(source, destination)
            copied, _ = fingerprint(destination)
            after, _ = fingerprint(source)
            if before != copied or before != after:
                raise ValueError("Target changed while being copied; retry with an immutable target")
            row.update(target=str(source), kind=classify(source), sha256=before,
                       snapshot=str(destination), manifest=manifest)
        return save(row)
    except BaseException:
        # Only remove the newly created, validated investigation workspace.
        shutil.rmtree(workspace)
        raise


FFS_OUTSIDE_ALLOWED = "Path is outside allowed directories"


def _ffs_admit_lexically(target: str, allowed: list[str]) -> None:
    """Allow-list gate for :func:`prepare_ffs` that runs before any filesystem probe of the target.

    The target is judged by its lexical absolute form (``~`` expanded, ``..`` collapsed, no
    link followed, no stat), so every path outside the allowed folders raises the same
    ``PermissionError(FFS_OUTSIDE_ALLOWED)`` whether it exists, is missing, or is a link.
    Allowed roots are matched both as written and as their realpath (owner config, not the target).
    """
    raw = reject_unsafe_path_text(target)
    if _is_unc_path(raw):
        try:
            resolve_allowed_path(raw, allowed)  # lexical for UNC paths; never contacts the share
        except PermissionError as exc:
            raise PermissionError(FFS_OUTSIDE_ALLOWED) from exc
        return
    if not allowed:
        raise PermissionError("No workspace directories are configured")
    candidate = os.path.normcase(os.path.abspath(os.path.expanduser(raw)))
    for root in allowed:
        root = str(root or "")
        if not root or root == LOCAL_NETWORK_SCOPE or "\x00" in root:
            continue
        expanded = os.path.expanduser(root)
        for base in {os.path.normcase(os.path.abspath(expanded)), os.path.normcase(os.path.realpath(expanded))}:
            try:
                if os.path.commonpath((base, candidate)) == base:
                    return
            except ValueError:
                continue
    raise PermissionError(FFS_OUTSIDE_ALLOWED)


def prepare_ffs(target: str, question: str, allowed: list[str] | None, task_id: str | None, *,
                source_type: str = "auto", investigation_id: str | None = None) -> dict:
    """RFC-0208: prepare (or adopt) a ``kind == "ffs"`` investigation for a full file-system dump.

    Unlike :func:`prepare` nothing is copied and no size cap applies: the original dump path
    is referenced read-only as the snapshot. ``allowed`` is the owner's allowed-directory
    list (an empty list admits nothing); ``None`` is reserved for trusted in-process callers.
    Adopting a closed/cancelled investigation, or one that references another dump, is refused.
    """
    from . import ffs_ingest

    if allowed is not None:
        # Allow-list first, on the lexical path only: nothing about an outside target (exists,
        # missing, link) may change the answer, so the caller cannot probe outside the folders.
        _ffs_admit_lexically(target, allowed)
    raw = Path(target).expanduser()
    if raw.is_symlink() or (raw.exists() and getattr(raw.lstat(), "st_file_attributes", 0) & 0x400):
        raise PermissionError("Linked/reparse target is not admitted")
    if allowed is not None:
        try:
            # Still enforce the realpath check, so a linked parent folder cannot escape the list.
            source = resolve_allowed_path(target, allowed)
        except PermissionError as exc:
            raise PermissionError(FFS_OUTSIDE_ALLOWED) from exc
    else:
        source = raw.resolve()
    if not source.exists():
        raise FileNotFoundError(f"Source target does not exist: {source}")
    stype = source_type if source_type != "auto" else ffs_ingest.detect_source_type(source)
    if stype not in {"folder", "zip", "tar", "raw"}:
        raise ValueError(f"Unknown source_type: {stype}")
    if (stype == "folder") != source.is_dir():
        raise ValueError(f"source_type {stype!r} does not match the target {source}")
    if investigation_id is None:
        ident = uuid.uuid4().hex
        workspace = directory(ident)
        private_directory(workspace)
        row: dict = {"id": ident, "task_id": task_id, "question": question or ffs_ingest.DEFAULT_QUESTION,
                     "evidence": [], "findings": [], "unknowns": [], "chain_of_custody": [],
                     "created_at": datetime.now(timezone.utc).isoformat()}
    else:
        row = load(investigation_id)
        if row.get("status") in TERMINAL_STATUSES:
            raise ValueError("Investigation is closed; prepare a new FFS ingest")
        if row.get("kind") == ffs_ingest.KIND and row.get("target") and row["target"] != str(source):
            raise ValueError("This FFS investigation already references a different dump; prepare a new one")
    row.setdefault("evidence", [])
    row.setdefault("unknowns", [])
    row.setdefault("chain_of_custody", [])
    # The dump itself is the snapshot: referenced in place, read-only, never copied.
    row.update(target=str(source), kind=ffs_ingest.KIND, source_type=stype, snapshot=str(source))
    if not any(e.get("event") == "source_admitted" for e in row["chain_of_custody"]):
        row["chain_of_custody"].append(ffs_ingest.make_chain_of_custody_entry(
            "source_admitted", source,
            f"FFS dump admitted for read-only, non-copying ingest ({stype}); referenced in place as the snapshot.",
            metadata={"source_stat": ffs_ingest.source_stat(source)},
            entry_index=len(row["chain_of_custody"]) + 1,
        ))
    if row.get("status") != "completed":
        row["status"] = "prepared"
        row.setdefault("ffs", {"status": "prepared", "files_indexed": 0, "bytes_indexed": 0,
                               "last_path": None, "updated_at": datetime.now(timezone.utc).isoformat(),
                               "unknowns": []})
        row.setdefault("progress", ffs_ingest._progress("prepared", 0, 0, None, None, None, False))
    idx = directory(row["id"]) / ffs_ingest.INDEX_DIR
    idx.mkdir(mode=0o700, parents=True, exist_ok=True)
    custody_path = idx / ffs_ingest.CUSTODY_FILE
    if not custody_path.is_file():
        atomic_json(custody_path, {
            "investigation_id": row["id"], "source": str(source), "source_kind": stype,
            "task_id": row.get("task_id"), "tool_version": ffs_ingest.TOOL_VERSION,
            "source_stat_at_admission": ffs_ingest.source_stat(source), "sessions": [],
            "source_sha256": None, "manifest": None,
        })
    return save(row)


def validate_snapshot(row: dict) -> None:
    from .ffs_ingest import FFS_KINDS
    # FFS snapshots are the dump itself; the ingest's own change detection covers them.
    if row["kind"] not in {"browser", *FFS_KINDS} and row.get("snapshot") and fingerprint(Path(row["snapshot"]))[0] != row["sha256"]:
        raise ValueError("Analysis snapshot changed; prepare a new investigation")


def write_report(row: dict, findings: list[dict], unknowns: list[str]) -> dict:
    ids = {e["id"] for e in row["evidence"] if e.get("success", True)}
    if not findings and not unknowns:
        raise ValueError("A report must contain supported findings or explicit unanswered questions")
    for finding in findings:
        if finding.get("kind") not in {"observation", "inference"} or not finding.get("claim"):
            raise ValueError("Findings require a claim and observation/inference kind")
        refs = finding.get("evidence_ids") or []
        if not refs or any(ref not in ids for ref in refs):
            raise ValueError("Every finding must cite saved evidence IDs")
    identity = row.get("sha256") or "live browser; capture-specific identity"
    from .ffs_ingest import FFS_KINDS
    if row.get("kind") in FFS_KINDS:
        identity, unknowns = _ffs_identity_and_unknowns(row, unknowns)
    row.update(findings=findings, unknowns=unknowns,
               status="partial" if unknowns else "reported")
    lines = [f"# Investigation: {row['question']}", "", f"Target: {row['target']}",
             f"Identity: {identity}", ""]
    for item in findings:
        lines.extend([f"- **{item['kind']}**: {item['claim']} [{', '.join(item['evidence_ids'])}]",
                      f"  Limitations: {item.get('limitations') or 'See cited evidence coverage.'}"])
    lines.extend(["", "## Unanswered questions", ""])
    lines.extend(f"- {item}" for item in unknowns)
    if not unknowns:
        lines.append("No remaining questions declared by the analyst; this is not proof of exhaustive coverage.")
    lines.extend(["", "## Evidence", ""])
    lines.extend(f"- [{e['id']}](evidence/{e['id']}.json): {e['operation']}" for e in row["evidence"])
    (directory(row["id"]) / "report.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    save(row)
    atomic_json(directory(row["id"]) / "report.json", row)
    return row


def _ffs_identity_and_unknowns(row: dict, unknowns: list[str]) -> tuple[str, list[str]]:
    """FFS reports cite the sealed manifest digest and keep every declared ingest unknown (RFC-0201)."""
    from . import ffs_ingest
    ffs = row.get("ffs") or {}
    declared = list(ffs.get("unknowns") or [])
    custody_path = directory(row["id"]) / ffs_ingest.INDEX_DIR / ffs_ingest.CUSTODY_FILE
    try:
        sealed = json.loads(custody_path.read_text(encoding="utf-8")).get("source_sha256")
    except (OSError, ValueError):
        sealed = None
    if ffs.get("status") == "completed" and sealed:
        identity = f"FFS manifest SHA-256 {sealed} (index/files.ndjson, chain of custody in index/custody.json)"
    else:
        identity = "FFS index not sealed; no manifest digest (ingest incomplete)"
        if ffs:
            declared.append(f"The FFS ingest is {ffs.get('status') or 'not started'} with "
                            f"{int(ffs.get('files_indexed') or 0)} file(s) indexed; the index is incomplete "
                            "and coverage of the dump is partial.")
        else:
            declared.append("Legacy forensic ingest without an RFC-0208 NDJSON index or sealed manifest; "
                            "coverage of the dump is unverified.")
    return identity, list(dict.fromkeys([*declared, *unknowns]))
