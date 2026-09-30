from __future__ import annotations

import asyncio
import json
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
    mark_stream_spoken,
    maybe_enqueue_streaming_social_tts,
    pending_chat_tts_text,
    publish_owner_text,
    stream_speak_offset,
)
from .weather import weather_system_message
from ..events import BUS
from ..agent.front_responder import (
    TwoLaneTiming,
    generate_front_reply,
    is_safe_front_speech,
    last_front_timing,
    note_front_audio,
    record_front_timing,
    resolve_front_model_id,
    run_two_lane_chat,
    terminal_front_completes_turn,
)
from ..agent.planning import requests_agent_tools
from ..agent.segmented_input import condense_segments
from .inference_context import ensure_context_for_messages, model_lane_event_payload
from ..agent.background_verify import schedule_background_verification
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


def append_owner_assistant_message(conversation_id: str | None, content: str) -> None:
    cid = (conversation_id or "").strip()
    cleaned = (content or "").strip()
    if not cid or not cleaned:
        return
    _conversations.setdefault(cid, [])
    _conversations[cid].append(ChatMessage(role="assistant", content=cleaned))


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


async def compose_owner_turn_messages(
    conversation_id: str,
    user_text: str,
    briefing: str | None = None,
) -> tuple[list[ChatMessage], "TurnWorkingSet"]:
    """Build the owner-chat inference prompt via RFC-0107 turn working set (no skip-if-empty)."""
    from ..agent.turn_working_set import TurnWorkingSet, apply_working_set_to_system, compose_turn_working_set

    history = list(_conversations.get(conversation_id, []))
    prompt = (user_text or "").strip()
    # Same composer as the agent loop: vault provenance, empty-miss surface, installable search.
    # needs_tools=False keeps dialogue from advertising executable tool schemas; installable
    # offers and vault hits still enter the system prefix via compose_turn_working_set.
    turn_ws = await compose_turn_working_set(
        prompt,
        task_class="conversation",
        agent_id="owner",
        recent_messages=history,
        needs_tools=False,
        include_vault=True,
        include_memory=True,
    )
    system = apply_working_set_to_system(OWNER_CHAT_SYSTEM, turn_ws)
    messages: list[ChatMessage] = [ChatMessage(role="system", content=system)]
    if briefing:
        messages.append(ChatMessage(role="system", content=briefing))
    messages.extend(turn_ws.recent_turns)
    messages.append(ChatMessage(role="user", content=prompt))
    return messages, turn_ws


