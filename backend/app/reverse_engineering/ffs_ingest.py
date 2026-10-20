"""RFC-0208 FFS dump self-ingest: streaming, read-only, resumable, with chain of custody.

Accepts an extracted folder, a ``.tar``/``.tar.*`` archive, a ``.zip`` archive or a raw
image file. The source is evidence: it is opened read-only, never copied and never
modified. Every member is streamed once in 1 MiB blocks; that single pass yields its
SHA-256, size, leading bytes, detected type and, for ``.tab`` files, the entropy profile
used by the ``.tab`` encryption review (``tab_analyzer``).

Workspace layout (``<investigation>/index/``):

- ``files.ndjson``  append-only index, one ``{path, bytes, sha256, mtime, magic_hex, type}``
  object per line (``.tab`` files add ``entropy``, ``tab_header_hex`` (first 64 bytes),
  ``top_byte`` (most common byte of the body, AT2 header excluded) and, for
  single-byte-XOR text, ``xor_key``; ``error`` marks unreadable members).
  This is the index the APK sidecar's FFS origin (RFC-0207 slice 4) reads.
- ``custody.json``  source, source kind, owning task, tool version, ISO-timestamped ingest
  sessions and, once complete, the finalized manifest digest (``source_sha256``).
- ``checkpoint.json`` small progress counters; the NDJSON itself is the resume state.
- ``tab_profile.json`` every ``.tab`` profile plus the aggregate summary.

The investigation row is prepared by ``store.prepare_ffs``: the dump is referenced in place
as the read-only snapshot. Closed/cancelled is the owner's decision and is never downgraded
by the ingest thread (``store.save_guarded``). Folder dumps are re-verified member by member
(size and mtime against the index) when the ingest completes, so a change anywhere in the
tree is declared as an unknown instead of being sealed as unchanged.

Resume re-reads the NDJSON (dropping a torn final line) and continues in the same
deterministic order without duplicating or dropping entries.
"""
from __future__ import annotations

import asyncio
from collections import Counter
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import stat
import tarfile
import threading
import time
from typing import Any, Callable, Generator, IO
import zipfile
import zlib

from . import store
from .tab_analyzer import TabProfiler, is_tab_path, parse_tab_header, summarize as summarize_tab_profiles

CHUNK_SIZE = 1024 * 1024  # RFC-0208: every member is hashed in 1 MiB blocks
HEADER_MAX_BYTES = 65536  # Header inspection window for magic detection
MAGIC_HEX_BYTES = 16  # Leading bytes recorded per index line

TOOL_VERSION = "anzu-ffs-ingest/2 (RFC-0208)"
KIND = "ffs"
LEGACY_KINDS = frozenset({"forensic"})  # rows written by the pre-conformance ingest (#582/#583)
FFS_KINDS = frozenset({KIND}) | LEGACY_KINDS
INDEX_DIR = "index"
INDEX_FILE = "files.ndjson"
CUSTODY_FILE = "custody.json"
CHECKPOINT_FILE = "checkpoint.json"
TAB_PROFILE_FILE = "tab_profile.json"
DEFAULT_QUESTION = "Forensic image ingest and file index"

DEFAULT_CHECKPOINT_INTERVAL = 256  # files between durable checkpoints
CHECKPOINT_SECONDS = 5.0  # ...or this many seconds, whichever comes first
MAX_EVIDENCE_TAB_FILES = 2000  # per-file .tab rows inlined in evidence; the rest stay in tab_profile.json
MAX_TYPE_GROUPS = 50
MAX_LISTED_PATHS = 20  # sample paths kept per unknown class
MAX_QUERY_LIMIT = 500

RAW_IMAGE_UNKNOWN = (
    "Filesystem enumeration requires Sleuth Kit; not yet provisioned. "
    "The raw image is indexed as a single whole-image blob."
)
MEMBER_ERRORS = (OSError, zipfile.BadZipFile, tarfile.TarError, zlib.error, EOFError, RuntimeError)

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
    on_data: Callable[[bytes], None] | None = None,
) -> tuple[str, int, str]:
    """Stream content once without loading it into memory.

    ``on_chunk`` receives each chunk length, ``on_data`` each chunk (used for the
    ``.tab`` profiler and cancellation checks).

    Returns:
        (sha256_hex, total_bytes, detected_magic_type)
    """
    sha256, size, magic, _header = _digest(stream, chunk_size, on_chunk, on_data)
    return sha256, size, magic


