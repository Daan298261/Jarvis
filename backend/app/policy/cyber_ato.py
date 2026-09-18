"""In-person cyber ATO licenses for Blue/Red runtime (RFC-0086 / RFC-0087).

Signed with Ed25519. Vendor issuance lives in the license manager; Jarvis
embeds only verify material (and an optional X25519 unseal key). This is the
authorization artifact for specialist routing and permission flags. It does
not register exploits, payloads, or hack-back skills.
"""
from __future__ import annotations

import argparse
import json
import os
import threading
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey, Ed25519PublicKey

from .. import __version__ as JARVIS_VERSION
from ..config import data_dir
from ..licensing.clock_log import CLOCK_ROLLBACK_MESSAGE, inspect_clock
from ..licensing.modules import normalize_module_id, requires_law_enforcement
from ..licensing.seal import SealError, is_sealed_document, seal_bytes, unseal_bytes

KIND = "jarvis-cyber-ato"
_LOCK = threading.RLock()
_DIRNAME = "cyber-ato"

_PRIVATE_KEY_NAME = "issuer.key"
_PUBLIC_KEY_NAME = "issuer.pub"
_TRUSTED_PUB_NAME = "trusted.pub"
_LICENSE_NAME = "license.json"
_SEALED_LICENSE_NAME = "license.jarvis-license"
_AUDIT_NAME = "audit.jsonl"

# Verify-only default. Override with JARVIS_ATO_PUBLIC_KEY or data/cyber-ato/trusted.pub.
DEFAULT_VENDOR_PUBLIC_KEY_HEX = "f4290aef926737074b32de8c8a52e8d702be787d81d02c4a7b5a4aa04a9d351a"


class AtoError(ValueError):
    pass


def _utcnow() -> datetime:
    return datetime.now(timezone.utc).replace(microsecond=0)


def _iso(value: datetime) -> str:
    text = value.astimezone(timezone.utc).replace(microsecond=0).isoformat()
    return text.replace("+00:00", "Z")


def _parse_iso(value: str) -> datetime:
    text = (value or "").strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    parsed = datetime.fromisoformat(text)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def ato_dir() -> Path:
    path = data_dir() / _DIRNAME
    path.mkdir(parents=True, exist_ok=True)
    return path


def issuer_private_path() -> Path:
    return ato_dir() / _PRIVATE_KEY_NAME


def issuer_public_path() -> Path:
    return ato_dir() / _PUBLIC_KEY_NAME


def trusted_public_path() -> Path:
    return ato_dir() / _TRUSTED_PUB_NAME


def license_path() -> Path:
    return ato_dir() / _LICENSE_NAME


def sealed_license_path() -> Path:
    return ato_dir() / _SEALED_LICENSE_NAME


def audit_path() -> Path:
    return ato_dir() / _AUDIT_NAME


def _audit(event: str, **fields: Any) -> None:
    record = {"at": _iso(_utcnow()), "event": event, **fields}
    with audit_path().open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(record, sort_keys=True) + "\n")


def _canonical(payload: dict[str, Any]) -> bytes:
    return json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")


def has_issuer() -> bool:
    return issuer_private_path().is_file() and issuer_public_path().is_file()


def load_or_create_issuer() -> tuple[Ed25519PrivateKey, Ed25519PublicKey]:
    private_path = issuer_private_path()
    public_path = issuer_public_path()
    if private_path.is_file() and public_path.is_file():
        private = Ed25519PrivateKey.from_private_bytes(private_path.read_bytes())
        public = Ed25519PublicKey.from_public_bytes(public_path.read_bytes())
        return private, public
    private = Ed25519PrivateKey.generate()
    public = private.public_key()
    private_bytes = private.private_bytes_raw()
    public_bytes = public.public_bytes_raw()
    tmp_private = private_path.with_suffix(private_path.suffix + ".tmp")
    tmp_public = public_path.with_suffix(public_path.suffix + ".tmp")
    tmp_private.write_bytes(private_bytes)
    tmp_public.write_bytes(public_bytes)
    try:
        os.chmod(tmp_private, 0o600)
    except OSError:
        pass
    os.replace(tmp_private, private_path)
    os.replace(tmp_public, public_path)
    _audit("issuer_created")
    return private, public


