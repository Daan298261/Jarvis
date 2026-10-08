"""RFC-0198 LTA protected-folder open pipeline (authorized recovery only).

Load XML Access → match owner cert → PKCS#7/CMS decrypt → 7-Zip extract.
Never logs passwords, private keys, or Access ciphertext.
"""

from __future__ import annotations

import base64
import json
import logging
import os
import re
import shutil
import subprocess
import sys
import tempfile
import threading
import uuid
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from ..config import data_dir, live_allowed_directories, load_settings, resolved_data_sidecar_dir
from ..tools.safety import resolve_allowed_path
from .lta_certs import (
    ResolvedKey,
    list_cert_candidates,
    normalize_hex_id,
    resolve_key_for_access,
    scrub_secret_fields,
)
from .lta_errors import (
    ArchiveFailed,
    CertNotFound,
    DecryptFailed,
    LtaError,
    ManifestNotFound,
    NoPrivateKey,
    PathDenied,
    XmlInvalid,
)
from .security_audit import audit_security_event

logger = logging.getLogger(__name__)

_LOCK = threading.RLock()
_JOB_ID_RE = re.compile(r"^[a-f0-9]{8,32}$")
_ACCESS_TAG = re.compile(r"access$", re.I)

THEMIS_PERSONA_HINT: dict[str, Any] = {
    "primary_persona_id": "themis",
    "persona_ids": ["themis"],
    "presence_shape_hint": "twin_shield",
    "voice_profile_hint": "tactical_aide_original_v1",
    "note": "Blue/defensive LTA unlock defaults to Themis (RFC-0137 / RFC-0198).",
}


@dataclass(frozen=True)
class AccessEntry:
    thumbprint: str
    subject_key_identifier: str
    ciphertext_b64: str


def jobs_root() -> Path:
    path = resolved_data_sidecar_dir(
        "lta-extract",
        local=data_dir() / "lta-extract",
        markers=("index.json",),
        need_bytes=512 * 1024**2,
    )
    path.mkdir(parents=True, exist_ok=True)
    return path


def job_directory(job_id: str) -> Path:
    ident = (job_id or "").strip()
    if not _JOB_ID_RE.fullmatch(ident):
        raise ValueError("invalid job id")
    path = jobs_root() / ident
    path.mkdir(parents=True, exist_ok=True)
    return path


def _utcnow() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _index_path() -> Path:
    return jobs_root() / "index.json"


