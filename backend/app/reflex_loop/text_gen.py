"""TYPE_TEXT path: smallest qualified text generator + bounded-string validation.

Ordinary form navigation only invokes generation here — never for CLICK/SELECT/etc.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Awaitable
import re

# Hard bounds for typed payload — fail closed if violated.
DEFAULT_MAX_CHARS = 500
DEFAULT_MIN_CHARS = 0

# Reject payloads that look like selectors, JS, shell, or coordinate dumps.
_FORBIDDEN_PATTERNS = (
    re.compile(r"^\s*document\.", re.I),
    re.compile(r"^\s*javascript:", re.I),
    re.compile(r"<script\b", re.I),
    re.compile(r"^\s*\$\(", re.I),
    re.compile(r"^\s*#\w+\s*>", re.I),  # css child selector lookalike as sole payload
    re.compile(r"^\s*//", re.I),
    re.compile(r"^\s*cmd\.exe\b", re.I),
    re.compile(r"^\s*powershell\b", re.I),
    re.compile(r"^\s*/bin/(ba)?sh\b", re.I),
)


@dataclass(frozen=True)
class TypedTextValidation:
    ok: bool
    text: str = ""
    reason: str = ""


def validate_typed_text(
    raw: str | None,
    *,
    max_chars: int = DEFAULT_MAX_CHARS,
    min_chars: int = DEFAULT_MIN_CHARS,
    allow_empty: bool = False,
) -> TypedTextValidation:
    if raw is None:
        return TypedTextValidation(False, reason="text generator returned None")
    if not isinstance(raw, str):
        return TypedTextValidation(False, reason=f"text must be str, got {type(raw).__name__}")
    text = raw.strip("\x00")
    if "\x00" in raw:
        return TypedTextValidation(False, reason="NUL byte in typed text")
    if not allow_empty and not text.strip():
        return TypedTextValidation(False, reason="empty typed text refused")
    if len(text) < min_chars:
        return TypedTextValidation(False, reason=f"text shorter than min_chars={min_chars}")
    if len(text) > max_chars:
        return TypedTextValidation(False, reason=f"text exceeds max_chars={max_chars} (got {len(text)})")
    for pattern in _FORBIDDEN_PATTERNS:
        if pattern.search(text):
            return TypedTextValidation(False, reason=f"typed text matches forbidden pattern {pattern.pattern}")
    # Reject pure coordinate pairs that models sometimes emit instead of text.
    if re.fullmatch(r"\s*\d{1,5}\s*,\s*\d{1,5}\s*", text):
        return TypedTextValidation(False, reason="typed text looks like coordinates")
    return TypedTextValidation(True, text=text)


TextGenerator = Callable[[str, dict[str, Any]], Awaitable[str] | str]


async def generate_bounded_text(
    goal: str,
    *,
    field_name: str,
    hint: str = "",
    generator: TextGenerator | None = None,
    max_chars: int = DEFAULT_MAX_CHARS,
) -> TypedTextValidation:
    """Invoke the smallest qualified generator only for TYPE_TEXT.

    Without an injected generator, uses the hint or a deterministic extract from
    the goal (quoted string). Never invents selectors/JS.
    """
    prompt_state = {"field_name": field_name, "hint": hint, "goal": goal, "max_chars": max_chars}
    raw: str | None = None
    if generator is not None:
        result = generator(goal, prompt_state)
        if hasattr(result, "__await__"):
            raw = await result  # type: ignore[misc]
        else:
            raw = str(result)
    elif hint.strip():
        raw = hint.strip()
    else:
        raw = _extract_quoted(goal) or _extract_after_type(goal)
        if raw is None:
            return TypedTextValidation(
                False,
                reason=(
                    "TYPE_TEXT requires a text generator, hint, or quoted string in the goal; "
                    "refusing to invent payload"
                ),
            )
    return validate_typed_text(raw, max_chars=max_chars)


def _extract_quoted(goal: str) -> str | None:
    match = re.search(r"[\"']([^\"']{1,500})[\"']", goal or "")
    return match.group(1) if match else None


def _extract_after_type(goal: str) -> str | None:
    # Require an explicit type/enter/write verb with a delimited or clearly bounded payload.
    # Vague goals like "fill the form somehow" must refuse rather than invent text.
    match = re.search(
        r"\b(?:type|enter|write)\s+[\"']([^\"']{1,500})[\"']",
        goal or "",
        re.I,
    )
    if match:
        return match.group(1).strip() or None
    match = re.search(
        r"\b(?:type|enter|write)\s+(?:the\s+text\s+)?([A-Za-z0-9._%+\-@]{1,200})\b",
        goal or "",
        re.I,
    )
    if not match:
        return None
    value = match.group(1).strip().rstrip(".")
    if value.lower() in {"the", "a", "an", "into", "in", "text", "something", "somehow"}:
        return None
    return value or None
