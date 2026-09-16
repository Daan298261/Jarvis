from __future__ import annotations

import re
from typing import Any

_THINK_BLOCK_RE = re.compile(r"<think>.*?</think>", re.DOTALL | re.IGNORECASE)
_REASONING_KEYS = (
    "reasoning_content",
    "reasoning",
    "thinking",
    "reasoning_text",
    "reasoningContent",
    "thinking_content",
)
_REASONING_PART_TYPES = {"reasoning", "thinking", "thought", "reasoning_content"}

EMPTY_GENERATION_ERROR = (
    "The model returned no text. This often happens when a reasoning model "
    "fills max_tokens with hidden thinking and leaves the answer empty. "
    "Load a ready model or try again."
)


def _as_dict(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    if value is None:
        return {}
    dump = getattr(value, "model_dump", None)
    if callable(dump):
        try:
            payload = dump(exclude_none=True)
        except TypeError:
            payload = dump()
        if isinstance(payload, dict):
            extra = getattr(value, "model_extra", None)
            if isinstance(extra, dict):
                return {**payload, **extra}
            return payload
    extra = getattr(value, "model_extra", None)
    if isinstance(extra, dict):
        return dict(extra)
    return {}


def _part_text(part: Any) -> tuple[str, bool]:
    if isinstance(part, str):
        return part, False
    payload = _as_dict(part)
    ptype = str(payload.get("type") or "").strip().lower()
    text = payload.get("text")
    if text is None:
        text = payload.get("content")
    if text is None:
        text = payload.get("reasoning") or payload.get("reasoning_content") or ""
    if not isinstance(text, str):
        text = str(text) if text else ""
    return text, ptype in _REASONING_PART_TYPES


def _stringify(value: Any, *, include_reasoning: bool) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    if isinstance(value, list):
        parts: list[str] = []
        for item in value:
            text, is_reasoning = _part_text(item)
            if text and (include_reasoning or not is_reasoning):
                parts.append(text)
        return "".join(parts)
    payload = _as_dict(value)
    if payload:
        direct = payload.get("content")
        if isinstance(direct, str) and not include_reasoning:
            return direct
        if isinstance(direct, list):
            return _stringify(direct, include_reasoning=include_reasoning)
        if include_reasoning:
            for key in _REASONING_KEYS:
                raw = payload.get(key)
                if isinstance(raw, str) and raw.strip():
                    return raw
    return str(value) if value else ""


def strip_think_blocks(text: str) -> str:
    cleaned = _THINK_BLOCK_RE.sub("", text or "")
    return re.sub(r"\n{3,}", "\n\n", cleaned).strip()


def reasoning_text_from_payload(payload: dict[str, Any] | None) -> str:
    if not payload:
        return ""
    for key in _REASONING_KEYS:
        raw = payload.get(key)
        if isinstance(raw, str) and raw.strip():
            return raw
        if isinstance(raw, list):
            joined = _stringify(raw, include_reasoning=True)
            if joined.strip():
                return joined
    content = payload.get("content")
    if isinstance(content, list):
        parts = [_part_text(item) for item in content]
        reasoning = "".join(text for text, is_reasoning in parts if is_reasoning and text)
        if reasoning.strip():
            return reasoning
    return ""


def content_text_from_payload(payload: dict[str, Any] | None) -> str:
    if not payload:
        return ""
    return _stringify(payload.get("content"), include_reasoning=False)


def message_payload_from_openai(message: Any, raw: dict[str, Any] | None = None) -> dict[str, Any]:
    dumped = _as_dict(message)
    extra = getattr(message, "model_extra", None)
    merged: dict[str, Any] = {}
    if isinstance(raw, dict):
        choices = raw.get("choices") or []
        if choices and isinstance(choices[0], dict):
            choice_message = choices[0].get("message") or {}
            if isinstance(choice_message, dict):
                merged.update(choice_message)
    merged.update(dumped)
    if isinstance(extra, dict):
        merged.update(extra)
    if message is not None and "content" not in merged:
        content = getattr(message, "content", None)
        if content is not None:
            merged["content"] = content
    return merged


def visible_completion_text(content: Any, reasoning: Any = None) -> str:
    """Prefer the public answer channel; use thinking/reasoning text if that is all we got."""
    main = strip_think_blocks(_stringify(content, include_reasoning=False))
    if main:
        return main
    mixed = strip_think_blocks(_stringify(content, include_reasoning=True))
    if mixed:
        return mixed
    reason_raw = _stringify(reasoning, include_reasoning=True)
    reason_stripped = strip_think_blocks(reason_raw)
    if reason_stripped:
        return reason_stripped
    return (reason_raw or "").strip()


def empty_generation_error(finish_reason: str | None = None) -> str:
    reason = (finish_reason or "").strip()
    if reason:
        return f"{EMPTY_GENERATION_ERROR} (finish_reason={reason})"
    return EMPTY_GENERATION_ERROR


def delta_text_channels(delta: Any) -> tuple[str, str]:
    payload = _as_dict(delta)
    extra = getattr(delta, "model_extra", None)
    if isinstance(extra, dict):
        payload = {**payload, **extra}
    content = _stringify(payload.get("content"), include_reasoning=False)
    if not content:
        content = getattr(delta, "content", None) or ""
        if not isinstance(content, str):
            content = _stringify(content, include_reasoning=False)
    reasoning = reasoning_text_from_payload(payload)
    if not reasoning:
        reasoning = getattr(delta, "reasoning_content", None) or getattr(delta, "reasoning", None) or ""
        if not isinstance(reasoning, str):
            reasoning = _stringify(reasoning, include_reasoning=True)
    return str(content or ""), str(reasoning or "")
