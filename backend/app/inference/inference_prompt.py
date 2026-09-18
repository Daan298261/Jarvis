"""Strip UI-only reasoning/plan dumps before llama.cpp / OpenAI-compat inference.

Owner-facing chevrons and speak filters may retain thinking text in stored
transcripts. Those bytes must not enter the serialized chat template or n_keep
budget. Durable memory stays in Obsidian / DB — not re-stuffed here.
"""

from __future__ import annotations

import json
import re
from typing import Any

from ..agent.compaction import WORKING_STATE_MARKER
from ..providers.base import ChatMessage
from ..providers.completion_text import strip_think_blocks

_PLAN_BOARD_RE = re.compile(
    r"(?im)^\s*(?:PLAN|END STATE|ACCEPTANCE|WORKING STATE|THOUGHT PROCESS|SHOW WORK)\s*:.*$",
)
_REASONING_LINE_RE = re.compile(
    r"(?im)^\s*(?:reasoning|thought\s+process|internal\s+monologue|chain\s+of\s+thought)\s*:.*$",
)
_FINAL_REPLY_PREFIX_RE = re.compile(
    r"(?is)^\s*(?:final\s+(?:reply|answer)|assistant)\s*:\s*",
)


def _message_text(content: str | list[dict[str, Any]]) -> str:
    if isinstance(content, str):
        return content
    return json.dumps(content, ensure_ascii=False)


def strip_inference_only_lines(text: str) -> str:
    """Remove plan boards and labeled reasoning dumps from assistant-visible text."""
    if not text:
        return ""
    cleaned = text
    if WORKING_STATE_MARKER in cleaned:
        cleaned = cleaned.split(WORKING_STATE_MARKER, 1)[0]
    cleaned = _FINAL_REPLY_PREFIX_RE.sub("", cleaned)
    lines: list[str] = []
    for line in cleaned.splitlines():
        if _PLAN_BOARD_RE.match(line):
            continue
        if _REASONING_LINE_RE.match(line):
            continue
        lines.append(line)
    return "\n".join(lines).strip()


def inference_message_text(message: ChatMessage) -> str:
    """Text that should count toward prompt tokens and HTTP serialization."""
    raw = _message_text(message.content)
    raw = strip_think_blocks(raw, trim=False)
    if message.role == "assistant":
        raw = strip_inference_only_lines(raw)
    return raw


def sanitize_message_for_inference(message: ChatMessage) -> ChatMessage:
    """Drop reasoning channels; keep tool-call transcripts intact."""
    if message.role == "tool":
        return ChatMessage(
            role=message.role,
            content=message.content,
            name=message.name,
            tool_call_id=message.tool_call_id,
            tool_calls=message.tool_calls,
            reasoning_content=None,
        )
    if isinstance(message.content, list):
        # Vision / multimodal parts — still omit reasoning_content on the wire.
        return ChatMessage(
            role=message.role,
            content=message.content,
            name=message.name,
            tool_call_id=message.tool_call_id,
            tool_calls=message.tool_calls,
            reasoning_content=None,
        )
    text = inference_message_text(message)
    return ChatMessage(
        role=message.role,
        content=text,
        name=message.name,
        tool_call_id=message.tool_call_id,
        tool_calls=message.tool_calls,
        reasoning_content=None,
    )


def sanitize_messages_for_inference(messages: list[ChatMessage]) -> list[ChatMessage]:
    return [sanitize_message_for_inference(message) for message in messages]


def serialized_inference_prompt(messages: list[ChatMessage]) -> str:
    """JSON body fragment used in acceptance tests (matches provider serialization)."""
    from ..providers.base import to_openai_messages

    sanitized = sanitize_messages_for_inference(messages)
    return json.dumps(to_openai_messages(sanitized, for_inference=True), ensure_ascii=False)