def _read_jobs_index() -> list[dict[str, Any]]:
    index = _index_path()
    if not index.is_file():
        return []
    try:
        payload = json.loads(index.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    rows = payload.get("jobs", []) if isinstance(payload, dict) else []
    return [row for row in rows if isinstance(row, dict)]


def _write_jobs_index(rows: list[dict[str, Any]]) -> None:
    index = _index_path()
    temp = index.with_suffix(".tmp")
    temp.write_text(json.dumps({"version": 1, "jobs": rows[-200:]}, indent=2) + "\n", encoding="utf-8")
    temp.replace(index)


def _save_job(job: dict[str, Any]) -> None:
    safe = scrub_secret_fields(job)
    with _LOCK:
        rows = [item for item in _read_jobs_index() if item.get("id") != safe.get("id")]
        rows.append(safe)
        _write_jobs_index(rows)


def list_lta_jobs() -> list[dict[str, Any]]:
    with _LOCK:
        return list(_read_jobs_index()[-100:])


def get_lta_job(job_id: str) -> dict[str, Any]:
    job = next((item for item in list_lta_jobs() if item.get("id") == job_id), None)
    if job is None:
        raise KeyError(job_id)
    out = dict(job)
    out["persona_bind_hint"] = dict(THEMIS_PERSONA_HINT)
    extract_dir = out.get("extract_dir")
    if extract_dir and Path(str(extract_dir)).is_dir() and not out.get("extract_listing"):
        out["extract_listing"] = list_extract_tree(Path(str(extract_dir)))
    return scrub_secret_fields(out)


def _append_job_log(job_id: str, line: str) -> None:
    # Never accept caller-supplied secrets into logs; callers must scrub first.
    text = (line or "").rstrip()
    lowered = text.lower()
    if any(token in lowered for token in ("private key", "begin rsa", "begin encrypted", "password=")):
        text = "[redacted log line]"
    log_file = job_directory(job_id) / "job.log"
    with log_file.open("a", encoding="utf-8") as handle:
        handle.write(text + "\n")


def audit_lta(event: str, **fields: Any) -> None:
    audit_security_event(f"lta.{event}", **scrub_secret_fields(fields))


def _path_roots(*, extra: list[str] | None = None) -> list[str]:
    settings = load_settings()
    roots = live_allowed_directories(settings.allowed_directories)
    for item in extra or []:
        text = str(item or "").strip()
        if text and text not in roots:
            roots.append(text)
    return roots


def assert_path_allowed(path: str | Path, *, extra_roots: list[str] | None = None) -> Path:
    """RFC-0079: deny paths outside allowed_directories / owner grant."""
    try:
        return resolve_allowed_path(str(path), _path_roots(extra=extra_roots))
    except PermissionError as exc:
        raise PathDenied(str(exc), detail="path_denied") from exc


def resolve_manifest_path(manifest_path: str) -> Path:
    raw = (manifest_path or "").strip()
    if not raw:
        raise ManifestNotFound("manifest_path is required")
    try:
        resolved = assert_path_allowed(raw)
    except PathDenied:
        raise
    if resolved.is_dir():
        candidate = assert_path_allowed(resolved / "manifest.xml")
        if not candidate.is_file():
            raise ManifestNotFound(f"manifest.xml not found under {resolved}")
        return candidate
    if not resolved.is_file():
        raise ManifestNotFound(f"manifest not found: {resolved}")
    return resolved


def _local_attr(attrs: dict[str, str], *names: str) -> str:
    for key, value in attrs.items():
        local = key.split("}", 1)[-1]
        if local in names:
            return str(value or "").strip()
    return ""


def parse_manifest_access(manifest_path: Path) -> list[AccessEntry]:
    allowed = assert_path_allowed(manifest_path)
    try:
        text = allowed.read_text(encoding="utf-8-sig")
    except OSError as exc:
        raise ManifestNotFound(f"manifest unreadable: {manifest_path}") from exc
    try:
        root = ET.fromstring(text)
    except ET.ParseError as exc:
        raise XmlInvalid("manifest XML is invalid", detail=type(exc).__name__) from exc

    entries: list[AccessEntry] = []
    for node in root.iter():
        tag = node.tag.split("}", 1)[-1] if isinstance(node.tag, str) else ""
        if not _ACCESS_TAG.search(tag):
            continue
        attrs = {str(k): str(v) for k, v in node.attrib.items()}
        thumb = normalize_hex_id(_local_attr(attrs, "CertThumbprint", "Thumbprint", "certThumbprint"))
        ski = normalize_hex_id(
            _local_attr(attrs, "SubjectKeyIdentifier", "SKI", "subjectKeyIdentifier", "Ski")
        )
        body = (node.text or "").strip()
        # Strip whitespace/newlines inside base64
        body = re.sub(r"\s+", "", body)
        if not body:
            raise XmlInvalid("Access entry has empty ciphertext")
        try:
            raw = base64.b64decode(body, validate=False)
        except Exception as exc:  # noqa: BLE001
            raise XmlInvalid("Access entry is not valid base64", detail=type(exc).__name__) from exc
        if len(raw) < 16:
            raise XmlInvalid("Access ciphertext too short")
        # Re-encode compact form for decrypt helpers (never logged)
        entries.append(
            AccessEntry(
                thumbprint=thumb,
                subject_key_identifier=ski,
                ciphertext_b64=base64.b64encode(raw).decode("ascii"),
            )
        )
    if not entries:
        raise XmlInvalid("manifest contains no Access entries")
    return entries


def discover_archive_path(manifest_path: Path, archive_path: str | None) -> Path:
    if archive_path and str(archive_path).strip():
        resolved = assert_path_allowed(str(archive_path).strip())
        if not resolved.is_file():
            raise ArchiveFailed(f"archive not found: {resolved}", detail="archive_missing")
        return resolved
    parent = assert_path_allowed(manifest_path.parent)
    candidates = [
        parent / "archive.7z",
        parent / "Archive.7z",
        parent / f"{manifest_path.stem}.7z",
    ]
    candidates.extend(sorted(parent.glob("*.7z")))
    for candidate in candidates:
        if candidate.is_file():
            # Re-check allowlist (sibling of allowed manifest should pass)
            return assert_path_allowed(candidate)
    raise ArchiveFailed(
        "no .7z archive found beside manifest; pass archive_path",
        detail="archive_missing",
    )


def find_7z_executable() -> str | None:
    configured = (os.environ.get("JARVIS_7Z_PATH") or "").strip()
    if configured and Path(configured).is_file():
        return configured
    for name in ("7z", "7za", "7zr"):
        found = shutil.which(name)
        if found:
            return found
    if sys.platform == "win32":
        for candidate in (
            Path(os.environ.get("ProgramFiles", r"C:\Program Files")) / "7-Zip" / "7z.exe",
            Path(os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)")) / "7-Zip" / "7z.exe",
        ):
            if candidate.is_file():
                return str(candidate)
    return None


def decrypt_pkcs7_password(ciphertext_b64: str, key: ResolvedKey) -> str:
    """Decrypt CMS EnvelopedData → archive password string. Never logs plaintext."""
    try:
        blob = base64.b64decode(ciphertext_b64)
    except Exception as exc:  # noqa: BLE001
        raise DecryptFailed("Access ciphertext decode failed", detail=type(exc).__name__) from exc

    if key.use_windows_cms:
        return _decrypt_windows_cms(blob)

    if not key.private_key_pem:
        raise NoPrivateKey("no private key material available for CMS decrypt")

    return _decrypt_openssl_cms(blob, key.private_key_pem)


def _decrypt_openssl_cms(blob: bytes, private_key_pem: bytes) -> str:
    openssl = shutil.which("openssl")
    if not openssl:
        raise DecryptFailed("openssl not available for CMS decrypt", detail="openssl_missing")
    tmp: str | None = None
    key_path: str | None = None
    try:
        with tempfile.NamedTemporaryFile(prefix="lta-cms-", suffix=".p7", delete=False) as handle:
            handle.write(blob)
            tmp = handle.name
        with tempfile.NamedTemporaryFile(prefix="lta-key-", suffix=".pem", delete=False) as handle:
            handle.write(private_key_pem)
            key_path = handle.name
            try:
                os.chmod(key_path, 0o600)
            except OSError:
                pass
        proc = subprocess.run(
            [openssl, "cms", "-decrypt", "-inform", "DER", "-in", tmp, "-inkey", key_path],
            capture_output=True,
            check=False,
        )
        if proc.returncode != 0:
            # Surface CMS error class only — never stderr blobs that may echo paths oddly
            err_class = "cms_decrypt_failed"
            stderr = (proc.stderr or b"").decode("utf-8", errors="replace").lower()
            if "key" in stderr and "match" in stderr:
                err_class = "cms_key_mismatch"
            elif "padding" in stderr:
                err_class = "cms_padding_error"
            raise DecryptFailed("PKCS#7/CMS decrypt failed", detail=err_class)
        password = proc.stdout.decode("utf-8", errors="strict").strip("\x00").strip()
        if not password:
            # Some LTA packs use UTF-16LE password bytes
            try:
                password = proc.stdout.decode("utf-16-le", errors="strict").strip("\x00").strip()
            except UnicodeError as exc:
                raise DecryptFailed("CMS plaintext is not a usable password string", detail="password_encoding") from exc
        if not password:
            raise DecryptFailed("CMS plaintext empty", detail="empty_password")
        return password
    finally:
        for path in (tmp, key_path):
            if path:
                try:
                    os.remove(path)
                except OSError:
                    pass


def _decrypt_windows_cms(blob: bytes) -> str:
    if sys.platform != "win32":
        raise DecryptFailed("Windows CMS decrypt unavailable on this platform", detail="platform_unsupported")
    import ctypes
    from ctypes import wintypes

    crypt32 = ctypes.WinDLL("crypt32", use_last_error=True)
    X509_ASN_ENCODING = 0x00000001
    PKCS_7_ASN_ENCODING = 0x00010000
    encoding = X509_ASN_ENCODING | PKCS_7_ASN_ENCODING
    CERT_STORE_PROV_SYSTEM = 10
    CERT_SYSTEM_STORE_CURRENT_USER = 0x00010000
    CERT_SYSTEM_STORE_LOCAL_MACHINE = 0x00020000
    CERT_STORE_READONLY_FLAG = 0x00008000
    CERT_STORE_OPEN_EXISTING_FLAG = 0x00004000

    class CRYPT_DECRYPT_MESSAGE_PARA(ctypes.Structure):
        _fields_ = [
            ("cbSize", wintypes.DWORD),
            ("dwMsgAndCertEncodingType", wintypes.DWORD),
            ("cCertStore", wintypes.DWORD),
            ("rghCertStore", ctypes.POINTER(ctypes.c_void_p)),
        ]

    CryptDecryptMessage = crypt32.CryptDecryptMessage
    CryptDecryptMessage.argtypes = [
        ctypes.POINTER(CRYPT_DECRYPT_MESSAGE_PARA),
        ctypes.c_void_p,
        wintypes.DWORD,
        ctypes.c_void_p,
        ctypes.POINTER(wintypes.DWORD),
        ctypes.c_void_p,
    ]
    CryptDecryptMessage.restype = wintypes.BOOL
    CertOpenStore = crypt32.CertOpenStore
    CertOpenStore.argtypes = [ctypes.c_void_p, wintypes.DWORD, ctypes.c_void_p, wintypes.DWORD, ctypes.c_void_p]
    CertOpenStore.restype = ctypes.c_void_p
    CertCloseStore = crypt32.CertCloseStore
    CertCloseStore.argtypes = [ctypes.c_void_p, wintypes.DWORD]
    CertCloseStore.restype = wintypes.BOOL

    stores: list[int] = []
    try:
        for location in (CERT_SYSTEM_STORE_CURRENT_USER, CERT_SYSTEM_STORE_LOCAL_MACHINE):
            flags = location | CERT_STORE_READONLY_FLAG | CERT_STORE_OPEN_EXISTING_FLAG
            handle = CertOpenStore(
                ctypes.c_void_p(CERT_STORE_PROV_SYSTEM),
                encoding,
                None,
                flags,
                ctypes.c_wchar_p("MY"),
            )
            if handle:
                stores.append(handle)
        if not stores:
            raise DecryptFailed("could not open Windows certificate stores", detail="store_open_failed")
        arr = (ctypes.c_void_p * len(stores))(*stores)
        para = CRYPT_DECRYPT_MESSAGE_PARA(
            cbSize=ctypes.sizeof(CRYPT_DECRYPT_MESSAGE_PARA),
            dwMsgAndCertEncodingType=encoding,
            cCertStore=len(stores),
            rghCertStore=ctypes.cast(arr, ctypes.POINTER(ctypes.c_void_p)),
        )
        size = wintypes.DWORD(0)
        blob_buf = (ctypes.c_byte * len(blob)).from_buffer_copy(blob)
        ok = CryptDecryptMessage(ctypes.byref(para), blob_buf, len(blob), None, ctypes.byref(size), None)
        if not ok and ctypes.get_last_error() not in {234, 122}:  # ERROR_MORE_DATA / insufficient buffer variants
            # Still try allocate if size was set
            if size.value == 0:
                raise DecryptFailed("CryptDecryptMessage failed", detail="cms_decrypt_failed")
        out_buf = (ctypes.c_byte * size.value)()
        if not CryptDecryptMessage(ctypes.byref(para), blob_buf, len(blob), out_buf, ctypes.byref(size), None):
            raise DecryptFailed("CryptDecryptMessage failed", detail="cms_decrypt_failed")
        raw = bytes(out_buf[: size.value])
        for encoding_name in ("utf-8", "utf-16-le"):
            try:
                password = raw.decode(encoding_name).strip("\x00").strip()
            except UnicodeError:
                continue
            if password:
                return password
        raise DecryptFailed("CMS plaintext is not a usable password string", detail="password_encoding")
    finally:
        for handle in stores:
            CertCloseStore(handle, 0)


_MAX_7Z_PASSWORD = 1024


def _validate_7z_password(password: str) -> str:
    if not isinstance(password, str) or not password:
        raise ArchiveFailed("archive password empty", detail="empty_password")
    if len(password) > _MAX_7Z_PASSWORD:
        raise ArchiveFailed("archive password too long", detail="password_too_long")
    if "\x00" in password or any(ord(ch) < 32 for ch in password):
        raise ArchiveFailed("archive password contains control characters", detail="password_invalid")
    return password


def extract_with_7z(archive_path: Path, password: str, dest_dir: Path) -> list[str]:
    exe = find_7z_executable()
    if not exe:
        raise ArchiveFailed("7-Zip executable not found (install 7z or set JARVIS_7Z_PATH)", detail="7z_missing")
    exe_path = Path(exe).expanduser()
    if not exe_path.is_file():
        raise ArchiveFailed("7-Zip executable not found (install 7z or set JARVIS_7Z_PATH)", detail="7z_missing")
    job_root = jobs_root()
    archive = assert_path_allowed(archive_path)
    dest = assert_path_allowed(dest_dir, extra_roots=[str(job_root), str(data_dir())])
    secret = _validate_7z_password(password)
    dest.mkdir(parents=True, exist_ok=True)
    # Argv list only — never shell=True, never interpolate into a command string.
    cmd = [
        str(exe_path),
        "x",
        "-p" + secret,
        "-o" + str(dest),
        "-y",
        "-bso0",
        "-bsp0",
        str(archive),
    ]
    try:
        proc = subprocess.run(cmd, capture_output=True, check=False, shell=False)
    except OSError as exc:
        raise ArchiveFailed("failed to invoke 7-Zip", detail=type(exc).__name__) from exc
    if proc.returncode != 0:
        # Map common 7z codes without echoing stderr (may mention paths only — still scrub)
        detail = f"7z_exit_{proc.returncode}"
        raise ArchiveFailed("7-Zip extract failed", detail=detail)
    return list_extract_tree(dest)


def succeeded_lta_extract_root(job_id: str) -> Path:
    """RFC-0200 §3.3: post-extract root after RFC-0198 open succeeded. No second unlock."""
    job = get_lta_job(job_id)
    if str(job.get("status") or "") != "succeeded":
        raise PathDenied("LTA job has not completed open", detail="lta_not_extracted")
    job_root = job_directory(str(job.get("id") or job_id)).resolve()
    extract = Path(str(job.get("extract_dir") or job_root / "files")).expanduser().resolve()
    try:
        extract.relative_to(job_root)
    except ValueError as exc:
        raise PathDenied("extract dir is not under the LTA job root", detail="lta_extract_mismatch") from exc
    return job_root


def list_extract_tree(root: Path, *, limit: int = 500) -> list[str]:
    if not root.is_dir():
        return []
    out: list[str] = []
    for path in sorted(root.rglob("*")):
        if path.is_file():
            try:
                rel = str(path.relative_to(root)).replace("\\", "/")
            except ValueError:
                rel = path.name
            out.append(rel)
            if len(out) >= limit:
                break
    return out


def _decrypt_first_access(entries: list[AccessEntry]) -> tuple[str, ResolvedKey, AccessEntry]:
    last_err: LtaError | None = None
    saw_cert = False
    saw_no_key = False
    for entry in entries:
        try:
            key = resolve_key_for_access(
                thumbprint=entry.thumbprint or None,
                subject_key_identifier=entry.subject_key_identifier or None,
            )
            saw_cert = True
            password = decrypt_pkcs7_password(entry.ciphertext_b64, key)
            return password, key, entry
        except CertNotFound as exc:
            last_err = exc
        except NoPrivateKey as exc:
            saw_cert = True
            saw_no_key = True
            last_err = exc
        except DecryptFailed as exc:
            saw_cert = True
            last_err = exc
    if last_err is None:
        raise CertNotFound("no Access entries could be resolved")
    if isinstance(last_err, DecryptFailed):
        raise last_err
    if saw_no_key and not isinstance(last_err, DecryptFailed):
        raise NoPrivateKey(str(last_err), detail=last_err.detail)
    if not saw_cert:
        raise CertNotFound(str(last_err), detail=last_err.detail)
    raise last_err


def run_protected_folder_open(
    *,
    manifest_path: str,
    archive_path: str | None = None,
    job_id: str | None = None,
) -> dict[str, Any]:
    """Execute the full unlock pipeline for one job (sync)."""
    ident = (job_id or uuid.uuid4().hex[:12]).strip()
    if not _JOB_ID_RE.fullmatch(ident):
        ident = uuid.uuid4().hex[:12]
    extract_dir = job_directory(ident) / "files"
    job: dict[str, Any] = {
        "id": ident,
        "status": "running",
        "created_at": _utcnow(),
        "updated_at": _utcnow(),
        "manifest_path": str(manifest_path),
        "archive_path": str(archive_path or ""),
        "extract_dir": str(extract_dir),
        "extract_listing": [],
        "cert_thumbprint_used": "",
        "cert_source": "",
        "error": "",
        "error_detail": "",
        "persona_bind_hint": dict(THEMIS_PERSONA_HINT),
        "daybreak_jobs_hint": f"Open Daybreak → Jobs / LTA for job {ident}",
    }
    _save_job(job)
    _append_job_log(ident, "status=running")
    audit_lta("open_started", job_id=ident, manifest_path=str(manifest_path))

    password: str | None = None
    try:
        manifest = resolve_manifest_path(manifest_path)
        job["manifest_path"] = str(manifest)
        entries = parse_manifest_access(manifest)
        job["access_entry_count"] = len(entries)
        archive = discover_archive_path(manifest, archive_path)
        job["archive_path"] = str(archive)
        password, key, entry = _decrypt_first_access(entries)
        job["cert_thumbprint_used"] = key.thumbprint or entry.thumbprint
        job["cert_source"] = key.source
        listing = extract_with_7z(archive, password, extract_dir)
        job["extract_listing"] = listing
        job["status"] = "succeeded"
        job["updated_at"] = _utcnow()
        _save_job(job)
        _append_job_log(ident, f"status=succeeded files={len(listing)}")
        audit_lta(
            "open_succeeded",
            job_id=ident,
            manifest_path=str(manifest),
            archive_path=str(archive),
            cert_thumbprint=job["cert_thumbprint_used"],
            cert_source=key.source,
            file_count=len(listing),
        )
        return get_lta_job(ident)
    except LtaError as exc:
        job["status"] = "failed"
        job["error"] = exc.code
        job["error_detail"] = exc.detail or str(exc)
        job["updated_at"] = _utcnow()
        _save_job(job)
        _append_job_log(ident, f"status=failed error={exc.code}")
        audit_lta(
            "open_failed",
            job_id=ident,
            error=exc.code,
            detail=exc.detail,
            manifest_path=job.get("manifest_path"),
        )
        return get_lta_job(ident)
    except Exception as exc:  # noqa: BLE001 — convert unexpected to archive/decrypt class
        job["status"] = "failed"
        job["error"] = "archive_failed"
        job["error_detail"] = type(exc).__name__
        job["updated_at"] = _utcnow()
        _save_job(job)
        _append_job_log(ident, f"status=failed error=archive_failed class={type(exc).__name__}")
        audit_lta("open_failed", job_id=ident, error="archive_failed", detail=type(exc).__name__)
        logger.exception("lta open unexpected failure")
        return get_lta_job(ident)
    finally:
        password = None  # noqa: F841 — drop reference promptly


def start_protected_folder_open(
    *,
    manifest_path: str,
    archive_path: str | None = None,
    sync: bool = False,
) -> dict[str, Any]:
    """Create a job and run the pipeline (sync or background thread)."""
    # Fail fast on path deny before queueing (honest API errors)
    try:
        resolve_manifest_path(manifest_path)
        if archive_path and str(archive_path).strip():
            assert_path_allowed(str(archive_path).strip())
    except PathDenied:
        audit_lta("open_denied", reason="path_denied", manifest_path=str(manifest_path or ""))
        raise
    except ManifestNotFound:
        # Allow job to record failure for missing manifest when path was allowed…
        # but if path itself denied, already raised. For missing file, still start job
        # only when parent path is allowed — resolve_manifest_path already enforced.
        pass

    ident = uuid.uuid4().hex[:12]
    job = {
        "id": ident,
        "status": "queued",
        "created_at": _utcnow(),
        "updated_at": _utcnow(),
        "manifest_path": str(manifest_path),
        "archive_path": str(archive_path or ""),
        "extract_dir": str(job_directory(ident) / "files"),
        "extract_listing": [],
        "cert_thumbprint_used": "",
        "cert_source": "",
        "error": "",
        "error_detail": "",
        "persona_bind_hint": dict(THEMIS_PERSONA_HINT),
        "daybreak_jobs_hint": f"Open Daybreak → Jobs / LTA for job {ident}",
    }
    _save_job(job)
    if sync:
        return run_protected_folder_open(
            manifest_path=manifest_path,
            archive_path=archive_path,
            job_id=ident,
        )

    def _worker() -> None:
        run_protected_folder_open(
            manifest_path=manifest_path,
            archive_path=archive_path,
            job_id=ident,
        )

    threading.Thread(target=_worker, name=f"lta-job-{ident}", daemon=True).start()
    return {
        "job_id": ident,
        "id": ident,
        "status": "queued",
        "persona_bind_hint": dict(THEMIS_PERSONA_HINT),
        "daybreak_jobs_hint": job["daybreak_jobs_hint"],
    }


def cert_candidates_payload() -> dict[str, Any]:
    return list_cert_candidates()