def _digest(
    stream: Any,
    chunk_size: int = CHUNK_SIZE,
    on_chunk: Callable[[int], None] | None = None,
    on_data: Callable[[bytes], None] | None = None,
) -> tuple[str, int, str, bytes]:
    hasher = hashlib.sha256()
    size = 0
    header_buf = bytearray()
    while True:
        chunk = stream.read(chunk_size)
        if not chunk:
            break
        if len(header_buf) < HEADER_MAX_BYTES:
            header_buf.extend(chunk[: HEADER_MAX_BYTES - len(header_buf)])
        hasher.update(chunk)
        size += len(chunk)
        if on_chunk is not None:
            on_chunk(len(chunk))
        if on_data is not None:
            on_data(chunk)
    header = bytes(header_buf)
    return hasher.hexdigest(), size, detect_magic(header, total_size=size), header


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
        "timestamp": _now(),
        "event": event,
        "source": str(source),
        "operator": operator,
        "details": details,
        "metadata": metadata or {},
    }


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _is_link(p: Path, st: os.stat_result) -> bool:
    return stat.S_ISLNK(st.st_mode) or bool(getattr(st, "st_file_attributes", 0) & 0x400)


def _safe_member(name: str) -> str | None:
    rel = PurePosixPath(name.replace("\\", "/")).as_posix().lstrip("/")
    if not rel or rel == "." or ".." in PurePosixPath(rel).parts:
        return None
    return rel


def iter_source_entries(
    source_path: Path, source_type: str, skipped: list[str] | None = None
) -> Generator[tuple[str, int, float, Callable[[], IO[bytes]]], None, None]:
    """Yield ``(relative_path, declared_size, mtime, opener)`` read-only for each member.

    Members are only opened when the caller invokes ``opener()``, so resume can skip
    already-indexed members without reading them. Order is deterministic per source.
    Links, reparse points and unsafe archive names are never followed; their paths are
    appended to ``skipped`` (when given) so coverage gaps are declared, not hidden.
    """
    def skip(reason: str) -> None:
        if skipped is not None:
            skipped.append(reason)

    if source_type == "folder":
        for parent, dirs, files in os.walk(source_path, followlinks=False):
            dirs.sort()
            files.sort()
            base = Path(parent)
            for d in list(dirs):
                dp = base / d
                if _is_link(dp, dp.lstat()):
                    dirs.remove(d)
                    skip(f"link:{dp.relative_to(source_path).as_posix()}")
            for name in files:
                p = base / name
                rel = p.relative_to(source_path).as_posix()
                st = p.lstat()
                if _is_link(p, st):
                    skip(f"link:{rel}")
                    continue
                if not stat.S_ISREG(st.st_mode):
                    skip(f"special:{rel}")
                    continue
                yield rel, st.st_size, st.st_mtime, (lambda p=p: p.open("rb"))
    elif source_type == "tar":
        with tarfile.open(source_path, mode="r:*") as tar:
            for member in tar:
                if member.isdir():
                    continue
                rel = _safe_member(member.name)
                if rel is None:
                    skip(f"unsafe:{member.name}")
                    continue
                if not member.isfile():
                    skip(f"special:{rel}")
                    continue
                yield rel, member.size, float(member.mtime), (lambda m=member: tar.extractfile(m))
    elif source_type == "zip":
        with zipfile.ZipFile(source_path, mode="r") as z:
            for item in z.infolist():
                if item.is_dir():
                    continue
                rel = _safe_member(item.filename)
                if rel is None:
                    skip(f"unsafe:{item.filename}")
                    continue
                try:
                    mtime = datetime(*item.date_time, tzinfo=timezone.utc).timestamp()
                except (ValueError, OverflowError):
                    mtime = 0.0
                yield rel, item.file_size, mtime, (lambda i=item: z.open(i, mode="r"))
    elif source_type == "raw":
        st = source_path.lstat()
        yield source_path.name, st.st_size, st.st_mtime, (lambda: source_path.open("rb"))
    else:
        raise ValueError(f"Unknown source_type: {source_type}")


