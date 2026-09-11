from __future__ import annotations

import uuid
from collections import defaultdict
from typing import Any, AsyncIterator

from ..config import load_settings
from ..inference.manager import MANAGER
from ..inference.profiles import resolve_profile
from ..providers.base import ChatMessage
from .chat_delivery import (
    OWNER_CHAT_CHANNEL,
    clear_stream_speak_state,
    maybe_enqueue_streaming_social_tts,
    publish_owner_text,
    stream_speak_offset,
)
from ..events import BUS

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
    stream_key = f"owner:{cid}"
    clear_stream_speak_state(stream_key)
    early_tts_ids: list[str] = []

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
            accumulated = "".join(parts)
            early_id = maybe_enqueue_streaming_social_tts(
                accumulated,
                source="owner_chat",
                stream_key=stream_key,
                user_prompt=cleaned,
            )
            if early_id:
                early_tts_ids.append(early_id)
                await BUS.publish_ephemeral(
                    OWNER_CHAT_CHANNEL,
                    "chat_tts",
                    "Speak reply",
                    accumulated[: stream_speak_offset(stream_key)],
                    stage="owner_chat",
                )
            yield {"type": "delta", "conversation_id": cid, "text": delta}
    except Exception as exc:
        clear_stream_speak_state(stream_key)
        yield {"type": "error", "detail": str(exc)[:500]}
        return

    reply = "".join(parts).strip()
    if reply:
        _conversations[cid].append(ChatMessage(role="user", content=cleaned))
        _conversations[cid].append(ChatMessage(role="assistant", content=reply))
        delivery = await publish_owner_text(
            reply,
            source="owner_chat",
            speak=True,
            user_prompt=cleaned,
            tts_char_offset=stream_speak_offset(stream_key),
        )
        clear_stream_speak_state(stream_key)
        tts_id = early_tts_ids[0] if early_tts_ids and not delivery.get("tts_id") else delivery.get("tts_id")
        yield {
            "type": "done",
            "conversation_id": cid,
            "text": reply,
            "tts_id": tts_id,
            "early_tts_ids": early_tts_ids,
        }
    else:
        clear_stream_speak_state(stream_key)
        yield {"type": "done", "conversation_id": cid, "text": ""}


async def complete_owner_chat(user_text: str, *, conversation_id: str | None = None) -> dict[str, Any]:
    last: dict[str, Any] = {"conversation_id": conversation_id, "text": ""}
    async for event in stream_owner_chat(user_text, conversation_id=conversation_id):
        if event.get("type") == "error":
            return {"ok": False, **event}
        if event.get("type") == "done":
            last = {"ok": True, **event}
    return last
