"""In-person cyber ATO licenses for Blue/Red runtime (RFC-0086).

Signed locally with Ed25519. This is the authorization artifact for specialist
routing and permission flags. It does not register exploits, payloads, or
hack-back skills.
"""
from __future__ import annotations

import argparse
import json
import os
import threading
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey, Ed25519PublicKey

from ..config import data_dir

KIND = "jarvis-cyber-ato"
_LOCK = threading.RLock()
_DIRNAME = "cyber-ato"

_PRIVATE_KEY_NAME = "issuer.key"
_PUBLIC_KEY_NAME = "issuer.pub"
_LICENSE_NAME = "license.json"
_AUDIT_NAME = "audit.jsonl"


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


def license_path() -> Path:
    return ato_dir() / _LICENSE_NAME


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


def _validate_payload(payload: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(payload, dict):
        raise AtoError("ATO payload must be an object")
    if payload.get("kind") != KIND:
        raise AtoError("Not a Jarvis cyber ATO license")
    if payload.get("v") != 1:
        raise AtoError("Unsupported ATO version")
    law_enforcement = bool(payload.get("law_enforcement"))
    blue_team = bool(payload.get("blue_team"))
    red_team = bool(payload.get("red_team"))
    if red_team and not law_enforcement:
        raise AtoError("Red team ATO requires the law-enforcement flag")
    if not blue_team and not red_team:
        raise AtoError("ATO must grant Blue team, Red team, or both")
    if not payload.get("in_person_verified"):
        raise AtoError("ATO must be marked in-person verified")
    for field in ("license_id", "issued_at", "not_before", "expires_at", "renew_by"):
        if not str(payload.get(field) or "").strip():
            raise AtoError(f"ATO is missing {field}")
    return {
        "v": 1,
        "kind": KIND,
        "license_id": str(payload["license_id"]).strip(),
        "in_person_verified": True,
        "law_enforcement": law_enforcement,
        "blue_team": blue_team,
        "red_team": red_team,
        "issued_at": str(payload["issued_at"]),
        "not_before": str(payload["not_before"]),
        "expires_at": str(payload["expires_at"]),
        "renew_by": str(payload["renew_by"]),
        "case_ref": str(payload.get("case_ref") or "").strip(),
    }


def sign_license(payload: dict[str, Any], private_key: Ed25519PrivateKey) -> dict[str, Any]:
    cleaned = _validate_payload(payload)
    signature = private_key.sign(_canonical(cleaned))
    public = private_key.public_key().public_bytes_raw()
    return {
        "payload": cleaned,
        "signature": signature.hex(),
        "public_key": public.hex(),
    }


def verify_license(document: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(document, dict):
        raise AtoError("License must be a JSON object")
    payload = _validate_payload(document.get("payload") or {})
    public = load_public_key()
    if public is None:
        raise AtoError("This Jarvis has no ATO issuer public key yet. Issue a license on this Leader first.")
    try:
        signature = bytes.fromhex(str(document.get("signature") or ""))
        public.verify(signature, _canonical(payload))
    except Exception as exc:
        raise AtoError("ATO signature is not valid for this Leader") from exc
    embedded = str(document.get("public_key") or "").strip()
    if embedded:
        expected = public.public_bytes_raw().hex()
        if embedded.lower() != expected.lower():
            raise AtoError("ATO public key does not match this Leader")
    return payload


def issue_license(
    *,
    law_enforcement: bool,
    blue_team: bool = True,
    red_team: bool = False,
    valid_days: int = 90,
    renew_in_days: int | None = None,
    case_ref: str = "",
    install: bool = False,
) -> dict[str, Any]:
    if valid_days < 1 or valid_days > 3660:
        raise AtoError("valid_days must be between 1 and 3660")
    renew_days = valid_days if renew_in_days is None else int(renew_in_days)
    if renew_days < 1 or renew_days > valid_days:
        raise AtoError("renew_in_days must be between 1 and valid_days")
    now = _utcnow()
    payload = {
        "v": 1,
        "kind": KIND,
        "license_id": str(uuid.uuid4()),
        "in_person_verified": True,
        "law_enforcement": bool(law_enforcement),
        "blue_team": bool(blue_team),
        "red_team": bool(red_team),
        "issued_at": _iso(now),
        "not_before": _iso(now),
        "expires_at": _iso(now + timedelta(days=valid_days)),
        "renew_by": _iso(now + timedelta(days=renew_days)),
        "case_ref": (case_ref or "").strip(),
    }
    with _LOCK:
        private, _public = load_or_create_issuer()
        document = sign_license(payload, private)
        _audit(
            "issued",
            license_id=payload["license_id"],
            law_enforcement=payload["law_enforcement"],
            blue_team=payload["blue_team"],
            red_team=payload["red_team"],
            expires_at=payload["expires_at"],
            renew_by=payload["renew_by"],
        )
        if install:
            _store_license_unlocked(document)
    return document


def _store_license_unlocked(document: dict[str, Any]) -> dict[str, Any]:
    payload = verify_license(document)
    path = license_path()
    temp = path.with_suffix(path.suffix + ".tmp")
    temp.write_text(json.dumps(document, indent=2) + "\n", encoding="utf-8")
    os.replace(temp, path)
    _audit("installed", license_id=payload["license_id"])
    return document


def install_license(document: dict[str, Any]) -> dict[str, Any]:
    with _LOCK:
        return _store_license_unlocked(document)


def load_installed() -> dict[str, Any] | None:
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
        path = license_path()
        if path.is_file():
            path.unlink()
            _audit("revoked")


def renew_license(*, valid_days: int = 90, renew_in_days: int | None = None, install: bool = True) -> dict[str, Any]:
    current = load_installed()
    if not current:
        raise AtoError("No ATO license is installed to renew")
    payload = verify_license(current)
    return issue_license(
        law_enforcement=bool(payload["law_enforcement"]),
        blue_team=bool(payload["blue_team"]),
        red_team=bool(payload["red_team"]),
        valid_days=valid_days,
        renew_in_days=renew_in_days,
        case_ref=str(payload.get("case_ref") or ""),
        install=install,
    )


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
        }


def evaluate() -> AtoStatus:
    can_issue = has_issuer()
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
    now = _utcnow()
    try:
        not_before = _parse_iso(str(payload["not_before"]))
        expires_at = _parse_iso(str(payload["expires_at"]))
        renew_by = _parse_iso(str(payload["renew_by"]))
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
            reason="ATO dates are not valid ISO timestamps",
        )
    expired = now >= expires_at
    too_early = now < not_before
    renewal_due = now >= renew_by
    if too_early:
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
        expired=expired,
        renewal_due=renewal_due,
        can_issue=can_issue,
        license_id=str(payload["license_id"]),
        expires_at=_iso(expires_at),
        renew_by=_iso(renew_by),
        case_ref=str(payload.get("case_ref") or ""),
        reason=reason,
    )


def role_allowed(role: str) -> bool:
    key = (role or "").strip().lower().replace("_", "-")
    if key in {"blue", "soc", "dfir"}:
        key = "blue-team"
    elif key in {"red", "pentest"}:
        key = "red-team"
    status = evaluate()
    if not status.valid:
        return False
    if key == "blue-team":
        return bool(status.blue_team)
    if key == "red-team":
        return bool(status.red_team and status.law_enforcement)
    return False


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

    sub.add_parser("status", help="Show installed ATO status")
    install = sub.add_parser("install", help="Install a signed license file")
    install.add_argument("path", help="Path to signed license JSON")
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
