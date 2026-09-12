from __future__ import annotations

import hashlib
import re

_SENSITIVE = re.compile(
    r"(?i)\b(delete|remove|erase|destroy|format|wipe|password|secret|token|privacy|"
    r"security|breach|hacked|danger|emergency|hurt|medical|money|payment|bank|failed|error)\b"
)

_NEUTRAL = (
    "On it.",
    "I'll check that now.",
    "I'll take a look.",
)

_LOW_STAKES = (
    "On it.",
    "I'll take a look. Let's see what the machine is hiding.",
    "Consider it under inspection.",
    "I'll check that now. Mystery is rarely a feature.",
)


def task_acknowledgement(prompt: str) -> str:
    """Return a fast, truthful acknowledgement without waiting for inference."""
    cleaned = (prompt or "").strip()
    choices = _NEUTRAL if _SENSITIVE.search(cleaned) else _LOW_STAKES
    digest = hashlib.blake2s(cleaned.encode("utf-8"), digest_size=2).digest()
    return choices[int.from_bytes(digest, "big") % len(choices)]
