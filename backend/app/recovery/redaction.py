from __future__ import annotations

import re
from copy import deepcopy
from typing import Any

_SECRET_KEY_RE = re.compile(
    r"(api[_-]?key|secret|password|token|credential|private[_-]?key|refresh[_-]?token|auth[_-]?token|oauth)",
    re.I,
)
_SENSITIVE_VALUE_HINTS = re.compile(r"(sk-[a-z0-9]{10,}|Bearer\s+[a-z0-9._-]+)", re.I)


def _is_secret_key(key: str) -> bool:
    lowered = key.lower()
    if _SECRET_KEY_RE.search(key):
        return True
    if lowered in {"auth_token", "inference_api_key", "private_key"}:
        return True
    return False


def redact_value(value: Any) -> Any:
    if isinstance(value, dict):
        return redact_mapping(value)
    if isinstance(value, list):
        return [redact_value(item) for item in value]
    if isinstance(value, str) and _SENSITIVE_VALUE_HINTS.search(value):
        return "[redacted]"
    return value


def redact_mapping(payload: dict[str, Any]) -> dict[str, Any]:
    cleaned: dict[str, Any] = {}
    for key, item in payload.items():
        if _is_secret_key(str(key)):
            cleaned[str(key)] = {"_ref": "redacted", "present": item is not None and str(item).strip() != ""}
            continue
        cleaned[str(key)] = redact_value(item)
    return cleaned


def redact_settings_control_plane(settings_dump: dict[str, Any]) -> dict[str, Any]:
    """Subset of settings safe to snapshot; secrets become metadata only."""
    allowed_top = {
        "autonomy",
        "execution_mode",
        "logging_level",
        "backup_enabled",
        "retry_limit",
        "default_timeout_seconds",
        "lan_access",
        "auth_required",
        "bind_host",
        "bind_port",
        "profile",
    }
    out: dict[str, Any] = {}
    for key in allowed_top:
        if key in settings_dump:
            out[key] = settings_dump[key]
    inference = settings_dump.get("inference")
    if isinstance(inference, dict):
        inf = {
            k: inference[k]
            for k in ("profile", "backend", "host", "port", "vision", "remote_model")
            if k in inference
        }
        if inference.get("api_key"):
            inf["api_key"] = {"_ref": "redacted", "present": True}
        out["inference"] = inf
    return out


def credential_reference_only(field: str, *, present: bool) -> dict[str, Any]:
    return {"_ref": "credential_metadata", "field": field, "present": present}
