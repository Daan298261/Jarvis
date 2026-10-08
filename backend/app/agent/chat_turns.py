"""User-visible chat turns. Agent prompt may still store Follow-up: internally."""

from __future__ import annotations

from typing import Any

from ..providers.base import ChatMessage
from .compaction import deserialize_messages
from .prompts import (
    CONTINUE_PROMPT,
    CRITIC_PROMPT,
    EXPERT_CONSULT_PROMPT,
    PLAN_PROMPT,
    STOP_AND_REPORT,
    VERIFY_PROMPT,
    VERIFY_REQUIRED_PROMPT,
)

FOLLOW_UP_MARKER = "\n\nFollow-up: "
INTERNAL_AUDIENCE = "internal"

# Agent-only instructions. They stay in the model transcript as user-role
# turns so the model follows them, and they are stripped before the owner UI.
_INTERNAL_PREFIXES = tuple(
    item.strip()
    for item in (
        CONTINUE_PROMPT,
        PLAN_PROMPT,
        VERIFY_PROMPT,
        VERIFY_REQUIRED_PROMPT,
        STOP_AND_REPORT,
        CRITIC_PROMPT,
        EXPERT_CONSULT_PROMPT,
        "END STATE:",
        "ACCEPTANCE CRITERIA:",
        "The requested files or actions appear to already exist.",
        "Verification is required before completion.",
        "Perform a short independent verification pass.",
        "Critique the plan before doing more work.",
        "You are the Expert model.",
        "RFC-0120:",
        "RFC-0197:",
        "Reverse engineering requires a saved investigation report.",
    )
    if item and item.strip()
)


def internal_user_message(content: str) -> ChatMessage:
    """Model-visible instruction that the owner transcript must not call 'You'."""
    return ChatMessage(role="user", content=content, audience=INTERNAL_AUDIENCE)


def is_internal_instruction(text: str) -> bool:
    """True when the text is an agent instruction, not something the owner said."""
    raw = (text or "").strip()
    if not raw:
        return False
    for prefix in _INTERNAL_PREFIXES:
        if raw == prefix or raw.startswith(prefix):
            return True
    return False


def owner_visible_user_text(text: str) -> str:
    """Drop agent instructions that were stored on a user-role turn."""
    raw = strip_continue_wrapper(text)
    plan_mark = "\n\nFirst, without calling tools"
    if plan_mark in raw:
        raw = raw.split(plan_mark, 1)[0].strip()
    if is_internal_instruction(raw):
        return ""
    return raw


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
        if str(getattr(message, "audience", "") or "") == INTERNAL_AUDIENCE:
            continue
        raw = str(message.content or "")
        content = owner_visible_user_text(raw) if message.role == "user" else strip_continue_wrapper(raw)
        if not content:
            continue
        if message.role == "user" and is_internal_instruction(content):
            continue
        if turns and turns[-1]["role"] == message.role and turns[-1]["content"] == content:
            continue
        turns.append({"role": message.role, "content": content})
    from .front_responder import merge_consecutive_assistant_turns

    return merge_consecutive_assistant_turns(turns)


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
