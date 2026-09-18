"""Fit llama.cpp / LM Studio keep-tokens to the *loaded* context window.

llama.cpp rejects a request when the tokens it would pin from the initial
prompt are at least as large as the live slot (`n_keep >= n_ctx`). Jarvis
used to size that keep-prefix from a profile or recovered conversation
(16k/32k) while the active GGUF was loaded at 4k.
"""

from __future__ import annotations

import json
import re
from typing import Any

# Conservative chars/token — matches fit_messages_to_context.
CHARS_PER_TOKEN = 2
# Durable blobs (tools, recovered context, skills) must not become n_keep.
# Pin only a short identity prefix so llama.cpp can drop the rest on shift.
MAX_KEEP_TOKENS = 768
MAX_KEEP_FRACTION = 0.22
_KEEP_DROP_MARKERS = (
    "Compacted earlier task memory:",
    "Compact working state:",
    "Tool exposure:",
    "On-demand skills:",
    "Recalled similar earlier tasks",
    "Live briefing",
    "[Look up dropped context",
)

_N_KEEP_OVERFLOW = re.compile(
    r"n_keep:\s*(\d+)\s*>=\s*n_ctx:\s*(\d+)",
    re.IGNORECASE,
)

_LOADED_KEYS = (
    "n_ctx",
    "ctx_size",
    "context_size",
    "loaded_context_length",
    "runtime_context_length",
)
_GENERIC_KEYS = (
    "context_length",
    "max_model_len",
    "context_window",
    "max_seq_len",
)
_MAX_KEYS = (
    "max_context_length",
    "max_context",
)
_INSTANCE_KEYS = ("loaded_instances", "instances", "loaded")
_NEST_KEYS = (
    "default_generation_settings",
    "generation_settings",
    "params",
    "parameters",
    "meta",
    "settings",
    "model_info",
)


def _positive_int(value: Any) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int) and value > 0:
        return value
    if isinstance(value, float) and value > 0:
        return int(value)
    if isinstance(value, str) and value.strip().isdigit():
        parsed = int(value.strip())
        return parsed if parsed > 0 else None
    return None


def _first_key(payload: dict[str, Any], keys: tuple[str, ...]) -> int | None:
    for key in keys:
        found = _positive_int(payload.get(key))
        if found:
            return found
    return None


def extract_loaded_n_ctx(payload: Any) -> int | None:
    """Return the *loaded* context window, not the model's theoretical max.

    LM Studio advertises `max_context_length` of 32k+ while the running
    instance may be 4096. llama.cpp `/props` reports the live slot as `n_ctx`.
    """
    found, _used_max = _extract_n_ctx(payload, allow_max=True)
    return found


def _extract_n_ctx(payload: Any, *, allow_max: bool) -> tuple[int | None, bool]:
    if payload is None:
        return None, False
    if isinstance(payload, (int, float, str)):
        return _positive_int(payload), False
    if isinstance(payload, list):
        fallback: int | None = None
        fallback_is_max = False
        for item in payload:
            found, used_max = _extract_n_ctx(item, allow_max=allow_max)
            if found and not used_max:
                return found, False
            if found and fallback is None:
                fallback, fallback_is_max = found, used_max
        return fallback, fallback_is_max
    if not isinstance(payload, dict):
        return None, False

    for key in _INSTANCE_KEYS:
        nested = payload.get(key)
        if nested:
            found, used_max = _extract_n_ctx(nested, allow_max=False)
            if found:
                return found, used_max

    for key in _NEST_KEYS:
        nested = payload.get(key)
        if isinstance(nested, (dict, list)):
            found, used_max = _extract_n_ctx(nested, allow_max=allow_max)
            if found and not used_max:
                return found, False
            if found:
                return found, used_max

    loaded = _first_key(payload, _LOADED_KEYS)
    if loaded:
        return loaded, False
    generic = _first_key(payload, _GENERIC_KEYS)
    if generic:
        return generic, False

    for key in ("data", "models"):
        nested = payload.get(key)
        if isinstance(nested, list):
            found, used_max = _extract_n_ctx(nested, allow_max=allow_max)
            if found:
                return found, used_max

    if allow_max:
        maximum = _first_key(payload, _MAX_KEYS)
        if maximum:
            return maximum, True
    return None, False


