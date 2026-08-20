from __future__ import annotations

import json
from typing import Any

from ..providers.base import ChatMessage


def compact_history(messages: list[ChatMessage], keep_last: int = 8) -> list[ChatMessage]:
    if len(messages) <= keep_last + 2:
        return messages
    head = messages[:2]
    middle = messages[2:-keep_last]
    tail = messages[-keep_last:]
    summary_bits: list[str] = []
    for message in middle:
        if message.role == "tool":
            text = message.content if isinstance(message.content, str) else json.dumps(message.content)
            summary_bits.append(f"- tool {message.name or ''}: {text[:400]}")
        elif message.role == "assistant" and message.tool_calls:
            names = [c.get("function", {}).get("name") for c in message.tool_calls]
            summary_bits.append(f"- called {', '.join(filter(None, names))}")
        elif message.role == "assistant" and isinstance(message.content, str) and message.content.strip():
            summary_bits.append(f"- assistant: {message.content[:300]}")
    summary = ChatMessage(
        role="system",
        content="Compacted earlier task memory:\n" + "\n".join(summary_bits[:80]),
    )
    return head + [summary] + tail


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
