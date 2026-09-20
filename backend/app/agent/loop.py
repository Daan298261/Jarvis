from __future__ import annotations

import asyncio
import base64
import hashlib
import json
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from openai import APIConnectionError, APIStatusError

from ..coding.usage import record_task_usage
from ..config import AppSettings, load_settings
from ..db.models import Checkpoint, Task, ToolCallRecord, utcnow
from ..db.session import SessionLocal
from ..events import BUS
from ..inference.manager import MANAGER
from ..inference.profiles import ModelProfile, resolve_profile
from ..inference.prompt_budget import (
    ModelCapacityExceeded,
    PromptBudget,
    calculate_prompt_budget,
    context_capacity_error,
    is_context_overflow,
    recover_context_after_overflow,
)
from ..inference.vision import messages_need_vision, should_load_vision
from ..providers.base import ChatMessage, ChatResult, parse_tool_arguments, tool_arguments_valid
from ..policy.authorize import AuthorizationResult, authorize
from ..policy.computer_permissions import (
    confirmation_payload_for_tool,
    consume_once_grants,
    evaluate_tool_permissions,
    permission_ids_for_tool,
)
from ..tools.exposure import ToolExposure
from ..tools.registry import REGISTRY
from ..tools.safety import RiskLevel, classify_command, is_destructive_operation, needs_confirmation
from .chat_turns import visible_chat_turns
from .compaction import (
    compact_history,
    deserialize_messages,
    estimate_prompt_tokens,
    serialize_messages,
    SUMMARY_MARKER,
)
from .context_policy import initial_context_size, next_context_size
from .metrics import LiveTaskMetrics
from .model_policy import select_context_size, task_needs_vision
from .coding_workers import (
    complete_coding_route,
    format_routing_block,
    record_coding_outcome,
    record_coding_route,
    route_coding_task,
    route_software_task,
    should_route,
)
from .forensic import professional_prompt_block
from .escalation import (
    EscalationSignals,
    build_expert_brief,
    consult_expert,
    looks_like_architecture,
    should_escalate,
    user_requested_expert,
)
from .planning import (
    CONVERSATION_CLASS,
    MANAGED_TASK,
    RequestRoute,
    WorkingState,
    best_of_n_plan_prompt,
    best_of_n_select_prompt,
    classify_task,
    route_request,
    follow_up_stays_conversation,
    format_selected_plan,
    is_plain_conversation,
    parse_plan_block,
    parse_plan_candidates,
    resolve_execution_policy,
    select_best_plan,
)
from ..persona.chat_delivery import (
    clear_stream_speak_state,
    maybe_enqueue_streaming_social_tts,
    publish_owner_text,
    stream_speak_offset,
)
from ..persona.acknowledgements import task_acknowledgement
from ..persona.owner_chat import OWNER_CHAT_SYSTEM, owner_chat_max_tokens
from ..persona.think_aloud import run_with_think_aloud
from ..persona.weather import weather_system_message
from ..providers.completion_text import empty_generation_error
from .front_responder import (
    classify_front_action,
    enforce_front_safety,
    fallback_text_for_action,
    generate_front_reply,
    is_safe_front_speech,
    last_front_timing,
    note_front_audio,
    run_two_lane_chat,
    worker_required,
)
from .worker_progress import (
    clear_worker_progress_for_task,
    mark_worker_useful_owner_text,
    run_worker_progress_watchdog,
    task_still_running,
)
from .recovery import recovery_hint
from .tool_exposure import grant_requested_tools, schemas_for as exposure_schemas_for, tool_names_for
from .skills import as_prompt_block as skills_prompt_block
from .skills import (
    bind_parameters,
    has_secret_parameters,
    instantiate_steps,
    promote_from_trajectories,
    relevant_skills,
    steps_are_executable,
)
from .tooling import apply_capability_request, expose_called_tool, should_enable_thinking
from .ingress_gate import SAFE_LARGE_PASTE_SPEECH, run_ingress_gate
from .trajectory import gated_trajectory_lessons, record_trajectory
from ..memory.ingress_spill import ingress_prompt_segment
from .policy import policy_guidance
from .prompts import (
    CONTINUE_PROMPT,
    CRITIC_PROMPT,
    PLAN_PROMPT,
    STOP_AND_REPORT,
    SYSTEM_PROMPT,
    VERIFY_PROMPT,
    VERIFY_REQUIRED_PROMPT,
)
from .docs_first_grounding import DocsFirstContext, maybe_docs_first
from .turn_working_set import apply_working_set_to_system, compose_turn_working_set
from .self_dev import KillSwitchActive, kill_switch_active


def _environment_block(settings: AppSettings) -> str:
    home = Path.home()
    allowed = "\n".join(f"- {p}" for p in (settings.allowed_directories or []))
    return (
        "\n\nEnvironment:\n"
        f"- Windows user profile: {home}\n"
        f"- Desktop: {home / 'Desktop'}\n"
        f"- Documents: {home / 'Documents'}\n"
        f"- Allowed directories:\n{allowed or '- (defaults)'}\n"
        "Never use a different username than the profile above.\n"
    )


def _image_message(path: str, prompt: str = "Inspect this image and use it to decide the next action.") -> ChatMessage:
    data = Path(path).read_bytes()
    b64 = base64.b64encode(data).decode("ascii")
    mime = "image/png" if path.lower().endswith(".png") else "image/jpeg"
    return ChatMessage(
        role="user",
        content=[
            {"type": "text", "text": prompt + f"\nImage path: {path}"},
            {"type": "image_url", "image_url": {"url": f"data:{mime};base64,{b64}"}},
        ],
    )


def _as_utc(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc)


def _exposed_csv(working: WorkingState, prompt: str | None = None) -> str:
    return ",".join(
        tool_names_for(
            working.task_class,
            working.requested_tools,
            security_role=working.security_role,
            prompt=prompt or working.goal,
            needs_tools=working.ingress_needs_tools,
        )
    )


def _latest_user_text(messages: list[ChatMessage], fallback: str = "") -> str:
    for message in reversed(messages or []):
        if message.role != "user":
            continue
        text = message.content if isinstance(message.content, str) else ""
        if text.strip():
            return text.strip()
    return (fallback or "").strip()


def _authorization_observation(result: AuthorizationResult) -> str:
    payload = json.dumps({"authorization": result.as_dict()})
    if result.requires_approval:
        return f"ERROR: Authorization approval required: {result.reason}\n{payload}"
    return f"ERROR: Authorization denied: {result.reason}\n{payload}"


def _tool_authorization(
    name: str,
    arguments: dict[str, Any],
    *,
    approved: bool = False,
    profile_id: str | None = None,
) -> AuthorizationResult:
    tool_meta = REGISTRY.tools.get(name)
    risk = tool_meta.risk if tool_meta else RiskLevel.MEDIUM
    command = arguments.get("command") if isinstance(arguments, dict) else None
    if command:
        risk = max(risk, classify_command(command), key=lambda item: list(RiskLevel).index(item))
    action = arguments.get("action") if isinstance(arguments, dict) else None
    if is_destructive_operation(name, arguments, command):
        risk = RiskLevel.IRREVERSIBLE
    return authorize(
        name,
        action=action,
        arguments=arguments if isinstance(arguments, dict) else None,
        risk=risk,
        profile_id=profile_id,
        approved=approved,
    )


def _tool_needs_operator_pause(
    autonomy: str,
    risk: RiskLevel,
    command: str | None,
    tool_name: str | None,
    arguments: dict[str, Any] | None,
) -> bool:
    if needs_confirmation(autonomy, risk, command, tool_name=tool_name, arguments=arguments):
        return True
    return evaluate_tool_permissions(tool_name or "", arguments or {}).status == "ask"


def _permission_denied_observation(tool_name: str | None, arguments: dict[str, Any] | None) -> str | None:
    decision = evaluate_tool_permissions(tool_name or "", arguments or {})
    if decision.status == "deny":
        return f"ERROR: Permission denied: {decision.reason}"
    return None