def source_totals(source_path: Path, source_type: str) -> tuple[int | None, int | None]:
    """Cheap (metadata-only) file/byte totals for progress; ``None`` when unknowable up front."""
    try:
        if source_type == "zip":
            with zipfile.ZipFile(source_path, mode="r") as z:
                items = [i for i in z.infolist() if not i.is_dir()]
                return len(items), sum(i.file_size for i in items)
        if source_type == "raw":
            return 1, source_path.stat().st_size
        if source_type == "folder":
            files = total = 0
            for parent, dirs, names in os.walk(source_path, followlinks=False):
                for name in names:
                    st = (Path(parent) / name).lstat()
                    if stat.S_ISREG(st.st_mode) and not _is_link(Path(parent) / name, st):
                        files += 1
                        total += st.st_size
            return files, total
    except (OSError, zipfile.BadZipFile):
        return None, None
    return None, None  # tar: only a full scan knows


def source_stat(source_path: Path) -> dict[str, Any]:
    """Admission/completion stat of the dump root (``bytes`` is ``None`` for a folder)."""
    st = source_path.stat()
    return {"bytes": st.st_size if not source_path.is_dir() else None, "mtime_ns": st.st_mtime_ns}


def _iso(mtime: float) -> str | None:
    if mtime <= 0:
        return None
    try:
        return datetime.fromtimestamp(mtime, tz=timezone.utc).isoformat()
    except (ValueError, OverflowError, OSError):
        return None


def index_dir(ident: str) -> Path:
    return store.directory(ident) / INDEX_DIR


def read_index(index_path: Path, *, repair: bool = False) -> tuple[set[str], int, int, Counter[str], int]:
    """Stream the NDJSON index: ``(paths, files, bytes, type_counts, valid_offset)``.

    A torn final line (crash mid-append) is dropped; with ``repair`` the file is
    truncated back to the last complete line. Corruption anywhere else fails closed.
    """
    paths: set[str] = set()
    files = total = 0
    types: Counter[str] = Counter()
    offset = 0
    if not index_path.is_file():
        return paths, files, total, types, offset
    with index_path.open("rb") as fh:
        lineno = 0
        for raw in fh:
            lineno += 1
            complete = raw.endswith(b"\n")
            try:
                obj = json.loads(raw.decode("utf-8")) if raw.strip() else None
            except (UnicodeDecodeError, json.JSONDecodeError):
                obj = None
                if complete:
                    raise ValueError(f"Corrupt FFS index line {lineno} in {index_path}; refusing to resume")
            if not complete:
                break  # torn tail: everything before ``offset`` is intact
            offset += len(raw)
            if obj is None:
                continue
            paths.add(obj["path"])
            files += 1
            total += int(obj.get("bytes") or 0)
            types[str(obj.get("type") or "unknown")] += 1
    if repair and index_path.stat().st_size != offset:
        with index_path.open("r+b") as fh:
            fh.truncate(offset)
    return paths, files, total, types, offset


def verify_folder_index(source_path: Path, index_path: Path, indexed: set[str]) -> dict[str, list[str]]:
    """Compare a folder dump with its finished index: ``{modified, removed, added}`` paths.

    Each index line's ``bytes``/``mtime`` were taken before its bytes were read, so any write to
    a member during or after its read (anywhere in the tree) shows up as ``modified``; the
    file set is re-walked for members that appeared. Metadata only: nothing is re-read.
    """
    modified: list[str] = []
    removed: list[str] = []
    with index_path.open("rb") as fh:
        for raw in fh:
            obj = json.loads(raw.decode("utf-8"))
            try:
                st = (source_path / obj["path"]).lstat()
            except FileNotFoundError:
                removed.append(obj["path"])
                continue
            if (not stat.S_ISREG(st.st_mode) or st.st_size != int(obj.get("bytes") or 0)
                    or _iso(st.st_mtime) != obj.get("mtime")):
                modified.append(obj["path"])
    added = [rel for rel, *_ in iter_source_entries(source_path, "folder") if rel not in indexed]
    return {"modified": modified, "removed": removed, "added": added}


def file_sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(CHUNK_SIZE), b""):
            h.update(chunk)
    return h.hexdigest()


