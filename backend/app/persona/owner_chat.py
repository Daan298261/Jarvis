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
Reply immediately, naturally, and briefly in a British-inspired operations-assistant register.
Put the useful answer in the first sentence, ideally no more than twelve words.
Default to one to three short sentences and conversational contractions.
An occasional original dry observation is welcome when the situation is low-stakes. Never force a joke, repeat a stock acknowledgement, quote a franchise, or imitate a named character.
When the topic involves danger, distress, failure, privacy, money, or destructive action, drop the wit and be direct.
This is dialogue only: do not produce task plans, status dumps, RFC lists, or setup wizard steps unless the owner explicitly asks.
Do not call tools or describe tool execution."""

OWNER_CHAT_MAX_TOKENS = 256

_conversations: dict[str, list[ChatMessage]] = defaultdict(list)


def reset_owner_conversations() -> None:
    _conversations.clear()


def get_conversation(conversation_id: str) -> list[ChatMessage]:
    return list(_conversations.get(conversation_id, []))


def conversation_ids() -> list[str]:
    return list(_conversations.keys())


def _estimate_history_char_budget(context_limit: int) -> int:
    """Reserve headroom for persona, owner system prompt, and model output."""
    tokens_for_history = max(256, int(context_limit) - 4096)
    return max(512, tokens_for_history * 4)


def _truncate_turns_for_budget(messages: list[ChatMessage], char_budget: int) -> list[ChatMessage]:
    if char_budget <= 0 or not messages:
        return list(messages)
    kept: list[ChatMessage] = []
    used = 0
    for message in reversed(messages):
        text = (message.content or "").strip()
        size = len(text) + 32
        if kept and used + size > char_budget:
            break
        kept.append(message)
        used += size
    if not kept and messages:
        last = messages[-1]
        snippet = (last.content or "")[: max(64, char_budget)]
        kept = [ChatMessage(role=last.role, content=snippet)]
    return list(reversed(kept))


def rebind_owner_conversations_after_hotswap(
    context_limit: int,
    *,
    previous_context_limit: int | None = None,
) -> None:
    """Keep owner-chat threads across model hotswap; drop oldest turns if context shrinks."""
    limit = int(context_limit or 0)
    if limit <= 0:
        return
    budget = _estimate_history_char_budget(limit)
    if previous_context_limit and int(previous_context_limit) > limit:
        for cid in list(_conversations.keys()):
            _conversations[cid] = _truncate_turns_for_budget(_conversations[cid], budget)
        return
    for cid, history in list(_conversations.items()):
        if _history_char_size(history) > budget:
            _conversations[cid] = _truncate_turns_for_budget(history, budget)


def _history_char_size(messages: list[ChatMessage]) -> int:
    return sum(len((message.content or "")) + 32 for message in messages)


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
            max_tokens=OWNER_CHAT_MAX_TOKENS,
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
