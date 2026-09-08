from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import threading
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any

from ..config import data_dir
from .runtime_profiles import RuntimeProfile, list_runtime_profiles

_GATE_FILE = "security-model-gates.json"
_LOCK = threading.RLock()
_SCRYPT_N = 1 << 14
_SCRYPT_R = 8
_SCRYPT_P = 1
_DKLEN = 32
_MIN_PASSWORD_LENGTH = 10

ROLE_ALIASES = {
    "blue": "blue-team",
    "blue-team": "blue-team",
    "soc": "blue-team",
    "dfir": "blue-team",
    "red": "red-team",
    "red-team": "red-team",
    "pentest": "red-team",
}

ROLE_PROFILES = {
    "blue-team": ("redsage-8b", "imperum-cyber"),
    "red-team": ("deephat-7b",),
}


@dataclass(frozen=True)
class GateStatus:
    role: str
    configured: bool
    enabled: bool

    def as_dict(self) -> dict[str, Any]:
        return {
            "role": self.role,
            "configured": self.configured,
            "enabled": self.enabled,
        }


def normalize_gate_role(role: str) -> str:
    key = (role or "").strip().lower().replace("_", "-")
    normalized = ROLE_ALIASES.get(key)
    if normalized is None:
        raise KeyError(f"unsupported security gate role: {role}")
    return normalized


def security_gates_path() -> Path:
    path = data_dir() / _GATE_FILE
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


def _empty_store() -> dict[str, Any]:
    return {"version": 1, "roles": {}}


def _load_store_unlocked() -> dict[str, Any]:
    path = security_gates_path()
    if not path.exists():
        return _empty_store()
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return _empty_store()
    if not isinstance(raw, dict):
        return _empty_store()
    roles = raw.get("roles")
    if not isinstance(roles, dict):
        roles = {}
    return {"version": 1, "roles": roles}


def _save_store_unlocked(store: dict[str, Any]) -> None:
    path = security_gates_path()
    temp = path.with_suffix(path.suffix + ".tmp")
    temp.write_text(json.dumps(store, indent=2), encoding="utf-8")
    os.replace(temp, path)


def _derive(password: str, salt: bytes) -> bytes:
    return hashlib.scrypt(
        password.encode("utf-8"),
        salt=salt,
        n=_SCRYPT_N,
        r=_SCRYPT_R,
        p=_SCRYPT_P,
        dklen=_DKLEN,
    )


def _new_password_record(password: str, *, enabled: bool) -> dict[str, Any]:
    if len(password) < _MIN_PASSWORD_LENGTH:
        raise ValueError(f"password must be at least {_MIN_PASSWORD_LENGTH} characters")
    salt = os.urandom(16)
    digest = _derive(password, salt)
    return {
        "kdf": "scrypt",
        "salt": base64.b64encode(salt).decode("ascii"),
        "digest": base64.b64encode(digest).decode("ascii"),
        "enabled": bool(enabled),
    }


def _verify_record(record: dict[str, Any], password: str) -> bool:
    if record.get("kdf") != "scrypt":
        return False
    try:
        salt = base64.b64decode(str(record["salt"]), validate=True)
        expected = base64.b64decode(str(record["digest"]), validate=True)
    except (KeyError, ValueError, TypeError):
        return False
    actual = _derive(password, salt)
    return hmac.compare_digest(actual, expected)


def get_gate_status(role: str) -> GateStatus:
    normalized = normalize_gate_role(role)
    with _LOCK:
        store = _load_store_unlocked()
        record = store["roles"].get(normalized)
        if not isinstance(record, dict):
            return GateStatus(role=normalized, configured=False, enabled=False)
        return GateStatus(
            role=normalized,
            configured=bool(record.get("digest")),
            enabled=bool(record.get("enabled", False)),
        )


def list_gate_statuses() -> list[GateStatus]:
    return [get_gate_status(role) for role in ("blue-team", "red-team")]


def set_gate_password(
    role: str,
    *,
    new_password: str,
    current_password: str | None = None,
    enable: bool | None = None,
) -> GateStatus:
    normalized = normalize_gate_role(role)
    with _LOCK:
        store = _load_store_unlocked()
        existing = store["roles"].get(normalized)
        if isinstance(existing, dict) and existing.get("digest"):
            if current_password is None or not _verify_record(existing, current_password):
                raise PermissionError("current password is invalid")
            target_enabled = bool(existing.get("enabled", False)) if enable is None else bool(enable)
        else:
            target_enabled = False if enable is None else bool(enable)

        store["roles"][normalized] = _new_password_record(
            new_password,
            enabled=target_enabled,
        )
        _save_store_unlocked(store)
        return GateStatus(normalized, configured=True, enabled=target_enabled)


def unlock_gate(role: str, password: str) -> GateStatus:
    normalized = normalize_gate_role(role)
    with _LOCK:
        store = _load_store_unlocked()
        record = store["roles"].get(normalized)
        if not isinstance(record, dict) or not record.get("digest"):
            raise RuntimeError("security gate password has not been configured")
        if not _verify_record(record, password):
            raise PermissionError("invalid password")
        record["enabled"] = True
        store["roles"][normalized] = record
        _save_store_unlocked(store)
        return GateStatus(normalized, configured=True, enabled=True)


def lock_gate(role: str) -> GateStatus:
    normalized = normalize_gate_role(role)
    with _LOCK:
        store = _load_store_unlocked()
        record = store["roles"].get(normalized)
        if not isinstance(record, dict):
            record = {"enabled": False}
        else:
            record["enabled"] = False
        store["roles"][normalized] = record
        _save_store_unlocked(store)
        return GateStatus(
            normalized,
            configured=bool(record.get("digest")),
            enabled=False,
        )


def gate_is_enabled(role: str) -> bool:
    return get_gate_status(role).enabled


def authorized_runtime_profiles(role: str) -> list[RuntimeProfile]:
    """Return a routing catalog with only the authorized role's templates activated.

    Persistent role enablement deliberately does not mutate the generic runtime
    registry. This prevents `/route` or `force_profile` from bypassing the
    security-role API and selecting a security specialist merely because the
    operator unlocked it earlier.
    """
    normalized = normalize_gate_role(role)
    if not gate_is_enabled(normalized):
        raise PermissionError(f"{normalized} password gate is locked")
    allowed_names = set(ROLE_PROFILES[normalized])
    return [
        replace(profile, enabled=True) if profile.name in allowed_names else profile
        for profile in list_runtime_profiles()
    ]