def query_index(
    ident: str,
    *,
    path_contains: str = "",
    suffix: str = "",
    type_contains: str = "",
    offset: int = 0,
    limit: int = 100,
) -> dict[str, Any]:
    """Page through an FFS index with simple filters (case-insensitive), streaming the NDJSON."""
    row = store.load(ident)
    if row.get("kind") != KIND:
        raise ValueError("Investigation is not an FFS ingest (kind == 'ffs')")
    index_path = index_dir(ident) / INDEX_FILE
    if not index_path.is_file():
        raise FileNotFoundError("FFS index has not been produced yet")
    limit = max(1, min(int(limit), MAX_QUERY_LIMIT))
    offset = max(0, int(offset))
    pc, sx, tc = path_contains.lower(), suffix.lower(), type_contains.lower()
    matched = 0
    items: list[dict[str, Any]] = []
    with index_path.open("rb") as fh:
        for raw in fh:
            if not raw.endswith(b"\n"):
                break
            obj = json.loads(raw.decode("utf-8"))
            path = str(obj.get("path", "")).lower()
            if pc and pc not in path:
                continue
            if sx and not path.endswith(sx):
                continue
            if tc and tc not in str(obj.get("type", "")).lower():
                continue
            if matched >= offset and len(items) < limit:
                items.append(obj)
            matched += 1
    return {"investigation_id": ident, "matched": matched, "offset": offset, "limit": limit,
            "items": items, "ffs": row.get("ffs")}


class IngestInterrupted(Exception):
    """Raised when an ingestion run is intentionally interrupted or halted."""


class IngestCancelled(Exception):
    """Raised inside the stream loop when the owner cancels or closes the investigation."""


_RUNNING: dict[str, "FFSIngest"] = {}
_RUNNING_LOCK = threading.Lock()


def running(ident: str) -> bool:
    with _RUNNING_LOCK:
        return ident in _RUNNING


def cancel(ident: str) -> bool:
    """Ask a running ingest to stop at the next block and checkpoint.

    Used by owner close/cancel, which are final: the investigation keeps its closed/cancelled
    status and is not resumed (prepare a new one instead). Only shutdown, ``stop_after`` and
    errors leave an ingest ``interrupted`` and resumable.
    """
    with _RUNNING_LOCK:
        ingest = _RUNNING.get(ident)
    if ingest is None:
        return False
    ingest.cancel_event.set()
    return True


def wait_stopped(ident: str, timeout: float | None) -> bool:
    """Block until a running ingest's worker thread has exited (True), or ``timeout`` passes (False).

    Close/cancel use this so the returned row is final; if a read is stuck past the timeout the
    guarded save still keeps the owner's closed/cancelled status.
    """
    with _RUNNING_LOCK:
        ingest = _RUNNING.get(ident)
    return True if ingest is None else ingest.finished.wait(timeout)


