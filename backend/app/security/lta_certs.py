"""RFC-0198 cert resolution for LTA Access decrypt (authorized recovery only).

Windows: enumerate Current User / Local Machine stores (thumbprint/SKI metadata only;
CryptDecryptMessage decrypts without exporting private keys).

Cross-platform: owner-provisioned recovery-keys vault under data_dir()/recovery-keys/
(metadata listings never include PEM/private key bytes).

No network calls. No PEM paste into chat. Synthetic keys belong in test temp dirs only.
"""

from __future__ import annotations

import json
import logging
import re
import sys
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

from ..config import data_dir
from .lta_errors import CertNotFound, NoPrivateKey, PlatformUnsupported

logger = logging.getLogger(__name__)

_LOCK = threading.RLock()

# Test-only injectable resolver: (thumbprint, ski) -> private key PEM bytes | None
_TEST_KEY_RESOLVER: Callable[[str | None, str | None], bytes | None] | None = None


@dataclass(frozen=True)
class CertCandidate:
    thumbprint: str
    subject_key_identifier: str
    subject: str
    has_private_key: bool
    source: str  # windows_store | recovery_keys

    def as_dict(self) -> dict[str, Any]:
        return {
            "thumbprint": self.thumbprint,
            "subject_key_identifier": self.subject_key_identifier,
            "subject": self.subject,
            "has_private_key": self.has_private_key,
            "source": self.source,
        }


@dataclass
class ResolvedKey:
    """In-memory key handle for decrypt. Never log .private_key_pem."""

    thumbprint: str
    subject_key_identifier: str
    source: str
    private_key_pem: bytes | None = None
    # Windows: CryptDecryptMessage path (no PEM export)
    use_windows_cms: bool = False
    windows_store_names: tuple[str, ...] = ()


def set_test_key_resolver(resolver: Callable[[str | None, str | None], bytes | None] | None) -> None:
    """Unit tests only — inject synthetic keys generated in temp dirs."""
    global _TEST_KEY_RESOLVER
    _TEST_KEY_RESOLVER = resolver


def normalize_hex_id(value: str | None) -> str:
    text = re.sub(r"[^0-9A-Fa-f]", "", (value or "").strip())
    return text.upper()


def recovery_keys_root() -> Path:
    path = data_dir() / "recovery-keys"
    path.mkdir(parents=True, exist_ok=True)
    return path


def _index_path() -> Path:
    return recovery_keys_root() / "index.json"


def _read_recovery_index() -> list[dict[str, Any]]:
    path = _index_path()
    if not path.is_file():
        return []
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    rows = payload.get("keys", []) if isinstance(payload, dict) else []
    return [row for row in rows if isinstance(row, dict)]


def list_recovery_key_metadata() -> list[CertCandidate]:
    """Metadata only — never returns key material."""
    out: list[CertCandidate] = []
    for row in _read_recovery_index():
        thumb = normalize_hex_id(str(row.get("thumbprint") or ""))
        ski = normalize_hex_id(str(row.get("subject_key_identifier") or row.get("ski") or ""))
        label = str(row.get("label") or row.get("subject") or "recovery-key").strip()[:200]
        key_rel = str(row.get("key_file") or "").strip()
        has_key = bool(key_rel) and (recovery_keys_root() / key_rel).is_file()
        if not thumb and not ski:
            continue
        out.append(
            CertCandidate(
                thumbprint=thumb,
                subject_key_identifier=ski,
                subject=label,
                has_private_key=has_key,
                source="recovery_keys",
            )
        )
    return out


