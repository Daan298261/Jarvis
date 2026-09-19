from __future__ import annotations

import uuid
from collections import defaultdict
from typing import Any, AsyncIterator
import time

from ..config import load_settings
from ..inference.manager import MANAGER
from ..inference.profiles import resolve_profile
from ..providers.base import ChatMessage
from ..providers.completion_text import empty_generation_error
from .chat_delivery import (
    OWNER_CHAT_CHANNEL,
    clear_stream_speak_state,
    maybe_enqueue_streaming_social_tts,
    publish_owner_text,
    stream_speak_offset,
)
from .session_personality import maybe_apply_owner_switch_intent, session_personality_system_addendum
from .weather import weather_system_message
from ..events import BUS
from ..agent.front_responder import (
    generate_front_reply,
    is_safe_front_speech,
    last_front_timing,
    note_front_audio,
    resolve_front_model_id,
    run_two_lane_chat,
)
from .inference_context import ensure_context_for_messages, model_lane_event_payload
from .reply_verifier import schedule_background_verification
from .slow_turn_feedback import SlowTurnNudger

OWNER_CHAT_SYSTEM = """You are Jarvis speaking with the owner in plain conversation.
Reply immediately, naturally, and briefly in a British-inspired operations-assistant register.
Put the useful answer in the first sentence, ideally no more than twelve words.
Default to one to three short sentences and conversational contractions.
An occasional original dry observation is welcome when the situation is low-stakes. Never force a joke, repeat a stock acknowledgement, quote a franchise, or imitate a named character.
When the topic involves danger, distress, failure, privacy, money, or destructive action, drop the wit and be direct.
This is dialogue only: do not produce task plans, status dumps, RFC lists, or setup wizard steps unless the owner explicitly asks.
Do not call tools or describe tool execution.
Never write a program, script, or file to answer a spoken factual question such as the weather.
If a live briefing is attached, use those facts and do not invent numbers.
Use internal reasoning when useful, but provide only the concise answer rather than hidden reasoning."""

OWNER_CHAT_MAX_TOKENS = 512


def owner_chat_max_tokens(profile: Any | None = None) -> int:
    """Keep direct dialogue bounded; this path deliberately disables extended reasoning."""
    del profile
    return OWNER_CHAT_MAX_TOKENS

_conversations: dict[str, list[ChatMessage]] = defaultdict(list)


def reset_owner_conversations() -> None:
    _conversations.clear()


def get_conversation(conversation_id: str) -> list[ChatMessage]:
    return list(_conversations.get(conversation_id, []))


async def hydrate_conversation(conversation_id: str) -> list[ChatMessage]:
    from ..projects.portal_store import load_owner_conversation

    loaded = await load_owner_conversation(conversation_id)
    if loaded:
        _conversations[conversation_id] = list(loaded)
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


