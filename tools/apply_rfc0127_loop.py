#!/usr/bin/env python3
"""Apply RFC-0127 loop.py edits idempotently."""
from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LOOP = ROOT / "backend/app/agent/loop.py"
text = LOOP.read_text()

IMPORT_OLD = """from .front_responder import (
    generate_front_reply,
    is_safe_front_speech,
    last_front_timing,
    note_front_audio,
    run_two_lane_chat,
)
from .recovery import recovery_hint"""

IMPORT_NEW = """from .front_responder import (
    classify_front_action,
    enforce_front_safety,
    fallback_text_for_action,
    generate_front_reply,
    is_safe_front_speech,
    last_front_timing,
    note_front_audio,
    run_two_lane_chat,
)
from .worker_progress import (
    clear_worker_progress_for_task,
    mark_worker_useful_owner_text,
    run_worker_progress_watchdog,
    task_still_running,
)
from .recovery import recovery_hint"""

if "worker_progress" not in text:
    text = text.replace(IMPORT_OLD, IMPORT_NEW)

MANAGED_OLD = """            if front.skipped or front.action == "silent_skip" or not front.text:
                await self._publish_front_events(task_id, "front_response_skipped", "Front response skipped")
                await BUS.publish(
                    task_id,
                    "chat_tts",
                    "Acknowledged",
                    task_acknowledgement(prompt),
                    stage="understand",
                )
                return"""

MANAGED_NEW = """            if front.action == "silent_skip" or not front.text:
                await self._publish_front_events(task_id, "front_response_skipped", "Front response skipped")
                heuristic = classify_front_action(prompt)
                _action, ack_text, _rejected = enforce_front_safety(
                    heuristic,
                    fallback_text_for_action(heuristic),
                    user_text=prompt,
                    heuristic=heuristic,
                )
                if not ack_text:
                    ack_text = task_acknowledgement(prompt)
                await BUS.publish(
                    task_id,
                    "chat_tts",
                    "Acknowledged",
                    ack_text,
                    stage="understand",
                )
                delivery = await publish_owner_text(
                    ack_text,
                    source="task_chat",
                    speak=True,
                    user_prompt=prompt,
                )
                if delivery.get("tts_id"):
                    note_front_audio(None, max(0.0, (time.perf_counter() - turn_started) * 1000))
                async with SessionLocal() as session:
                    task = await session.get(Task, task_id)
                    if task and task.status in {"queued", "running", "waiting"} and not (task.result or "").strip():
                        await self._update(
                            task_id,
                            result=ack_text,
                            first_response_ms=round((time.perf_counter() - turn_started) * 1000, 1),
                            current_action=ack_text[:120],
                        )
                return"""

if MANAGED_NEW not in text:
    text = text.replace(MANAGED_OLD, MANAGED_NEW)

CONV_OLD = """        profile = resolve_profile(profile_name)
        if not MANAGER.provider or not MANAGER.state.loaded:
            await BUS.publish(task_id, "stage", "Loading local model", stage="model")
            await MANAGER.load(settings, profile_name)
        await self._update(task_id, stage="act", current_action="Replying", task_class=CONVERSATION_CLASS)
        working.task_class = CONVERSATION_CLASS
        prior = [
            message
            for message in (history or [])
            if message.role in {"user", "assistant"} and (message.content or "").strip()
        ]
        user_text = (extra_prompt or "").strip() or prompt
        messages = [ChatMessage(role="system", content=OWNER_CHAT_SYSTEM), *prior]
        briefing = await weather_system_message(user_text)
        if briefing:
            messages.insert(1, ChatMessage(role="system", content=briefing))
        last = prior[-1] if prior else None
        if last is None or last.role != "user" or (last.content or "").strip() != user_text:
            messages.append(ChatMessage(role="user", content=user_text))
        first_response_ms = 0.0
        model_started = time.perf_counter()
        stream_key = f"task:{task_id}"
        clear_stream_speak_state(stream_key)
        front_text = ""
        front_action = ""
        worker_started = False
        spoken_parts: list[str] = []"""

CONV_NEW = """        profile = resolve_profile(profile_name)
        turn_started = turn_started if turn_started is not None else time.perf_counter()
        await self._update(task_id, stage="act", current_action="Replying", task_class=CONVERSATION_CLASS)
        working.task_class = CONVERSATION_CLASS
        prior = [
            message
            for message in (history or [])
            if message.role in {"user", "assistant"} and (message.content or "").strip()
        ]
        user_text = (extra_prompt or "").strip() or prompt
        messages = [ChatMessage(role="system", content=OWNER_CHAT_SYSTEM), *prior]
        briefing = await weather_system_message(user_text)
        if briefing:
            messages.insert(1, ChatMessage(role="system", content=briefing))
        last = prior[-1] if prior else None
        if last is None or last.role != "user" or (last.content or "").strip() != user_text:
            messages.append(ChatMessage(role="user", content=user_text))

        prefetched_front = await generate_front_reply(
            user_text,
            history=prior,
            settings=settings,
            turn_started=turn_started,
        )
        stream_key = f"task:{task_id}"
        clear_stream_speak_state(stream_key)
        if prefetched_front.text and prefetched_front.action != "silent_skip":
            await self._publish_front_events(task_id, "front_response_started", "Front response started")
            await self._publish_front_events(
                task_id,
                "front_response_completed",
                "Front response",
                json.dumps(prefetched_front.as_dict(), ensure_ascii=False)[:4000],
            )
            await self._speak_front_reply(
                task_id,
                prefetched_front,
                prompt=prompt,
                stream_key=stream_key,
                turn_started=turn_started,
            )
            await self._persist_front_partial(
                task_id,
                messages,
                prefetched_front.text,
                first_response_ms=prefetched_front.first_text_ms or 0.0,
                current_action="Checking details…"
                if prefetched_front.action in {"ack_continue", "handoff_notice"}
                else "Replying",
            )

        progress_watch = asyncio.create_task(
            run_worker_progress_watchdog(
                task_id,
                turn_started=turn_started,
                settings=settings,
                should_continue=lambda: task_still_running(task_id),
            )
        )

        if not MANAGER.provider or not MANAGER.state.loaded:
            await BUS.publish(task_id, "stage", "Loading local model", stage="model")
            await MANAGER.load(settings, profile_name)
        first_response_ms = prefetched_front.first_text_ms or 0.0
        model_started = time.perf_counter()
        front_text = prefetched_front.text or ""
        front_action = prefetched_front.action or ""
        worker_started = False
        spoken_parts: list[str] = []"""