def register_recovery_key_metadata(
    *,
    thumbprint: str,
    subject_key_identifier: str = "",
    label: str = "recovery-key",
    key_file: str,
) -> dict[str, Any]:
    """Register owner-provisioned key file under recovery-keys (path relative).

    Used by desktop provisioning / tests. Does not accept raw PEM over the API.
    """
    thumb = normalize_hex_id(thumbprint)
    ski = normalize_hex_id(subject_key_identifier)
    rel = Path(str(key_file or "").strip()).name
    if not rel or rel != str(key_file).replace("\\", "/").split("/")[-1]:
        raise ValueError("key_file must be a plain filename under recovery-keys/")
    if ".." in rel or "/" in rel or "\\" in rel:
        raise ValueError("key_file must be a plain filename under recovery-keys/")
    target = recovery_keys_root() / rel
    if not target.is_file():
        raise FileNotFoundError(f"recovery key file missing: {rel}")
    row = {
        "thumbprint": thumb,
        "subject_key_identifier": ski,
        "label": (label or "recovery-key").strip()[:200],
        "key_file": rel,
    }
    with _LOCK:
        rows = [item for item in _read_recovery_index() if normalize_hex_id(str(item.get("thumbprint") or "")) != thumb]
        rows.append(row)
        index = _index_path()
        temp = index.with_suffix(".tmp")
        temp.write_text(json.dumps({"version": 1, "keys": rows}, indent=2) + "\n", encoding="utf-8")
        temp.replace(index)
    return {"thumbprint": thumb, "subject_key_identifier": ski, "label": row["label"], "source": "recovery_keys"}


def _load_recovery_key_pem(thumbprint: str | None, ski: str | None) -> ResolvedKey | None:
    want_thumb = normalize_hex_id(thumbprint)
    want_ski = normalize_hex_id(ski)
    for row in _read_recovery_index():
        thumb = normalize_hex_id(str(row.get("thumbprint") or ""))
        row_ski = normalize_hex_id(str(row.get("subject_key_identifier") or row.get("ski") or ""))
        match = False
        if want_thumb and thumb and want_thumb == thumb:
            match = True
        if want_ski and row_ski and want_ski == row_ski:
            match = True
        if not match:
            continue
        rel = str(row.get("key_file") or "").strip()
        if not rel:
            raise NoPrivateKey("recovery-keys entry has no key_file", detail="no_private_key")
        path = recovery_keys_root() / Path(rel).name
        if not path.is_file():
            raise NoPrivateKey("recovery-keys file missing", detail="no_private_key")
        try:
            pem = path.read_bytes()
        except OSError as exc:
            raise NoPrivateKey("recovery-keys unreadable", detail="no_private_key") from exc
        if b"PRIVATE KEY" not in pem:
            raise NoPrivateKey("recovery-keys file is not a private key", detail="no_private_key")
        return ResolvedKey(
            thumbprint=thumb,
            subject_key_identifier=row_ski,
            source="recovery_keys",
            private_key_pem=pem,
            use_windows_cms=False,
        )
    return None


def _windows_store_candidates() -> list[CertCandidate]:
    if sys.platform != "win32":
        return []
    try:
        return _enumerate_windows_certs()
    except Exception as exc:  # noqa: BLE001 — surface as empty + log class only
        logger.warning("windows cert store enumeration failed: %s", type(exc).__name__)
        return []


