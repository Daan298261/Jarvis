from __future__ import annotations

import re
from typing import Any

_SECRET_PATTERNS = [
    re.compile(r"(?i)authorization:\s*bearer\s+[^\s,;]+"),
    re.compile(r"(?i)(cookie|set-cookie|x-api-key|api[_-]?key|sessionid|csrftoken)\s*[:=]\s*[^\s,;]+"),
    re.compile(r"(?i)(password|passwd|secret|token|credential)\s*[:=]\s*[^\s,;]+"),
    re.compile(r"(?i)sessionid=[^;\s]+"),
    re.compile(r"(?i)csrftoken=[^;\s]+"),
    re.compile(r"(?i)bearer\s+[^\s,;]+"),
]


def redact_text(value: str) -> str:
    text = value or ""
    for pattern in _SECRET_PATTERNS:
        text = pattern.sub("[REDACTED]", text)
    return text


def redact_artifact(data: dict[str, Any]) -> dict[str, Any]:
    cleaned: dict[str, Any] = {}
    for key, value in data.items():
        if isinstance(value, str):
            cleaned[key] = redact_text(value)
        elif isinstance(value, list):
            cleaned[key] = [redact_text(str(item)) if isinstance(item, str) else item for item in value]
        elif isinstance(value, dict):
            cleaned[key] = redact_artifact(value)
        else:
            cleaned[key] = value
    return cleaned
