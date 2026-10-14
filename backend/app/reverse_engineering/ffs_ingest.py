"""Forensic image ingest module with streaming hashing, magic detection, and chain of custody.

Accepts extracted folders, tar/zip archives, and raw image files read-only.
Streams file bytes without loading them into memory. Builds an index per file with
relative path, size, SHA-256, mtime and detected magic type. Persists chain-of-custody
records in the investigation evidence store and checkpoints progress for resumability.
"""
from __future__ import annotations

import asyncio
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import stat
import tarfile
from typing import Any, Callable, Generator
import uuid
import zipfile

from ..tools.safety import resolve_allowed_path
from . import store
from .privacy import private_directory

CHUNK_SIZE = 64 * 1024  # 64 KiB chunks for streaming
HEADER_MAX_BYTES = 65536  # Header inspection window for magic detection


def detect_magic(header: bytes, total_size: int = 0) -> str:
    """Detect file magic type from header bytes without loading the full file."""
    if not header:
        return "application/x-empty"

    # Executables & object formats
    if header.startswith(b"\x7fELF"):
        return "application/x-executable; elf"
    if header.startswith(b"MZ"):
        return "application/x-dosexec; pe"
    if header.startswith((b"\xfe\xed\xfa\xce", b"\xfe\xed\xfa\xcf", b"\xce\xfa\xed\xfe", b"\xcf\xfa\xed\xfe")):
        return "application/x-mach-binary"
    if header.startswith(b"\xca\xfe\xba\xbe"):
        return "application/x-java-applet"

    # Archives and compressed formats
    if header.startswith((b"PK\x03\x04", b"PK\x05\x06", b"PK\x07\x08")):
        return "application/zip"
    if len(header) >= 262 and header[257:262] == b"ustar":
        return "application/x-tar"
    if header.startswith(b"\x1f\x8b"):
        return "application/gzip"
    if header.startswith(b"BZh"):
        return "application/x-bzip2"
    if header.startswith(b"\xfd7zXZ\x00"):
        return "application/x-xz"
    if header.startswith(b"7z\xbc\xaf\x27\x1c"):
        return "application/x-7z-compressed"
    if header.startswith(b"Rar!\x1a\x07"):
        return "application/x-rar"

    # Forensic & disk images
    if len(header) >= 32774 and header[32769:32774] == b"CD001":
        return "application/x-iso9660-image"
    if len(header) >= 520 and header[512:520] == b"EFI PART":
        return "raw-image/gpt"
    if len(header) >= 512 and header[510:512] == b"\x55\xaa":
        return "raw-image/mbr"
    if len(header) >= 1082 and header[1080:1082] == b"\x53\xef":
        return "filesystem/ext4"
    if len(header) >= 7 and header[3:7] == b"NTFS":
        return "filesystem/ntfs"
    if len(header) >= 8 and (header[3:8] == b"MSDOS" or b"FAT12" in header[:60] or b"FAT16" in header[:60] or b"FAT32" in header[:60]):
        return "filesystem/fat"
    if header.startswith(b"EVF\t\r\n\xff\x00"):
        return "application/x-ewf"

    # Documents & databases
    if header.startswith(b"%PDF-"):
        return "application/pdf"
    if header.startswith(b"SQLite format 3\x00"):
        return "application/vnd.sqlite3"

    # Media
    if header.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    if header.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    if header.startswith((b"GIF87a", b"GIF89a")):
        return "image/gif"
    if header.startswith(b"BM"):
        return "image/bmp"
    if len(header) >= 12 and header.startswith(b"RIFF") and header[8:12] == b"WEBP":
        return "image/webp"
    if len(header) >= 12 and header.startswith(b"RIFF") and header[8:12] == b"WAVE":
        return "audio/wav"
    if header.startswith((b"II*\x00", b"MM\x00*")):
        return "image/tiff"

    # Structured text & scripts
    stripped = header.lstrip()
    if stripped.startswith(b"#!/"):
        return "text/x-shellscript"
    if stripped.startswith((b"<?xml", b"<!DOCTYPE", b"<html", b"<?XML")):
        return "text/xml"
    if stripped.startswith((b"{", b"[")):
        try:
            sample = stripped[:1024].decode("utf-8")
            if sample.startswith("{") or sample.startswith("["):
                return "application/json"
        except UnicodeDecodeError:
            pass

    # Printable plain text
    try:
        decoded = header[:4096].decode("utf-8")
        control_chars = sum(1 for c in decoded if ord(c) < 32 and c not in "\r\n\t")
        if control_chars == 0:
            return "text/plain"
    except UnicodeDecodeError:
        pass

    return "application/octet-stream"


