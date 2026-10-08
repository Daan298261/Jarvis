"""Owner instructions that must win over a model's tool habit."""

from __future__ import annotations

import re
from typing import Any

_REPLY_ONLY_RE = re.compile(
    r"(?i)^\s*(?:please\s+)?(?:just\s+)?"
    r"(?:say|reply|respond|answer)"
    r"(?:\s+only|\s+with|\s+me|\s+the\s+word)\b"
)
_SHORT_SAY_RE = re.compile(r"(?i)^(?:please\s+)?(?:just\s+)?say\s+\S")

_FORBID_FILE_WRITES_RE = re.compile(
    r"(?i)(?:"
    r"do not write (?:a |any |the )?(?:file|files|script|to disk|to the desktop)"
    r"|don't write (?:a |any |the )?(?:file|files|script|to disk|to the desktop)"
    r"|do not (?:save|create) (?:a |any |the )?(?:file|files)"
    r"|don't (?:save|create) (?:a |any |the )?(?:file|files)"
    r"|only return (?:the |me )?(?:code|script|text|answer)"
    r"|just return (?:the |me )?(?:code|script|text|answer)"
    r"|return only (?:the )?(?:code|script|text|answer)"
    r"|do not write (?:anything )?to (?:disk|the desktop|a file)"
    r"|no file writes?"
    r"|without (?:writing|saving|creating) (?:a |any )?(?:file|files)"
    r")"
)

_MUTATING_FILESYSTEM = frozenset(
    {"write", "edit", "append", "move", "copy", "delete", "mkdir", "extract", "restore", "rename"}
)
_MUTATING_OFFICE = frozenset({"create", "append", "save_as", "write"})


def is_reply_only_request(text: str) -> bool:
    """The owner asked for words back, not for a tool to run."""
    raw = (text or "").strip()
    if not raw or len(raw) > 240:
        return False
    if _REPLY_ONLY_RE.search(raw):
        return True
    return len(raw) <= 80 and bool(_SHORT_SAY_RE.match(raw))


def owner_forbids_file_writes(text: str) -> bool:
    """True when the owner said to answer in chat and not create a file."""
    return bool(_FORBID_FILE_WRITES_RE.search(text or ""))


def tool_write_denied(name: str, arguments: dict[str, Any] | None, prompt: str) -> str | None:
    """Block a mutating tool when the owner forbade file writes."""
    if not owner_forbids_file_writes(prompt):
        return None
    action = str((arguments or {}).get("action") or "").strip().lower()
    tool = (name or "").strip().lower()
    blocked = False
    if tool == "filesystem" and action in _MUTATING_FILESYSTEM:
        blocked = True
    elif tool == "office" and action in _MUTATING_OFFICE:
        blocked = True
    elif tool in {"python", "terminal"}:
        blocked = True
    if not blocked:
        return None
    return (
        "ERROR: The owner asked for the answer in chat and forbade writing a file. "
        f"Refused {tool or 'tool'}"
        + (f" action {action}." if action else ".")
        + " Return the result in the reply. Do not create or edit a file."
    )