class AgentRuntime:
    def __init__(self) -> None:
        self._tasks: dict[str, asyncio.Task] = {}
        self._heartbeat_tasks: dict[str, asyncio.Task] = {}
        self._last_heartbeat: dict[str, datetime] = {}
        self._cancel = set()

    async def _heartbeat_loop(self, task_id: str) -> None:
        try:
            while True:
                self._last_heartbeat[task_id] = utcnow()
                await asyncio.sleep(5)
        except asyncio.CancelledError:
            raise

    def _start_runner(self, task_id: str, coroutine: Any) -> asyncio.Task:
        previous = self._heartbeat_tasks.pop(task_id, None)
        if previous:
            previous.cancel()
        runner = asyncio.create_task(coroutine)
        heartbeat = asyncio.create_task(self._heartbeat_loop(task_id))
        self._tasks[task_id] = runner
        self._heartbeat_tasks[task_id] = heartbeat

        def finish(_finished: asyncio.Task) -> None:
            current = self._heartbeat_tasks.pop(task_id, None)
            if current:
                current.cancel()
            self._last_heartbeat[task_id] = utcnow()

        runner.add_done_callback(finish)
        return runner

    def runtime_status(self, task_id: str) -> dict[str, Any]:
        runner = self._tasks.get(task_id)
        alive = bool(runner and not runner.done())
        heartbeat = self._last_heartbeat.get(task_id)
        return {
            "alive": alive,
            "last_heartbeat_at": heartbeat.isoformat() if heartbeat else None,
            "heartbeat_status": "alive" if alive else "stopped",
        }

    async def create_task(
        self,
        prompt: str,
        autonomy: str | None = None,
        profile: str | None = None,
        execution_mode: str | None = None,
        request_id: str | None = None,
        security_role: str | None = None,
    ) -> Task:
        if kill_switch_active():
            raise KillSwitchActive(
                "Emergency stop is active (data/STOP_JARVIS). "
                "New tasks are blocked until POST /api/self-dev/resume."
            )
        # Mobile and scheduled submissions use a stable ID across retries/restarts.
        if request_id:
            async with SessionLocal() as session:
                existing = await session.get(Task, request_id)
                if existing:
                    if existing.status == "queued" and request_id not in self._tasks:
                        self._tasks[request_id] = asyncio.create_task(self._run(request_id, continue_existing=False))
                    return existing
        settings = load_settings()
        mode = execution_mode or settings.execution_mode or "balanced"
        route = route_request(prompt)
        task_class = route.task_class
        if security_role == "blue-team" and route.kind != "managed_task":
            task_class = classify_task(prompt)
            route = RequestRoute(MANAGED_TASK, task_class)
        REGISTRY.apply_settings(settings)
        task = Task(
            id=request_id or str(uuid.uuid4()),
            title=prompt.strip().splitlines()[0][:120],
            prompt=prompt,
            status="queued",
            stage="queued",
            autonomy=autonomy or settings.autonomy,
            profile=profile or settings.inference.profile,
            execution_mode=mode,
            task_class=task_class,
            security_role=security_role or "",
            response_route=route.kind,
            exposed_tools=",".join(tool_names_for(task_class, security_role=security_role or "", prompt=prompt)),
        )
        async with SessionLocal() as session:
            session.add(task)
            await session.commit()
        if route.kind == "managed_task":
            acknowledgement = task_acknowledgement(prompt)
            task.current_action = acknowledgement
            async with SessionLocal() as session:
                stored = await session.get(Task, task.id)
                assert stored
                stored.current_action = acknowledgement
                stored.first_response_ms = 0.0
                await session.commit()
            await BUS.publish(task.id, "acknowledgement", "Acknowledged", acknowledgement, stage="queued")
        self._start_runner(task.id, self._run(task.id, continue_existing=False))
        return task

    async def continue_task(self, task_id: str, prompt: str | None = None) -> Task:
        if kill_switch_active():
            raise KillSwitchActive(
                "Emergency stop is active (data/STOP_JARVIS). "
                "New tasks are blocked until POST /api/self-dev/resume."
            )
        async with SessionLocal() as session:
            task = await session.get(Task, task_id)
            if not task:
                raise KeyError(task_id)
            if prompt:
                previous_prompt = task.prompt or ""
                task.prompt = previous_prompt + "\n\nFollow-up: " + prompt
                history = deserialize_messages(task.conversation_json)
                if not any(message.role in {"user", "assistant"} for message in history):
                    seeded = visible_chat_turns(previous_prompt, "[]", task.result or "", task.error or "")
                    history = [
                        ChatMessage(role=item["role"], content=item["content"])
                        for item in seeded
                    ]
                last = history[-1] if history else None
                if last is None or last.role != "user" or (last.content or "").strip() != prompt.strip():
                    history.append(ChatMessage(role="user", content=prompt.strip()))
                task.conversation_json = serialize_messages(history)
            task.status = "queued"
            task.waiting_for_confirmation = False
            task.updated_at = utcnow()
            await session.commit()
        self._start_runner(task_id, self._run(task_id, continue_existing=True, extra_prompt=prompt))
        return task

    async def confirm_task(
        self,
        task_id: str,
        approved: bool,
        expected_payload: str | None = None,
        grant_mode: str | None = None,
        permission_id: str | None = None,
    ) -> Task:
        async with SessionLocal() as session:
            task = await session.get(Task, task_id)
            if not task:
                raise KeyError(task_id)
            if expected_payload is not None:
                from sqlalchemy import update
                # Bind mobile approval to exactly one still-pending action. A stale
                # dialog or concurrent second device cannot approve its replacement.
                changed = await session.execute(update(Task).where(
                    Task.id == task_id, Task.waiting_for_confirmation.is_(True),
                    Task.confirmation_payload == expected_payload,
                ).values(waiting_for_confirmation=False))
                if changed.rowcount != 1:
                    raise ValueError("The pending action changed or was already resolved")
            payload = json.loads(task.confirmation_payload or "{}")
            if approved:
                from ..policy.computer_permissions import apply_grant

                mode = (grant_mode or "").strip().lower()
                if mode in {"allow_once", "allow_session", "always"}:
                    ids: list[str] = []
                    primary = permission_id or payload.get("permission_id")
                    if primary:
                        ids.append(str(primary))
                    for extra in payload.get("pending") or []:
                        text = str(extra)
                        if text not in ids:
                            ids.append(text)
                    try:
                        for item in ids:
                            apply_grant(item, mode)
                    except PermissionError as exc:
                        approved = False
                        await BUS.publish(task_id, "confirm", "Permission grant refused", str(exc)[:1500], stage="act")
            if not approved:
                task.status = "cancelled"
                task.stage = "cancelled"
                task.waiting_for_confirmation = False
                await session.commit()
                await BUS.publish(task_id, "cancelled", "User rejected the pending action")
                return task
            task.waiting_for_confirmation = False
            task.status = "running"
            await session.commit()
        self._start_runner(task_id, self._run(task_id, continue_existing=True, pending_tool=payload))
        return task

    def cancel(self, task_id: str) -> None:
        self._cancel.add(task_id)
        running = self._tasks.get(task_id)
        if running:
            running.cancel()

    async def _update(self, task_id: str, **fields: Any) -> None:
        async with SessionLocal() as session:
            task = await session.get(Task, task_id)
            if not task:
                return
            for key, value in fields.items():
                setattr(task, key, value)
            task.updated_at = utcnow()
            if not task.started_at and fields.get("status") == "running":
                task.started_at = utcnow()
            if _as_utc(task.started_at) and fields.get("status") in {"completed", "failed", "cancelled"}:
                finished = utcnow()
                task.finished_at = finished
                started = _as_utc(task.started_at)
                if started:
                    task.duration_seconds = (finished - started).total_seconds()
            await session.commit()

    async def _complete(
        self,
        task_id: str,
        messages: list[ChatMessage],
        content: str,
        verification: str,
        working: WorkingState | None = None,
        metrics: LiveTaskMetrics | None = None,
    ) -> None:
        fields = {
            "status": "completed",
            "stage": "completed",
            "result": content,
            "conversation_json": serialize_messages(messages),
            "verification": verification,
            "current_action": "Completed",
            "current_tool": "",
        }
        if metrics is not None:
            fields.update(metrics.as_fields())
        await self._update(task_id, **fields)
        if working is not None:
            await record_trajectory(task_id, working, "completed")
            await record_task_usage(task_id, "completed", verified=bool(verification))
            for skill in await promote_from_trajectories():
                await BUS.publish(task_id, "progress", f"Promoted reusable skill: {skill.name}", skill.description[:800])
        await complete_coding_route(task_id, "completed", verification)
        await self._release_lazy_vision()
        await BUS.publish(task_id, "completed", "Task completed", content[:2000], stage="completed")

    async def _note_coding_outcome(self, task_id: str, working: WorkingState, outcome: str, verification: str = "") -> None:
        if not working.coding_worker:
            return
        duration = 0.0
        async with SessionLocal() as session:
            task = await session.get(Task, task_id)
            if task:
                duration = float(task.duration_seconds or 0)
        await record_coding_outcome(
            task_id=task_id,
            task_class=working.task_class,
            worker_id=working.coding_worker,
            complexity=working.coding_complexity,
            outcome=outcome,
            verification=verification[:2000],
            duration_seconds=duration,
        )

    async def _release_lazy_vision(self) -> None:
        try:
            await MANAGER.release_vision(load_settings())
        except Exception:
            pass

    async def _recover_context_pressure(
        self,
        task_id: str,
        messages: list[ChatMessage],
        working: WorkingState,
        profile: ModelProfile,
        settings: AppSettings,
        *,
        tools: list[dict[str, Any]] | None,
        max_tokens: int | None,
    ) -> tuple[list[ChatMessage], list[dict[str, Any]] | None, bool, ModelProfile]:
        async def _emit(kind: str, budget: PromptBudget, detail: str) -> None:
            payload = json.dumps({**budget.as_dict(), "detail": detail})
            await BUS.publish(task_id, kind, kind.replace("_", " ").title(), payload[:4000], stage="act")

        updated, recovered_tools, recovered = await recover_context_after_overflow(
            messages,
            tools,
            profile,
            max_tokens,
            settings,
            manager=MANAGER,
            working_state_block=working.as_prompt_block(),
            emit=_emit,
        )
        if not recovered:
            from ..persona.inference_context import maybe_autoselect_runtime_for_budget
            budget = calculate_prompt_budget(messages, tools, profile=profile, max_tokens=max_tokens, active_context=MANAGER.live_context_size())
            switched = await maybe_autoselect_runtime_for_budget(budget, profile, settings, user_prompt=working.goal or "", task_id=task_id)
            if switched:
                profile = switched
                updated, recovered_tools, recovered = await recover_context_after_overflow(messages, tools, profile, max_tokens, settings, manager=MANAGER, working_state_block=working.as_prompt_block(), emit=_emit)
        return updated, recovered_tools, recovered, profile

    async def _publish_front_events(self, task_id: str, kind: str, title: str, detail: str = "", *, persist: bool = True) -> None:
        await BUS.publish(task_id, kind, title, detail, stage="chat", persist=persist)

    async def _speak_front_reply(
        self,
        task_id: str,
        front,
        *,
        prompt: str,
        stream_key: str,
        turn_started: float,
        source: str = "task_chat",
    ) -> None:
        settings = load_settings()
        if not settings.front_responder.speak_immediately:
            return
        if not front or not is_safe_front_speech(front.action, front.text):
            return
        spoken = front.text if front.text.endswith((".", "!", "?")) else f"{front.text}."
        early_id = maybe_enqueue_streaming_social_tts(
            spoken,
            source=source,
            stream_key=stream_key,
            user_prompt=prompt,
        )
        audio_ms = max(0.0, (time.perf_counter() - turn_started) * 1000)
        if early_id:
            await BUS.publish(task_id, "chat_tts", "Speak reply", front.text, stage="chat")
            note_front_audio(None, audio_ms)
            front.first_audio_ms = audio_ms
            return
        delivery = await publish_owner_text(
            front.text,
            source=source,
            speak=True,
            user_prompt=prompt,
        )
        if delivery.get("tts_id"):
            await BUS.publish(task_id, "chat_tts", "Speak reply", front.text, stage="chat")
            note_front_audio(None, audio_ms)
            front.first_audio_ms = audio_ms

    async def _persist_front_partial(
        self,
        task_id: str,
        messages: list[ChatMessage],
        front_text: str,
        *,
        first_response_ms: float,
        current_action: str,
    ) -> None:
        visible = [
            message
            for message in messages
            if message.role in {"user", "assistant"} and (message.content or "").strip()
        ]
        if not visible or visible[-1].role != "assistant":
            visible.append(ChatMessage(role="assistant", content=front_text))
        else:
            visible[-1] = ChatMessage(role="assistant", content=front_text)
        await self._update(
            task_id,
            result=front_text,
            conversation_json=serialize_messages(visible),
            first_response_ms=round(first_response_ms, 1),
            current_action=current_action,
        )

    async def _run_managed_front_lane(
        self,
        task_id: str,
        prompt: str,
        settings: AppSettings,
        *,
        turn_started: float,
        history: list[ChatMessage] | None = None,
    ) -> None:
        """Fast first reply/TTS while a managed worker continues (does not block the loop)."""
        try:
            await self._publish_front_events(task_id, "front_response_started", "Front response started")
            front = await generate_front_reply(
                prompt,
                history=history,
                settings=settings,
                turn_started=turn_started,
            )
            if front.action == "silent_skip" or not front.text:
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
                return
            await self._publish_front_events(
                task_id,
                "front_response_completed",
                "Front response",
                json.dumps(front.as_dict(), ensure_ascii=False)[:4000],
            )
            stream_key = f"task:{task_id}:front"
            clear_stream_speak_state(stream_key)
            await self._speak_front_reply(
                task_id,
                front,
                prompt=prompt,
                stream_key=stream_key,
                turn_started=turn_started,
            )
            async with SessionLocal() as session:
                task = await session.get(Task, task_id)
                if task and task.status in {"queued", "running", "waiting"} and not (task.result or "").strip():
                    await self._update(
                        task_id,
                        result=front.text,
                        first_response_ms=round(front.first_text_ms or (time.perf_counter() - turn_started) * 1000, 1),
                        current_action=front.text[:120],
                    )
        except Exception:
            await BUS.publish(
                task_id,
                "chat_tts",
                "Acknowledged",
                task_acknowledgement(prompt),
                stage="understand",
            )

    async def _run_conversation(
        self,
        task_id: str,
        prompt: str,
        profile_name: str | None,
        settings: AppSettings,
        working: WorkingState,
        metrics: LiveTaskMetrics,
        *,
        history: list[ChatMessage] | None = None,
        extra_prompt: str | None = None,
        turn_started: float | None = None,
    ) -> None:
        """Plain owner dialogue: front responder first, then worker if needed."""
        profile = resolve_profile(profile_name)
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
        from ..memory.obsidian_vault import public_binding_status, vault_prompt_block

        if public_binding_status().get("bound"):
            vault_block = vault_prompt_block(user_text)
            if vault_block:
                messages.insert(1, ChatMessage(role="system", content=vault_block))
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
        front_spoken_early = False
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
            front_spoken_early = True
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
        spoken_parts: list[str] = []

        from ..persona.inference_context import ensure_context_for_messages, model_lane_event_payload
        from ..agent.front_responder import resolve_front_model_id

        async def _expand_notice(before: int, after: int) -> None:
            front = await generate_front_reply(
                user_text,
                history=prior,
                settings=settings,
                turn_started=turn_started or model_started,
            )
            if front.text:
                await self._speak_front_reply(
                    task_id,
                    front,
                    prompt=prompt,
                    stream_key=stream_key,
                    turn_started=turn_started or model_started,
                )
            await BUS.publish(
                task_id,
                "model_lane",
                "Context resize",
                model_lane_event_payload(
                    lane="system",
                    model=resolve_front_model_id(settings),
                    text=f"Expanding context {before} → {after}",
                ),
                stage="model",
                persist=False,
            )

        await ensure_context_for_messages(
            messages,
            settings=settings,
            profile_name=profile.name,
            on_expanding=_expand_notice,
            task_id=task_id,
        )
        profile = resolve_profile(MANAGER.state.profile or profile.name)

        async def worker_stream():
            async for delta in MANAGER.chat_stream(
                messages,
                temperature=profile.temperature,
                top_p=profile.top_p,
                top_k=profile.top_k,
                max_tokens=owner_chat_max_tokens(profile),
                thinking=False,
            ):
                yield delta

        async def on_delta(lane: str, delta: str) -> None:
            nonlocal first_response_ms
            if not delta:
                return
            if lane == "worker":
                mark_worker_useful_owner_text(task_id)
            spoken_parts.append(delta)
            elapsed = max(0.0, (time.perf_counter() - (turn_started or model_started)) * 1000)
            if not first_response_ms:
                first_response_ms = elapsed
                await self._update(task_id, first_response_ms=round(first_response_ms, 1))
            accumulated = "".join(spoken_parts)
            early_id = maybe_enqueue_streaming_social_tts(
                accumulated,
                source="task_chat",
                stream_key=stream_key,
                user_prompt=prompt,
            )
            if early_id:
                await BUS.publish(
                    task_id,
                    "chat_tts",
                    "Speak reply",
                    accumulated[: stream_speak_offset(stream_key)],
                    stage="chat",
                )
                note_front_audio(None, elapsed)
            from ..persona.inference_context import model_lane_event_payload
            from ..agent.front_responder import resolve_front_model_id

            lane_model = resolve_front_model_id(settings) if lane == "front" else str(
                getattr(MANAGER.provider, "model", "") or profile.name
            )
            await BUS.publish(
                task_id,
                "assistant_delta",
                "Reply",
                delta,
                stage="chat",
                persist=False,
            )
            await BUS.publish(
                task_id,
                "model_lane",
                f"{lane} output",
                model_lane_event_payload(lane=lane, model=lane_model, text=delta[:240]),
                stage="chat",
                persist=False,
            )

        try:
            done: dict[str, Any] | None = None
            async for event in run_two_lane_chat(
                user_text,
                history=prior,
                settings=settings,
                turn_started=turn_started or model_started,
                worker_stream=worker_stream,
                on_delta=on_delta,
                prefetched_front=prefetched_front if prefetched_front.text else None,
            ):
                kind = event.get("type")
                if kind == "front_response_started":
                    await self._publish_front_events(task_id, "front_response_started", "Front response started")
                elif kind == "front_response_skipped":
                    await self._publish_front_events(task_id, "front_response_skipped", "Front response skipped")
                elif kind == "front_response_completed":
                    front = event.get("reply")
                    front_text = getattr(front, "text", "") or ""
                    front_action = getattr(front, "action", "") or ""
                    if front:
                        await self._publish_front_events(
                            task_id,
                            "front_response_completed",
                            "Front response",
                            json.dumps(front.as_dict(), ensure_ascii=False)[:4000],
                        )
                        if front_text and not front_spoken_early:
                            await self._persist_front_partial(
                                task_id,
                                messages,
                                front_text,
                                first_response_ms=front.first_text_ms or first_response_ms,
                                current_action="Checking details…" if front.action in {"ack_continue", "handoff_notice"} else "Replying",
                            )
                        if not front_spoken_early:
                            await self._speak_front_reply(
                                task_id,
                                front,
                                prompt=prompt,
                                stream_key=stream_key,
                                turn_started=turn_started or model_started,
                            )
                elif kind == "worker_response_started":
                    worker_started = True
                    await self._publish_front_events(task_id, "worker_response_started", "Worker response started")
                elif kind == "worker_response_completed":
                    await self._publish_front_events(task_id, "worker_response_completed", "Worker response completed")
                elif kind == "done":
                    done = event
        except Exception as exc:
            clear_stream_speak_state(stream_key)
            err = str(exc)
            await self._update(
                task_id,
                status="failed",
                stage="failed",
                error=err,
                result=err,
                **metrics.as_fields(),
            )
            await BUS.publish(task_id, "failed", "Conversation failed", err, stage="failed")
            return
        finally:
            progress_watch.cancel()
            try:
                await progress_watch
            except asyncio.CancelledError:
                pass
            clear_worker_progress_for_task(task_id)

        timing = (done or {}).get("timing") or last_front_timing()
        done_worker = str((done or {}).get("worker_text") or "").strip()
        merged = str((done or {}).get("text") or "").strip()
        front_action_resolved = front_action or str((done or {}).get("front_action") or "")
        if worker_required(front_action_resolved) and not done_worker:
            content = ""
        else:
            content = merged or front_text or ""
        content = content.strip()
        front_obj = (done or {}).get("front")
        model_ms = max(0.0, (time.perf_counter() - model_started) * 1000)
        if front_obj and not getattr(front_obj, "skipped", False):
            metrics.note_model_elapsed(max(1.0, float(getattr(front_obj, "complete_ms", 0) or 0)))
        if worker_started:
            metrics.note_model_elapsed(max(1.0, float(timing.get("worker_complete_ms") or model_ms)))
        elif not front_obj or getattr(front_obj, "skipped", False):
            metrics.note_model_elapsed(model_ms)
        if not first_response_ms:
            first_response_ms = float(timing.get("front_first_text_ms") or timing.get("worker_first_text_ms") or 0)
            if first_response_ms:
                await self._update(task_id, first_response_ms=round(first_response_ms, 1))
        if not content:
            err = empty_generation_error()
            await self._update(
                task_id,
                status="failed",
                stage="failed",
                error=err,
                result=err,
                **metrics.as_fields(),
            )
            await BUS.publish(task_id, "failed", "Conversation failed", err, stage="failed")
            return
        await publish_owner_text(
            content,
            source="task_chat",
            speak=True,
            user_prompt=prompt,
            tts_char_offset=stream_speak_offset(stream_key),
        )
        from .background_verify import schedule_background_verification

        schedule_background_verification(
            user_text,
            content,
            source="task_chat",
            task_id=task_id,
        )
        clear_stream_speak_state(stream_key)
        await BUS.publish(
            task_id,
            "response_timing",
            "Response timing",
            (
                f"First word {first_response_ms / 1000:.2f}s · completed {model_ms / 1000:.2f}s\n"
                + json.dumps(
                    {
                        **timing,
                        "first_word_s": round((first_response_ms or 0) / 1000, 2),
                        "completed_s": round(model_ms / 1000, 2),
                        "front_action": front_action or timing.get("front_action"),
                    },
                    ensure_ascii=False,
                )
            )[:4000],
            stage="chat",
        )
        if messages and messages[-1].role == "assistant":
            messages[-1] = ChatMessage(role="assistant", content=content)
        else:
            messages.append(ChatMessage(role="assistant", content=content))
        working.verified = True
        await self._complete(task_id, messages, content, content, working, metrics)

    async def _run(
        self,
        task_id: str,
        continue_existing: bool,
        extra_prompt: str | None = None,
        pending_tool: dict[str, Any] | None = None,
    ) -> None:
        turn_started = time.perf_counter()
        progress_watch: asyncio.Task | None = None
        settings = load_settings()
        REGISTRY.apply_settings(settings)
        exposure = ToolExposure("mixed")
        REGISTRY.bind_exposure(exposure)
        fields = {
            "status": "running",
            "stage": "understand",
            "current_action": "Understanding the request",
            "waiting_for_confirmation": False,
            "first_response_ms": 0.0,
        }
        if not continue_existing:
            fields["started_at"] = utcnow()
        await self._update(task_id, **fields)
        await BUS.publish(task_id, "stage", "Understanding the request", stage="understand")
        async with SessionLocal() as session:
            task = await session.get(Task, task_id)
            assert task
            prompt = task.prompt
            autonomy = task.autonomy
            profile_name = task.profile
            execution_mode = task.execution_mode or settings.execution_mode or "balanced"
            existing = deserialize_messages(task.conversation_json)
            working = WorkingState.loads(task.compact_memory)
            if not working.goal:
                working.goal = prompt.strip().splitlines()[0][:240]
            if not working.task_class:
                working.task_class = task.task_class or classify_task(prompt)
            working.security_role = getattr(task, "security_role", "") or ""
        gate_text = (extra_prompt or prompt).strip()
        active_prompt = gate_text or prompt
        if gate_text and not continue_existing:
            ingress_gate = await run_ingress_gate(
                user_text=gate_text,
                task_class=working.task_class or classify_task(gate_text),
                task_id=task_id,
                conversation_id=task_id,
                settings=settings,
            )
            working.ingress_blob_id = ingress_gate.blob_id or ""
            working.ingress_size_class = ingress_gate.size_class
            working.ingress_needs_tools = ingress_gate.needs_tools
            working.ingress_complexity_hint = ingress_gate.complexity_hint
            await self._update(task_id, compact_memory=working.dumps())
            await BUS.publish(
                task_id,
                "ingress_size_classified",
                "Ingress size classified",
                json.dumps(ingress_gate.as_dict(), ensure_ascii=False)[:4000],
                stage="understand",
            )
            if ingress_gate.blob_id:
                await BUS.publish(
                    task_id,
                    "ingress_spill_stored",
                    "Ingress spill stored",
                    json.dumps(
                        {
                            "blob_id": ingress_gate.blob_id,
                            "byte_size": ingress_gate.byte_size,
                            "token_estimate": ingress_gate.token_estimate,
                        },
                        ensure_ascii=False,
                    )[:2000],
                    stage="understand",
                )
            if ingress_gate.vault_mirrored:
                await BUS.publish(
                    task_id,
                    "ingress_spill_vault_optional",
                    "Ingress spill mirrored to vault",
                    json.dumps({"blob_id": ingress_gate.blob_id}, ensure_ascii=False)[:500],
                    stage="understand",
                )
            if ingress_gate.size_class == "big":
                if settings.front_responder.enabled:
                    await BUS.publish(
                        task_id,
                        "chat_tts",
                        "Processing large paste",
                        SAFE_LARGE_PASTE_SPEECH,
                        stage="understand",
                    )
        if working.ingress_blob_id and working.ingress_size_class == "big":
            spill = await ingress_prompt_segment(working.ingress_blob_id, working.goal or active_prompt)
            if spill:
                active_prompt = f"{gate_text[:1200]}\n\n{spill}"
        metrics = LiveTaskMetrics()
        follow_route = route_request(extra_prompt or prompt) if extra_prompt else None
        if (working.task_class == CONVERSATION_CLASS or (follow_route and follow_route.kind != "managed_task")) and not pending_tool:
            if follow_up_stays_conversation(extra_prompt, security_role=working.security_role):
                working.task_class = CONVERSATION_CLASS
                await self._run_conversation(
                    task_id,
                    prompt,
                    profile_name,
                    settings,
                    working,
                    metrics,
                    history=existing,
                    extra_prompt=extra_prompt,
                    turn_started=turn_started,
                )
                return
            working.task_class = (follow_route.task_class if follow_route else classify_task(extra_prompt or prompt))
        if not continue_existing and not pending_tool and not extra_prompt:
            progress_watch = asyncio.create_task(
                run_worker_progress_watchdog(
                    task_id,
                    turn_started=turn_started,
                    settings=settings,
                    should_continue=lambda: task_still_running(task_id),
                )
            )
            if settings.front_responder.enabled:
                asyncio.create_task(
                    self._run_managed_front_lane(
                        task_id,
                        extra_prompt or prompt,
                        settings,
                        turn_started=turn_started,
                        history=existing,
                    )
                )
            else:
                await BUS.publish(
                    task_id,
                    "chat_tts",
                    "Acknowledged",
                    task_acknowledgement(prompt),
                    stage="understand",
                )
        await self._update(task_id, exposed_tools=_exposed_csv(working, extra_prompt or prompt))
        policy = resolve_execution_policy(execution_mode)
        profile = resolve_profile(profile_name)
        from ..inference.ram_policy import hardware_context_ceiling

        effective_cap = hardware_context_ceiling(profile, settings)
        recommended_context = select_context_size(
            task_class=working.task_class,
            execution_mode=execution_mode,
            profile_name=profile_name,
            profile_cap=effective_cap,
            prompt=prompt,
        )
        need_vision = should_load_vision(working.task_class)
        working.recommended_context = recommended_context
        working.vision_requested = need_vision
        plan_prompt = best_of_n_plan_prompt(policy.best_of_n) if policy.best_of_n > 1 else PLAN_PROMPT
        vision_mode = settings.inference.vision_mode or "lazy"
        need_vision = task_needs_vision(working.task_class, prompt, vision_mode)
        wanted_context = select_context_size(
            task_class=working.task_class,
            execution_mode=execution_mode,
            profile_name=profile.name,
            profile_cap=effective_cap,
            prompt=prompt,
            current=MANAGER.state.context_size if MANAGER.state.loaded else None,
        )
        if not MANAGER.provider or not MANAGER.state.loaded:
            await BUS.publish(task_id, "stage", "Loading local model", stage="model")
            await MANAGER.load(settings, profile_name)
        target_ctx = initial_context_size(working.task_class, profile)
        live_ctx = await MANAGER.apply_context(settings, target_ctx, allow_shrink=True)
        if live_ctx != effective_cap:
            await BUS.publish(
                task_id,
                "progress",
                f"Using {live_ctx} context (RAM-aware cap {effective_cap})",
                stage="model",
            )
        provider = MANAGER.provider
        assert provider is not None
        await BUS.publish(
            task_id,
            "progress",
            f"Context {MANAGER.state.context_size} · vision {'on' if MANAGER.state.vision_loaded else vision_mode} · thinking {'selective' if profile.thinking else 'off'}",
            stage="understand",
        )

        recent_hashes: list[str] = []
        max_steps = policy.max_steps
        verifying = False
        critic_done = False
        tools_used = False
        consecutive_failures = 0
        failures_by_tool: dict[str, int] = {}
        tool_rounds = 0
        verify_tool_rounds = 0
        last_tool_name = ""
        last_tool_action = ""
        same_tool_streak = 0
        force_final = False
        plan_candidates: list = []
        awaiting_plan_selection = False
        best_of_n_complete = policy.best_of_n <= 1
        skill_requires_verify = False
        metrics = LiveTaskMetrics()
        already_escalated = bool(getattr(working, "escalated", False))
        critic_rejected = False
        exposed_tools = set(
            tool_names_for(
                working.task_class,
                working.requested_tools,
                security_role=working.security_role,
                prompt=active_prompt,
                needs_tools=working.ingress_needs_tools,
            )
        )
        if working.ingress_needs_tools is False:
            exposed_tools.update({"request_capability"})
        else:
            exposed_tools.update({"request_tools", "request_capability"})

        if existing and continue_existing:
            messages = existing
            if extra_prompt:
                follow_up_grounding = maybe_docs_first(DocsFirstContext(user_message=extra_prompt))
                if follow_up_grounding and follow_up_grounding.prompt_block():
                    for idx, message in enumerate(messages):
                        if message.role == "system":
                            messages[idx] = ChatMessage(
                                role="system",
                                content=message.content + "\n\n" + follow_up_grounding.prompt_block(),
                            )
                            break
                messages.append(ChatMessage(role="user", content=CONTINUE_PROMPT + "\n\n" + extra_prompt))
            else:
                messages.append(ChatMessage(role="user", content=CONTINUE_PROMPT))
        else:
            system_prompt = SYSTEM_PROMPT + "\n\n" + policy_guidance(active_prompt) + _environment_block(settings)
            grounding = maybe_docs_first(DocsFirstContext(user_message=active_prompt))
            if grounding and grounding.prompt_block():
                system_prompt += "\n\n" + grounding.prompt_block()
            matched_skills = await relevant_skills(working.task_class, working.goal)
            skills = skills_prompt_block(matched_skills)
            if skills:
                system_prompt += "\n\n" + skills
                await BUS.publish(task_id, "progress", "Applying a known skill", skills[:1500], stage="understand")
            if should_route(working.task_class, prompt):
                decision = route_software_task(prompt, task_class=working.task_class)
                await record_coding_route(task_id, decision)
                routing = await route_coding_task(prompt, task_class=working.task_class)
                working.coding_worker = decision.selected_worker or routing.get("execute_worker") or ""
                working.coding_tier = decision.tier_name or ""
                working.coding_complexity = int(decision.score or routing.get("complexity") or 0)
                system_prompt += "\n\n" + format_routing_block(routing)
                await BUS.publish(task_id, "progress", "Coding worker selected", format_routing_block(routing)[:1500], stage="understand")
            budget_headroom = None
            try:
                budget_headroom = max(
                    0,
                    profile.context_size
                    - estimate_prompt_tokens(
                        [ChatMessage(role="system", content=system_prompt), ChatMessage(role="user", content=active_prompt)]
                    ),
                )
            except Exception:
                budget_headroom = None
            lessons, injected_rows, dropped = await gated_trajectory_lessons(
                working.task_class,
                working.goal or active_prompt,
                remaining_token_budget=budget_headroom,
            )
            if dropped:
                await BUS.publish(
                    task_id,
                    "trajectory_lessons_dropped",
                    "Trajectory lessons dropped",
                    json.dumps({"reasons": dropped[:20]}, ensure_ascii=False)[:2000],
                    stage="understand",
                )
            if lessons:
                system_prompt += "\n\n" + lessons
                await BUS.publish(
                    task_id,
                    "trajectory_lessons_injected",
                    "Trajectory lessons injected",
                    json.dumps({"rows": len(injected_rows)}, ensure_ascii=False)[:500],
                    stage="understand",
                )
                await BUS.publish(task_id, "progress", "Recalled similar earlier tasks", lessons[:1500], stage="understand")
            turn_ws = await compose_turn_working_set(
                active_prompt,
                task_class=working.task_class,
                extra_capabilities=working.requested_tools,
                security_role=working.security_role,
                agent_id="owner",
                needs_tools=working.ingress_needs_tools,
            )
            if working.ingress_needs_tools is False and not turn_ws.tool_schemas:
                await BUS.publish(
                    task_id,
                    "tool_schemas_empty_qa",
                    "Tool schemas empty for Q&A",
                    json.dumps({"tool_count": 0}, ensure_ascii=False)[:500],
                    stage="understand",
                )
            system_prompt = apply_working_set_to_system(system_prompt, turn_ws)
            audit = professional_prompt_block(prompt)
            if audit:
                # Append after tool exposure so context fitting keeps this block in the tail.
                system_prompt += "\n\n" + audit
            messages = [
                ChatMessage(role="system", content=system_prompt),
                ChatMessage(role="user", content=active_prompt + "\n\n" + plan_prompt),
            ]
            for skill in matched_skills:
                if has_secret_parameters(skill):
                    continue
                bound = bind_parameters(skill, working.goal)
                if bound is None:
                    continue
                steps = instantiate_steps(skill, bound)
                if not steps_are_executable(steps):
                    continue
                blocked = False
                for step in steps:
                    tool_meta = REGISTRY.tools.get(step.get("tool") or "")
                    risk = tool_meta.risk if tool_meta else RiskLevel.MEDIUM
                    command = (step.get("arguments") or {}).get("command") if isinstance(step.get("arguments"), dict) else None
                    if _tool_needs_operator_pause(
                        autonomy,
                        risk,
                        command,
                        step.get("tool"),
                        step.get("arguments") or {},
                    ) or _permission_denied_observation(step.get("tool"), step.get("arguments") or {}):
                        blocked = True
                        break
                if blocked:
                    continue
                await BUS.publish(
                    task_id,
                    "progress",
                    f"Running skill {skill.name}",
                    json.dumps({"parameters": bound, "steps": [s.get("tool") for s in steps]})[:1500],
                    stage="act",
                )
                skill_ok = True
                for index, step in enumerate(steps):
                    name = step.get("tool") or ""
                    arguments = step.get("arguments") if isinstance(step.get("arguments"), dict) else {}
                    call_id = f"skill-{skill.name}-{index}"
                    messages.append(
                        ChatMessage(
                            role="assistant",
                            content="",
                            tool_calls=[
                                {
                                    "id": call_id,
                                    "type": "function",
                                    "function": {"name": name, "arguments": json.dumps(arguments)},
                                }
                            ],
                        )
                    )
                    await self._update(task_id, current_tool=name, current_action=f"Skill {skill.name}: {name}")
                    await BUS.publish(task_id, "tool", f"Running {name}", json.dumps(arguments)[:1500], stage="act")
                    observation, attach = await self._execute_tool_ex(task_id, name, arguments, autonomy, settings)
                    failed = "ERROR:" in observation or observation.lower().startswith("error")
                    working.note_tool(name, observation, not failed)
                    messages.append(ChatMessage(role="tool", name=name, tool_call_id=call_id, content=observation))
                    if attach:
                        messages.append(_image_message(attach))
                        working.vision_requested = True
                    if failed:
                        skill_ok = False
                        await BUS.publish(task_id, "error", f"Skill {skill.name} failed at {name}", observation[:1500], stage="diagnose")
                        break
                    await BUS.publish(task_id, "observation", f"{name} finished", observation[:1500], stage="observe")
                if skill_ok:
                    tools_used = True
                    verifying = True
                    skill_requires_verify = True
                    best_of_n_complete = True
                    awaiting_plan_selection = False
                    working.next_action = "independent verification"
                    await BUS.publish(task_id, "stage", "Independent verification pass", stage="verify")
                    messages.append(ChatMessage(role="user", content=VERIFY_PROMPT))
                    await self._update(
                        task_id,
                        conversation_json=serialize_messages(messages),
                        compact_memory=working.dumps(),
                        current_action=f"Ran skill {skill.name}",
                    )
                    break

        if pending_tool:
            result_text = await self._execute_tool(
                task_id,
                pending_tool["name"],
                pending_tool["arguments"],
                autonomy,
                settings,
                approved=True,
            )
            messages.append(
                ChatMessage(
                    role="tool",
                    name=pending_tool["name"],
                    tool_call_id=pending_tool.get("id") or "confirmed",
                    content=result_text,
                )
            )
            tools_used = True

        context_recovery_attempts = 0
        try:
            for _step in range(max_steps):
                if task_id in self._cancel or kill_switch_active():
                    reason = "Stopped by emergency kill switch" if kill_switch_active() else "Cancelled"
                    await self._update(
                        task_id,
                        status="cancelled",
                        stage="cancelled",
                        current_action=reason,
                        error=reason,
                    )
                    await BUS.publish(task_id, "cancelled", reason)
                    return
                await self._update(
                    task_id,
                    stage="verify" if verifying else "act",
                    current_action="Waiting on model",
                    compact_memory=working.dumps(),
                    execution_mode=execution_mode,
                    task_class=working.task_class,
                    exposed_tools=_exposed_csv(working, _latest_user_text(messages, extra_prompt or prompt)),
                )
                think = should_enable_thinking(
                    profile,
                    force_final=force_final,
                    verifying=verifying,
                    turn_index=_step,
                    consecutive_failures=consecutive_failures,
                    awaiting_plan_selection=awaiting_plan_selection,
                    best_of_n_complete=best_of_n_complete,
                )
                await BUS.publish(
                    task_id,
                    "model",
                    "Writing final report" if force_final else ("Verifying result" if verifying else ("Model is thinking" if think else "Model is responding")),
                    stage="verify" if verifying else "act",
                )
                messages = compact_history(messages, working_state_block=working.as_prompt_block())
                compacted = any(
                    isinstance(message.content, str) and message.content.startswith(SUMMARY_MARKER)
                    for message in messages
                )
                needed = next_context_size(
                    int(MANAGER.state.context_size or profile.context_size),
                    profile.context_size,
                    estimate_prompt_tokens(messages),
                    compacted=compacted,
                )
                if needed:
                    grown = await MANAGER.apply_context(settings, needed, allow_shrink=False)
                    if grown >= needed:
                        await BUS.publish(task_id, "progress", f"Expanded context to {grown}", stage="act")
                        provider = MANAGER.provider or provider
                vision_turn = messages_need_vision(messages)
                if vision_turn:
                    await MANAGER.ensure_vision(settings)
                    provider = MANAGER.provider or provider
                try:
                    turn_tools = (
                        None
                        if force_final
                        else exposure_schemas_for(
                            working.task_class,
                            working.requested_tools,
                            security_role=working.security_role,
                            prompt=_latest_user_text(messages, working.goal or active_prompt),
                            needs_tools=working.ingress_needs_tools,
                        )
                    )
                    turn_max_tokens = 400 if force_final else 1024

                    async def _model_turn() -> ChatResult:
                        return await asyncio.wait_for(
                            MANAGER.chat(
                                messages,
                                tools=turn_tools,
                                temperature=profile.temperature,
                                top_p=profile.top_p,
                                top_k=profile.top_k,
                                thinking=think,
                                max_tokens=turn_max_tokens,
                                settings=settings,
                                working_state_block=working.as_prompt_block(),
                            ),
                            timeout=90 if force_final else 180,
                        )

                    think_context = (
                        "Writing the final report"
                        if force_final
                        else ("Verifying the result" if verifying else "Thinking through the next step")
                    )
                    result: ChatResult = await run_with_think_aloud(
                        task_id,
                        context=think_context,
                        operation=_model_turn,
                    )
                except ModelCapacityExceeded as exc:
                    await self._release_lazy_vision()
                    if context_recovery_attempts < 2:
                        messages, turn_tools, recovered, profile = await self._recover_context_pressure(
                            task_id,
                            messages,
                            working,
                            profile,
                            settings,
                            tools=turn_tools,
                            max_tokens=turn_max_tokens,
                        )
                        if recovered:
                            context_recovery_attempts += 1
                            continue
                    err = context_capacity_error(exc.budget)
                    await self._update(
                        task_id,
                        status="failed",
                        stage="failed",
                        result=err,
                        error=err,
                        current_action="Failed: model capacity exceeded",
                        current_tool="",
                        **metrics.as_fields(),
                    )
                    await record_trajectory(task_id, working, "failed")
                    await complete_coding_route(task_id, "failed", err)
                    await BUS.publish(task_id, "failed", "Inference failed", err, stage="failed")
                    return
                except (APIStatusError, APIConnectionError) as exc:
                    await self._release_lazy_vision()
                    if isinstance(exc, APIStatusError) and is_context_overflow(exc):
                        if context_recovery_attempts < 2:
                            messages, turn_tools, recovered, profile = await self._recover_context_pressure(
                                task_id,
                                messages,
                                working,
                                profile,
                                settings,
                                tools=turn_tools,
                                max_tokens=turn_max_tokens,
                            )
                            if recovered:
                                context_recovery_attempts += 1
                                continue
                        budget = calculate_prompt_budget(
                            messages,
                            turn_tools,
                            profile=profile,
                            max_tokens=turn_max_tokens,
                            active_context=MANAGER.live_context_size(),
                        )
                        err = context_capacity_error(budget)
                        await self._update(
                            task_id,
                            status="failed",
                            stage="failed",
                            result=err,
                            error=err,
                            current_action="Failed: context capacity exceeded",
                            current_tool="",
                            **metrics.as_fields(),
                        )
                        await record_trajectory(task_id, working, "failed")
                        await complete_coding_route(task_id, "failed", err)
                        await BUS.publish(task_id, "failed", "Context capacity exceeded", err, stage="failed")
                        return
                    if isinstance(exc, APIStatusError):
                        detail = getattr(exc, "message", None) or str(exc)
                        err = f"Inference server error ({exc.status_code}): {detail}"
                    else:
                        err = f"Inference server unreachable: {exc}"
                    await self._update(
                        task_id,
                        status="failed",
                        stage="failed",
                        result=err,
                        error=err,
                        current_action="Failed: inference error",
                        current_tool="",
                        **metrics.as_fields(),
                    )
                    await record_trajectory(task_id, working, "failed")
                    await complete_coding_route(task_id, "failed", err)
                    await BUS.publish(task_id, "failed", "Inference failed", err, stage="failed")
                    return
                except TimeoutError:
                    await self._release_lazy_vision()
                    if tools_used and verifying:
                        content = (
                            "The model timed out while writing the final report. "
                            "Actions already executed are in the activity log; verify files from that log."
                        )
                        await self._complete(task_id, messages, content, "Timed out after verification tools ran.", working, metrics)
                        return
                    content = "The model timed out before verification completed."
                    await self._update(
                        task_id,
                        status="failed",
                        stage="failed",
                        result=content,
                        error=content,
                        current_action="Failed: model timeout before verification",
                        current_tool="",
                        **metrics.as_fields(),
                    )
                    await record_trajectory(task_id, working, "failed")
                    await complete_coding_route(task_id, "failed", content)
                    await BUS.publish(task_id, "failed", "Task ended after model timeout", content, stage="failed")
                    return
                else:
                    if vision_turn:
                        await self._release_lazy_vision()
                        provider = MANAGER.provider or provider
                await MANAGER.record_timings(result.timings)
                metrics.note_model(result.timings)
                await self._update(task_id, **metrics.as_fields())
                if (result.content or "").strip():
                    mark_worker_useful_owner_text(task_id)

                if force_final:
                    content = (result.content or "").strip() or (
                        "Task finished. The tool log contains the actions that were taken and verified."
                    )
                    messages.append(ChatMessage(role="assistant", content=content, reasoning_content=result.reasoning or None))
                    working.verified = True
                    await self._update(task_id, compact_memory=working.dumps())
                    await self._complete(task_id, messages, content, content, working, metrics)
                    return

                parsed = parse_plan_block(result.content or "")
                if best_of_n_complete and not awaiting_plan_selection:
                    if parsed.get("end_state") or parsed.get("acceptance_criteria") or parsed.get("plan"):
                        working.apply_plan(parsed, prompt)
                        await self._update(
                            task_id,
                            acceptance_criteria="\n".join(working.acceptance_criteria),
                            plan_json=json.dumps(working.plan),
                            compact_memory=working.dumps(),
                            summary=working.goal,
                        )

                if result.tool_calls:
                    tools_used = True
                    best_of_n_complete = True
                    awaiting_plan_selection = False
                    if parsed.get("end_state") or parsed.get("acceptance_criteria") or parsed.get("plan"):
                        working.apply_plan(parsed, prompt)
                        await self._update(
                            task_id,
                            acceptance_criteria="\n".join(working.acceptance_criteria),
                            plan_json=json.dumps(working.plan),
                            compact_memory=working.dumps(),
                            summary=working.goal,
                        )
                    tool_rounds += 1
                    if verifying:
                        verify_tool_rounds += 1
                    names = [c.get("function", {}).get("name") or "" for c in result.tool_calls]
                    primary = names[0] if names else ""
                    last_tool_for_think = primary
                    hints: list[str] = []
                    if primary == last_tool_name:
                        same_tool_streak += 1
                    else:
                        same_tool_streak = 1
                        last_tool_name = primary
                    messages.append(
                        ChatMessage(
                            role="assistant",
                            content=result.content or "",
                            tool_calls=result.tool_calls,
                            reasoning_content=result.reasoning or None,
                        )
                    )
                    for call in result.tool_calls:
                        name = call["function"]["name"]
                        raw_args = call["function"]["arguments"]
                        schema_error = not tool_arguments_valid(raw_args)
                        arguments = parse_tool_arguments(raw_args)
                        if name == "request_tools":
                            granted = grant_requested_tools(arguments)
                            working.requested_tools = sorted(set(working.requested_tools) | set(granted))
                            await self._update(task_id, exposed_tools=_exposed_csv(working), compact_memory=working.dumps())
                            await BUS.publish(
                                task_id,
                                "progress",
                                "Expanded tool set",
                                ", ".join(granted) or "(none recognized)",
                                stage="act",
                            )
                        signature = hashlib.sha256(f"{name}:{json.dumps(arguments, sort_keys=True)}".encode()).hexdigest()
                        if recent_hashes[-3:].count(signature) >= 2:
                            observation = "Repeated identical failing/identical tool call blocked. Choose a different strategy."
                            await BUS.publish(task_id, "retry", "Blocked identical retry", observation, stage="diagnose")
                            messages.append(ChatMessage(role="tool", name=name, tool_call_id=call["id"], content=observation))
                            working.note_tool(name, observation, False)
                            continue
                        recent_hashes.append(signature)
                        tool_meta = REGISTRY.tools.get(name)
                        risk = tool_meta.risk if tool_meta else RiskLevel.MEDIUM
                        command = arguments.get("command") if isinstance(arguments, dict) else None
                        denied = _permission_denied_observation(name, arguments)
                        if denied:
                            messages.append(ChatMessage(role="tool", name=name, tool_call_id=call["id"], content=denied))
                            working.note_tool(name, denied, False)
                            continue
                        if _tool_needs_operator_pause(autonomy, risk, command, name, arguments):
                            metrics.note_confirmation()
                            irreversible = needs_confirmation(
                                autonomy, risk, command, tool_name=name, arguments=arguments
                            )
                            payload = confirmation_payload_for_tool(
                                call_id=call["id"],
                                name=name,
                                arguments=arguments,
                                irreversible=irreversible,
                            )
                            await self._update(
                                task_id,
                                status="waiting",
                                waiting_for_confirmation=True,
                                confirmation_payload=json.dumps(payload),
                                current_action=f"Waiting for confirmation: {name}",
                                conversation_json=serialize_messages(messages),
                                compact_memory=working.dumps(),
                                **metrics.as_fields(),
                            )
                            await BUS.publish(
                                task_id,
                                "confirm",
                                f"Confirmation required for {name}",
                                json.dumps(arguments)[:1500],
                                stage="act",
                            )
                            return
                        await self._update(task_id, current_tool=name, current_action=f"Running {name}")
                        await BUS.publish(task_id, "tool", f"Running {name}", json.dumps(arguments)[:1500], stage="act")
                        if name == "request_capability":
                            exposed_tools, _added, observation = apply_capability_request(exposed_tools, arguments)
                            granted = grant_requested_tools(arguments)
                            working.requested_tools = sorted(set(working.requested_tools) | set(granted))
                            await self._update(
                                task_id,
                                exposed_tools=_exposed_csv(working, extra_prompt or prompt),
                                compact_memory=working.dumps(),
                            )
                            attach = None
                            failed = False
                        else:
                            if name in REGISTRY.tools and name not in exposed_tools:
                                exposed_tools = expose_called_tool(exposed_tools, name)
                            observation, attach = await self._execute_tool_ex(
                                task_id, name, arguments, autonomy, settings, metrics=metrics, schema_error=schema_error
                            )
                            failed = "ERROR:" in observation or observation.lower().startswith("error")
                        if failed:
                            consecutive_failures += 1
                            failures_by_tool[name] = failures_by_tool.get(name, 0) + 1
                            hints.append(recovery_hint(name, observation, failures_by_tool[name]))
                            await BUS.publish(task_id, "error", f"{name} failed", observation[:1500], stage="diagnose")
                        else:
                            consecutive_failures = 0
                            failures_by_tool.pop(name, None)
                            recovering = False
                            await BUS.publish(task_id, "observation", f"{name} finished", observation[:1500], stage="observe")
                        working.note_tool(name, observation, not failed)
                        messages.append(ChatMessage(role="tool", name=name, tool_call_id=call["id"], content=observation))
                        if attach:
                            messages.append(_image_message(attach))
                            working.vision_requested = True
                    if hints:
                        guidance = "\n\n".join(hints)
                        working.next_action = "recover with a different strategy"
                        recovering = True
                        await BUS.publish(task_id, "retry", "Choosing a recovery strategy", guidance[:1500], stage="diagnose")
                        messages.append(ChatMessage(role="user", content=guidance))
                        expert = await self._maybe_consult_expert(
                            task_id,
                            working,
                            prompt,
                            consecutive_failures,
                            failures_by_tool,
                            profile_name,
                            settings,
                            verifying,
                        )
                        if expert:
                            messages.append(
                                ChatMessage(
                                    role="user",
                                    content="Expert 27B analysis (execute this plan with tools; do not wait):\n" + expert,
                                )
                            )
                    elif verifying and verify_tool_rounds >= policy.max_verify_tools:
                        force_final = True
                        messages.append(ChatMessage(role="user", content=STOP_AND_REPORT))
                    elif not verifying and tool_rounds >= policy.force_verify_after:
                        verifying = True
                        working.next_action = "independent verification"
                        await self._update(task_id, stage="verify", current_action="Independent verification")
                        await BUS.publish(task_id, "stage", "Independent verification pass", stage="verify")
                        messages.append(ChatMessage(role="user", content=VERIFY_PROMPT))
                    elif same_tool_streak >= 3 and not verifying:
                        verifying = True
                        await BUS.publish(task_id, "stage", "Independent verification pass", stage="verify")
                        messages.append(ChatMessage(role="user", content=VERIFY_PROMPT))
                    await self._update(
                        task_id,
                        conversation_json=serialize_messages(messages),
                        retries=consecutive_failures,
                        compact_memory=working.dumps(),
                        current_action=f"Ran {primary}" if primary else "Observed tools",
                        **metrics.as_fields(),
                    )
                    continue

                content = (result.content or "").strip()
                messages.append(ChatMessage(role="assistant", content=content, reasoning_content=result.reasoning or None))
                await self._update(task_id, conversation_json=serialize_messages(messages), result=content, compact_memory=working.dumps())

                if not best_of_n_complete and not awaiting_plan_selection:
                    plan_candidates = parse_plan_candidates(result.content or "")
                    if len(plan_candidates) >= 2:
                        awaiting_plan_selection = True
                        await self._update(task_id, stage="plan", current_action="Comparing candidate plans")
                        await BUS.publish(
                            task_id,
                            "stage",
                            "Comparing candidate plans",
                            f"{len(plan_candidates)} strategies",
                            stage="plan",
                        )
                        messages.append(ChatMessage(role="user", content=best_of_n_select_prompt(plan_candidates)))
                        continue
                    best_of_n_complete = True
                    if parsed.get("end_state") or parsed.get("acceptance_criteria") or parsed.get("plan"):
                        working.apply_plan(parsed, prompt)
                        await self._update(
                            task_id,
                            acceptance_criteria="\n".join(working.acceptance_criteria),
                            plan_json=json.dumps(working.plan),
                            compact_memory=working.dumps(),
                            summary=working.goal,
                        )

                if awaiting_plan_selection:
                    chosen = select_best_plan(plan_candidates, result.content or "")
                    working.apply_plan(chosen.as_parsed(), prompt)
                    awaiting_plan_selection = False
                    best_of_n_complete = True
                    critic_done = True
                    await self._update(
                        task_id,
                        acceptance_criteria="\n".join(working.acceptance_criteria),
                        plan_json=json.dumps(working.plan),
                        compact_memory=working.dumps(),
                        summary=working.goal,
                        stage="plan",
                        current_action=f"Selected plan {chosen.label}",
                    )
                    await BUS.publish(
                        task_id,
                        "stage",
                        f"Selected plan {chosen.label}",
                        format_selected_plan(chosen)[:1500],
                        stage="plan",
                    )
                    messages.append(ChatMessage(role="user", content=format_selected_plan(chosen)))
                    continue

                if policy.critic_pass and not critic_done and not verifying:
                    critic_done = True
                    critic_turn = True
                    await BUS.publish(task_id, "stage", "Critiquing plan", stage="plan")
                    messages.append(ChatMessage(role="user", content=CRITIC_PROMPT))
                    continue
                if not tools_used:
                    messages.append(
                        ChatMessage(
                            role="user",
                            content="Now execute the plan with tools. Do not conclude until the end state exists on disk or in the environment.",
                        )
                    )
                    continue
                if not verifying:
                    verifying = True
                    working.next_action = "independent verification"
                    await self._update(task_id, stage="verify", current_action="Independent verification", compact_memory=working.dumps())
                    await BUS.publish(task_id, "stage", "Independent verification pass", stage="verify")
                    messages.append(ChatMessage(role="user", content=VERIFY_PROMPT))
                    continue
                if (policy.require_verify_tools or skill_requires_verify) and verify_tool_rounds == 0:
                    messages.append(ChatMessage(role="user", content=VERIFY_REQUIRED_PROMPT))
                    continue
                working.verified = True
                verification = content or "Independent verification pass completed; acceptance criteria checked."
                await self._update(task_id, compact_memory=working.dumps(), verification=verification)
                await self._complete(task_id, messages, content or verification, verification, working, metrics)
                return
            await self._update(task_id, status="failed", stage="failed", error="Step limit reached before verification", **metrics.as_fields())
            await record_trajectory(task_id, working, "failed")
            await complete_coding_route(task_id, "failed", "Step limit reached before verification")
            await self._release_lazy_vision()
            await BUS.publish(task_id, "failed", "Step limit reached", stage="failed")
        except asyncio.CancelledError:
            await self._update(task_id, status="cancelled", stage="cancelled", **metrics.as_fields())
            await complete_coding_route(task_id, "cancelled")
            await self._release_lazy_vision()
            raise
        except Exception as exc:
            await self._update(task_id, status="failed", stage="failed", error=str(exc), **metrics.as_fields())
            await record_trajectory(task_id, working, "failed")
            await complete_coding_route(task_id, "failed", str(exc))
            await self._release_lazy_vision()
            await BUS.publish(task_id, "failed", "Task failed", str(exc), stage="failed")
        finally:
            if progress_watch is not None:
                progress_watch.cancel()
                try:
                    await progress_watch
                except asyncio.CancelledError:
                    pass
            clear_worker_progress_for_task(task_id)

    async def _execute_tool(
        self,
        task_id: str,
        name: str,
        arguments: dict[str, Any],
        autonomy: str,
        settings: AppSettings,
        *,
        approved: bool = False,
        profile_id: str | None = None,
    ) -> str:
        authz = _tool_authorization(name, arguments, approved=approved, profile_id=profile_id)
        if not authz.allowed:
            return _authorization_observation(authz)
        text, _ = await self._execute_tool_ex(
            task_id,
            name,
            arguments,
            autonomy,
            settings,
            approved=approved,
            profile_id=profile_id,
        )
        return text

    async def _execute_tool_ex(
        self,
        task_id: str,
        name: str,
        arguments: dict[str, Any],
        autonomy: str,
        settings: AppSettings,
        metrics: LiveTaskMetrics | None = None,
        schema_error: bool = False,
        *,
        approved: bool = False,
        profile_id: str | None = None,
    ) -> tuple[str, str | None]:
        authz = _tool_authorization(name, arguments, approved=approved, profile_id=profile_id)
        if not authz.allowed:
            return _authorization_observation(authz), None
        consume_once_grants(permission_ids_for_tool(name, arguments))
        started = datetime.now(timezone.utc)

        async def _run_tool():
            async with SessionLocal() as session:
                task = await session.get(Task, task_id)
                security_role = getattr(task, "security_role", "") if task else ""
            if security_role:
                return await REGISTRY.execute(name, arguments, security_role=security_role)
            return await REGISTRY.execute(name, arguments)

        result = await run_with_think_aloud(
            task_id,
            context=f"Running {name}",
            operation=_run_tool,
        )
        duration = (datetime.now(timezone.utc) - started).total_seconds() * 1000
        if metrics is not None:
            metrics.note_tool(duration, schema_error=schema_error)
        async with SessionLocal() as session:
            session.add(
                ToolCallRecord(
                    task_id=task_id,
                    tool_name=name,
                    arguments_json=json.dumps(arguments),
                    output=result.text()[:20000],
                    success=result.success,
                    error=result.error,
                    duration_ms=duration,
                )
            )
            if name == "git" and arguments.get("action") == "checkpoint":
                session.add(Checkpoint(task_id=task_id, kind="git", path=arguments.get("path") or "", note=result.output[:500]))
            await session.commit()
        attach = None
        if isinstance(result.data, dict):
            attach = result.data.get("attach_image")
            if not attach and result.data.get("path"):
                if name == "screenshot" or (name == "browser" and arguments.get("action") == "screenshot"):
                    attach = result.data.get("path")
        return result.text(), attach

    async def _maybe_consult_expert(
        self,
        task_id: str,
        working: WorkingState,
        prompt: str,
        consecutive_failures: int,
        failures_by_tool: dict[str, int],
        profile_name: str,
        settings: AppSettings,
        verifying: bool,
    ) -> str | None:
        if verifying:
            return None
        signals = EscalationSignals(
            consecutive_failures=consecutive_failures,
            failed_tools=list(failures_by_tool),
            task_class=working.task_class,
            user_requested_expert=user_requested_expert(prompt),
            architecture_task=looks_like_architecture(prompt, working.task_class),
            already_consulted=working.expert_consults,
        )
        if not should_escalate(signals):
            return None
        brief = build_expert_brief(working, unresolved=working.next_action or working.current_state)

        async def _load(name: str):
            return await MANAGER.load(settings, name)

        async def _chat(raw_messages: list[dict[str, Any]]):
            if not MANAGER.provider:
                raise RuntimeError("no provider after expert load")
            wrapped = [ChatMessage(role=item["role"], content=item["content"]) for item in raw_messages]
            return await MANAGER.chat(wrapped, tools=None, thinking=True, max_tokens=1024)

        await BUS.publish(task_id, "stage", "Consulting Expert 27B", brief.unresolved_problem[:800], stage="diagnose")
        advice = await consult_expert(
            brief,
            primary_profile=profile_name or "balanced",
            load=_load,
            unload=MANAGER.unload,
            chat=_chat,
        )
        working.expert_consults += 1
        if advice.used:
            await BUS.publish(task_id, "progress", "Expert analysis ready", advice.content[:1500], stage="diagnose")
            return advice.content
        await BUS.publish(task_id, "progress", "Expert consult skipped", (advice.reason or "unavailable")[:1500], stage="diagnose")
        return None


AGENT = AgentRuntime()
