"""User-visible chat turns. Agent prompt may still store Follow-up: internally."""

from __future__ import annotations

from typing import Any

from ..providers.base import ChatMessage
from .compaction import deserialize_messages
from .prompts import CONTINUE_PROMPT

FOLLOW_UP_MARKER = "\n\nFollow-up: "


def strip_continue_wrapper(text: str) -> str:
    raw = (text or "").strip()
    marker = CONTINUE_PROMPT.strip()
    if raw.startswith(marker):
        rest = raw[len(marker) :].lstrip()
        return rest.strip()
    if raw.startswith("Continue the existing task."):
        split = raw.find("\n\n")
        if split >= 0:
            return raw[split + 2 :].strip()
        return ""
    return raw


def _from_messages(raw: str) -> list[dict[str, str]]:
    turns: list[dict[str, str]] = []
    try:
        messages: list[ChatMessage] = deserialize_messages(raw or "[]")
    except Exception:
        return turns
    for message in messages:
        if message.role not in {"user", "assistant"}:
            continue
        content = strip_continue_wrapper(str(message.content or ""))
        if not content:
            continue
        if turns and turns[-1]["role"] == message.role and turns[-1]["content"] == content:
            continue
        turns.append({"role": message.role, "content": content})
    return turns


def _from_prompt(prompt: str, result: str = "", error: str = "") -> list[dict[str, str]]:
    turns: list[dict[str, str]] = []
    blob = (prompt or "").strip()
    if blob:
        parts = blob.split(FOLLOW_UP_MARKER)
        for part in parts:
            text = part.strip()
            if text:
                turns.append({"role": "user", "content": text})
    reply = (result or error or "").strip()
    if reply:
        turns.append({"role": "assistant", "content": reply})
    return turns


def visible_chat_turns(
    prompt: str = "",
    conversation_json: str = "[]",
    result: str = "",
    error: str = "",
) -> list[dict[str, Any]]:
    turns = _from_messages(conversation_json)
    if turns:
        return turns
    return _from_prompt(prompt, result=result, error=error)