def load_public_key() -> Ed25519PublicKey | None:
    path = issuer_public_path()
    if not path.is_file():
        return None
    return Ed25519PublicKey.from_public_bytes(path.read_bytes())


def _parse_ed25519_public(raw: str | bytes) -> Ed25519PublicKey:
    if isinstance(raw, bytes):
        data = raw
        if len(data) != 32:
            text = data.decode("ascii", errors="ignore").strip()
            try:
                data = bytes.fromhex(text)
            except ValueError:
                import base64

                data = base64.b64decode(text)
        if len(data) != 32:
            raise AtoError("ATO public key must be 32 bytes")
        return Ed25519PublicKey.from_public_bytes(data)
    text = raw.strip()
    try:
        data = bytes.fromhex(text)
    except ValueError:
        import base64

        data = base64.b64decode(text)
    if len(data) != 32:
        raise AtoError("ATO public key must be 32 bytes")
    return Ed25519PublicKey.from_public_bytes(data)


def _pin_trusted_public(public: Ed25519PublicKey) -> None:
    path = trusted_public_path()
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_bytes(public.public_bytes_raw())
    os.replace(tmp, path)


def get_verify_public_keys() -> list[Ed25519PublicKey]:
    keys: list[Ed25519PublicKey] = []
    seen: set[bytes] = set()

    def _add(public: Ed25519PublicKey | None) -> None:
        if public is None:
            return
        raw = public.public_bytes_raw()
        if raw in seen:
            return
        seen.add(raw)
        keys.append(public)

    override = (os.environ.get("JARVIS_ATO_PUBLIC_KEY") or "").strip()
    if override:
        try:
            _add(_parse_ed25519_public(override))
        except Exception:
            pass
    trusted = trusted_public_path()
    if trusted.is_file():
        try:
            _add(Ed25519PublicKey.from_public_bytes(trusted.read_bytes()[:32]))
        except Exception:
            pass
    _add(load_public_key())
    try:
        _add(_parse_ed25519_public(DEFAULT_VENDOR_PUBLIC_KEY_HEX))
    except Exception:
        pass
    return keys


def _modules_from_flags(*, blue_team: bool, red_team: bool, extra: list[str] | None = None) -> list[str]:
    modules: list[str] = []
    for raw in extra or []:
        key = normalize_module_id(str(raw))
        if key and key not in modules:
            modules.append(key)
    if blue_team and "blue-team" not in modules:
        modules.insert(0, "blue-team")
    if red_team and "red-team" not in modules:
        modules.append("red-team")
    return modules


