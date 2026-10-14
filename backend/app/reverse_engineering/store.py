from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import stat
import uuid
from datetime import datetime, timezone
from pathlib import Path

from ..config import data_dir
from ..tools.safety import resolve_allowed_path
from .privacy import private_directory

_ID = re.compile(r"^[a-f0-9]{32}$")
MAX_FILES = 50000
MAX_BYTES = 8 * 1024**3


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


def validate_snapshot(row: dict) -> None:
    if row["kind"] not in {"browser", "forensic"} and row.get("snapshot") and fingerprint(Path(row["snapshot"]))[0] != row["sha256"]:
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
    row.update(findings=findings, unknowns=unknowns,
               status="partial" if unknowns else "reported")
    lines = [f"# Investigation: {row['question']}", "", f"Target: {row['target']}",
             f"Identity: {row.get('sha256') or 'live browser; capture-specific identity'}", ""]
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