def _enumerate_windows_certs() -> list[CertCandidate]:
    """Enumerate MY stores; metadata only (no private key export)."""
    import ctypes
    from ctypes import wintypes

    crypt32 = ctypes.WinDLL("crypt32", use_last_error=True)
    CERT_STORE_PROV_SYSTEM = 10
    CERT_SYSTEM_STORE_CURRENT_USER = 0x00010000
    CERT_SYSTEM_STORE_LOCAL_MACHINE = 0x00020000
    CERT_STORE_READONLY_FLAG = 0x00008000
    CERT_STORE_OPEN_EXISTING_FLAG = 0x00004000
    X509_ASN_ENCODING = 0x00000001
    PKCS_7_ASN_ENCODING = 0x00010000
    encoding = X509_ASN_ENCODING | PKCS_7_ASN_ENCODING
    CERT_KEY_PROV_INFO_PROP_ID = 2
    CERT_SHA1_HASH_PROP_ID = 3
    CERT_FIND_ANY = 0

    class CRYPT_KEY_PROV_INFO(ctypes.Structure):
        _fields_ = [
            ("pwszContainerName", wintypes.LPWSTR),
            ("pwszProvName", wintypes.LPWSTR),
            ("dwProvType", wintypes.DWORD),
            ("dwFlags", wintypes.DWORD),
            ("cProvParam", wintypes.DWORD),
            ("rgProvParam", ctypes.c_void_p),
            ("dwKeySpec", wintypes.DWORD),
        ]

    CertOpenStore = crypt32.CertOpenStore
    CertOpenStore.argtypes = [ctypes.c_void_p, wintypes.DWORD, ctypes.c_void_p, wintypes.DWORD, ctypes.c_void_p]
    CertOpenStore.restype = ctypes.c_void_p
    CertCloseStore = crypt32.CertCloseStore
    CertCloseStore.argtypes = [ctypes.c_void_p, wintypes.DWORD]
    CertCloseStore.restype = wintypes.BOOL
    CertEnumCertificatesInStore = crypt32.CertEnumCertificatesInStore
    CertEnumCertificatesInStore.argtypes = [ctypes.c_void_p, ctypes.c_void_p]
    CertEnumCertificatesInStore.restype = ctypes.c_void_p
    CertGetCertificateContextProperty = crypt32.CertGetCertificateContextProperty
    CertGetCertificateContextProperty.argtypes = [
        ctypes.c_void_p,
        wintypes.DWORD,
        ctypes.c_void_p,
        ctypes.POINTER(wintypes.DWORD),
    ]
    CertGetCertificateContextProperty.restype = wintypes.BOOL
    CertFreeCertificateContext = crypt32.CertFreeCertificateContext
    CertFreeCertificateContext.argtypes = [ctypes.c_void_p]
    CertFreeCertificateContext.restype = wintypes.BOOL

    class CERT_CONTEXT(ctypes.Structure):
        _fields_ = [
            ("dwCertEncodingType", wintypes.DWORD),
            ("pbCertEncoded", ctypes.POINTER(ctypes.c_byte)),
            ("cbCertEncoded", wintypes.DWORD),
            ("pCertInfo", ctypes.c_void_p),
            ("hCertStore", ctypes.c_void_p),
        ]

    def _prop_bytes(ctx: int, prop_id: int) -> bytes | None:
        size = wintypes.DWORD(0)
        if not CertGetCertificateContextProperty(ctx, prop_id, None, ctypes.byref(size)):
            return None
        buf = (ctypes.c_byte * size.value)()
        if not CertGetCertificateContextProperty(ctx, prop_id, buf, ctypes.byref(size)):
            return None
        return bytes(buf[: size.value])

    def _thumbprint(ctx: int) -> str:
        raw = _prop_bytes(ctx, CERT_SHA1_HASH_PROP_ID)
        if not raw:
            return ""
        return raw.hex().upper()

    def _has_private_key(ctx: int) -> bool:
        size = wintypes.DWORD(0)
        return bool(CertGetCertificateContextProperty(ctx, CERT_KEY_PROV_INFO_PROP_ID, None, ctypes.byref(size)))

    def _ski_from_der(der: bytes) -> str:
        try:
            from cryptography import x509
            from cryptography.x509.oid import ExtensionOID

            cert = x509.load_der_x509_certificate(der)
            ext = cert.extensions.get_extension_for_oid(ExtensionOID.SUBJECT_KEY_IDENTIFIER)
            return ext.value.digest.hex().upper()
        except Exception:
            return ""

    def _subject_from_der(der: bytes) -> str:
        try:
            from cryptography import x509

            cert = x509.load_der_x509_certificate(der)
            return cert.subject.rfc4514_string()[:240]
        except Exception:
            return ""

    stores = (
        ("MY", CERT_SYSTEM_STORE_CURRENT_USER, "windows_store:current_user"),
        ("MY", CERT_SYSTEM_STORE_LOCAL_MACHINE, "windows_store:local_machine"),
    )
    CERT_STORE_PROV_SYSTEM_W = ctypes.c_void_p(CERT_STORE_PROV_SYSTEM)
    out: list[CertCandidate] = []
    seen: set[str] = set()
    for store_name, location, source in stores:
        flags = location | CERT_STORE_READONLY_FLAG | CERT_STORE_OPEN_EXISTING_FLAG
        handle = CertOpenStore(
            CERT_STORE_PROV_SYSTEM_W,
            encoding,
            None,
            flags,
            ctypes.c_wchar_p(store_name),
        )
        if not handle:
            continue
        try:
            ctx = None
            while True:
                ctx = CertEnumCertificatesInStore(handle, ctx)
                if not ctx:
                    break
                thumb = _thumbprint(ctx)
                # CERT_CONTEXT layout: pbCertEncoded / cbCertEncoded
                cctx = ctypes.cast(ctx, ctypes.POINTER(CERT_CONTEXT)).contents
                der = ctypes.string_at(cctx.pbCertEncoded, cctx.cbCertEncoded)
                ski = _ski_from_der(der)
                subject = _subject_from_der(der)
                key = thumb or ski
                if not key or key in seen:
                    continue
                seen.add(key)
                out.append(
                    CertCandidate(
                        thumbprint=thumb,
                        subject_key_identifier=ski,
                        subject=subject,
                        has_private_key=_has_private_key(ctx),
                        source=source,
                    )
                )
        finally:
            CertCloseStore(handle, 0)
    return out