def stream_digest_and_magic(
    stream: Any,
    chunk_size: int = CHUNK_SIZE,
    on_chunk: Callable[[int], None] | None = None,
) -> tuple[str, int, str]:
    """Streams file content without loading full file into memory.

    Returns:
        (sha256_hex, total_bytes, detected_magic_type)
    """
    hasher = hashlib.sha256()
    size = 0
    header_buf = bytearray()

    while True:
        chunk = stream.read(chunk_size)
        if not chunk:
            break
        if len(header_buf) < HEADER_MAX_BYTES:
            take = min(len(chunk), HEADER_MAX_BYTES - len(header_buf))
            header_buf.extend(chunk[:take])
        hasher.update(chunk)
        chunk_len = len(chunk)
        size += chunk_len
        if on_chunk is not None:
            on_chunk(chunk_len)

    magic = detect_magic(bytes(header_buf), total_size=size)
    return hasher.hexdigest(), size, magic


def detect_source_type(path: Path) -> str:
    """Classify input as 'folder', 'zip', 'tar', or 'raw'."""
    if path.is_dir():
        return "folder"
    if zipfile.is_zipfile(path):
        return "zip"
    if tarfile.is_tarfile(path):
        return "tar"
    if path.is_file():
        return "raw"
    raise ValueError(f"Target is not a valid directory or regular file: {path}")


def make_chain_of_custody_entry(
    event: str,
    source: str | Path,
    details: str,
    operator: str = "anzu_ffs_ingest",
    metadata: dict[str, Any] | None = None,
    entry_index: int = 1,
) -> dict[str, Any]:
    """Create a standardized chain-of-custody audit entry."""
    return {
        "entry_id": f"COC-{entry_index:04d}",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "event": event,
        "source": str(source),
        "operator": operator,
        "details": details,
        "metadata": metadata or {},
    }


def iter_source_entries(
    source_path: Path, source_type: str
) -> Generator[tuple[str, int, float, Any], None, None]:
    """Yields (relative_path, declared_size, mtime, stream) read-only for each member.

    The caller is responsible for closing the yielded stream.
    """
    if source_type == "folder":
        for parent, dirs, files in os.walk(source_path, followlinks=False):
            dirs.sort()
            files.sort()
            for name in files:
                p = Path(parent) / name
                st = p.lstat()
                if p.is_symlink() or getattr(st, "st_file_attributes", 0) & 0x400:
                    continue
                if not stat.S_ISREG(st.st_mode):
                    continue
                rel = p.relative_to(source_path).as_posix()
                yield rel, st.st_size, st.st_mtime, p.open("rb")
    elif source_type == "tar":
        with tarfile.open(source_path, mode="r:*") as tar:
            for member in tar:
                if not member.isfile():
                    continue
                rel = PurePosixPath(member.name.replace("\\", "/")).as_posix().lstrip("/")
                if ".." in PurePosixPath(rel).parts:
                    continue
                f = tar.extractfile(member)
                if f is None:
                    continue
                yield rel, member.size, float(member.mtime), f
    elif source_type == "zip":
        with zipfile.ZipFile(source_path, mode="r") as z:
            for item in z.infolist():
                if item.is_dir():
                    continue
                rel = PurePosixPath(item.filename.replace("\\", "/")).as_posix().lstrip("/")
                if ".." in PurePosixPath(rel).parts:
                    continue
                try:
                    dt = datetime(*item.date_time, tzinfo=timezone.utc)
                    mtime = dt.timestamp()
                except Exception:
                    mtime = 0.0
                yield rel, item.file_size, mtime, z.open(item, mode="r")
    elif source_type == "raw":
        st = source_path.lstat()
        rel = source_path.name
        yield rel, st.st_size, st.st_mtime, source_path.open("rb")
    else:
        raise ValueError(f"Unknown source_type: {source_type}")


