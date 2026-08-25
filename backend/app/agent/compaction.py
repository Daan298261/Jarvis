from __future__ import annotations

import json
from typing import Any

from ..providers.base import ChatMessage

WORKING_MEMORY_MARK = "[Compacted working memory — do not lose the goal]"


def ensure_single_system(messages: list[ChatMessage]) -> list[ChatMessage]:
    """Qwen chat templates reject system messages after the first turn."""
    if not messages:
        return messages
    out: list[ChatMessage] = []
    for index, message in enumerate(messages):
        if index > 0 and message.role == "system":
            content = message.content if isinstance(message.content, str) else json.dumps(message.content)
            out.append(ChatMessage(role="user", content=content))
        else:
            out.append(message)
    return out


def _text(content: Any) -> str:
    if content is None:
        return ""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts: list[str] = []
        for item in content:
            if isinstance(item, dict) and item.get("type") == "text":
                parts.append(str(item.get("text") or ""))
            elif isinstance(item, str):
                parts.append(item)
        return "\n".join(parts)
    return json.dumps(content)


def _first_user_index(messages: list[ChatMessage]) -> int:
    for index, message in enumerate(messages):
        if message.role == "user":
            return index
    return min(1, len(messages) - 1) if messages else 0


def _is_memory(message: ChatMessage) -> bool:
    text = _text(message.content)
    return message.role == "user" and (
        WORKING_MEMORY_MARK in text or "[Compacted earlier task memory]" in text
    )


def _dedupe(items: list[str], limit: int) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for item in items:
        key = " ".join(item.lower().split())[:160]
        if not key or key in seen:
            continue
        seen.add(key)
        out.append(item)
        if len(out) >= limit:
            break
    return out


def _snippet(text: str, limit: int = 240) -> str:
    return " ".join((text or "").split())[:limit]


def working_memory_text(messages: list[ChatMessage]) -> str:
    for message in messages:
        if _is_memory(message):
            return _text(message.content)
    return ""


def _structured_summary(head: list[ChatMessage], middle: list[ChatMessage], goal: str | None) -> ChatMessage:
    goal_text = (goal or "").strip()
    if not goal_text:
        for message in head:
            if message.role == "user" and not _is_memory(message):
                goal_text = _text(message.content)
                break
    goal_line = ""
    for line in goal_text.splitlines():
        stripped = line.strip()
        if stripped:
            goal_line = stripped[:400]
            break
    expected: list[str] = []
    try:
        from .artifacts import expected_output_paths

        expected = expected_output_paths(goal_text) if goal_text else []
    except Exception:
        expected = []

    completed: list[str] = []
    failures: list[str] = []
    observations: list[str] = []
    followups: list[str] = []

    for message in middle:
        text = _text(message.content)
        if message.role == "user":
            if _is_memory(message):
                for block, bucket in (
                    ("Later instructions:", followups),
                    ("Completed:", completed),
                    ("Known failures:", failures),
                    ("Observations:", observations),
                ):
                    if block not in text:
                        continue
                    section = text.split(block, 1)[1]
                    for other in (
                        "Later instructions:",
                        "Completed:",
                        "Known failures:",
                        "Observations:",
                        "Continue the original",
                    ):
                        if other != block and other in section:
                            section = section.split(other, 1)[0]
                    for raw in section.splitlines():
                        line = raw.strip().lstrip("- ").strip()
                        if line:
                            bucket.append(line)
                continue
            followups.append(_snippet(text, 400))
            continue
        if message.role == "tool":
            name = message.name or "tool"
            snippet = _snippet(text)
            lower = text.lower()
            if text.startswith("ERROR") or "failed" in lower[:120] or "traceback" in lower:
                failures.append(f"{name}: {snippet}")
            elif any(token in lower for token in ("wrote ", "created ", "title=", "saved ", "edited ")):
                completed.append(f"{name}: {snippet}")
            else:
                observations.append(f"{name}: {snippet}")
            continue
        if message.role == "assistant" and message.tool_calls:
            names = [str((call.get("function") or {}).get("name") or "") for call in message.tool_calls]
            named = ", ".join(n for n in names if n)
            if named:
                observations.append(f"called {named}")
        elif message.role == "assistant" and text.strip():
            observations.append(f"assistant: {_snippet(text, 200)}")

    parts = [WORKING_MEMORY_MARK, f"Goal: {goal_line or '(see the original user message)'}"]
    if expected:
        parts.append("Acceptance files:\n" + "\n".join(f"- {path}" for path in expected[:8]))
    if followups:
        parts.append("Later instructions:\n" + "\n".join(f"- {item}" for item in _dedupe(followups, 4)))
    if completed:
        parts.append("Completed:\n" + "\n".join(f"- {item}" for item in _dedupe(completed, 10)))
    if failures:
        parts.append("Known failures:\n" + "\n".join(f"- {item}" for item in _dedupe(failures, 8)))
    if observations:
        parts.append("Observations:\n" + "\n".join(f"- {item}" for item in _dedupe(observations, 8)))
    parts.append("Continue the original goal. Do not restart from scratch.")
    content = "\n\n".join(parts)
    if len(content) > 4000:
        content = content[:3990] + "\n…"
    return ChatMessage(role="user", content=content)


def compact_history(
    messages: list[ChatMessage],
    keep_last: int = 10,
    goal: str | None = None,
) -> list[ChatMessage]:
    """Keep the original goal plus a structured summary; drop bulky older tool traces."""
    messages = ensure_single_system(list(messages))
    if len(messages) <= keep_last + 3:
        return messages
    goal_idx = _first_user_index(messages)
    head_end = goal_idx + 1
    cut = len(messages) - keep_last
    if cut < head_end:
        return messages
    while cut > head_end and cut < len(messages) and messages[cut].role == "tool":
        cut -= 1
    if cut <= head_end:
        return messages
    head = messages[:head_end]
    middle = messages[head_end:cut]
    tail = messages[cut:]
    if not middle:
        return messages
    summary = _structured_summary(head, middle, goal)
    return ensure_single_system(head + [summary] + tail)


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