class FFSIngest:
    """Streaming FFS ingest with NDJSON index, checkpoints and chain of custody (RFC-0208)."""

    def __init__(
        self,
        source: str | Path,
        investigation_id: str | None = None,
        task_id: str | None = None,
        question: str = DEFAULT_QUESTION,
        source_type: str = "auto",
        checkpoint_interval: int = DEFAULT_CHECKPOINT_INTERVAL,
        allowed_directories: list[str] | None = None,
        stop_after: int | None = None,
    ):
        self.source = str(source)
        self.investigation_id = investigation_id
        self.task_id = task_id
        self.question = question or DEFAULT_QUESTION
        self.source_type = source_type
        self.checkpoint_interval = max(1, checkpoint_interval)
        self.allowed_directories = allowed_directories
        self.stop_after = stop_after
        self.cancel_event = threading.Event()
        self.finished = threading.Event()

    # ----- setup -------------------------------------------------------------------------

    def prepare_investigation(self) -> dict[str, Any]:
        """Create (or adopt) the investigation row as ``kind == "ffs"`` via ``store.prepare_ffs``."""
        row = store.prepare_ffs(self.source, self.question, self.allowed_directories, self.task_id,
                                source_type=self.source_type, investigation_id=self.investigation_id)
        self.investigation_id = row["id"]
        return row

    def _save(self, row: dict[str, Any]) -> dict[str, Any]:
        """Persist progress without overwriting the owner's close/cancel; stop if one landed."""
        if store.save_guarded(row):
            self.cancel_event.set()
        return row

    # ----- run ---------------------------------------------------------------------------

    def run_sync(self) -> dict[str, Any]:
        # Always (re)admit: creates the row, adopts an existing one, or refuses a different dump.
        self.prepare_investigation()
        ident = self.investigation_id
        assert ident is not None
        with _RUNNING_LOCK:
            if ident in _RUNNING:
                raise RuntimeError("An FFS ingest is already running for this investigation")
            _RUNNING[ident] = self
        try:
            # A close/cancel that landed between admission and registration (when ``cancel``
            # found nothing to signal) must still win: never start on a closed investigation.
            if store.load(ident).get("status") in store.TERMINAL_STATUSES:
                raise ValueError("Investigation is closed; prepare a new FFS ingest")
            return self._run(ident)
        finally:
            with _RUNNING_LOCK:
                if _RUNNING.get(ident) is self:
                    _RUNNING.pop(ident, None)
            self.finished.set()

    async def run(self) -> dict[str, Any]:
        """Run the ingest on a worker thread (the event loop stays responsive)."""
        return await asyncio.to_thread(self.run_sync)

    def _run(self, ident: str) -> dict[str, Any]:
        row = store.load(ident)
        if row.get("status") == "completed" and (index_dir(ident) / INDEX_FILE).is_file():
            return row  # idempotent: a finished index is evidence and is never rewritten
        source_path = Path(row["target"])
        source_type = row["source_type"]
        idx = index_dir(ident)
        idx.mkdir(mode=0o700, parents=True, exist_ok=True)
        index_path = idx / INDEX_FILE
        custody_path = idx / CUSTODY_FILE
        checkpoint_path = idx / CHECKPOINT_FILE
        custody = json.loads(custody_path.read_text(encoding="utf-8"))

        indexed, files, total_bytes, types, _ = read_index(index_path, repair=True)
        resumed = files > 0
        unknowns: list[str] = list(row.get("ffs", {}).get("unknowns") or [])
        chain = row["chain_of_custody"]
        chain.append(make_chain_of_custody_entry(
            "ingest_resumed" if resumed else "ingest_started", source_path,
            (f"Resuming read-only ingest after {files} indexed entries." if resumed
             else f"Started read-only ingest of {source_type} source."),
            metadata={"tool_version": TOOL_VERSION}, entry_index=len(chain) + 1,
        ))
        session = {"started_at": _now(), "ended_at": None, "resumed_from_files": files,
                   "files_indexed": 0, "outcome": "running"}
        custody["sessions"].append(session)
        store.atomic_json(custody_path, custody)
        total_files_hint, total_bytes_hint = source_totals(source_path, source_type)
        row["status"] = "ingesting"
        self._progress(row, "resuming" if resumed else "indexing", files, total_bytes, None,
                       total_files_hint, total_bytes_hint, resumed, unknowns)
        self._save(row)

        skipped: list[str] = []
        seen: set[str] = set()
        duplicates: list[str] = []
        errors: list[str] = []
        session_files = 0
        last_cp_files, last_cp_time = files, time.monotonic()
        current: str | None = None
        outcome = "completed"

        def check_cancel(_chunk: bytes) -> None:
            if self.cancel_event.is_set():
                raise IngestCancelled()

        try:
            with index_path.open("ab") as out:
                for rel, declared, mtime, opener in iter_source_entries(source_path, source_type, skipped):
                    if self.cancel_event.is_set():
                        raise IngestCancelled()
                    if rel in seen:
                        duplicates.append(rel)
                        continue
                    seen.add(rel)
                    if rel in indexed:
                        continue  # resume: already in the append-only index
                    current = rel
                    entry: dict[str, Any] = {"path": rel, "bytes": declared, "sha256": None,
                                             "mtime": _iso(mtime), "magic_hex": None, "type": None}
                    profiler = TabProfiler() if is_tab_path(rel) else None

                    def on_data(chunk: bytes, profiler=profiler) -> None:
                        check_cancel(chunk)
                        if profiler is not None:
                            profiler.update(chunk)

                    try:
                        with opener() as stream:
                            sha, size, magic, header = _digest(stream, on_data=on_data)
                        entry.update(bytes=size, sha256=sha, magic_hex=header[:MAGIC_HEX_BYTES].hex(), type=magic)
                        if profiler is not None:
                            profile = profiler.result()
                            entry["entropy"] = profile["entropy"]
                            entry["tab_header_hex"] = profile["container_hex"]
                            entry["top_byte"] = profile["top_byte"]
                            if profile["xor_key"] is not None:
                                entry["xor_key"] = profile["xor_key"]
                    except IngestCancelled:
                        raise
                    except MEMBER_ERRORS as exc:
                        if not source_path.exists():
                            raise  # the dump went away (drive unplugged): interrupt, resumable
                        entry["error"] = f"{type(exc).__name__}: {exc}"[:500]
                        errors.append(rel)
                    out.write((json.dumps(entry, ensure_ascii=False, separators=(",", ":")) + "\n").encode("utf-8"))
                    out.flush()
                    indexed.add(rel)
                    files += 1
                    session_files += 1
                    total_bytes += int(entry["bytes"] or 0)
                    types[str(entry["type"] or "unknown")] += 1
                    if (files - last_cp_files >= self.checkpoint_interval
                            or time.monotonic() - last_cp_time >= CHECKPOINT_SECONDS):
                        os.fsync(out.fileno())
                        self._checkpoint(checkpoint_path, row, "in_progress", files, total_bytes, rel,
                                         total_files_hint, total_bytes_hint, resumed, unknowns)
                        last_cp_files, last_cp_time = files, time.monotonic()
                    if self.stop_after is not None and session_files >= self.stop_after:
                        raise IngestInterrupted(f"Halted after {session_files} entries as requested by stop_after.")
                os.fsync(out.fileno())
        except (IngestInterrupted, IngestCancelled) as exc:
            outcome = "cancelled" if isinstance(exc, IngestCancelled) else "interrupted"
        except BaseException as exc:
            outcome = "interrupted"
            row["last_error"] = f"{type(exc).__name__}: {exc}"[:2000]
            self._finish_session(custody_path, custody, session, session_files, outcome)
            self._interrupt(row, checkpoint_path, source_path, files, total_bytes, current,
                            total_files_hint, total_bytes_hint, resumed, unknowns, outcome)
            raise
        if outcome != "completed":
            self._finish_session(custody_path, custody, session, session_files, outcome)
            return self._interrupt(row, checkpoint_path, source_path, files, total_bytes, current,
                                   total_files_hint, total_bytes_hint, resumed, unknowns, outcome)

        # ----- completed: declare gaps, verify the source, seal the manifest ----------------
        if source_type == "raw" and RAW_IMAGE_UNKNOWN not in unknowns:
            unknowns.append(RAW_IMAGE_UNKNOWN)
        _declare(unknowns, errors, "member(s) could not be read; indexed with an error and no SHA-256")
        _declare(unknowns, duplicates, "archive member path(s) appear more than once; only the first occurrence is indexed")
        _declare(unknowns, [s.split(":", 1)[1] for s in skipped if s.startswith("link:")],
                 "symlink/reparse entries were not followed")
        _declare(unknowns, [s.split(":", 1)[1] for s in skipped if s.startswith("special:")],
                 "non-regular entries (devices, FIFOs, links inside archives) were not indexed")
        _declare(unknowns, [s.split(":", 1)[1] for s in skipped if s.startswith("unsafe:")],
                 "archive member name(s) were unsafe (absolute or '..') and were not indexed")
        if source_type == "folder":
            # The root directory's mtime does not move when a nested file changes: re-verify
            # every indexed member (size + mtime against its index line) and the file set.
            changes = verify_folder_index(source_path, index_path, indexed)
            source_unchanged = not any(changes.values())
            change_detection = "per-member size and mtime re-verified against the index at completion"
            _declare(unknowns, changes["modified"],
                     "indexed member(s) changed size or modification time during ingest; their index "
                     "hashes reflect the bytes read at the time and the dump should be re-verified")
            _declare(unknowns, changes["removed"], "indexed member(s) disappeared from the dump during ingest")
            _declare(unknowns, changes["added"], "file(s) appeared in the dump during ingest and are not indexed")
            custody["source_changes"] = {k: len(v) for k, v in changes.items()}
        else:
            admitted = custody.get("source_stat_at_admission") or {}
            source_unchanged = admitted == source_stat(source_path)
            change_detection = "source file size and mtime compared with admission"
            if not source_unchanged:
                unknowns.append("The source's size or modification time changed during ingest; "
                                "hashes reflect the bytes read at the time and the dump should be re-verified.")
        manifest_sha = file_sha256(index_path)
        tab = self._tab_profile(ident, index_path)
        custody["manifest"] = {"index": f"{INDEX_DIR}/{INDEX_FILE}", "files": files, "bytes": total_bytes,
                               "sha256": manifest_sha}
        custody["source_sha256"] = manifest_sha
        custody["source_unchanged"] = source_unchanged
        custody["change_detection"] = change_detection
        self._finish_session(custody_path, custody, session, session_files, "completed")
        chain.append(make_chain_of_custody_entry(
            "ingest_completed", source_path,
            f"Completed read-only ingest: {files} files, {total_bytes} bytes; manifest SHA-256 {manifest_sha}.",
            metadata={"manifest_sha256": manifest_sha, "source_unchanged": source_unchanged},
            entry_index=len(chain) + 1,
        ))
        ingest_id = self._evidence(row, "ffs_ingest", {
            "provider": "ANZU FFS Ingest",
            "tool_version": TOOL_VERSION,
            "source": str(source_path),
            "source_type": source_type,
            "file_count": files,
            "total_bytes": total_bytes,
            "index": f"{INDEX_DIR}/{INDEX_FILE}",
            "index_sha256": manifest_sha,
            "custody": f"{INDEX_DIR}/{CUSTODY_FILE}",
            "source_unchanged": source_unchanged,
            "change_detection": change_detection,
            "types": [{"type": t, "files": n} for t, n in types.most_common(MAX_TYPE_GROUPS)],
            "unreadable_members": len(errors),
            "unknowns": unknowns,
            "limitations": [
                "Streamed read-only; the dump was neither copied nor executed.",
                "SHA-256 per member records bit-level identity; the manifest digest seals the index.",
            ],
        }, source_path, manifest_sha)
        tab_id = self._evidence(row, "ffs_tab_profile", {
            "provider": "ANZU .tab profiler",
            "derived_from": ingest_id,
            "profile": f"{INDEX_DIR}/{TAB_PROFILE_FILE}",
            "summary": tab["summary"],
            "files": tab["files"][:MAX_EVIDENCE_TAB_FILES],
            "files_truncated": len(tab["files"]) > MAX_EVIDENCE_TAB_FILES,
            "limitations": [
                "Entropy and header bytes describe the stored bytes only; high entropy is consistent "
                "with encryption or compression and does not by itself prove either.",
            ],
        }, source_path, manifest_sha)
        chain.append(make_chain_of_custody_entry(
            "evidence_recorded", source_path, f"Recorded {ingest_id} (index) and {tab_id} (.tab profile).",
            entry_index=len(chain) + 1,
        ))
        row["unknowns"] = list(dict.fromkeys([*row.get("unknowns", []), *unknowns]))
        row["status"] = "completed"
        row.pop("last_error", None)
        self._progress(row, "completed", files, total_bytes, None, files, total_bytes, resumed, unknowns)
        row["ffs"]["coverage"] = "partial" if unknowns else "complete"
        row["ffs"]["manifest_sha256"] = manifest_sha
        row["ffs"]["tab_files"] = tab["summary"]["file_count"]
        store.atomic_json(checkpoint_path, {"status": "completed", "files_indexed": files, "bytes_indexed": total_bytes,
                                            "updated_at": _now()})
        return self._save(row)

    # ----- helpers -------------------------------------------------------------------------

    def _progress(self, row: dict, phase: str, files: int, total_bytes: int, current: str | None,
                  total_files: int | None, total_size: int | None, resumed: bool, unknowns: list[str]) -> None:
        row["progress"] = _progress(phase, files, total_bytes, current, total_files, total_size, resumed)
        row["ffs"] = {**(row.get("ffs") or {}), "status": phase, "files_indexed": files,
                      "bytes_indexed": total_bytes, "last_path": current, "updated_at": _now(),
                      "unknowns": list(unknowns), "total_files": total_files, "total_bytes": total_size}

    def _checkpoint(self, path: Path, row: dict, status: str, files: int, total_bytes: int, current: str | None,
                    total_files: int | None, total_size: int | None, resumed: bool, unknowns: list[str]) -> None:
        store.atomic_json(path, {"status": status, "files_indexed": files, "bytes_indexed": total_bytes,
                                 "last_path": current, "updated_at": _now()})
        self._progress(row, "indexing", files, total_bytes, current, total_files, total_size, resumed, unknowns)
        self._save(row)

    def _interrupt(self, row: dict, checkpoint_path: Path, source_path: Path, files: int, total_bytes: int,
                   current: str | None, total_files: int | None, total_size: int | None, resumed: bool,
                   unknowns: list[str], outcome: str) -> dict:
        store.atomic_json(checkpoint_path, {"status": outcome, "files_indexed": files, "bytes_indexed": total_bytes,
                                            "last_path": current, "updated_at": _now()})
        chain = row["chain_of_custody"]
        chain.append(make_chain_of_custody_entry(
            "ingest_interrupted", source_path,
            f"Ingest {outcome} after {files} indexed entries; resumable from the NDJSON index.",
            entry_index=len(chain) + 1,
        ))
        row["status"] = "interrupted"  # resumable, unless the owner closed/cancelled it (kept by _save)
        self._progress(row, outcome, files, total_bytes, current, total_files, total_size, resumed, unknowns)
        return self._save(row)

    @staticmethod
    def _finish_session(custody_path: Path, custody: dict, session: dict, session_files: int, outcome: str) -> None:
        session.update(ended_at=_now(), files_indexed=session_files, outcome=outcome)
        store.atomic_json(custody_path, custody)

    @staticmethod
    def _tab_profile(ident: str, index_path: Path) -> dict[str, Any]:
        files: list[dict[str, Any]] = []
        with index_path.open("rb") as fh:
            for raw in fh:
                obj = json.loads(raw.decode("utf-8"))
                if is_tab_path(obj["path"]) and "entropy" in obj:
                    # Indexes written before the container parser carry only the 16-byte magic;
                    # parse_tab_header then reports what it can (no key id) instead of guessing.
                    # The real member size lets it flag a keyed member that ends inside its
                    # 64-byte header, which the captured bytes alone cannot distinguish.
                    header_raw = obj.get("tab_header_hex") or obj.get("magic_hex") or ""
                    files.append({"path": obj["path"], "bytes": obj["bytes"], "sha256": obj["sha256"],
                                  "entropy": obj["entropy"], "header_hex": obj.get("magic_hex") or "",
                                  "container": parse_tab_header(bytes.fromhex(header_raw), obj["bytes"]),
                                  "top_byte": obj.get("top_byte"), "xor_key": obj.get("xor_key")})
        files.sort(key=lambda item: item["path"])
        payload = {"investigation_id": ident, "summary": summarize_tab_profiles(files), "files": files}
        store.atomic_json(index_dir(ident) / TAB_PROFILE_FILE, payload)
        return payload

    @staticmethod
    def _evidence(row: dict, operation: str, result: dict, source_path: Path, manifest_sha: str) -> str:
        evidence_id = f"E{len(row['evidence']) + 1:05d}"
        directory = store.directory(row["id"]) / "evidence"
        directory.mkdir(mode=0o700, exist_ok=True)
        store.atomic_json(directory / f"{evidence_id}.json", {
            "id": evidence_id, "operation": operation,
            "arguments": {"source": str(source_path), "source_type": row["source_type"]},
            "target_sha256": manifest_sha, "success": True, "result": result,
        })
        row["evidence"].append({"id": evidence_id, "operation": operation, "success": True})
        return evidence_id