class IngestInterrupted(Exception):
    """Raised when an ingestion run is intentionally interrupted or halted."""
    pass


class FFSIngest:
    """Forensic image ingest service with checkpointing, streaming, and chain-of-custody."""

    def __init__(
        self,
        source: str | Path,
        investigation_id: str | None = None,
        task_id: str | None = None,
        question: str = "Forensic image ingest and file index",
        source_type: str = "auto",
        checkpoint_interval: int = 1,
        allowed_directories: list[str] | None = None,
        stop_after: int | None = None,
    ):
        self.source = str(source)
        self.investigation_id = investigation_id
        self.task_id = task_id
        self.question = question or "Forensic image ingest and file index"
        self.source_type = source_type
        self.checkpoint_interval = max(1, checkpoint_interval)
        self.allowed_directories = allowed_directories
        self.stop_after = stop_after

    def _resolve_source(self) -> Path:
        raw = Path(self.source).expanduser()
        if raw.is_symlink() or (raw.exists() and getattr(raw.lstat(), "st_file_attributes", 0) & 0x400):
            raise PermissionError("Linked/reparse target is not admitted")
        if self.allowed_directories:
            resolved = resolve_allowed_path(self.source, self.allowed_directories)
        else:
            resolved = raw.resolve()
        if not resolved.exists():
            raise FileNotFoundError(f"Source target does not exist: {resolved}")
        return resolved

    def prepare_investigation(self) -> dict[str, Any]:
        """Prepares or registers the investigation row in the investigation store."""
        source_path = self._resolve_source()
        stype = self.source_type if self.source_type != "auto" else detect_source_type(source_path)

        if self.investigation_id is None:
            ident = uuid.uuid4().hex
            self.investigation_id = ident
            workspace = store.directory(ident)
            workspace.mkdir(mode=0o700, exist_ok=True)
            private_directory(workspace)
            row = {
                "id": ident,
                "task_id": self.task_id,
                "target": str(source_path),
                "question": self.question,
                "kind": "forensic",
                "source_type": stype,
                "status": "ingesting",
                "evidence": [],
                "findings": [],
                "unknowns": [],
                "chain_of_custody": [
                    make_chain_of_custody_entry(
                        "source_admitted",
                        source_path,
                        f"Forensic target admitted for read-only ingest ({stype}).",
                        entry_index=1,
                    )
                ],
                "progress": {
                    "phase": "starting",
                    "percent": 0.0,
                    "processed_files": 0,
                    "total_files": None,
                    "processed_bytes": 0,
                    "total_bytes": None,
                    "current_file": None,
                },
                "created_at": datetime.now(timezone.utc).isoformat(),
            }
            return store.save(row)
        else:
            row = store.load(self.investigation_id)
            row["status"] = "ingesting"
            row["kind"] = "forensic"
            row["source_type"] = stype
            return store.save(row)

    def _save_checkpoint(
        self,
        checkpoint_path: Path,
        source_path: Path,
        source_type: str,
        status: str,
        entries: dict[str, dict[str, Any]],
        processed_bytes: int,
        chain_of_custody: list[dict[str, Any]],
        total_files: int | None = None,
        total_bytes: int | None = None,
    ) -> dict[str, Any]:
        cp_data = {
            "investigation_id": self.investigation_id,
            "source_path": str(source_path),
            "source_type": source_type,
            "status": status,
            "processed_count": len(entries),
            "processed_bytes": processed_bytes,
            "total_files": total_files,
            "total_bytes": total_bytes,
            "entries": entries,
            "chain_of_custody": chain_of_custody,
            "last_checkpoint_at": datetime.now(timezone.utc).isoformat(),
        }
        store.atomic_json(checkpoint_path, cp_data)
        return cp_data

    def run_sync(self) -> dict[str, Any]:
        """Synchronously execute forensic image ingestion."""
        source_path = self._resolve_source()
        source_type = self.source_type if self.source_type != "auto" else detect_source_type(source_path)

        if self.investigation_id is None:
            self.prepare_investigation()
        assert self.investigation_id is not None
        ident = self.investigation_id
        row = store.load(ident)

        workspace = store.directory(ident)
        workspace.mkdir(mode=0o700, exist_ok=True)
        checkpoint_file = workspace / "checkpoint.json"

        # Check for resumable checkpoint
        is_resumed = False
        entries: dict[str, dict[str, Any]] = {}
        chain_of_custody: list[dict[str, Any]] = list(row.get("chain_of_custody", []))
        processed_bytes = 0

        if checkpoint_file.is_file():
            try:
                cp = json.loads(checkpoint_file.read_text(encoding="utf-8"))
                if cp.get("source_path") == str(source_path) and cp.get("status") != "completed":
                    entries = cp.get("entries", {})
                    processed_bytes = cp.get("processed_bytes", sum(e["size"] for e in entries.values()))
                    chain_of_custody = cp.get("chain_of_custody", chain_of_custody)
                    is_resumed = True
                    coc = make_chain_of_custody_entry(
                        "ingest_resumed",
                        source_path,
                        f"Resuming ingestion from checkpoint with {len(entries)} already-processed entries.",
                        entry_index=len(chain_of_custody) + 1,
                    )
                    chain_of_custody.append(coc)
            except (OSError, json.JSONDecodeError):
                pass

        if not is_resumed:
            coc = make_chain_of_custody_entry(
                "ingest_started",
                source_path,
                f"Started read-only forensic ingestion of {source_type} source.",
                entry_index=len(chain_of_custody) + 1,
            )
            chain_of_custody.append(coc)

        row["status"] = "ingesting"
        row["chain_of_custody"] = chain_of_custody
        row["progress"] = {
            "phase": "resuming" if is_resumed else "indexing",
            "percent": None,
            "processed_files": len(entries),
            "total_files": None,
            "processed_bytes": processed_bytes,
            "total_bytes": None,
            "current_file": None,
            "resumed": is_resumed,
        }
        store.save(row)

        processed_paths = set(entries.keys())
        last_checkpoint_count = len(entries)

        try:
            for rel_path, declared_size, mtime, stream in iter_source_entries(source_path, source_type):
                with stream:
                    if rel_path in processed_paths:
                        continue

                    # Stream file without loading into memory
                    sha256, actual_size, magic = stream_digest_and_magic(stream)
                    mtime_iso = (
                        datetime.fromtimestamp(mtime, tz=timezone.utc).isoformat()
                        if mtime > 0
                        else ""
                    )

                    entry = {
                        "path": rel_path,
                        "relative_path": rel_path,
                        "size": actual_size,
                        "bytes": actual_size,
                        "sha256": sha256,
                        "mtime": mtime,
                        "mtime_iso": mtime_iso,
                        "magic": magic,
                        "magic_type": magic,
                    }
                    entries[rel_path] = entry
                    processed_paths.add(rel_path)
                    processed_bytes += actual_size

                    # Checkpoint periodically
                    if (len(entries) - last_checkpoint_count) >= self.checkpoint_interval:
                        self._save_checkpoint(
                            checkpoint_file,
                            source_path,
                            source_type,
                            "in_progress",
                            entries,
                            processed_bytes,
                            chain_of_custody,
                        )
                        last_checkpoint_count = len(entries)
                        row["progress"] = {
                            "phase": "indexing",
                            "percent": None,
                            "processed_files": len(entries),
                            "total_files": None,
                            "processed_bytes": processed_bytes,
                            "total_bytes": None,
                            "current_file": rel_path,
                            "resumed": is_resumed,
                        }
                        store.save(row)

                    if self.stop_after is not None and len(entries) >= self.stop_after:
                        self._save_checkpoint(
                            checkpoint_file,
                            source_path,
                            source_type,
                            "interrupted",
                            entries,
                            processed_bytes,
                            chain_of_custody,
                        )
                        row["status"] = "interrupted"
                        row["progress"]["phase"] = "interrupted"
                        row["progress"]["current_file"] = rel_path
                        store.save(row)
                        raise IngestInterrupted(
                            f"Halted after {len(entries)} entries as requested by stop_after."
                        )

        except IngestInterrupted:
            return store.load(ident)
        except BaseException as exc:
            self._save_checkpoint(
                checkpoint_file,
                source_path,
                source_type,
                "interrupted",
                entries,
                processed_bytes,
                chain_of_custody,
            )
            row["status"] = "interrupted"
            row["last_error"] = str(exc)[:2000]
            store.save(row)
            raise

        # Completed successfully
        coc_complete = make_chain_of_custody_entry(
            "ingest_completed",
            source_path,
            f"Completed forensic ingest. {len(entries)} files indexed, total {processed_bytes} bytes.",
            entry_index=len(chain_of_custody) + 1,
        )
        chain_of_custody.append(coc_complete)

        self._save_checkpoint(
            checkpoint_file,
            source_path,
            source_type,
            "completed",
            entries,
            processed_bytes,
            chain_of_custody,
            total_files=len(entries),
            total_bytes=processed_bytes,
        )

        # Store full index in investigation workspace
        index_file = workspace / "index.json"
        index_data = {
            "investigation_id": ident,
            "source": str(source_path),
            "source_type": source_type,
            "file_count": len(entries),
            "total_bytes": processed_bytes,
            "entries": list(entries.values()),
        }
        store.atomic_json(index_file, index_data)

        # Record in evidence store
        evidence_dir = workspace / "evidence"
        evidence_dir.mkdir(mode=0o700, exist_ok=True)
        evidence_id = f"E{len(row.get('evidence', [])) + 1:05d}"
        evidence_file = evidence_dir / f"{evidence_id}.json"

        evidence_payload = {
            "id": evidence_id,
            "operation": "ffs_ingest",
            "arguments": {
                "source": str(source_path),
                "source_type": source_type,
                "question": self.question,
            },
            "target_sha256": (
                entries[source_path.name]["sha256"]
                if source_type == "raw" and source_path.name in entries
                else None
            ),
            "success": True,
            "result": {
                "provider": "ANZU FFS Ingest",
                "source": str(source_path),
                "source_type": source_type,
                "file_count": len(entries),
                "total_bytes": processed_bytes,
                "chain_of_custody": chain_of_custody,
                "index": list(entries.values()),
                "limitations": [
                    "Streamed read-only without executing target code.",
                    "Cryptographic SHA-256 hashes record bit-level chain of custody.",
                ],
            },
        }
        store.atomic_json(evidence_file, evidence_payload)

        # Update final investigation row
        row["status"] = "completed"
        row["chain_of_custody"] = chain_of_custody
        row["evidence"].append({
            "id": evidence_id,
            "operation": "ffs_ingest",
            "success": True,
            "file_count": len(entries),
            "total_bytes": processed_bytes,
        })
        row["progress"] = {
            "phase": "completed",
            "percent": 100.0,
            "processed_files": len(entries),
            "total_files": len(entries),
            "processed_bytes": processed_bytes,
            "total_bytes": processed_bytes,
            "current_file": None,
            "resumed": is_resumed,
        }
        return store.save(row)

    async def run(self) -> dict[str, Any]:
        """Asynchronously execute forensic image ingestion."""
        return await asyncio.to_thread(self.run_sync)


async def ingest_source(
    source: str | Path,
    investigation_id: str | None = None,
    task_id: str | None = None,
    question: str = "Forensic image ingest and file index",
    source_type: str = "auto",
    allowed_directories: list[str] | None = None,
    checkpoint_interval: int = 1,
    stop_after: int | None = None,
) -> dict[str, Any]:
    """Helper function to execute an ingestion run."""
    ingest = FFSIngest(
        source=source,
        investigation_id=investigation_id,
        task_id=task_id,
        question=question,
        source_type=source_type,
        checkpoint_interval=checkpoint_interval,
        allowed_directories=allowed_directories,
        stop_after=stop_after,
    )
    return await ingest.run()
