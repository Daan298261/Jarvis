from __future__ import annotations

import json
from typing import Any

from ..providers.base import ChatMessage

SUMMARY_MARKER = "Compacted earlier task memory:"
WORKING_STATE_MARKER = "Compact working state:"


def _text_of(message: ChatMessage) -> str:
    if isinstance(message.content, str):
        return message.content
    return json.dumps(message.content)


def _tail_start(messages: list[ChatMessage], keep_last: int) -> int:
    """Start the kept tail on a message that does not orphan a tool result.

    A `tool` message is only valid when the assistant message carrying its
    tool_calls is still present, so walk backwards past any leading tool
    results until that assistant turn is included.
    """
    start = max(len(messages) - keep_last, 0)
    while start > 0 and messages[start].role == "tool":
        start -= 1
    return start


def _summarize(middle: list[ChatMessage], max_entries: int, snippet: int) -> list[str]:
    bits: list[str] = []
    for message in middle:
        if message.role == "tool":
            bits.append(f"- tool {message.name or ''}: {_text_of(message)[:snippet]}")
        elif message.role == "assistant" and message.tool_calls:
            names = [call.get("function", {}).get("name") for call in message.tool_calls]
            bits.append(f"- called {', '.join(filter(None, names))}")
        elif message.role == "assistant":
            text = _text_of(message).strip()
            if text:
                bits.append(f"- assistant: {text[:snippet]}")
        elif message.role == "user":
            text = _text_of(message).strip()
            if text and not text.startswith(WORKING_STATE_MARKER):
                bits.append(f"- instruction: {text[:200]}")
    if len(bits) <= max_entries:
        return bits
    # Keep the oldest few for origin and the most recent for continuity.
    head = max_entries // 3
    return bits[:head] + [f"- ...{len(bits) - max_entries} earlier steps omitted..."] + bits[head - max_entries :]


def compact_history(
    messages: list[ChatMessage],
    keep_last: int = 8,
    working_state_block: str | None = None,
    max_summary_entries: int = 40,
    snippet: int = 400,
) -> list[ChatMessage]:
    """Keep the prompt small without dropping what the model needs to continue.

    Old turns collapse into a structured summary. The caller's compact working
    state, when supplied, is refreshed on every pass so the model always sees
    current goal, criteria, plan, and known failures.
    """
    # Earlier passes injected their own summary and working-state blocks. Drop
    # them so they are rebuilt from current data instead of nesting.
    cleaned = [message for message in messages if not _is_generated(message)]
    head = cleaned[:2]
    extra: list[ChatMessage] = []

    start = _tail_start(cleaned, keep_last)
    if start <= len(head):
        tail = cleaned[len(head) :]
    else:
        middle = cleaned[len(head) : start]
        tail = cleaned[start:]
        bits = _summarize(middle, max_summary_entries, snippet)
        if bits:
            extra.append(ChatMessage(role="system", content=SUMMARY_MARKER + "\n" + "\n".join(bits)))

    if working_state_block:
        extra.append(ChatMessage(role="system", content=working_state_block))

    return head + extra + tail


def estimate_prompt_tokens(messages: list[ChatMessage]) -> int:
    """Cheap char/4 estimate so we can grow context before llama.cpp starts spilling."""
    total = 0
    for message in messages:
        total += len(_text_of(message))
        if message.tool_calls:
            total += len(json.dumps(message.tool_calls))
    return max(1, total // 4)


def _is_generated(message: ChatMessage) -> bool:
    """Drop previously injected summaries so they do not nest on each pass."""
    if message.role != "system":
        return False
    text = _text_of(message)
    return text.startswith(SUMMARY_MARKER) or text.startswith(WORKING_STATE_MARKER)


def serialize_messages(messages: list[ChatMessage]) -> str:
    payload: list[dict[str, Any]] = []
    for message in messages:
        payload.append(
            {
                "role": message.role,
                "content": message.content if isinstance(message.content, str) else message.content,
                "name": message.name,
                "tool_call_id": message.tool_call_id,
                "tool_calls": message.tool_calls,
            }
        )
    return json.dumps(payload)


def deserialize_messages(raw: str) -> list[ChatMessage]:
    if not raw:
        return []
    data = json.loads(raw)
    return [
        ChatMessage(
            role=item.get("role", "user"),
            content=item.get("content") or "",
            name=item.get("name"),
            tool_call_id=item.get("tool_call_id"),
            tool_calls=item.get("tool_calls"),
        )
        for item in data
    ]