def _validate_payload(payload: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(payload, dict):
        raise AtoError("ATO payload must be an object")
    if payload.get("kind") != KIND:
        raise AtoError("Not a Jarvis cyber ATO license")
    if payload.get("v") != 1:
        raise AtoError("Unsupported ATO version")
    law_enforcement = bool(payload.get("law_enforcement"))
    extra_modules = payload.get("modules") or []
    if extra_modules and not isinstance(extra_modules, list):
        raise AtoError("ATO modules must be a list")
    modules = _modules_from_flags(
        blue_team=bool(payload.get("blue_team")),
        red_team=bool(payload.get("red_team")),
        extra=[str(item) for item in extra_modules],
    )
    blue_team = "blue-team" in modules or bool(payload.get("blue_team"))
    red_team = "red-team" in modules or bool(payload.get("red_team"))
    if blue_team and "blue-team" not in modules:
        modules.insert(0, "blue-team")
    if red_team and "red-team" not in modules:
        modules.append("red-team")
    if red_team and not law_enforcement:
        raise AtoError("Red team ATO requires the law-enforcement flag")
    if any(requires_law_enforcement(item) for item in modules) and not law_enforcement:
        raise AtoError("Red team ATO requires the law-enforcement flag")
    if not modules:
        raise AtoError("ATO must grant at least one licensed module")
    if not payload.get("in_person_verified"):
        raise AtoError("ATO must be marked in-person verified")
    for field in ("license_id", "issued_at", "not_before", "expires_at", "renew_by"):
        if not str(payload.get(field) or "").strip():
            raise AtoError(f"ATO is missing {field}")
    licensee_email = str(payload.get("licensee_email") or "").strip()
    if licensee_email and "@" not in licensee_email:
        raise AtoError("Licensee email is not valid")
    expires_at = str(payload["expires_at"])
    max_expires_at = str(payload.get("max_expires_at") or expires_at)
    auto_renew = bool(payload.get("auto_renew"))
    try:
        term_days = int(payload.get("term_days") or 0)
    except (TypeError, ValueError) as exc:
        raise AtoError("term_days must be an integer") from exc
    if auto_renew and term_days < 1:
        raise AtoError("auto_renew requires term_days >= 1")
    jarvis_version = str(payload.get("jarvis_version") or JARVIS_VERSION).strip()
    cleaned: dict[str, Any] = {
        "v": 1,
        "kind": KIND,
        "license_id": str(payload["license_id"]).strip(),
        "in_person_verified": True,
        "law_enforcement": law_enforcement,
        "blue_team": bool(blue_team),
        "red_team": bool(red_team),
        "modules": modules,
        "licensee_name": str(payload.get("licensee_name") or "").strip(),
        "licensee_email": licensee_email,
        "licensee_address": str(payload.get("licensee_address") or "").strip(),
        "jarvis_version": jarvis_version,
        "jarvis_version_min": str(payload.get("jarvis_version_min") or jarvis_version).strip(),
        "jarvis_version_max": str(payload.get("jarvis_version_max") or "").strip(),
        "issued_at": str(payload["issued_at"]),
        "issued_system_utc": str(payload.get("issued_system_utc") or payload["issued_at"]),
        "not_before": str(payload["not_before"]),
        "expires_at": expires_at,
        "renew_by": str(payload["renew_by"]),
        "max_expires_at": max_expires_at,
        "auto_renew": auto_renew,
        "term_days": term_days if term_days > 0 else 0,
        "case_ref": str(payload.get("case_ref") or "").strip(),
    }
    package_class = str(payload.get("package_class") or "").strip()
    if package_class:
        cleaned["package_class"] = package_class
    return cleaned


def sign_license(payload: dict[str, Any], private_key: Ed25519PrivateKey) -> dict[str, Any]:
    cleaned = _validate_payload(payload)
    signature = private_key.sign(_canonical(cleaned))
    public = private_key.public_key().public_bytes_raw()
    return {
        "payload": cleaned,
        "signature": signature.hex(),
        "public_key": public.hex(),
    }


def _open_signed_document(document: dict[str, Any]) -> dict[str, Any]:
    if is_sealed_document(document):
        try:
            inner = json.loads(unseal_bytes(document).decode("utf-8"))
        except (SealError, json.JSONDecodeError, UnicodeDecodeError) as exc:
            raise AtoError("Sealed license could not be opened") from exc
        if not isinstance(inner, dict):
            raise AtoError("Sealed license payload is not an object")
        return inner
    return document


def verify_license(document: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(document, dict):
        raise AtoError("License must be a JSON object")
    opened = _open_signed_document(document)
    payload = _validate_payload(opened.get("payload") or {})
    try:
        signature = bytes.fromhex(str(opened.get("signature") or ""))
    except ValueError as exc:
        raise AtoError("ATO signature is not valid") from exc
    body = _canonical(payload)
    for public in get_verify_public_keys():
        try:
            public.verify(signature, body)
            return payload
        except Exception:
            continue
    embedded = str(opened.get("public_key") or "").strip()
    pinned = bool((os.environ.get("JARVIS_ATO_PUBLIC_KEY") or "").strip()) or trusted_public_path().is_file() or issuer_public_path().is_file()
    if embedded and not pinned:
        try:
            tofu = _parse_ed25519_public(embedded)
            tofu.verify(signature, body)
            _pin_trusted_public(tofu)
            _audit("pinned_vendor_key")
            return payload
        except Exception:
            pass
    raise AtoError("ATO signature is not valid")


def issue_license(
    *,
    law_enforcement: bool,
    blue_team: bool = True,
    red_team: bool = False,
    valid_days: int = 90,
    renew_in_days: int | None = None,
    case_ref: str = "",
    install: bool = False,
    modules: list[str] | None = None,
    licensee_name: str = "",
    licensee_email: str = "",
    licensee_address: str = "",
    jarvis_version: str | None = None,
    auto_renew: bool = False,
    term_days: int | None = None,
    max_days: int | None = None,
    max_expires_at: str | None = None,
    private_key: Ed25519PrivateKey | None = None,
    package_class: str = "",
) -> dict[str, Any]:
    if valid_days < 1 or valid_days > 3660:
        raise AtoError("valid_days must be between 1 and 3660")
    renew_days = valid_days if renew_in_days is None else int(renew_in_days)
    if renew_days < 1 or renew_days > valid_days:
        raise AtoError("renew_in_days must be between 1 and valid_days")
    selected = _modules_from_flags(blue_team=blue_team, red_team=red_team, extra=modules)
    if not selected:
        raise AtoError("ATO must grant at least one licensed module")
    if ("red-team" in selected or red_team) and not law_enforcement:
        raise AtoError("Red team ATO requires the law-enforcement flag")
    now = _utcnow()
    term = int(term_days) if term_days is not None else valid_days
    if auto_renew and term < 1:
        raise AtoError("auto_renew requires term_days >= 1")
    cap_days = int(max_days) if max_days is not None else valid_days
    if max_expires_at:
        cap_iso = str(max_expires_at)
    else:
        if cap_days < valid_days:
            cap_days = valid_days
        cap_iso = _iso(now + timedelta(days=cap_days))
    version = (jarvis_version or JARVIS_VERSION).strip()
    payload = {
        "v": 1,
        "kind": KIND,
        "license_id": str(uuid.uuid4()),
        "in_person_verified": True,
        "law_enforcement": bool(law_enforcement),
        "blue_team": "blue-team" in selected,
        "red_team": "red-team" in selected,
        "modules": selected,
        "licensee_name": (licensee_name or "").strip(),
        "licensee_email": (licensee_email or "").strip(),
        "licensee_address": (licensee_address or "").strip(),
        "jarvis_version": version,
        "jarvis_version_min": version,
        "jarvis_version_max": "",
        "issued_at": _iso(now),
        "issued_system_utc": _iso(now),
        "not_before": _iso(now),
        "expires_at": _iso(now + timedelta(days=valid_days)),
        "renew_by": _iso(now + timedelta(days=renew_days)),
        "max_expires_at": cap_iso,
        "auto_renew": bool(auto_renew),
        "term_days": term if auto_renew or term_days is not None else 0,
        "case_ref": (case_ref or "").strip(),
    }
    package_tag = (package_class or "").strip()
    if package_tag:
        payload["package_class"] = package_tag
    with _LOCK:
        signing_key = private_key if private_key is not None else load_or_create_issuer()[0]
        document = sign_license(payload, signing_key)
        _audit(
            "issued",
            license_id=payload["license_id"],
            law_enforcement=payload["law_enforcement"],
            blue_team=payload["blue_team"],
            red_team=payload["red_team"],
            modules=payload["modules"],
            expires_at=payload["expires_at"],
            renew_by=payload["renew_by"],
        )
        if install:
            _store_license_unlocked(document)
    return document


def _seal_document(document: dict[str, Any]) -> dict[str, Any]:
    inner = json.dumps(document, separators=(",", ":"), sort_keys=True).encode("utf-8")
    return seal_bytes(inner)


def _store_license_unlocked(document: dict[str, Any]) -> dict[str, Any]:
    opened = _open_signed_document(document) if is_sealed_document(document) else document
    payload = verify_license(opened)
    sealed = document if is_sealed_document(document) else _seal_document(opened)
    sealed_path = sealed_license_path()
    temp = sealed_path.with_suffix(sealed_path.suffix + ".tmp")
    temp.write_text(json.dumps(sealed, indent=2) + "\n", encoding="utf-8")
    os.replace(temp, sealed_path)
    json_path = license_path()
    if json_path.is_file():
        json_path.unlink()
    _audit("installed", license_id=payload["license_id"])
    return sealed if is_sealed_document(document) else opened


def install_license(document: dict[str, Any]) -> dict[str, Any]:
    with _LOCK:
        return _store_license_unlocked(document)


def load_installed() -> dict[str, Any] | None:
    sealed = sealed_license_path()
    if sealed.is_file():
        try:
            raw = json.loads(sealed.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            raw = None
        if isinstance(raw, dict):
            return raw
    path = license_path()
    if not path.is_file():
        return None
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return raw if isinstance(raw, dict) else None


def revoke_license() -> None:
    with _LOCK:
        removed = False
        for path in (sealed_license_path(), license_path()):
            if path.is_file():
                path.unlink()
                removed = True
        if removed:
            _audit("revoked")


def renew_license(*, valid_days: int = 90, renew_in_days: int | None = None, install: bool = True) -> dict[str, Any]:
    current = load_installed()
    if not current:
        raise AtoError("No ATO license is installed to renew")
    payload = verify_license(current)
    try:
        max_expires = _parse_iso(str(payload.get("max_expires_at") or payload["expires_at"]))
        remaining = int((max_expires - _utcnow()).total_seconds() // 86400)
    except ValueError:
        remaining = valid_days
    if remaining < 1:
        raise AtoError("Cannot renew past signed max_expires_at")
    days = min(valid_days, remaining)
    return issue_license(
        law_enforcement=bool(payload["law_enforcement"]),
        blue_team=bool(payload["blue_team"]),
        red_team=bool(payload["red_team"]),
        valid_days=days,
        renew_in_days=renew_in_days if renew_in_days is None else min(int(renew_in_days), days),
        case_ref=str(payload.get("case_ref") or ""),
        install=install,
        modules=list(payload.get("modules") or []),
        licensee_name=str(payload.get("licensee_name") or ""),
        licensee_email=str(payload.get("licensee_email") or ""),
        licensee_address=str(payload.get("licensee_address") or ""),
        jarvis_version=str(payload.get("jarvis_version") or JARVIS_VERSION),
        auto_renew=bool(payload.get("auto_renew")),
        term_days=int(payload.get("term_days") or 0) or None,
        max_expires_at=str(payload.get("max_expires_at") or payload["expires_at"]),
    )


def effective_expires_at(payload: dict[str, Any], now: datetime | None = None) -> datetime:
    current = now or _utcnow()
    expires_at = _parse_iso(str(payload["expires_at"]))
    max_expires = _parse_iso(str(payload.get("max_expires_at") or payload["expires_at"]))
    if max_expires < expires_at:
        max_expires = expires_at
    auto_renew = bool(payload.get("auto_renew"))
    try:
        term_days = int(payload.get("term_days") or 0)
    except (TypeError, ValueError):
        term_days = 0
    if not auto_renew or term_days < 1:
        return min(expires_at, max_expires)
    if inspect_clock(now=current, record=False).locked:
        return min(expires_at, max_expires)
    if current < expires_at:
        return min(expires_at, max_expires)
    if current >= max_expires:
        return max_expires
    elapsed = current - expires_at
    extra_terms = int(elapsed.total_seconds() // (term_days * 86400)) + 1
    rolled = expires_at + timedelta(days=term_days * extra_terms)
    return min(rolled, max_expires)


@dataclass(frozen=True)
class AtoStatus:
    installed: bool
    valid: bool
    law_enforcement: bool
    blue_team: bool
    red_team: bool
    in_person_verified: bool
    expired: bool
    renewal_due: bool
    can_issue: bool
    license_id: str = ""
    expires_at: str = ""
    renew_by: str = ""
    case_ref: str = ""
    reason: str = ""
    clock_rollback: bool = False
    auto_renew: bool = False
    max_expires_at: str = ""
    modules: list[str] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return {
            "installed": self.installed,
            "valid": self.valid,
            "law_enforcement": self.law_enforcement,
            "blue_team": self.blue_team,
            "red_team": self.red_team,
            "in_person_verified": self.in_person_verified,
            "expired": self.expired,
            "renewal_due": self.renewal_due,
            "can_issue": self.can_issue,
            "license_id": self.license_id,
            "expires_at": self.expires_at,
            "renew_by": self.renew_by,
            "case_ref": self.case_ref,
            "reason": self.reason,
            "clock_rollback": self.clock_rollback,
            "auto_renew": self.auto_renew,
            "max_expires_at": self.max_expires_at,
            "modules": list(self.modules),
        }


def evaluate(*, now: datetime | None = None) -> AtoStatus:
    can_issue = has_issuer()
    current = now or _utcnow()
    document = load_installed()
    if document is None:
        return AtoStatus(
            installed=False,
            valid=False,
            law_enforcement=False,
            blue_team=False,
            red_team=False,
            in_person_verified=False,
            expired=False,
            renewal_due=False,
            can_issue=can_issue,
            reason="No in-person cyber ATO license is installed",
        )
    try:
        payload = verify_license(document)
    except AtoError as exc:
        return AtoStatus(
            installed=True,
            valid=False,
            law_enforcement=False,
            blue_team=False,
            red_team=False,
            in_person_verified=False,
            expired=False,
            renewal_due=False,
            can_issue=can_issue,
            reason=str(exc),
        )
    clock = inspect_clock(now=current, record=True)
    try:
        not_before = _parse_iso(str(payload["not_before"]))
        expires_at = effective_expires_at(payload, current)
        renew_by = _parse_iso(str(payload["renew_by"]))
        max_expires = _parse_iso(str(payload.get("max_expires_at") or payload["expires_at"]))
    except ValueError:
        return AtoStatus(
            installed=True,
            valid=False,
            law_enforcement=False,
            blue_team=False,
            red_team=False,
            in_person_verified=True,
            expired=True,
            renewal_due=True,
            can_issue=can_issue,
            license_id=str(payload.get("license_id") or ""),
            modules=list(payload.get("modules") or []),
            reason="ATO dates are not valid ISO timestamps",
        )
    modules = list(payload.get("modules") or [])
    expired = current >= expires_at
    too_early = current < not_before
    renewal_due = current >= renew_by
    if clock.locked:
        reason = CLOCK_ROLLBACK_MESSAGE
        valid = False
    elif too_early:
        reason = "ATO is not valid yet"
        valid = False
    elif expired:
        reason = "ATO has expired — renew in person"
        valid = False
    else:
        reason = "ATO renewal is due" if renewal_due else "In-person ATO is valid"
        valid = True
    return AtoStatus(
        installed=True,
        valid=valid,
        law_enforcement=bool(payload["law_enforcement"]),
        blue_team=bool(payload["blue_team"]),
        red_team=bool(payload["red_team"]),
        in_person_verified=True,
        expired=expired and not clock.locked,
        renewal_due=renewal_due,
        can_issue=can_issue,
        license_id=str(payload["license_id"]),
        expires_at=_iso(expires_at),
        renew_by=_iso(renew_by),
        case_ref=str(payload.get("case_ref") or ""),
        reason=reason,
        clock_rollback=clock.locked,
        auto_renew=bool(payload.get("auto_renew")),
        max_expires_at=_iso(max_expires),
        modules=modules,
    )


def role_allowed(role: str, *, now: datetime | None = None) -> bool:
    return licensed_module_allowed(role, now=now)


def licensed_module_allowed(module_id: str, *, now: datetime | None = None) -> bool:
    key = normalize_module_id(module_id)
    status = evaluate(now=now)
    if not status.valid or status.clock_rollback:
        return False
    if key in status.modules:
        if key == "red-team":
            return bool(status.law_enforcement)
        return True
    if key == "blue-team":
        return bool(status.blue_team)
    if key == "red-team":
        return bool(status.red_team and status.law_enforcement)
    return False


def license_blocks(module_id: str, *, now: datetime | None = None) -> str | None:
    """Return a lock reason if this module is licensed and currently suspended."""
    key = normalize_module_id(module_id)
    status = evaluate(now=now)
    licensed = key in status.modules
    if not licensed and key == "blue-team":
        licensed = bool(status.blue_team)
    if not licensed and key == "red-team":
        licensed = bool(status.red_team)
    if not status.installed or not licensed:
        return None
    if status.clock_rollback or not status.valid:
        return status.reason or CLOCK_ROLLBACK_MESSAGE
    return None


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Issue in-person Jarvis cyber ATO licenses (Blue/Red runtime). Does not add exploits."
    )
    sub = parser.add_subparsers(dest="command", required=True)

    issue = sub.add_parser("issue", help="Mint a signed ATO license JSON")
    issue.add_argument("--le", action="store_true", help="Law-enforcement authorization")
    issue.set_defaults(blue=True)
    issue.add_argument("--no-blue", dest="blue", action="store_false", help="Do not grant Blue team")
    issue.add_argument("--red", action="store_true", help="Allow Red team runtime (requires --le)")
    issue.add_argument("--days", type=int, default=90, help="Validity in days")
    issue.add_argument("--renew-in", type=int, default=None, help="ATO renewal reminder in days")
    issue.add_argument("--case", default="", help="Case / authorization reference")
    issue.add_argument("--install", action="store_true", help="Install onto this Leader after signing")
    issue.add_argument("--module", action="append", default=[], help="Licensed module id (repeatable)")
    issue.add_argument("--auto-renew", action="store_true", help="Allow local term roll up to max_expires_at")
    issue.add_argument("--max-days", type=int, default=None, help="Signed autorenew cap in days")
    issue.add_argument("--name", default="", help="Licensee name")
    issue.add_argument("--email", default="", help="Licensee email")
    issue.add_argument("--address", default="", help="Licensee address")

    sub.add_parser("status", help="Show installed ATO status")
    install = sub.add_parser("install", help="Install a signed or sealed license file")
    install.add_argument("path", help="Path to signed JSON or .jarvis-license")
    renew = sub.add_parser("renew", help="Issue a renewal of the installed ATO")
    renew.add_argument("--days", type=int, default=90)
    renew.add_argument("--renew-in", type=int, default=None)
    sub.add_parser("revoke", help="Remove the installed ATO from this Leader")

    args = parser.parse_args(argv)
    try:
        if args.command == "issue":
            document = issue_license(
                law_enforcement=args.le,
                blue_team=args.blue,
                red_team=args.red,
                valid_days=args.days,
                renew_in_days=args.renew_in,
                case_ref=args.case,
                install=args.install,
                modules=list(args.module or []),
                auto_renew=bool(args.auto_renew),
                max_days=args.max_days,
                licensee_name=args.name,
                licensee_email=args.email,
                licensee_address=args.address,
            )
            print(json.dumps(document, indent=2))
            return 0
        if args.command == "status":
            print(json.dumps(evaluate().as_dict(), indent=2))
            return 0
        if args.command == "install":
            raw = json.loads(Path(args.path).read_text(encoding="utf-8"))
            install_license(raw)
            print(json.dumps(evaluate().as_dict(), indent=2))
            return 0
        if args.command == "renew":
            document = renew_license(valid_days=args.days, renew_in_days=args.renew_in, install=True)
            print(json.dumps(document, indent=2))
            return 0
        if args.command == "revoke":
            revoke_license()
            print(json.dumps(evaluate().as_dict(), indent=2))
            return 0
    except AtoError as exc:
        parser.exit(2, f"{exc}\n")
    parser.exit(2, "unknown command\n")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