def list_cert_candidates() -> dict[str, Any]:
    """Thumbprints/SKIs available for Access match — never private key export."""
    windows: list[dict[str, Any]] = []
    platform_note = ""
    if sys.platform == "win32":
        windows = [item.as_dict() for item in _windows_store_candidates()]
    else:
        platform_note = "windows_cert_store_unavailable"
    recovery = [item.as_dict() for item in list_recovery_key_metadata()]
    return {
        "platform": sys.platform,
        "platform_note": platform_note,
        "candidates": windows + recovery,
        "private_key_export": False,
        "persona_bind_hint": {
            "primary_persona_id": "themis",
            "presence_shape_hint": "twin_shield",
            "voice_profile_hint": "tactical_aide_original_v1",
        },
    }


def resolve_key_for_access(*, thumbprint: str | None, subject_key_identifier: str | None) -> ResolvedKey:
    """Resolve a private-key handle for one Access entry. Never logs key bytes."""
    want_thumb = normalize_hex_id(thumbprint)
    want_ski = normalize_hex_id(subject_key_identifier)
    if not want_thumb and not want_ski:
        raise CertNotFound("Access entry missing CertThumbprint and SubjectKeyIdentifier")

    if _TEST_KEY_RESOLVER is not None:
        pem = _TEST_KEY_RESOLVER(want_thumb or None, want_ski or None)
        if pem:
            return ResolvedKey(
                thumbprint=want_thumb,
                subject_key_identifier=want_ski,
                source="test_resolver",
                private_key_pem=pem,
            )

    recovered = _load_recovery_key_pem(want_thumb or None, want_ski or None)
    if recovered is not None:
        return recovered

    if sys.platform != "win32":
        # No Windows store — if recovery-keys also missed, classify honestly.
        raise CertNotFound(
            "no matching certificate in recovery-keys (Windows cert store unavailable on this platform)",
            detail=platform_note_for_store(),
        )

    candidates = _windows_store_candidates()
    matched = [
        c
        for c in candidates
        if (want_thumb and c.thumbprint == want_thumb) or (want_ski and c.subject_key_identifier == want_ski)
    ]
    if not matched:
        raise CertNotFound("no matching certificate in Windows cert store or recovery-keys")
    with_key = [c for c in matched if c.has_private_key]
    if not with_key:
        raise NoPrivateKey("matching certificate found but private key is not available")
    chosen = with_key[0]
    return ResolvedKey(
        thumbprint=chosen.thumbprint,
        subject_key_identifier=chosen.subject_key_identifier,
        source=chosen.source,
        private_key_pem=None,
        use_windows_cms=True,
        windows_store_names=("MY",),
    )


def platform_note_for_store() -> str:
    if sys.platform == "win32":
        return ""
    return "windows_cert_store_unavailable"


def require_windows_cert_store() -> None:
    if sys.platform != "win32":
        raise PlatformUnsupported(
            "Windows certificate store APIs require Windows",
            detail="windows_cert_store_unavailable",
        )


def scrub_secret_fields(payload: dict[str, Any]) -> dict[str, Any]:
    """Drop keys that must never appear in audit/logs/API job dumps."""
    banned = {
        "password",
        "archive_password",
        "private_key",
        "private_key_pem",
        "pem",
        "inkey",
        "access",
        "ciphertext",
        "access_blob",
        "key_bytes",
        "secret",
    }
    out: dict[str, Any] = {}
    for key, value in payload.items():
        if str(key).lower() in banned:
            continue
        if isinstance(value, dict):
            out[key] = scrub_secret_fields(value)
        else:
            out[key] = value
    return out