async def _owner_messages(
    conversation_id: str,
    user_text: str,
    briefing: str | None = None,
) -> list[ChatMessage]:
    messages, _working = await compose_owner_turn_messages(conversation_id, user_text, briefing)
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

    if requests_agent_tools(cleaned):
        from ..agent.loop import AGENT

        try:
            task = await AGENT.create_task(cleaned)
        except Exception as exc:
            yield {"type": "error", "detail": f"Could not start tool run: {exc}"[:500]}
            return
        spoken = "Right — I'll run that with the agent harness and tools on this PC."
        _conversations.setdefault(cid, [])
        _conversations[cid].append(ChatMessage(role="user", content=cleaned))
        _conversations[cid].append(ChatMessage(role="assistant", content=spoken))
        await publish_owner_text(spoken, source="owner_chat", speak=True, user_prompt=cleaned)
        yield {
            "type": "task_delegated",
            "conversation_id": cid,
            "task_id": task.id,
            "reply": spoken,
        }
        yield {"type": "done", "conversation_id": cid, "reply": spoken}
        return

    from ..agent.context_policy import profile_cap
    from ..agent.intake import plan_owner_intake, start_sequential_chain

    intake = await asyncio.to_thread(
        plan_owner_intake,
        cleaned,
        context_tokens=profile_cap(resolve_profile(load_settings().inference.profile)),
    )
    if intake.strategy != "direct":
        await BUS.publish_ephemeral(
            OWNER_CHAT_CHANNEL,
            "stage",
            "Long message intake",
            json.dumps(intake.as_dict()),
            stage="owner_chat",
        )
    if intake.strategy == "sequential":
        try:
            chain = await start_sequential_chain(intake, conversation_id=cid)
        except Exception as exc:
            yield {"type": "error", "detail": f"Could not start the long-message run: {exc}"[:500]}
            return
        spoken = (
            f"That's a long one (about {intake.tokens:,} tokens). I split it into "
            f"{len(intake.segments)} parts and I'm working through them in order; "
            "each part picks up the result of the one before."
        )
        _conversations.setdefault(cid, [])
        _conversations[cid].append(ChatMessage(role="user", content=cleaned[:2000]))
        _conversations[cid].append(ChatMessage(role="assistant", content=spoken))
        await publish_owner_text(spoken, source="owner_chat", speak=True, user_prompt=cleaned[:2000])
        yield {
            "type": "task_delegated",
            "conversation_id": cid,
            "task_id": chain["task_ids"][0],
            "intake_chain_id": chain["id"],
            "intake": intake.as_dict(),
            "reply": spoken,
        }
        yield {"type": "done", "conversation_id": cid, "reply": spoken}
        return
    worker_text = cleaned

    from .session_personality import maybe_switch_from_owner_message

    switched = maybe_switch_from_owner_message(cleaned)
    if switched:
        yield {
            "type": "session_mode",
            "conversation_id": cid,
            "mode": switched.as_dict(),
        }

    settings = load_settings()
    profile = resolve_profile(settings.inference.profile)
    briefing = await weather_system_message(cleaned)
    history = await hydrate_conversation(cid)
    turn_started = time.perf_counter()
    stream_key = f"owner:{cid}"
    clear_stream_speak_state(stream_key)
    early_tts_ids: list[str] = []
    front_spoken_early = False
    front_text_emitted = False

    prefetched_front = await generate_front_reply(
        cleaned,
        history=history,
        settings=settings,
        turn_started=turn_started,
    )
    front_safe = bool(
        prefetched_front.text
        and prefetched_front.action != "silent_skip"
        and is_safe_front_speech(prefetched_front.action, prefetched_front.text)
    )
    if front_safe:
        # Emit ONLY validated sanitized text — never raw model chunks / JSON envelopes.
        safe_text = (prefetched_front.text or "").strip()
        chunks = [safe_text] if safe_text else []
        for chunk in chunks:
            if not chunk:
                continue
            front_text_emitted = True
            yield {
                "type": "delta",
                "conversation_id": cid,
                "text": chunk,
                "lane": "front",
            }
        if (
            settings.front_responder.speak_immediately
            and not front_spoken_early
        ):
            spoken = (
                prefetched_front.text
                if prefetched_front.text.endswith((".", "!", "?"))
                else f"{prefetched_front.text}."
            )
            early_id = maybe_enqueue_streaming_social_tts(
                spoken,
                source="owner_chat",
                stream_key=stream_key,
                user_prompt=cleaned,
            )
            if not early_id:
                delivery = await publish_owner_text(
                    prefetched_front.text,
                    source="owner_chat",
                    speak=True,
                    user_prompt=cleaned,
                )
                if delivery.get("tts_id"):
                    early_tts_ids.append(str(delivery["tts_id"]))
                    # publish_owner_text does not advance the stream cursor;
                    # mark it so the final reply path cannot re-speak.
                    mark_stream_spoken(stream_key, len(prefetched_front.text))
            else:
                early_tts_ids.append(early_id)
                await BUS.publish_ephemeral(
                    OWNER_CHAT_CHANNEL,
                    "chat_tts",
                    "Speak reply",
                    pending_chat_tts_text(early_id) or spoken,
                    stage="owner_chat",
                )
            audio_ms = (time.perf_counter() - turn_started) * 1000
            note_front_audio(None, audio_ms)
            prefetched_front.first_audio_ms = audio_ms
            front_spoken_early = True

        # final_basic / ask_clarification: complete without loading the worker —
        # unless RFC-0107 requires the vault working set (bound + vault-relevant).
        if terminal_front_completes_turn(prefetched_front.action):
            from ..memory.obsidian_vault import vault_ask_requires_working_set

            if not vault_ask_requires_working_set(cleaned):
                reply = prefetched_front.text.strip()
                timing = TwoLaneTiming(
                    front_model=prefetched_front.model or resolve_front_model_id(settings),
                    front_action=prefetched_front.action,
                    queue_ms=max(0.0, (time.perf_counter() - turn_started) * 1000),
                    front_first_text_ms=prefetched_front.first_text_ms,
                    front_complete_ms=prefetched_front.complete_ms,
                    front_first_audio_ms=prefetched_front.first_audio_ms,
                    tts_first_audio_ms=prefetched_front.first_audio_ms,
                )
                recorded = record_front_timing(timing.as_dict())
                _conversations[cid].append(ChatMessage(role="user", content=worker_text))
                _conversations[cid].append(ChatMessage(role="assistant", content=reply))
                from ..projects.portal_store import save_owner_conversation

                await save_owner_conversation(
                    cid,
                    _conversations[cid],
                    title=cleaned[:120],
                )
                try:
                    from ..memory.obsidian_vault import mirror_owner_chat_turn

                    mirror_owner_chat_turn(
                        conversation_id=cid,
                        user_text=worker_text,
                        assistant_text=reply,
                    )
                except Exception:
                    pass
                # Already spoken above when speak_immediately; only fill remainder.
                delivery = await publish_owner_text(
                    reply,
                    source="owner_chat",
                    speak=True,
                    user_prompt=cleaned,
                    tts_char_offset=stream_speak_offset(stream_key),
                )
                clear_stream_speak_state(stream_key)
                tts_id = (
                    early_tts_ids[0]
                    if early_tts_ids and not delivery.get("tts_id")
                    else delivery.get("tts_id")
                )
                yield {
                    "type": "done",
                    "conversation_id": cid,
                    "text": reply,
                    "tts_id": tts_id,
                    "early_tts_ids": early_tts_ids,
                    "front_action": prefetched_front.action,
                    "timing": recorded,
                    "slow_nudges": 0,
                    "background_verify": False,
                    "front_terminal": True,
                }
                return
            # Fall through to worker so compose_turn_working_set runs with vault hits.

    if not MANAGER.provider or not MANAGER.state.loaded:
        try:
            await BUS.publish_ephemeral(
                OWNER_CHAT_CHANNEL,
                "stage",
                "Loading local model",
                "",
                stage="model",
            )
            await MANAGER.load(settings, profile.name)
        except Exception as exc:
            yield {"type": "error", "detail": f"Inference model is not loaded: {exc}"[:500]}
            return

    if not MANAGER.provider:
        yield {"type": "error", "detail": "Inference model is not loaded"}
        return

    worker_messages = await _owner_messages(cid, cleaned, briefing)
    if intake.strategy == "compress":
        async def _segment_progress(index: int, total: int) -> None:
            await BUS.publish_ephemeral(
                OWNER_CHAT_CHANNEL,
                "stage",
                f"Reading input part {index}/{total}",
                "",
                stage="owner_chat",
            )

        try:
            brief = await condense_segments(intake.segments, on_segment=_segment_progress)
        except Exception as exc:
            yield {"type": "error", "detail": f"Could not process the full long message: {exc}"[:500]}
            return
        worker_text = (
            f"Owner message (~{intake.tokens:,} tokens) processed in {len(intake.segments)} ordered parts. "
            f"The full text is saved at {intake.original_path}; read exact passages with the filesystem "
            f"tool when wording matters. Answer this complete brief:\n{brief}"
        )
        worker_messages[-1] = ChatMessage(role="user", content=worker_text)
    parts: list[str] = []
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
        bus_channel=OWNER_CHAT_CHANNEL,
    )
    profile = resolve_profile(settings.inference.profile)
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
        # Front text/TTS already left the gate; do not re-append or re-speak it.
        if lane == "front" and (front_text_emitted or front_spoken_early):
            return
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
            prefetched_front=prefetched_front if prefetched_front.text else None,
        ):
            kind = event.get("type")
            if kind == "delta":
                if event.get("lane") == "front" and front_text_emitted:
                    continue
                yield {"type": "delta", "conversation_id": cid, "text": event.get("text") or "", "lane": event.get("lane")}
            elif kind == "front_response_completed":
                front = event.get("reply")
                text = getattr(front, "text", "") or ""
                if text and not parts and not front_text_emitted:
                    yield {"type": "delta", "conversation_id": cid, "text": text, "lane": "front"}
                if (
                    front
                    and not front_spoken_early
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
                            mark_stream_spoken(stream_key, len(front.text or ""))
                    elif early_id:
                        early_tts_ids.append(early_id)
                        await BUS.publish_ephemeral(
                            OWNER_CHAT_CHANNEL,
                            "chat_tts",
                            "Speak reply",
                            pending_chat_tts_text(early_id) or front.text,
                            stage="owner_chat",
                        )
                    note_front_audio(None, (time.perf_counter() - turn_started) * 1000)
                    if front:
                        front.first_audio_ms = max(
                            float(getattr(front, "first_audio_ms", 0.0) or 0.0),
                            (time.perf_counter() - turn_started) * 1000,
                        )
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
        # History keeps what the worker saw, so a compressed paste stays compressed next turn.
        _conversations[cid].append(ChatMessage(role="user", content=worker_text))
        _conversations[cid].append(ChatMessage(role="assistant", content=reply))
        from ..projects.portal_store import save_owner_conversation

        await save_owner_conversation(
            cid,
            _conversations[cid],
            title=cleaned[:120],
        )
        try:
            from ..memory.obsidian_vault import mirror_owner_chat_turn

            # Mirror what the worker (and next-turn composer) actually saw.
            mirror_owner_chat_turn(
                conversation_id=cid,
                user_text=worker_text,
                assistant_text=reply,
            )
        except Exception:
            pass
        delivery = await publish_owner_text(
            reply,
            source="owner_chat",
            speak=True,
            user_prompt=cleaned,
            tts_char_offset=stream_speak_offset(stream_key),
        )
        clear_stream_speak_state(stream_key)
        tts_id = early_tts_ids[0] if early_tts_ids and not delivery.get("tts_id") else delivery.get("tts_id")
        # Direct front terminal turns skip verify (#481); otherwise apply RFC-0167 admission.
        front_action = (done or {}).get("front_action") or prefetched_front.action
        verify_scheduled = False
        if not terminal_front_completes_turn(str(front_action or "")):
            from ..agent.planning import route_request

            route = route_request(cleaned)
            verify_scheduled = schedule_background_verification(
                cleaned,
                reply,
                source="owner_chat",
                speak=True,
                conversation_id=cid,
                route_kind=route.kind,
                task_class=route.task_class,
            )
        yield {
            "type": "done",
            "conversation_id": cid,
            "text": reply,
            "tts_id": tts_id,
            "early_tts_ids": early_tts_ids,
            "front_action": front_action,
            "timing": (done or {}).get("timing") or last_front_timing(),
            "slow_nudges": nudge_meta.get("nudges", 0),
            "background_verify": bool(verify_scheduled),
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