def generation_headroom(n_ctx: int, max_tokens: int | None) -> int:
    """Tokens that must stay free so n_keep + generation still fit in n_ctx."""
    limit = int(n_ctx or 0)
    if limit <= 1:
        return 1
    requested = int(max_tokens or 0)
    reserved = max(64, min(requested or 256, max(64, limit // 2)))
    # llama.cpp's check is `n_keep >= n_ctx`, so leave at least one token.
    return min(limit - 1, reserved + 1)


def max_stable_keep_tokens(n_ctx: int) -> int:
    """Upper bound for the KV keep-prefix: identity only, never the catalog."""
    limit = int(n_ctx or 0)
    if limit <= 1:
        return 0
    return max(1, min(MAX_KEEP_TOKENS, int(limit * MAX_KEEP_FRACTION)))


def clamp_n_keep(n_keep: int, n_ctx: int, *, max_tokens: int | None = None) -> int:
    """Force n_keep strictly below n_ctx with room for the completion."""
    limit = int(n_ctx or 0)
    if limit <= 1:
        return 0
    ceiling = min(
        limit - generation_headroom(limit, max_tokens),
        max_stable_keep_tokens(limit),
    )
    return max(0, min(int(n_keep), ceiling))


def estimate_text_tokens(text: str) -> int:
    if not text:
        return 0
    return max(1, (len(text) + CHARS_PER_TOKEN - 1) // CHARS_PER_TOKEN)


def _message_content(message: Any) -> str:
    content = getattr(message, "content", None)
    if content is None and isinstance(message, dict):
        content = message.get("content")
    if isinstance(content, str):
        return content
    if content is not None:
        return json.dumps(content, ensure_ascii=False)
    return ""


def stable_keep_prefix(messages: list[Any], *, identity_text: str | None = None) -> str:
    """Leading identity only. Recovered context, tools, and skills are not kept.

    llama.cpp n_keep pins the first N tokens of the serialized prompt. Putting
    the durable blob there both 400s on 4k slots and prevents on-demand lookup.
    """
    identity = (identity_text or "").strip()
    system = ""
    for message in messages:
        role = getattr(message, "role", None)
        if role is None and isinstance(message, dict):
            role = message.get("role")
        if role != "system":
            continue
        system = _message_content(message).strip()
        break
    if identity and system.startswith(identity):
        prefix = identity
    elif identity and identity in system[: max(len(identity) * 2, 64)]:
        prefix = identity
    else:
        prefix = system
        for marker in _KEEP_DROP_MARKERS:
            idx = prefix.find(marker)
            if idx > 0:
                prefix = prefix[:idx].rstrip()
                break
    cap_chars = MAX_KEEP_TOKENS * CHARS_PER_TOKEN
    if len(prefix) > cap_chars:
        prefix = prefix[:cap_chars].rstrip()
    return prefix


def n_keep_for_messages(
    messages: list[Any],
    n_ctx: int,
    *,
    max_tokens: int | None = None,
    identity_text: str | None = None,
) -> int:
    """Keep only the stable identity prefix, never the full recovered blob."""
    prefix = stable_keep_prefix(messages, identity_text=identity_text)
    estimated = estimate_text_tokens(prefix) if prefix else 0
    return clamp_n_keep(estimated, n_ctx, max_tokens=max_tokens)


def parse_n_keep_overflow(detail: Any) -> tuple[int, int] | None:
    """Parse llama.cpp's n_keep >= n_ctx 400 body. Returns (n_keep, n_ctx)."""
    text = _error_text(detail)
    match = _N_KEEP_OVERFLOW.search(text)
    if not match:
        return None
    return int(match.group(1)), int(match.group(2))


def is_n_keep_overflow(detail: Any) -> bool:
    return parse_n_keep_overflow(detail) is not None


def n_keep_overflow_message(n_keep: int, n_ctx: int) -> str:
    return (
        f"Prompt keep tokens exceed the loaded model context "
        f"(n_keep: {n_keep} >= n_ctx: {n_ctx}). "
        "Load the model with a larger context length, or shorten the system prompt and history."
    )


def _error_text(detail: Any) -> str:
    if detail is None:
        return ""
    if isinstance(detail, str):
        return detail
    if isinstance(detail, dict):
        parts = [json.dumps(detail, ensure_ascii=False)]
        err = detail.get("error")
        if isinstance(err, dict):
            parts.append(str(err.get("message") or ""))
        elif err is not None:
            parts.append(str(err))
        for key in ("message", "detail"):
            if detail.get(key):
                parts.append(str(detail.get(key)))
        return " ".join(parts)
    return str(detail)
