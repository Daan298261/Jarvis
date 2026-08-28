from __future__ import annotations

import re
from typing import Any

_SECRET_KEY_RE = re.compile(
    r"(password|passwd|secret|token|api[_-]?key|credential|auth|bearer|private[_-]?key)",
    re.I,
)
_BEARER_RE = re.compile(r"Bearer\s+[A-Za-z0-9._~+/=-]+", re.I)
_AWS_KEY_RE = re.compile(r"AKIA[0-9A-Z]{16}")
_GH_TOKEN_RE = re.compile(r"ghp_[A-Za-z0-9]{20,}")
_SK_PREFIX_RE = re.compile(r"\bsk-[A-Za-z0-9]{20,}\b")
_REDACTED = "[REDACTED]"


def _is_secret_key(key: str) -> bool:
    return bool(_SECRET_KEY_RE.search(key))


def redact_string(value: str) -> str:
    if not value:
        return value
    text = _BEARER_RE.sub(f"Bearer {_REDACTED}", value)
    text = _AWS_KEY_RE.sub(_REDACTED, text)
    text = _GH_TOKEN_RE.sub(_REDACTED, text)
    text = _SK_PREFIX_RE.sub(_REDACTED, text)
    return text


def redact_value(value: Any) -> Any:
    if isinstance(value, str):
        return redact_string(value)
    if isinstance(value, dict):
        return redact_mapping(value)
    if isinstance(value, list):
        return [redact_value(item) for item in value]
    return value


def redact_mapping(mapping: dict[str, Any]) -> dict[str, Any]:
    cleaned: dict[str, Any] = {}
    for key, value in mapping.items():
        if _is_secret_key(str(key)):
            cleaned[key] = _REDACTED
        else:
            cleaned[key] = redact_value(value)
    return cleaned


def redact_trajectory_payload(payload: dict[str, Any]) -> dict[str, Any]:
    """Redact secrets from a trajectory dict before persistence."""
    return redact_mapping(payload)
