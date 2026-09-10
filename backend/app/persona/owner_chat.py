from __future__ import annotations

import uuid
from collections import defaultdict
from typing import Any, AsyncIterator

from ..config import load_settings
from ..inference.manager import MANAGER
from ..inference.profiles import resolve_profile
from ..providers.base import ChatMessage
from .chat_delivery import publish_owner_text

OWNER_CHAT_SYSTEM = """You are Jarvis speaking with the owner in plain conversation.
Reply naturally, warmly, and briefly in a British-inspired butler register.
This is dialogue only: do not produce task plans, status dumps, RFC lists, or setup wizard steps unless the owner explicitly asks.
Do not call tools or describe tool execution."""

_conversations: dict[str, list[ChatMessage]] = defaultdict(list)


def reset_owner_conversations() -> None:
    _conversations.clear()


def get_conversation(conversation_id: str) -> list[ChatMessage]:
    return list(_conversations.get(conversation_id, []))


def _ensure_conversation(conversation_id: str | None) -> str:
    cid = (conversation_id or "").strip() or str(uuid.uuid4())
    _conversations.setdefault(cid, [])
    return cid


def _owner_messages(conversation_id: str, user_text: str) -> list[ChatMessage]:
    history = _conversations[conversation_id]
    messages = [
        ChatMessage(role="system", content=OWNER_CHAT_SYSTEM),
        *history,
        ChatMessage(role="user", content=user_text.strip()),
    ]
    return messages


async def stream_owner_chat(
    user_text: str,
    *,
    conversation_id: str | None = None,
) -> AsyncIterator[dict[str, Any]]:
    """Stream a conversational owner reply without agent-loop approval gates."""
    cleaned = (user_text or "").strip()
    if not cleaned:
        yield {"type": "error", "detail": "Message is empty"}
        return

    cid = _ensure_conversation(conversation_id)
    yield {"type": "start", "conversation_id": cid}

    if not MANAGER.provider:
        yield {"type": "error", "detail": "Inference model is not loaded"}
        return

    settings = load_settings()
    profile = resolve_profile(settings.inference.profile)
    messages = _owner_messages(cid, cleaned)
    parts: list[str] = []

    try:
        async for delta in MANAGER.chat_stream(
            messages,
            temperature=profile.temperature,
            top_p=profile.top_p,
            top_k=profile.top_k,
            max_tokens=512,
            thinking=False,
        ):
            parts.append(delta)
            yield {"type": "delta", "conversation_id": cid, "text": delta}
    except Exception as exc:
        yield {"type": "error", "detail": str(exc)[:500]}
        return

    reply = "".join(parts).strip()
    if reply:
        _conversations[cid].append(ChatMessage(role="user", content=cleaned))
        _conversations[cid].append(ChatMessage(role="assistant", content=reply))
        delivery = await publish_owner_text(reply, source="owner_chat", speak=True)
        yield {
            "type": "done",
            "conversation_id": cid,
            "text": reply,
            "tts_id": delivery.get("tts_id"),
        }
    else:
        yield {"type": "done", "conversation_id": cid, "text": ""}


async def complete_owner_chat(user_text: str, *, conversation_id: str | None = None) -> dict[str, Any]:
    last: dict[str, Any] = {"conversation_id": conversation_id, "text": ""}
    async for event in stream_owner_chat(user_text, conversation_id=conversation_id):
        if event.get("type") == "error":
            return {"ok": False, **event}
        if event.get("type") == "done":
            last = {"ok": True, **event}
    return last