def _owner_messages(conversation_id: str, user_text: str, briefing: str | None = None) -> list[ChatMessage]:
    history = _conversations[conversation_id]
    system = OWNER_CHAT_SYSTEM
    addendum = session_personality_system_addendum()
    if addendum:
        system = f"{system}\n\n{addendum}"
    messages = [
        ChatMessage(role="system", content=system),
    ]
    if briefing:
        messages.append(ChatMessage(role="system", content=briefing))
    messages.extend(history)
    messages.append(ChatMessage(role="user", content=user_text.strip()))
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

    switch = maybe_apply_owner_switch_intent(cleaned)
    if switch:
        ack = str(switch.get("acknowledgement") or "").strip()
        _conversations[cid].append(ChatMessage(role="user", content=cleaned))
        _conversations[cid].append(ChatMessage(role="assistant", content=ack))
        yield {"type": "delta", "conversation_id": cid, "text": ack, "lane": "personality"}
        yield {
            "type": "done",
            "conversation_id": cid,
            "text": ack,
            "personality": {
                "id": switch.get("personality_id"),
                "display_name": switch.get("display_name"),
                "hud_theme": switch.get("hud_theme"),
                "changed": switch.get("changed"),
            },
        }
        return

    if not MANAGER.provider:
        yield {"type": "error", "detail": "Inference model is not loaded"}
        return

    settings = load_settings()
    profile = resolve_profile(settings.inference.profile)
    briefing = await weather_system_message(cleaned)
    history = await hydrate_conversation(cid)
    worker_messages = _owner_messages(cid, cleaned, briefing)
    parts: list[str] = []
    stream_key = f"owner:{cid}"
    clear_stream_speak_state(stream_key)
    early_tts_ids: list[str] = []
    turn_started = time.perf_counter()
    worker_model = str(getattr(MANAGER.provider, "model", "") or profile.name)

    async def _speak_context_expand(before: int, after: int) -> None:
        front = await generate_front_reply(
            cleaned,
            history=history,
            settings=settings,
            turn_started=turn_started,
        )
        if front.text and is_safe_front_speech(front.action, front.text):
            await publish_owner_text(
                front.text,
                source="owner_chat",
                speak=True,
                user_prompt=cleaned,
            )
        detail = model_lane_event_payload(
            lane="system",
            model=resolve_front_model_id(settings),
            text=f"Expanding context {before} → {after}",
        )
        await BUS.publish_ephemeral(
            OWNER_CHAT_CHANNEL,
            "model_lane",
            "Context resize",
            detail,
            stage="model",
        )

    ctx_meta = await ensure_context_for_messages(
        worker_messages,
        settings=settings,
        profile_name=profile.name,
        on_expanding=_speak_context_expand,
    )
    worker_model = str(getattr(MANAGER.provider, "model", "") or profile.name)
    await BUS.publish_ephemeral(
        OWNER_CHAT_CHANNEL,
        "model_lane",
        "Worker context",
        model_lane_event_payload(
            lane="worker",
            model=worker_model,
            extra=ctx_meta,
        ),
        stage="model",
    )

    async def worker_stream():
        async for delta in MANAGER.chat_stream(
            worker_messages,
            temperature=profile.temperature,
            top_p=profile.top_p,
            top_k=profile.top_k,
            max_tokens=owner_chat_max_tokens(profile),
            thinking=False,
        ):
            yield delta

    async def on_delta(lane: str, delta: str) -> None:
        parts.append(delta)
        model_id = resolve_front_model_id(settings) if lane == "front" else worker_model
        await BUS.publish_ephemeral(
            OWNER_CHAT_CHANNEL,
            "model_lane",
            f"{lane} output",
            model_lane_event_payload(lane=lane, model=model_id, text=delta[:240]),
            stage="owner_chat",
        )
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
            note_front_audio(None, (time.perf_counter() - turn_started) * 1000)

    nudger = SlowTurnNudger(cleaned, started=turn_started, source="owner_chat")
    nudger.start()
    try:
        done: dict[str, Any] | None = None
        async for event in run_two_lane_chat(
            cleaned,
            history=history,
            settings=settings,
            turn_started=turn_started,
            worker_stream=worker_stream,
            on_delta=on_delta,
        ):
            kind = event.get("type")
            if kind == "delta":
                yield {"type": "delta", "conversation_id": cid, "text": event.get("text") or "", "lane": event.get("lane")}
            elif kind == "front_response_completed":
                front = event.get("reply")
                text = getattr(front, "text", "") or ""
                if text and not parts:
                    yield {"type": "delta", "conversation_id": cid, "text": text, "lane": "front"}
                if (
                    front
                    and settings.front_responder.speak_immediately
                    and is_safe_front_speech(front.action, front.text)
                    and not early_tts_ids
                ):
                    early_id = maybe_enqueue_streaming_social_tts(
                        front.text if front.text.endswith((".", "!", "?")) else f"{front.text}.",
                        source="owner_chat",
                        stream_key=stream_key,
                        user_prompt=cleaned,
                    )
                    if not early_id:
                        delivery = await publish_owner_text(
                            front.text,
                            source="owner_chat",
                            speak=True,
                            user_prompt=cleaned,
                        )
                        if delivery.get("tts_id"):
                            early_tts_ids.append(str(delivery["tts_id"]))
                    elif early_id:
                        early_tts_ids.append(early_id)
                        await BUS.publish_ephemeral(
                            OWNER_CHAT_CHANNEL,
                            "chat_tts",
                            "Speak reply",
                            front.text,
                            stage="owner_chat",
                        )
                    note_front_audio(None, (time.perf_counter() - turn_started) * 1000)
            elif kind == "done":
                done = event
    except Exception as exc:
        await nudger.stop()
        clear_stream_speak_state(stream_key)
        yield {"type": "error", "detail": str(exc)[:500]}
        return
    finally:
        nudge_meta = await nudger.stop()

    reply = ((done or {}).get("text") or "".join(parts)).strip()
    if reply:
        _conversations[cid].append(ChatMessage(role="user", content=cleaned))
        _conversations[cid].append(ChatMessage(role="assistant", content=reply))
        from ..projects.portal_store import save_owner_conversation

        await save_owner_conversation(
            cid,
            _conversations[cid],
            title=cleaned[:120],
        )
        delivery = await publish_owner_text(
            reply,
            source="owner_chat",
            speak=True,
            user_prompt=cleaned,
            tts_char_offset=stream_speak_offset(stream_key),
        )
        clear_stream_speak_state(stream_key)
        tts_id = early_tts_ids[0] if early_tts_ids and not delivery.get("tts_id") else delivery.get("tts_id")
        if len(reply) >= 40:
            await publish_owner_text(
                "I'll run a quick background verification and speak up if anything material changes.",
                source="owner_chat",
                speak=True,
                user_prompt=cleaned,
            )
        schedule_background_verification(cleaned, reply, source="owner_chat", speak=True)
        yield {
            "type": "done",
            "conversation_id": cid,
            "text": reply,
            "tts_id": tts_id,
            "early_tts_ids": early_tts_ids,
            "front_action": (done or {}).get("front_action"),
            "timing": (done or {}).get("timing") or last_front_timing(),
            "slow_nudges": nudge_meta.get("nudges", 0),
            "background_verify": True,
        }
    else:
        clear_stream_speak_state(stream_key)
        yield {"type": "error", "detail": empty_generation_error()}


async def complete_owner_chat(user_text: str, *, conversation_id: str | None = None) -> dict[str, Any]:
    last: dict[str, Any] = {"conversation_id": conversation_id, "text": ""}
    async for event in stream_owner_chat(user_text, conversation_id=conversation_id):
        if event.get("type") == "error":
            return {"ok": False, **event}
        if event.get("type") == "done":
            last = {"ok": True, **event}
    return last