if "prefetched_front" not in text:
    text = text.replace(CONV_OLD, CONV_NEW)

ON_DELTA_OLD = """            if not delta:
                return
            spoken_parts.append(delta)"""
ON_DELTA_NEW = """            if not delta:
                return
            if lane == "worker":
                mark_worker_useful_owner_text(task_id)
            spoken_parts.append(delta)"""
if "mark_worker_useful_owner_text(task_id)" not in text:
    text = text.replace(ON_DELTA_OLD, ON_DELTA_NEW, 1)

if "prefetched_front=prefetched_front" not in text:
    text = text.replace(
        "                on_delta=on_delta,\n            ):",
        "                on_delta=on_delta,\n                prefetched_front=prefetched_front if prefetched_front.text else None,\n            ):",
        1,
    )

NUDGER_BLOCK = """        from ..persona.slow_turn_feedback import SlowTurnNudger

        nudger = SlowTurnNudger(user_text, started=turn_started or model_started, source="task_chat")
        nudger.start()
        try:"""
if NUDGER_BLOCK in text:
    text = text.replace(NUDGER_BLOCK, "        try:")

FINALLY_OLD = """        finally:
            await nudger.stop()

        content = ((done or {}).get("text") or front_text or "").strip()"""
FINALLY_NEW = """        finally:
            progress_watch.cancel()
            try:
                await progress_watch
            except asyncio.CancelledError:
                pass

        content = ((done or {}).get("text") or front_text or "").strip()"""
if FINALLY_NEW not in text:
    text = text.replace(FINALLY_OLD, FINALLY_NEW)

if "await nudger.stop()" in text:
    text = text.replace("            await nudger.stop()\n", "")

RUN_INIT_OLD = """        turn_started = time.perf_counter()
        settings = load_settings()
        REGISTRY.apply_settings(settings)"""
RUN_INIT_NEW = """        turn_started = time.perf_counter()
        settings = load_settings()
        clear_worker_progress_for_task(task_id)
        progress_watch: asyncio.Task | None = None
        REGISTRY.apply_settings(settings)"""
if "clear_worker_progress_for_task" not in text:
    text = text.replace(RUN_INIT_OLD, RUN_INIT_NEW)

MANAGED_WATCH_OLD = """        if not continue_existing and not pending_tool and not extra_prompt:
            if settings.front_responder.enabled:"""
MANAGED_WATCH_NEW = """        if not continue_existing and not pending_tool and not extra_prompt:
            progress_watch = asyncio.create_task(
                run_worker_progress_watchdog(
                    task_id,
                    turn_started=turn_started,
                    settings=settings,
                    should_continue=lambda: task_still_running(task_id),
                )
            )
            if settings.front_responder.enabled:"""
if "progress_watch = asyncio.create_task" not in text.split("_run_conversation")[0]:
    text = text.replace(MANAGED_WATCH_OLD, MANAGED_WATCH_NEW, 1)

MARK_WORKER = """                    result: ChatResult = await run_with_think_aloud(
                        task_id,
                        context=think_context,
                        operation=_model_turn,
                    )"""
MARK_WORKER_NEW = MARK_WORKER + """
                    if (result.content or "").strip():
                        mark_worker_useful_owner_text(task_id)"""
if "mark_worker_useful_owner_text(task_id)" not in text.split("_execute_tool")[0]:
    text = text.replace(MARK_WORKER, MARK_WORKER_NEW, 1)

TASK_FINALLY_OLD = """            await BUS.publish(task_id, "failed", "Task failed", str(exc), stage="failed")

    async def _execute_tool("""
TASK_FINALLY_NEW = """            await BUS.publish(task_id, "failed", "Task failed", str(exc), stage="failed")
        finally:
            if progress_watch is not None:
                progress_watch.cancel()
                try:
                    await progress_watch
                except asyncio.CancelledError:
                    pass

    async def _execute_tool("""
if "if progress_watch is not None" not in text:
    text = text.replace(TASK_FINALLY_OLD, TASK_FINALLY_NEW, 1)

LOOP.write_text(text)
print("Applied RFC-0127 loop patches")