def _progress(phase: str, files: int, total_bytes: int, current: str | None,
              total_files: int | None, total_size: int | None, resumed: bool) -> dict[str, Any]:
    percent = None
    if phase == "completed":
        percent = 100.0
    elif total_size:
        percent = round(min(99.9, 100.0 * total_bytes / total_size), 1)
    return {"phase": phase, "percent": percent, "processed_files": files, "total_files": total_files,
            "processed_bytes": total_bytes, "total_bytes": total_size, "current_file": current, "resumed": resumed}


def _declare(unknowns: list[str], paths: list[str], what: str) -> None:
    if not paths:
        return
    sample = ", ".join(paths[:MAX_LISTED_PATHS])
    more = f" (+{len(paths) - MAX_LISTED_PATHS} more)" if len(paths) > MAX_LISTED_PATHS else ""
    unknowns.append(f"{len(paths)} {what}: {sample}{more}")


async def ingest_source(
    source: str | Path,
    investigation_id: str | None = None,
    task_id: str | None = None,
    question: str = DEFAULT_QUESTION,
    source_type: str = "auto",
    allowed_directories: list[str] | None = None,
    checkpoint_interval: int = DEFAULT_CHECKPOINT_INTERVAL,
    stop_after: int | None = None,
) -> dict[str, Any]:
    """Run one ingest to completion (or interruption) and return the investigation row."""
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
