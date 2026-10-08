from __future__ import annotations

import asyncio
import base64
import contextlib
import hashlib
import json
import logging
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

log = logging.getLogger("jarvis.agent.loop")

from openai import APIConnectionError, APIStatusError

from ..coding.usage import record_task_usage
from ..config import AppSettings, load_settings
from sqlalchemy import func, select, update

from ..db.models import Checkpoint, Task, ToolCallRecord, utcnow
from ..db.session import SessionLocal
from ..events import BUS
from ..inference.backends import is_inference_template_error
from ..inference.manager import MANAGER
from ..inference.tool_capability import probe_tool_capability
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
from .durable_execution.repository import get_task_status, last_committed_step_key
from .durable_execution.runner import run_model_step, run_tool_step
from ..providers.base import ChatMessage, ChatResult, parse_tool_arguments, tool_arguments_valid
from ..providers.openai_compat import OpenAICompatProvider
from ..providers.tool_call_compat import validate_turn_calls
from ..policy.authorize import AuthorizationResult
from ..policy.action_gate import _to_authorization, gate_side_effect, gate_tool_call
from ..policy.approval_grant import decide_approval_request
from ..policy.computer_permissions import (
    confirmation_payload_for_tool,
    consume_once_grants,
    evaluate_tool_permissions,
    permission_ids_for_tool,
)
from ..policy.reversibility_gate import register_post_success_undo
from ..policy.undo_restore import capture_prior_for_effect
from ..tools.exposure import ToolExposure
from ..tools.registry import REGISTRY
from ..tools.safety import RiskLevel, classify_command, is_destructive_operation, needs_confirmation
from .chat_turns import internal_user_message, visible_chat_turns
from .compaction import (
    compact_history,
    deserialize_messages,
    estimate_prompt_tokens,
    serialize_messages,
    SUMMARY_MARKER,
)
from .context_policy import initial_context_size, next_context_size, profile_cap
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
from .coding_contract import (
    applies_3d_execution_contract,
    applies_coding_execution_contract,
    contract_completion_blocked_message,
    contract_satisfied,
    ensure_coding_worktree,
    evidence_from_working,
    init_coding_execution,
    note_contract_tool,
    persist_execution_evidence,
)
from .cyber_execution import (
    applies_cyber_tool_execution,
    cyber_completion_blocked_message,
    cyber_execution_satisfied,
    init_cyber_execution,
    note_cyber_tool,
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
    DIRECT_LOOKUP,
    DIRECT_REPLY,
    MANAGED_TASK,
    RequestRoute,
    WorkingState,
    best_of_n_plan_prompt,
    best_of_n_select_prompt,
    classify_task,
    route_request,
    follow_up_stays_conversation,
    simple_app_control,
    simple_file_control,
    format_selected_plan,
    is_plain_conversation,
    parse_plan_block,
    parse_plan_candidates,
    resolve_execution_policy,
    select_best_plan,
)
from ..tts.persona_speech import speech_lane_for_model
from ..persona.chat_delivery import (
    clear_stream_speak_state,
    mark_stream_spoken,
    maybe_enqueue_streaming_social_tts,
    pending_chat_tts_text,
    publish_owner_text,
    stream_speak_offset,
    stream_spoken_prefix,
)
from ..persona.acknowledgements import task_acknowledgement
from ..persona.narrator import forget_task, plain_failure, speak_outcome, speak_progress
from ..persona.owner_chat import OWNER_CHAT_SYSTEM, owner_chat_max_tokens
from ..persona.think_aloud import run_with_think_aloud
from ..persona.weather import weather_system_message
from ..providers.completion_text import empty_generation_error
from .front_responder import (
    QueueSentenceWatch,
    ack_is_held,
    classify_front_action,
    enforce_front_safety,
    fallback_text_for_action,
    front_worker_should_overlap,
    generate_front_reply,
    is_safe_front_speech,
    last_front_timing,
    live_text_update,
    note_front_audio,
    note_worker_first_sentence,
    open_worker_sentence_watch,
    close_worker_sentence_watch,
    run_two_lane_chat,
    should_prefetch_turn_retrieval,
    spawn_context_expand_keep_busy,
    wait_for_late_ack,
    worker_required,
    first_sentence_ready,
)
from .task_fastpath import (
    TERMINAL_FRONT_ACTIONS,
    admit_fastpath,
    admit_lookup_fastpath,
    note_fastpath_decision,
    resolve_route_kind,
    should_skip_background_verify,
)
from .worker_progress import (
    clear_worker_progress_for_task,
    mark_worker_useful_owner_text,
    run_worker_progress_watchdog,
    task_still_running,
)
from .recovery import canned_method_switch_plan, classify_failure, recovery_hint
from ..tools.call_normalize import normalize_tool_call
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
from .tooling import apply_capability_request, should_enable_thinking
from .turn_tools import select_turn_schemas
from .ingress_gate import SAFE_LARGE_PASTE_SPEECH, run_ingress_gate
from .trajectory import gated_trajectory_lessons, record_trajectory
from ..memory.ingress_spill import ingress_prompt_segment, list_ingress_chunks
from .segmented_input import condense_text
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
    from ..config import live_allowed_directories

    home = Path.home()
    roots = live_allowed_directories(settings.allowed_directories)
    allowed = "\n".join(f"- {p}" for p in roots)
    return (
        "\n\nEnvironment:\n"
        f"- Windows user profile: {home}\n"
        f"- Desktop: {home / 'Desktop'}\n"
        f"- Documents: {home / 'Documents'}\n"
        f"- Allowed directories:\n{allowed or '- (defaults)'}\n"
        "- <local-network-shares> means private LAN SMB paths such as \\\\nas.local\\share; it is not a literal directory.\n"
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


def _tool_risk(name: str, arguments: dict[str, Any] | None) -> tuple[RiskLevel, str | None, str | None]:
    tool_meta = REGISTRY.tools.get(name)
    risk = tool_meta.risk if tool_meta else RiskLevel.MEDIUM
    args = arguments if isinstance(arguments, dict) else {}
    command = args.get("command")
    if command:
        command_risk = classify_command(str(command))
        # TerminalTool defaults to HIGH as a catalog hint; per-command classification
        # must win so routine echo/pytest are not treated as UNKNOWN high-consequence.
        if (name or "").strip().lower() == "terminal":
            risk = command_risk
        else:
            risk = max(risk, command_risk, key=lambda item: list(RiskLevel).index(item))
    action = args.get("action")
    if is_destructive_operation(name, args, command if isinstance(command, str) else None):
        risk = RiskLevel.IRREVERSIBLE
    return risk, str(action) if action is not None else None, str(command) if command is not None else None


def _tool_authorization(
    name: str,
    arguments: dict[str, Any],
    *,
    approved: bool = False,
    profile_id: str | None = None,
    grant_id: str | None = None,
    task_id: str | None = None,
) -> AuthorizationResult:
    risk, action, _command = _tool_risk(name, arguments)
    return gate_tool_call(
        name,
        action=action,
        arguments=arguments if isinstance(arguments, dict) else None,
        risk=risk,
        profile_id=profile_id,
        approved=approved,
        grant_id=grant_id,
        task_id=task_id,
    )


def _side_effect_decision(
    name: str,
    arguments: dict[str, Any],
    *,
    grant_id: str | None = None,
    task_id: str | None = None,
    profile_id: str | None = None,
    park_if_needed: bool = True,
):
    risk, action, _command = _tool_risk(name, arguments)
    return gate_side_effect(
        name,
        action=action,
        arguments=arguments if isinstance(arguments, dict) else None,
        risk=risk,
        profile_id=profile_id,
        grant_id=grant_id,
        task_id=task_id,
        park_if_needed=park_if_needed,
    )


_TERMINAL_TASK_STATUSES = frozenset({"completed", "failed", "cancelled"})


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
        self._front_tasks: dict[str, asyncio.Task] = {}

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
        from .request_routing import evaluate_request_route

        route = await evaluate_request_route(prompt, route_request(prompt))
        task_class = route.task_class
        from ..security.security_agents import (
            assert_mode_entitled,
            init_purple,
            is_security_role,
            normalize_role,
        )

        role = normalize_role(security_role) if security_role else None
        if role is not None:
            assert_mode_entitled(role)
            security_role = role
        if is_security_role(security_role) and route.kind != "managed_task":
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
        if role == "purple-team":
            init_purple(task.id)
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

                # RFC-0031: human confirm creates an unforgeable ApprovalGrant.
                # Model/tool confirmed=true never reaches this path.
                # If grant_id is already attached (API decide path), do not re-decide.
                pending_approval_id = payload.get("pending_approval_id")
                if approved and payload.get("grant_id"):
                    pass
                elif approved and pending_approval_id:
                    try:
                        outcome = decide_approval_request(
                            str(pending_approval_id),
                            decision="always" if mode == "always" else "allow_once",
                            origin_channel="ui",
                            actor="owner",
                            session_id=task_id,
                        )
                        grant = outcome.get("grant") or {}
                        if grant.get("id"):
                            payload["grant_id"] = grant["id"]
                            payload["action_id"] = grant.get("action_id")
                    except Exception as exc:  # noqa: BLE001
                        approved = False
                        await BUS.publish(
                            task_id,
                            "confirm",
                            "ApprovalGrant refused",
                            str(exc)[:1500],
                            stage="act",
                        )
                elif approved and not payload.get("grant_id"):
                    # Legacy destructive/permission pause without prior park: mint grant now.
                    try:
                        from ..policy.approval_grant import action_id_for, park_approval_request

                        tool_name = str(payload.get("name") or "")
                        arguments = payload.get("arguments") if isinstance(payload.get("arguments"), dict) else {}
                        action = str(arguments.get("action") or "")
                        target = str(
                            arguments.get("path")
                            or arguments.get("command")
                            or arguments.get("url")
                            or ""
                        )[:500]
                        action_id = action_id_for(tool_name, action, target, task_id=task_id)
                        parked = park_approval_request(
                            action_id=action_id,
                            tool_name=tool_name,
                            action=action,
                            scope={"legacy_confirm": True},
                            target=target,
                            task_id=task_id,
                            reason="legacy confirmation upgraded to ApprovalGrant",
                        )
                        outcome = decide_approval_request(
                            parked["id"],
                            decision="always" if mode == "always" else "allow_once",
                            origin_channel="ui",
                            actor="owner",
                            session_id=task_id,
                        )
                        grant = outcome.get("grant") or {}
                        if grant.get("id"):
                            payload["grant_id"] = grant["id"]
                            payload["action_id"] = grant.get("action_id")
                            payload["pending_approval_id"] = parked["id"]
                    except Exception as exc:  # noqa: BLE001
                        await BUS.publish(
                            task_id,
                            "confirm",
                            "ApprovalGrant mint failed",
                            str(exc)[:1500],
                            stage="act",
                        )
            if not approved:
                pending_approval_id = payload.get("pending_approval_id")
                if pending_approval_id:
                    try:
                        decide_approval_request(
                            str(pending_approval_id),
                            decision="deny",
                            origin_channel="ui",
                            actor="owner",
                            session_id=task_id,
                        )
                    except Exception:
                        pass
                task.status = "cancelled"
                task.stage = "cancelled"
                task.waiting_for_confirmation = False
                await session.commit()
                await BUS.publish(task_id, "cancelled", "User rejected the pending action")
                return task
            task.waiting_for_confirmation = False
            task.status = "running"
            task.confirmation_payload = json.dumps(payload)
            await session.commit()
        self._start_runner(task_id, self._run(task_id, continue_existing=True, pending_tool=payload))
        return task

    def cancel(self, task_id: str) -> None:
        self._cancel.add(task_id)
        running = self._tasks.get(task_id)
        if running:
            running.cancel()

    async def _await_managed_front(self, task_id: str) -> None:
        front = self._front_tasks.pop(task_id, None)
        if front is None:
            return
        try:
            await asyncio.wait_for(asyncio.shield(front), timeout=2.0)
        except (TimeoutError, asyncio.CancelledError, Exception):
            return

    async def _update(self, task_id: str, **fields: Any) -> None:
        incoming_status = fields.get("status")
        async with SessionLocal() as session:
            task = await session.get(Task, task_id)
            if not task:
                return
            session.expire(task)
            await session.refresh(task)
            if task.status in _TERMINAL_TASK_STATUSES and incoming_status not in _TERMINAL_TASK_STATUSES:
                return
            if incoming_status not in _TERMINAL_TASK_STATUSES:
                values = dict(fields)
                values["updated_at"] = utcnow()
                if incoming_status == "running" and not task.started_at:
                    values["started_at"] = utcnow()
                await session.execute(
                    update(Task)
                    .where(
                        Task.id == task_id,
                        Task.status.in_(("queued", "running", "waiting")),
                    )
                    .values(**values)
                )
                await session.commit()
                return
            for key, value in fields.items():
                setattr(task, key, value)
            task.updated_at = utcnow()
            if not task.started_at and fields.get("status") == "running":
                task.started_at = utcnow()
            terminal_status = fields.get("status")
            if _as_utc(task.started_at) and terminal_status in {"completed", "failed", "cancelled"}:
                finished = utcnow()
                task.finished_at = finished
                started = _as_utc(task.started_at)
                if started:
                    task.duration_seconds = (finished - started).total_seconds()
            await session.commit()
            if terminal_status in {"completed", "failed", "cancelled"}:
                from ..reverse_engineering.runtime import SERVICE as investigations
                await investigations.release_task(task_id, cancelled=terminal_status != "completed")
                from ..automation.breaker import on_task_terminal
                from .intake import on_task_terminal as advance_intake_chain

                on_task_terminal(
                    task_id,
                    status=str(terminal_status),
                    verification=task.verification or "",
                    error=task.error or "",
                    waiting_for_confirmation=bool(task.waiting_for_confirmation),
                )
                advance_intake_chain(task_id, status=str(terminal_status), result=task.result or "")
                route = str(getattr(task, "response_route", "") or "")
                task_class = str(getattr(task, "task_class", "") or "")
                # Conversation replies are already spoken; managed tasks need a
                # natural outcome, and every failure/cancel is spoken in plain language.
                if terminal_status in {"failed", "cancelled"} or route == MANAGED_TASK or (
                    task_class and task_class != CONVERSATION_CLASS
                ):
                    await speak_outcome(
                        task_id,
                        success=terminal_status == "completed",
                        result=task.result or "",
                        error=task.error or "",
                        cancelled=terminal_status == "cancelled",
                    )
                else:
                    forget_task(task_id)

    async def _complete(
        self,
        task_id: str,
        messages: list[ChatMessage],
        content: str,
        verification: str,
        working: WorkingState | None = None,
        metrics: LiveTaskMetrics | None = None,
    ) -> bool:
        prompt = content
        if working is not None:
            async with SessionLocal() as session:
                task = await session.get(Task, task_id)
                if task and task.prompt:
                    prompt = task.prompt
            if applies_coding_execution_contract(prompt, working.task_class) or applies_3d_execution_contract(
                prompt, working.task_class
            ):
                if not contract_satisfied(working, prompt, working.task_class):
                    block = contract_completion_blocked_message(working, prompt, working.task_class)
                    messages.append(internal_user_message(block))
                    await self._update(
                        task_id,
                        status="running",
                        stage="act",
                        result=block,
                        verification="",
                        current_action="RFC-0120: real edit/run/verify or DCC required",
                        conversation_json=serialize_messages(messages),
                        compact_memory=working.dumps(),
                        **(metrics.as_fields() if metrics else {}),
                    )
                    await BUS.publish(task_id, "progress", "Coding/3D contract blocked chat-only completion", block[:1500], stage="act")
                    return False
                persist_execution_evidence(task_id, working)
            if getattr(working, "requires_tool_execution", False) or applies_cyber_tool_execution(
                working.security_role, prompt
            ):
                if not cyber_execution_satisfied(working):
                    block = cyber_completion_blocked_message(working)
                    messages.append(internal_user_message(block))
                    await self._update(
                        task_id,
                        status="running",
                        stage="act",
                        result=block,
                        verification="",
                        current_action="RFC-0197: cyber tool/job evidence required",
                        conversation_json=serialize_messages(messages),
                        compact_memory=working.dumps(),
                        **(metrics.as_fields() if metrics else {}),
                    )
                    await BUS.publish(
                        task_id,
                        "progress",
                        "Security-agent verify blocked narration-only completion",
                        block[:1500],
                        stage="act",
                    )
                    return False
        from ..memory.owner_facts import is_memory_store_request
        from ..reverse_engineering.skill import requested as reverse_requested

        if working is not None and is_memory_store_request(prompt) and not working.memory_stored:
            block = (
                "This task asked to remember a fact, but nothing was stored in memory. "
                "Write the fact with the memory tools, then complete. Do not report success yet."
            )
            messages.append(internal_user_message(block))
            await self._update(
                task_id,
                status="running",
                stage="act",
                result=block,
                verification="",
                current_action="Memory store required",
                conversation_json=serialize_messages(messages),
                compact_memory=working.dumps(),
                **(metrics.as_fields() if metrics else {}),
            )
            await BUS.publish(task_id, "progress", "Remembered fact was not stored", block[:1500], stage="act")
            return False
        if reverse_requested(prompt) or (working and working.task_class == "reverse engineering"):
            from ..reverse_engineering.store import list_rows, directory
            reports = [row for row in list_rows(task_id)
                       if row["status"] in {"reported", "partial", "closed"}
                       and (directory(row["id"]) / "report.json").is_file()]
            if not reports:
                block = "Reverse engineering requires a saved investigation report. Use reverse_engineer to prepare the supplied target, collect evidence, and report findings or explicit unknowns before completing."
                messages.append(internal_user_message(block))
                await self._update(task_id, status="running", stage="act", result=block,
                                   verification="", current_action="Investigation report required",
                                   conversation_json=serialize_messages(messages))
                return False
        await self._await_managed_front(task_id)
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
        return True

    async def _fail_task(
        self,
        task_id: str,
        error: str,
        working: WorkingState | None = None,
        metrics: LiveTaskMetrics | None = None,
        *,
        current_action: str = "Failed",
        stage: str = "failed",
    ) -> None:
        spoken = plain_failure(error)
        await self._await_managed_front(task_id)
        fields: dict[str, Any] = {
            "status": "failed",
            "stage": "failed",
            "error": error,
            "result": spoken,
            "current_action": current_action,
            "current_tool": "",
        }
        if metrics is not None:
            fields.update(metrics.as_fields())
        await self._update(task_id, **fields)
        if working is not None:
            await record_trajectory(task_id, working, "failed")
        await complete_coding_route(task_id, "failed", error)
        await self._release_lazy_vision()
        await BUS.publish(task_id, "failed", spoken, error[:1500], stage=stage)

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
            switched = await maybe_autoselect_runtime_for_budget(
                budget,
                profile,
                settings,
                user_prompt=working.goal or "",
                task_id=task_id,
                minimum_answer_tier=int(working.minimum_answer_tier or 0),
            )
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
    ) -> bool:
        """Speak a front ack immediately. Returns True when TTS was actually enqueued."""
        settings = load_settings()
        if not settings.front_responder.speak_immediately:
            return False
        if not front or not is_safe_front_speech(front.action, front.text):
            return False
        # Already past early TTS (or a prior speak) — do not re-speak on expand/retry.
        if stream_speak_offset(stream_key) > 0:
            return False
        spoken = front.text if front.text.endswith((".", "!", "?")) else f"{front.text}."
        early_id = maybe_enqueue_streaming_social_tts(
            spoken,
            source=source,
            stream_key=stream_key,
            user_prompt=prompt,
            lane="front",
            model=getattr(front, "model", "") or "",
        )
        audio_ms = max(0.0, (time.perf_counter() - turn_started) * 1000)
        if early_id:
            await BUS.publish(
                task_id,
                "chat_tts",
                "Speak reply",
                pending_chat_tts_text(early_id) or spoken,
                stage="chat",
            )
            note_front_audio(None, audio_ms)
            front.first_audio_ms = audio_ms
            return True
        delivery = await publish_owner_text(
            front.text,
            source=source,
            speak=True,
            user_prompt=prompt,
            lane="front",
            model=getattr(front, "model", "") or "",
        )
        if delivery.get("tts_id"):
            # Advance the stream cursor so the final merged reply cannot re-speak
            # this front prefix (publish_owner_text does not do it itself).
            mark_stream_spoken(stream_key, len(front.text or ""), prefix=front.text or "")
            await BUS.publish(task_id, "chat_tts", "Speak reply", front.text, stage="chat")
            note_front_audio(None, audio_ms)
            front.first_audio_ms = audio_ms
            return True
        return False

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
        watch = open_worker_sentence_watch(task_id)
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
                held = heuristic if ack_is_held(heuristic) else "ack_continue"
                if not await wait_for_late_ack(held, turn_started=turn_started, worker_ready=watch):
                    return
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
            if ack_is_held(front.action) and not await wait_for_late_ack(
                front.action,
                turn_started=turn_started,
                worker_ready=watch,
            ):
                return
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
            # BUS chat_tts alone does not enqueue speech — publish_owner_text does.
            ack_text = task_acknowledgement(prompt)
            if not await wait_for_late_ack("ack_continue", turn_started=turn_started, worker_ready=watch):
                return
            await BUS.publish(
                task_id,
                "chat_tts",
                "Acknowledged",
                ack_text,
                stage="understand",
            )
            try:
                await publish_owner_text(
                    ack_text,
                    source="task_chat",
                    speak=True,
                    user_prompt=prompt,
                )
            except Exception:
                log.debug("Managed front fallback ack failed for %s", task_id, exc_info=True)
        finally:
            close_worker_sentence_watch(task_id)

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
        from ..agent.turn_working_set import (
            MAX_RECENT_CHARS,
            MAX_RECENT_TURNS,
            apply_working_set_to_system,
            bound_recent_turns,
            compose_turn_working_set,
        )

        # Bound history only — do NOT await vault/Supermemory before routing/front.
        # Simple replies must not wait on memory timeouts.
        prior = bound_recent_turns(prior)
        if len(prior) > MAX_RECENT_TURNS:
            prior = prior[-MAX_RECENT_TURNS:]
        used = 0
        bounded: list[ChatMessage] = []
        for message in reversed(prior):
            size = len(message.content or "") + 24
            if bounded and used + size > MAX_RECENT_CHARS:
                break
            bounded.append(message)
            used += size
        prior = list(reversed(bounded))

        from ..inference.answer_routing import prepare_answer_route
        from ..inference.model_escalation import schedule_orchestrator_restore
        from ..tts.speech_safe import speech_safe

        stored_route = ""
        async with SessionLocal() as session:
            task_row = await session.get(Task, task_id)
            if task_row is not None:
                stored_route = str(getattr(task_row, "response_route", "") or "")
        route_kind = resolve_route_kind(user_text, stored_route=stored_route)

        # Front before weather HTTP — ack/first-audible must not wait on Open-Meteo.
        weather_task = asyncio.create_task(weather_system_message(user_text))

        # Lean prompt for fast-path only — vault/Supermemory compose happens after miss.
        # Briefing is injected after the front lane when the weather task completes.
        lean_messages: list[ChatMessage] = [ChatMessage(role="system", content=OWNER_CHAT_SYSTEM), *prior]
        last = prior[-1] if prior else None
        if last is None or last.role != "user" or (last.content or "").strip() != user_text:
            lean_messages.append(ChatMessage(role="user", content=user_text))

        # RFC-0085 hard bypass: front reply before vault/tool/Supermemory retrieval and
        # before heavy answer-routing. Terminal fronts complete here without memory wait.
        # When the front server is distinct, worker prep+tokens start during that reply.
        overlap_cancel = asyncio.Event()
        overlap_queue: asyncio.Queue = asyncio.Queue()
        overlap_errors: list[BaseException] = []
        overlap_task: asyncio.Task | None = None
        retrieval_task: asyncio.Task | None = None
        sentence_watch: QueueSentenceWatch | None = None
        worker_speech_gate = asyncio.Event()

        async def _produce_conversation_worker() -> None:
            try:
                briefing_local = await weather_task
                if overlap_cancel.is_set():
                    return
                if retrieval_task is not None:
                    turn_ws_local = await retrieval_task
                else:
                    turn_ws_local = await compose_turn_working_set(
                        user_text,
                        task_class=CONVERSATION_CLASS,
                        agent_id="owner",
                        recent_messages=prior,
                        needs_tools=False,
                    )
                if overlap_cancel.is_set():
                    return
                recent = list(turn_ws_local.recent_turns)
                if len(recent) > MAX_RECENT_TURNS:
                    recent = recent[-MAX_RECENT_TURNS:]
                system = apply_working_set_to_system(OWNER_CHAT_SYSTEM, turn_ws_local)
                produced = [ChatMessage(role="system", content=system), *recent]
                if briefing_local:
                    produced.insert(1, ChatMessage(role="system", content=briefing_local))
                last_local = recent[-1] if recent else None
                if last_local is None or last_local.role != "user" or (last_local.content or "").strip() != user_text:
                    produced.append(ChatMessage(role="user", content=user_text))
                warm_local = ()
                if MANAGER.state.loaded and MANAGER.state.profile:
                    warm_local = (MANAGER.state.profile,)
                produced_profile, produced, _route_decision, _switched = await prepare_answer_route(
                    task_id,
                    user_message=user_text,
                    working=working,
                    settings=settings,
                    profile_name=profile.name,
                    history=recent,
                    messages=produced,
                    tools_available=True,
                    vision_requested=task_needs_vision(
                        working.task_class, user_text, settings.inference.vision_mode or "lazy"
                    ),
                    new_user_turn=True,
                    warm_models=warm_local,
                )
                if overlap_cancel.is_set():
                    return
                if not MANAGER.provider or not MANAGER.state.loaded:
                    await MANAGER.load(settings, produced_profile)
                if overlap_cancel.is_set():
                    return
                from ..persona.inference_context import ensure_context_for_messages as _ensure_ctx

                await _ensure_ctx(
                    produced,
                    settings=settings,
                    profile_name=produced_profile,
                    task_id=task_id,
                )
                if overlap_cancel.is_set():
                    return
                active = resolve_profile(MANAGER.state.profile or produced_profile)
                async for delta in MANAGER.chat_stream(
                    produced,
                    temperature=active.temperature,
                    top_p=active.top_p,
                    top_k=active.top_k,
                    max_tokens=owner_chat_max_tokens(active),
                    thinking=False,
                ):
                    if overlap_cancel.is_set():
                        break
                    await overlap_queue.put(delta)
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                overlap_errors.append(exc)
            finally:
                await overlap_queue.put(None)

        from ..memory.obsidian_vault import vault_ask_requires_working_set as _vault_required

        if should_prefetch_turn_retrieval(user_text, vault_required=_vault_required(user_text)):

            async def _prefetch_conversation_ws():
                return await compose_turn_working_set(
                    user_text,
                    task_class=CONVERSATION_CLASS,
                    agent_id="owner",
                    recent_messages=prior,
                    needs_tools=False,
                )

            retrieval_task = asyncio.create_task(_prefetch_conversation_ws())

        if front_worker_should_overlap(settings, user_text, strategy="direct"):
            overlap_task = asyncio.create_task(_produce_conversation_worker())
            sentence_watch = QueueSentenceWatch(overlap_queue)
            sentence_watch.start()

        prefetched_front = await generate_front_reply(
            user_text,
            history=prior,
            settings=settings,
            turn_started=turn_started,
        )
        stream_key = f"task:{task_id}"
        clear_stream_speak_state(stream_key)
        front_spoken_early = False
        ack_suppressed = False
        show_front_ack = True
        if (
            prefetched_front.text
            and prefetched_front.action != "silent_skip"
            and ack_is_held(prefetched_front.action)
        ):
            ready = sentence_watch.ready if sentence_watch is not None else asyncio.Event()
            show_front_ack = await wait_for_late_ack(
                prefetched_front.action,
                turn_started=turn_started,
                worker_ready=ready,
            )
            ack_suppressed = not show_front_ack
        if prefetched_front.text and prefetched_front.action != "silent_skip" and show_front_ack:
            await self._publish_front_events(task_id, "front_response_started", "Front response started")
            await self._publish_front_events(
                task_id,
                "front_response_completed",
                "Front response",
                json.dumps(prefetched_front.as_dict(), ensure_ascii=False)[:4000],
            )
            front_spoken_early = await self._speak_front_reply(
                task_id,
                prefetched_front,
                prompt=prompt,
                stream_key=stream_key,
                turn_started=turn_started,
            )
            await self._persist_front_partial(
                task_id,
                lean_messages,
                prefetched_front.text,
                first_response_ms=prefetched_front.first_text_ms or 0.0,
                current_action="Checking details…"
                if prefetched_front.action in {"ack_continue", "handoff_notice"}
                else "Replying",
            )

        terminal = admit_fastpath(
            user_text,
            route_kind=route_kind,
            front_action=prefetched_front.action,
            front_text=prefetched_front.text,
        )
        if terminal.admitted:
            note_fastpath_decision(terminal, task_id=task_id)
            overlap_cancel.set()
            weather_task.cancel()
            if sentence_watch is not None:
                sentence_watch.stop()
            if retrieval_task is not None:
                retrieval_task.cancel()
            if overlap_task is not None:
                overlap_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await weather_task
            if retrieval_task is not None:
                with contextlib.suppress(asyncio.CancelledError, Exception):
                    await retrieval_task
            if overlap_task is not None:
                with contextlib.suppress(asyncio.CancelledError):
                    await overlap_task
            await BUS.publish(
                task_id,
                "fastpath",
                "Fast path hit",
                json.dumps(terminal.as_dict(), ensure_ascii=False)[:1500],
                stage="chat",
            )
            spoken_front = speech_safe(prefetched_front.text or "") or (prefetched_front.text or "").strip()
            first_ms = float(prefetched_front.first_text_ms or 0.0)
            complete_ms = float(prefetched_front.complete_ms or first_ms or 0.0)
            if complete_ms:
                metrics.note_model_elapsed(max(1.0, complete_ms))
            await BUS.publish(
                task_id,
                "response_timing",
                "Response timing",
                (
                    f"First word {first_ms / 1000:.2f}s · completed {complete_ms / 1000:.2f}s\n"
                    + json.dumps(
                        {
                            "fastpath": True,
                            "fastpath_reason": terminal.reason,
                            "first_word_s": round(first_ms / 1000, 2),
                            "completed_s": round(complete_ms / 1000, 2),
                            "front_action": prefetched_front.action,
                            "stages_skipped": list(terminal.stages_skipped),
                        },
                        ensure_ascii=False,
                    )
                )[:4000],
                stage="chat",
            )
            # Terminal front has no independent verification evidence.
            working.verified = False
            await self._complete(
                task_id,
                [*lean_messages, ChatMessage(role="assistant", content=spoken_front)],
                spoken_front,
                "",
                working,
                metrics,
            )
            return

        briefing = await weather_task
        if briefing:
            lean_messages.insert(1, ChatMessage(role="system", content=briefing))

        lookup = admit_lookup_fastpath(user_text, route_kind=route_kind, briefing=briefing)
        if lookup.admitted:
            note_fastpath_decision(lookup, task_id=task_id)
            overlap_cancel.set()
            if sentence_watch is not None:
                sentence_watch.stop()
            if retrieval_task is not None:
                retrieval_task.cancel()
            if overlap_task is not None:
                overlap_task.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await overlap_task
            if retrieval_task is not None:
                with contextlib.suppress(asyncio.CancelledError, Exception):
                    await retrieval_task
            await BUS.publish(
                task_id,
                "fastpath",
                "Fast path hit",
                json.dumps(lookup.as_dict(), ensure_ascii=False)[:1500],
                stage="chat",
            )
            await self._run_direct_lookup_fastpath(
                task_id,
                prompt=prompt,
                user_text=user_text,
                messages=lean_messages,
                profile_name=profile.name,
                settings=settings,
                working=working,
                metrics=metrics,
                turn_started=turn_started,
                stream_key=stream_key,
                first_response_ms=float(prefetched_front.first_text_ms or 0.0),
            )
            return

        miss_decision = terminal if route_kind == DIRECT_REPLY else lookup
        note_fastpath_decision(miss_decision, task_id=task_id)
        await BUS.publish(
            task_id,
            "fastpath",
            "Fast path miss",
            json.dumps(miss_decision.as_dict(), ensure_ascii=False)[:1500],
            stage="chat",
        )

        # Fast-path miss: retrieve vault/tools/Supermemory only now (does not delay first reply).
        # Overlap already started that retrieval beside the front reply.
        if overlap_task is None:
            if retrieval_task is not None:
                turn_ws = await retrieval_task
            else:
                turn_ws = await compose_turn_working_set(
                    user_text,
                    task_class=CONVERSATION_CLASS,
                    agent_id="owner",
                    recent_messages=prior,
                    needs_tools=False,
                )
            prior = list(turn_ws.recent_turns)
            if len(prior) > MAX_RECENT_TURNS:
                prior = prior[-MAX_RECENT_TURNS:]
            system = apply_working_set_to_system(OWNER_CHAT_SYSTEM, turn_ws)
            messages = [ChatMessage(role="system", content=system), *prior]
            if briefing:
                messages.insert(1, ChatMessage(role="system", content=briefing))
            last = prior[-1] if prior else None
            if last is None or last.role != "user" or (last.content or "").strip() != user_text:
                messages.append(ChatMessage(role="user", content=user_text))
        else:
            messages = lean_messages
        # Fail closed: a terminal front that could not be admitted must not
        # suppress the worker (empty/unsafe text would otherwise soft-complete).
        if (
            prefetched_front.action in TERMINAL_FRONT_ACTIONS
            and miss_decision.reason in {"empty_front_text", "unsafe_front_speech", "missing_front_action"}
        ):
            prefetched_front.action = "silent_skip"
            prefetched_front.skipped = True
            prefetched_front.text = ""
            front_spoken_early = False

        # RFC-0127: start the 60s progress watchdog before heavy answer routing /
        # model load so slow prepare_answer_route (e.g. hotswap after hard-bypass
        # miss) cannot leave the owner silent past the first progress deadline.
        progress_watch = asyncio.create_task(
            run_worker_progress_watchdog(
                task_id,
                turn_started=turn_started,
                settings=settings,
                should_continue=lambda: task_still_running(task_id),
            )
        )
        done: dict[str, Any] | None = None
        first_response_ms = prefetched_front.first_text_ms or 0.0
        model_started = turn_started
        front_text = prefetched_front.text or ""
        front_action = prefetched_front.action or ""
        worker_started = False
        spoken_parts: list[str] = []

        try:
            if overlap_task is not None:
                # Producer already retrieved, loaded, and is streaming tokens.
                messages = lean_messages
            else:
                warm = ()
                if MANAGER.state.loaded and MANAGER.state.profile:
                    warm = (MANAGER.state.profile,)
                profile_name, messages, _route_decision, _switched = await prepare_answer_route(
                    task_id,
                    user_message=user_text,
                    working=working,
                    settings=settings,
                    profile_name=profile.name,
                    history=prior,
                    messages=messages,
                    tools_available=True,
                    vision_requested=task_needs_vision(working.task_class, user_text, settings.inference.vision_mode or "lazy"),
                    new_user_turn=True,
                    warm_models=warm,
                )
                profile = resolve_profile(profile_name)
                await self._update(task_id, compact_memory=working.dumps(), profile=profile.name)

                if not MANAGER.provider or not MANAGER.state.loaded:
                    await BUS.publish(task_id, "stage", "Loading local model", stage="model")
                    await MANAGER.load(settings, profile_name)
                model_started = time.perf_counter()

                from ..persona.inference_context import ensure_context_for_messages, model_lane_event_payload
                from ..agent.front_responder import resolve_front_model_id

                async def _expand_notice(before: int, after: int) -> None:
                    # Publish the resize notice only; do not await a second front
                    # regen (blocked the worker) or re-speak after early TTS.
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
                    if stream_speak_offset(stream_key) > 0:
                        return

                    async def _on_spoken(text: str) -> None:
                        if stream_speak_offset(stream_key) > 0:
                            return
                        await publish_owner_text(
                            text,
                            source="task_chat",
                            speak=True,
                            user_prompt=prompt,
                        )

                    spawn_context_expand_keep_busy(on_spoken=_on_spoken)

                await ensure_context_for_messages(
                    messages,
                    settings=settings,
                    profile_name=profile.name,
                    on_expanding=_expand_notice,
                    task_id=task_id,
                )
                profile = resolve_profile(MANAGER.state.profile or profile.name)

            async def worker_stream():
                if overlap_task is not None:
                    if sentence_watch is not None:
                        for item in await sentence_watch.finish():
                            if item is None:
                                if overlap_errors:
                                    raise overlap_errors[0]
                                return
                            yield item
                    while True:
                        item = await overlap_queue.get()
                        if item is None:
                            break
                        yield item
                    if overlap_errors:
                        raise overlap_errors[0]
                    return
                async for delta in MANAGER.chat_stream(
                    messages,
                    temperature=profile.temperature,
                    top_p=profile.top_p,
                    top_k=profile.top_k,
                    max_tokens=owner_chat_max_tokens(profile),
                    thinking=False,
                ):
                    yield delta

            if front_spoken_early or ack_suppressed or not (prefetched_front.text or "").strip():
                worker_speech_gate.set()

            async def on_delta(lane: str, delta: str) -> None:
                nonlocal first_response_ms
                if not delta:
                    return
                if lane == "worker" and not worker_speech_gate.is_set():
                    await worker_speech_gate.wait()
                if lane == "worker":
                    mark_worker_useful_owner_text(task_id)
                    spoken_parts.append(delta)
                    if first_sentence_ready("".join(spoken_parts)):
                        note_worker_first_sentence(task_id)
                else:
                    spoken_parts.append(delta)
                elapsed = max(0.0, (time.perf_counter() - (turn_started or model_started)) * 1000)
                if not first_response_ms:
                    first_response_ms = elapsed
                    await self._update(task_id, first_response_ms=round(first_response_ms, 1))
                accumulated = "".join(spoken_parts)
                from ..persona.inference_context import model_lane_event_payload
                from ..agent.front_responder import resolve_front_model_id

                lane_model = resolve_front_model_id(settings) if lane == "front" else str(
                    getattr(MANAGER.provider, "model", "") or profile.name
                )
                # A visible front line is already on screen. Worker tokens are
                # consolidated after the stream so a paraphrase is not appended live.
                publish_worker_live = lane != "worker" or ack_suppressed
                early_id = maybe_enqueue_streaming_social_tts(
                    accumulated,
                    source="task_chat",
                    stream_key=stream_key,
                    user_prompt=prompt,
                    lane=speech_lane_for_model(lane, lane_model),
                    model=lane_model,
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
                if publish_worker_live:
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

            async for event in run_two_lane_chat(
                user_text,
                history=prior,
                settings=settings,
                turn_started=turn_started or model_started,
                worker_stream=worker_stream,
                on_delta=on_delta,
                prefetched_front=prefetched_front if prefetched_front.text else None,
                suppress_front=ack_suppressed,
            ):
                kind = event.get("type")
                if kind == "front_response_started":
                    await self._publish_front_events(task_id, "front_response_started", "Front response started")
                elif kind == "front_response_skipped":
                    worker_speech_gate.set()
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
                            front_spoken_early = await self._speak_front_reply(
                                task_id,
                                front,
                                prompt=prompt,
                                stream_key=stream_key,
                                turn_started=turn_started or model_started,
                            )
                    worker_speech_gate.set()
                elif kind == "worker_response_started":
                    worker_speech_gate.set()
                    worker_started = True
                    await self._publish_front_events(task_id, "worker_response_started", "Worker response started")
                elif kind == "worker_response_completed":
                    await self._publish_front_events(task_id, "worker_response_completed", "Worker response completed")
                elif kind == "done":
                    done = event
        except Exception as exc:
            clear_stream_speak_state(stream_key)
            from ..tts.persona_speech import announce_stream_stall

            await announce_stream_stall(exc, source="task_chat")
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
        if not ack_suppressed:
            front_line = (front_text or "").strip()
            update = live_text_update(front_line, content) if front_line else None
            if update:
                mode, payload = update
                await BUS.publish(
                    task_id,
                    "replace_previous_text" if mode == "replace" else "assistant_delta",
                    "Reply",
                    payload,
                    stage="chat",
                    persist=False,
                )
        await publish_owner_text(
            content,
            source="task_chat",
            speak=True,
            user_prompt=prompt,
            tts_char_offset=stream_speak_offset(stream_key),
            spoken_prefix=stream_spoken_prefix(stream_key),
            lane="worker",
            model=str(getattr(MANAGER.provider, "model", "") or ""),
        )
        if not should_skip_background_verify(route_kind):
            from .background_verify import schedule_background_verification

            schedule_background_verification(
                user_text,
                content,
                source="task_chat",
                task_id=task_id,
                route_kind=route_kind,
                task_class=getattr(working, "task_class", None) or CONVERSATION_CLASS,
            )
        clear_stream_speak_state(stream_key)
        schedule_orchestrator_restore(settings)
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
        # Conversation answer is not independent verification evidence.
        working.verified = False
        await self._complete(task_id, messages, content, "", working, metrics)

    async def _run_direct_lookup_fastpath(
        self,
        task_id: str,
        *,
        prompt: str,
        user_text: str,
        messages: list[ChatMessage],
        profile_name: str | None,
        settings: AppSettings,
        working: WorkingState,
        metrics: LiveTaskMetrics,
        turn_started: float,
        stream_key: str,
        first_response_ms: float = 0.0,
    ) -> None:
        """RFC-0085 direct_lookup: briefing + one answer call; no tools/verify/two-lane."""
        await self._update(task_id, stage="act", current_action="Checking the forecast…")
        await BUS.publish(
            task_id,
            "stage",
            "Direct lookup",
            "Using the dedicated weather briefing path",
            stage="act",
        )
        profile = resolve_profile(profile_name)
        if not MANAGER.provider or not MANAGER.state.loaded:
            await BUS.publish(task_id, "stage", "Loading local model", stage="model")
            await MANAGER.load(settings, profile.name)
            profile = resolve_profile(MANAGER.state.profile or profile.name)
        if not MANAGER.provider:
            err = "Inference model is not loaded for direct lookup"
            await self._update(
                task_id,
                status="failed",
                stage="failed",
                error=err,
                result=err,
                **metrics.as_fields(),
            )
            await BUS.publish(task_id, "failed", "Direct lookup failed", err, stage="failed")
            return

        model_started = time.perf_counter()
        parts: list[str] = []
        try:
            async for delta in MANAGER.chat_stream(
                messages,
                temperature=profile.temperature,
                top_p=profile.top_p,
                top_k=profile.top_k,
                max_tokens=owner_chat_max_tokens(profile),
                thinking=False,
            ):
                if not delta:
                    continue
                parts.append(delta)
                if not first_response_ms:
                    first_response_ms = max(0.0, (time.perf_counter() - turn_started) * 1000)
                    await self._update(task_id, first_response_ms=round(first_response_ms, 1))
                await BUS.publish(
                    task_id,
                    "assistant_delta",
                    "Reply",
                    delta,
                    stage="chat",
                    persist=False,
                )
        except Exception as exc:
            from ..tts.persona_speech import announce_stream_stall

            await announce_stream_stall(exc, source="task_chat")
            err = str(exc)
            await self._update(
                task_id,
                status="failed",
                stage="failed",
                error=err,
                result=err,
                **metrics.as_fields(),
            )
            await BUS.publish(task_id, "failed", "Direct lookup failed", err, stage="failed")
            return

        content = "".join(parts).strip()
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
            await BUS.publish(task_id, "failed", "Direct lookup failed", err, stage="failed")
            return

        model_ms = max(0.0, (time.perf_counter() - model_started) * 1000)
        metrics.note_model_elapsed(max(1.0, model_ms))
        await publish_owner_text(
            content,
            source="task_chat",
            speak=True,
            user_prompt=prompt,
            tts_char_offset=stream_speak_offset(stream_key),
            spoken_prefix=stream_spoken_prefix(stream_key),
            lane="worker",
            model=str(getattr(MANAGER.provider, "model", "") or ""),
        )
        await BUS.publish(
            task_id,
            "response_timing",
            "Response timing",
            (
                f"First word {(first_response_ms or 0) / 1000:.2f}s · completed {model_ms / 1000:.2f}s\n"
                + json.dumps(
                    {
                        "fastpath": True,
                        "fastpath_reason": "direct_lookup_briefing",
                        "first_word_s": round((first_response_ms or 0) / 1000, 2),
                        "completed_s": round(model_ms / 1000, 2),
                        "route_kind": DIRECT_LOOKUP,
                    },
                    ensure_ascii=False,
                )
            )[:4000],
            stage="chat",
        )
        clear_stream_speak_state(stream_key)
        if messages and messages[-1].role == "assistant":
            messages[-1] = ChatMessage(role="assistant", content=content)
        else:
            messages.append(ChatMessage(role="assistant", content=content))
        # Direct lookup has no independent verification — never treat the answer as evidence.
        working.verified = False
        not_verified = json.dumps(
            {
                "result": "NOT_VERIFIED",
                "checks": [],
                "warnings": ["direct_lookup produced an answer without independent verification evidence"],
                "answer_changed_by_verification": False,
            },
            ensure_ascii=False,
        )
        await self._complete(task_id, messages, content, not_verified, working, metrics)

    async def _run_simple_app_control(
        self,
        task_id: str,
        *,
        action: str,
        name: str,
        working: WorkingState,
        metrics: LiveTaskMetrics,
        settings: AppSettings,
        autonomy: str,
        profile_id: str | None,
    ) -> None:
        """Open or close a named app without waiting for the language model."""
        arguments = {"action": action, "name": name}
        await self._update(task_id, stage="act", current_action=f"{action} {name}", current_tool="apps")
        await BUS.publish(task_id, "stage", "Acting", stage="act")
        await speak_progress(task_id, "apps", arguments)
        observation, _ = await self._execute_tool_ex(
            task_id,
            "apps",
            arguments,
            autonomy,
            settings,
            metrics=metrics,
            profile_id=profile_id,
        )
        lowered = observation.lower()
        failed = observation.startswith("ERROR:") or any(
            marker in lowered
            for marker in ("did not start", "no installed app", "authorization denied", "could not start")
        )
        display = " ".join(word.capitalize() if word.islower() else word for word in name.split()) or name
        if failed:
            await self._fail_task(task_id, observation, working, metrics)
            return
        content = f"{display} is open." if action == "open" else f"{display} is closed."
        messages = [
            ChatMessage(role="user", content=f"{action} {name}"),
            ChatMessage(role="assistant", content=content),
        ]
        await self._complete(task_id, messages, content, observation[:1500], working, metrics)

    async def _run_simple_file_control(
        self,
        task_id: str,
        *,
        action: str,
        path: str,
        content: str,
        working: WorkingState,
        metrics: LiveTaskMetrics,
        settings: AppSettings,
        autonomy: str,
        profile_id: str | None,
    ) -> None:
        """Read or write one named text file without waiting for the language model."""
        arguments: dict[str, Any] = {"action": action, "path": path}
        if action == "write":
            arguments["content"] = content
        await self._update(task_id, stage="act", current_action=f"{action} {path}", current_tool="filesystem")
        await BUS.publish(task_id, "stage", "Acting", stage="act")
        await speak_progress(task_id, "filesystem", arguments)
        observation, _ = await self._execute_tool_ex(
            task_id,
            "filesystem",
            arguments,
            autonomy,
            settings,
            metrics=metrics,
            profile_id=profile_id,
        )
        lowered = observation.lower()
        failed = observation.startswith("ERROR:") or any(
            marker in lowered
            for marker in ("authorization denied", "not allowed", "permission denied", "path is outside")
        )
        if failed:
            await self._fail_task(task_id, observation, working, metrics)
            return
        spoken = "The file is saved." if action == "write" else "I read the file."
        messages = [
            ChatMessage(role="user", content=f"{action} {path}"),
            ChatMessage(role="assistant", content=spoken),
        ]
        await self._complete(task_id, messages, spoken, observation[:1500], working, metrics)

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
            if working.security_role == "purple-team":
                from ..security.security_agents import load_purple_state

                purple = load_purple_state(task_id)
                working.purple_phase = purple.phase
                working.purple_locked = purple.locked
        gate_text = (extra_prompt or prompt).strip()
        active_prompt = gate_text or prompt
        if not await self._ensure_owner_memory(task_id, active_prompt, working):
            return
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
        from .request_routing import evaluate_request_route

        follow_route = await evaluate_request_route(extra_prompt, route_request(extra_prompt)) if extra_prompt else None
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
        if not pending_tool:
            app_job = simple_app_control(extra_prompt or prompt)
            if app_job:
                await self._run_simple_app_control(
                    task_id,
                    action=app_job[0],
                    name=app_job[1],
                    working=working,
                    metrics=metrics,
                    settings=settings,
                    autonomy=autonomy,
                    profile_id=profile_name,
                )
                return
            file_job = simple_file_control(extra_prompt or prompt)
            if file_job:
                await self._run_simple_file_control(
                    task_id,
                    action=file_job[0],
                    path=file_job[1],
                    content=file_job[2],
                    working=working,
                    metrics=metrics,
                    settings=settings,
                    autonomy=autonomy,
                    profile_id=profile_name,
                )
                return
        user_turn = (extra_prompt or "").strip()
        managed_retrieval: asyncio.Task | None = None
        managed_retrieval_prompt = active_prompt
        if not pending_tool and (not continue_existing or user_turn):
            async def _prefetch_managed_ws():
                return await compose_turn_working_set(
                    managed_retrieval_prompt,
                    task_class=working.task_class,
                    extra_capabilities=working.requested_tools,
                    security_role=working.security_role,
                    agent_id="owner",
                    recent_messages=existing,
                    needs_tools=working.ingress_needs_tools,
                )

            managed_retrieval = asyncio.create_task(_prefetch_managed_ws())
            progress_watch = asyncio.create_task(
                run_worker_progress_watchdog(
                    task_id,
                    turn_started=turn_started,
                    settings=settings,
                    should_continue=lambda: task_still_running(task_id),
                )
            )
            if settings.front_responder.enabled:
                self._front_tasks[task_id] = asyncio.create_task(
                    self._run_managed_front_lane(
                        task_id,
                        extra_prompt or prompt,
                        settings,
                        turn_started=turn_started,
                        history=existing,
                    )
                )
            elif not continue_existing:
                ack_text = task_acknowledgement(extra_prompt or prompt)
                await BUS.publish(
                    task_id,
                    "chat_tts",
                    "Acknowledged",
                    ack_text,
                    stage="understand",
                )
                await publish_owner_text(
                    ack_text,
                    source="task_chat",
                    speak=True,
                    user_prompt=extra_prompt or prompt,
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
        from ..inference.answer_routing import prepare_answer_route
        from ..inference.profile_roles import infer_runtime_role_and_tier

        loaded_name = MANAGER.state.profile if MANAGER.state.loaded else profile_name
        loaded_role, loaded_tier = infer_runtime_role_and_tier(loaded_name or profile_name)
        if loaded_role == "orchestrator" or loaded_tier <= 1:
            warm = (loaded_name,) if loaded_name else ()
            profile_name, _route_messages, _route_decision, _switched = await prepare_answer_route(
                task_id,
                user_message=active_prompt,
                working=working,
                settings=settings,
                profile_name=profile_name,
                history=existing,
                messages=[ChatMessage(role="user", content=active_prompt)],
                tools_available=True,
                vision_requested=need_vision,
                new_user_turn=bool(not continue_existing or user_turn),
                warm_models=warm,
            )
            profile = resolve_profile(profile_name)
            await self._update(task_id, compact_memory=working.dumps(), profile=profile.name)
        if not MANAGER.provider or not MANAGER.state.loaded:
            await BUS.publish(task_id, "stage", "Loading local model", stage="model")
            await publish_owner_text("Loading the model now.", source="progress", speak=True)
            try:
                await MANAGER.load(settings, profile_name)
            except Exception as exc:
                await self._fail_task(
                    task_id,
                    f"The language model could not be loaded: {exc}",
                    working,
                    metrics,
                )
                return
        if MANAGER.provider is None or not MANAGER.state.loaded:
            await self._fail_task(task_id, "The language model is not loaded.", working, metrics)
            return
        target_ctx = initial_context_size(working.task_class, profile)
        from ..inference.lmstudio_context import LocalContextRestoreError
        try:
            live_ctx = await MANAGER.apply_context(
                settings, target_ctx, allow_shrink=True, allow_reload=True
            )
        except LocalContextRestoreError as exc:
            await self._fail_task(
                task_id,
                f"The language model could not be restored after a context resize: {exc}",
                working,
                metrics,
            )
            return
        if live_ctx != effective_cap:
            await BUS.publish(
                task_id,
                "progress",
                f"Using {live_ctx} context (RAM-aware cap {effective_cap})",
                stage="model",
            )
        provider = MANAGER.provider
        if working.ingress_blob_id and working.ingress_size_class == "big" and not existing:
            stored_chunks = await list_ingress_chunks(working.ingress_blob_id)
            if not stored_chunks:
                detail = "The stored long message could not be read. No input segments were skipped."
                await self._update(task_id, status="failed", stage="failed", error=detail, result=detail)
                await BUS.publish(task_id, "failed", "Long input unavailable", detail, stage="understand")
                return

            async def _segment_progress(index: int, total: int) -> None:
                await BUS.publish(
                    task_id,
                    "progress",
                    f"Reading input part {index}/{total}",
                    stage="understand",
                )

            try:
                brief, segment_count = await condense_text(
                    "".join(row.body or "" for row in stored_chunks),
                    on_segment=_segment_progress,
                )
            except Exception as exc:
                detail = f"Could not process every part of the long message: {exc}"
                await self._update(task_id, status="failed", stage="failed", error=detail, result=detail)
                await BUS.publish(task_id, "failed", "Long input processing failed", detail[:1500], stage="understand")
                return
            active_prompt = (
                f"Owner request, processed in {segment_count} ordered parts. "
                f"Original input id: {working.ingress_blob_id}. "
                "Use read_ingress with that id and a character offset for exact details. "
                "Form an internal plan; use tools when the owner requested action, then observe and verify.\n\n"
                f"Working brief:\n{brief}"
            )
        if isinstance(provider, OpenAICompatProvider) and working.ingress_needs_tools is not False and working.task_class != "conversation":
            capability = await probe_tool_capability(provider, thinking=profile.thinking)
            if capability["status"] != "ready":
                detail = capability["detail"]
                await self._update(task_id, status="failed", stage="failed", error=detail, result=detail,
                                   current_action="Agent tools unavailable for selected model")
                await BUS.publish(task_id, "failed", "Model tool-call check failed", detail, stage="model")
                return
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
        failure_kinds: list[str] = []
        last_failed_tool = ""
        last_failed_observation = ""
        tool_rounds = 0
        invalid_tool_turns = 0
        model_turn_index = 0
        verify_tool_rounds = 0
        last_tool_name = ""
        last_tool_action = ""
        same_tool_streak = 0
        force_final = False
        plan_candidates: list = []
        awaiting_plan_selection = False
        best_of_n_complete = policy.best_of_n <= 1
        skill_requires_verify = False
        coding_worktree_path = ensure_coding_worktree(task_id) if (
            applies_coding_execution_contract(active_prompt, working.task_class)
            or applies_3d_execution_contract(active_prompt, working.task_class)
        ) else None
        if applies_coding_execution_contract(active_prompt, working.task_class) or applies_3d_execution_contract(
            active_prompt, working.task_class
        ):
            init_coding_execution(working)
            skill_requires_verify = True
        if applies_cyber_tool_execution(working.security_role, active_prompt):
            init_cyber_execution(working, requires_tool_execution=True)
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
                # RFC-0107 Wave B: refresh vault working set for the follow-up ask —
                # continue_existing must not keep a stale or empty vault block.
                follow_ws = await compose_turn_working_set(
                    extra_prompt,
                    task_class=working.task_class,
                    extra_capabilities=working.requested_tools,
                    security_role=working.security_role,
                    agent_id="owner",
                    recent_messages=existing,
                    needs_tools=working.ingress_needs_tools,
                )
                from .turn_working_set import replace_vault_block_in_system

                for idx, message in enumerate(messages):
                    if message.role == "system":
                        refreshed = replace_vault_block_in_system(
                            message.content if isinstance(message.content, str) else "",
                            follow_ws.vault_block,
                        )
                        messages[idx] = ChatMessage(role="system", content=refreshed)
                        break
                follow_up_grounding = maybe_docs_first(DocsFirstContext(user_message=extra_prompt))
                if follow_up_grounding and follow_up_grounding.prompt_block():
                    for idx, message in enumerate(messages):
                        if message.role == "system":
                            messages[idx] = ChatMessage(
                                role="system",
                                content=message.content + "\n\n" + follow_up_grounding.prompt_block(),
                            )
                            break
                messages.append(internal_user_message(CONTINUE_PROMPT))
                messages.append(ChatMessage(role="user", content=extra_prompt))
            else:
                messages.append(internal_user_message(CONTINUE_PROMPT))
        else:
            guidance = policy_guidance(active_prompt)
            system_prompt = SYSTEM_PROMPT + (("\n\n" + guidance) if guidance else "") + _environment_block(settings)
            grounding = maybe_docs_first(DocsFirstContext(user_message=active_prompt))
            if grounding and grounding.prompt_block():
                system_prompt += "\n\n" + grounding.prompt_block()
            matched_skills = await relevant_skills(working.task_class, working.goal)
            skills = skills_prompt_block(matched_skills)
            if skills:
                system_prompt += "\n\n" + skills
                await BUS.publish(task_id, "progress", "Applying a known skill", skills[:1500], stage="understand")
            if should_route(working.task_class, active_prompt):
                decision = route_software_task(active_prompt, task_class=working.task_class)
                await record_coding_route(task_id, decision)
                routing = await route_coding_task(active_prompt, task_class=working.task_class)
                working.coding_worker = decision.selected_worker or routing.get("execute_worker") or ""
                working.coding_tier = decision.tier_name or ""
                working.coding_complexity = int(decision.score or routing.get("complexity") or 0)
                system_prompt += "\n\n" + format_routing_block(routing)
                await BUS.publish(task_id, "progress", "Coding worker selected", format_routing_block(routing)[:1500], stage="understand")
            if coding_worktree_path:
                system_prompt += (
                    f"\n\nRFC-0005 coding worktree for this task: {coding_worktree_path}\n"
                    "Edit and verify inside this worktree via filesystem/git/terminal/python/verify_code."
                )
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
            turn_ws = None
            if managed_retrieval is not None and active_prompt == managed_retrieval_prompt:
                try:
                    turn_ws = await managed_retrieval
                except (asyncio.CancelledError, Exception):
                    turn_ws = None
            elif managed_retrieval is not None:
                managed_retrieval.cancel()
                with contextlib.suppress(asyncio.CancelledError, Exception):
                    await managed_retrieval
            if turn_ws is None:
                turn_ws = await compose_turn_working_set(
                    active_prompt,
                    task_class=working.task_class,
                    extra_capabilities=working.requested_tools,
                    security_role=working.security_role,
                    agent_id="owner",
                    recent_messages=existing,
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
            from ..reverse_engineering.skill import prompt_block as reverse_skill_block
            system_prompt += "\n\n" + reverse_skill_block(active_prompt, working.task_class)
            audit = professional_prompt_block(active_prompt)
            if audit:
                # Append after tool exposure so context fitting keeps this block in the tail.
                system_prompt += "\n\n" + audit
            messages = [
                ChatMessage(role="system", content=system_prompt),
                ChatMessage(role="user", content=active_prompt),
                internal_user_message(plan_prompt),
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
                    await speak_progress(task_id, name, arguments)
                    observation, attach = await self._execute_tool_ex(task_id, name, arguments, autonomy, settings)
                    failed = "ERROR:" in observation or observation.lower().startswith("error")
                    working.note_tool(name, observation, not failed)
                    self._note_memory_tool(working, name, arguments, not failed)
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
                    messages.append(internal_user_message(VERIFY_PROMPT))
                    await self._update(
                        task_id,
                        conversation_json=serialize_messages(messages),
                        compact_memory=working.dumps(),
                        current_action=f"Ran skill {skill.name}",
                    )
                    break

        if pending_tool:
            pending_name = pending_tool["name"]
            pending_args = pending_tool["arguments"] if isinstance(pending_tool.get("arguments"), dict) else {}
            pending_grant_id = pending_tool.get("grant_id")
            await speak_progress(task_id, pending_name, pending_args)
            result_text = await self._execute_tool(
                task_id,
                pending_name,
                pending_args,
                autonomy,
                settings,
                approved=bool(pending_grant_id),
                grant_id=str(pending_grant_id) if pending_grant_id else None,
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
        template_retries = 0
        work_wrap_retries = 0
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
                messages = compact_history(
                    messages,
                    working_state_block=working.as_prompt_block(),
                    user_fallback=working.goal or extra_prompt or prompt,
                )
                compacted = any(
                    isinstance(message.content, str) and message.content.startswith(SUMMARY_MARKER)
                    for message in messages
                )
                needed = next_context_size(
                    int(MANAGER.state.context_size or profile.context_size),
                    effective_cap or profile_cap(profile, settings),
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
                    turn_tools = select_turn_schemas(
                        turn_tools,
                        model_family=profile.family,
                        prompt=_latest_user_text(messages, working.goal or active_prompt),
                    )
                    if working.ingress_blob_id and not force_final:
                        ingress_tool = REGISTRY.tools.get("read_ingress")
                        if ingress_tool is not None and ingress_tool.enabled:
                            selected = list(turn_tools or [])
                            if not any(item.get("function", {}).get("name") == "read_ingress" for item in selected):
                                selected.append(ingress_tool.schema())
                            turn_tools = selected
                    turn_max_tokens = 400 if force_final else 1024

                    async def _model_turn_inner() -> ChatResult:
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

                    async def _model_turn() -> ChatResult:
                        nonlocal model_turn_index
                        model_turn_index += 1
                        predecessor = await last_committed_step_key(task_id)
                        predecessors = [predecessor] if predecessor else []
                        step_key = (
                            f"model:{model_turn_index}:{int(verifying)}:{int(force_final)}"
                        )
                        fingerprint = {
                            "model_turn": model_turn_index,
                            "messages_len": len(messages),
                            "tool_rounds": tool_rounds,
                            "verifying": verifying,
                            "force_final": force_final,
                        }

                        def _model_cost(chat: ChatResult) -> tuple[int, float, float]:
                            usage = chat.usage or {}
                            timings = chat.timings or {}
                            tokens = int(usage.get("total_tokens") or usage.get("completion_tokens") or 0)
                            ms = float(timings.get("total_ms") or timings.get("generation_ms") or 0.0)
                            return tokens, ms, 0.0

                        return await run_model_step(
                            task_id,
                            step_key,
                            predecessor_keys=predecessors,
                            input_fingerprint=fingerprint,
                            operation=_model_turn_inner,
                            cost_extractor=_model_cost,
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
                        if is_inference_template_error(exc) and template_retries < 1:
                            template_retries += 1
                            if messages and messages[-1].role == "user":
                                messages = messages[:-1]
                            continue
                        if tools_used and work_wrap_retries < 1:
                            work_wrap_retries += 1
                            wrap = "The requested work already ran on disk."
                            if await self._complete(
                                task_id,
                                messages,
                                wrap,
                                wrap,
                                working,
                                metrics,
                            ):
                                return
                            continue
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
                        if await self._complete(task_id, messages, content, "Timed out after verification tools ran.", working, metrics):
                            return
                        continue
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
                    if first_sentence_ready(result.content or ""):
                        note_worker_first_sentence(task_id)

                if force_final:
                    content = (result.content or "").strip() or (
                        "Task finished. The tool log contains the actions that were taken and verified."
                    )
                    messages.append(ChatMessage(role="assistant", content=content, reasoning_content=result.reasoning or None))
                    working.verified = True
                    await self._update(task_id, compact_memory=working.dumps())
                    if await self._complete(task_id, messages, content, content, working, metrics):
                        return
                    continue

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
                    call_error = validate_turn_calls(result.tool_calls, turn_tools)
                    if call_error:
                        invalid_tool_turns += 1
                        metrics.schema_errors += 1
                        await self._update(task_id, **metrics.as_fields())
                        await BUS.publish(task_id, "error", "Rejected model tool call", call_error, stage="diagnose")
                        if invalid_tool_turns >= 3:
                            await self._update(task_id, status="failed", stage="failed", error=call_error,
                                               result=call_error, current_action="Failed: invalid model tool calls")
                            await record_trajectory(task_id, working, "failed")
                            await complete_coding_route(task_id, "failed", call_error)
                            return
                        messages.append(internal_user_message(
                            f"Your tool call was rejected: {call_error} Return one valid call using only the offered schemas."
                        ))
                        continue
                    invalid_tool_turns = 0
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
                        name, arguments = normalize_tool_call(name, arguments, REGISTRY.tools.get(name))
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
                            consecutive_failures += 1
                            last_failed_observation = observation
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
                        side = _side_effect_decision(
                            name,
                            arguments if isinstance(arguments, dict) else {},
                            task_id=task_id,
                            park_if_needed=True,
                        )
                        if side.requires_approval or (
                            not side.allowed
                            and _tool_needs_operator_pause(autonomy, risk, command, name, arguments)
                        ):
                            metrics.note_confirmation()
                            irreversible = needs_confirmation(
                                autonomy, risk, command, tool_name=name, arguments=arguments
                            ) or side.effect.destructive_effect
                            payload = confirmation_payload_for_tool(
                                call_id=call["id"],
                                name=name,
                                arguments=arguments,
                                irreversible=irreversible,
                            )
                            payload["pending_approval_id"] = side.pending_approval_id
                            payload["action_id"] = side.action_id
                            payload["reversibility"] = side.effect.reversibility.value
                            payload["rfc0031"] = True
                            if not side.pending_approval_id:
                                # Ensure a parked request exists even if pause came from legacy path.
                                from ..policy.approval_grant import action_id_for, park_approval_request

                                target = side.effect.target
                                action_id = side.action_id or action_id_for(
                                    name, side.effect.action, target, task_id=task_id
                                )
                                parked = park_approval_request(
                                    action_id=action_id,
                                    tool_name=name,
                                    action=side.effect.action,
                                    scope={"call_id": call["id"]},
                                    target=target,
                                    task_id=task_id,
                                    reason=side.reason,
                                    effect=side.effect.as_dict(),
                                )
                                payload["pending_approval_id"] = parked["id"]
                                payload["action_id"] = action_id
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
                                json.dumps(
                                    {
                                        "arguments": arguments,
                                        "pending_approval_id": payload.get("pending_approval_id"),
                                        "reversibility": payload.get("reversibility"),
                                        "reason": side.reason,
                                    },
                                    default=str,
                                )[:1500],
                                stage="act",
                            )
                            return
                        if not side.allowed:
                            observation = _authorization_observation(_tool_authorization(name, arguments))
                            messages.append(
                                ChatMessage(role="tool", name=name, tool_call_id=call["id"], content=observation)
                            )
                            working.note_tool(name, observation, False)
                            continue
                        await self._update(task_id, current_tool=name, current_action=f"Running {name}")
                        await BUS.publish(task_id, "tool", f"Running {name}", json.dumps(arguments)[:1500], stage="act")
                        await speak_progress(task_id, name, arguments)
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
                            observation, attach = await self._execute_tool_ex(
                                task_id, name, arguments, autonomy, settings, metrics=metrics, schema_error=schema_error
                            )
                            failed = "ERROR:" in observation or observation.lower().startswith("error")
                        if failed:
                            consecutive_failures += 1
                            failures_by_tool[name] = failures_by_tool.get(name, 0) + 1
                            kind = classify_failure(observation)
                            failure_kinds.append(kind)
                            last_failed_tool = name
                            last_failed_observation = observation
                            hints.append(recovery_hint(name, observation, failures_by_tool[name]))
                            await BUS.publish(task_id, "error", f"{name} failed", observation[:1500], stage="diagnose")
                            from ..security.blue_watch import note_tool_outcome

                            note_tool_outcome(task_id, name, arguments, observation, failed=True)
                            note_cyber_tool(working, name, arguments, observation, success=False)
                        else:
                            consecutive_failures = 0
                            failures_by_tool.pop(name, None)
                            recovering = False
                            await BUS.publish(task_id, "observation", f"{name} finished", observation[:1500], stage="observe")
                            note_contract_tool(working, name, arguments, observation, success=True)
                            note_cyber_tool(working, name, arguments, observation, success=True)
                        working.note_tool(name, observation, not failed)
                        self._note_memory_tool(working, name, arguments, not failed)
                        messages.append(ChatMessage(role="tool", name=name, tool_call_id=call["id"], content=observation))
                        if attach:
                            messages.append(_image_message(attach))
                            working.vision_requested = True
                    if consecutive_failures >= 5:
                        await self._fail_task(
                            task_id,
                            last_failed_observation or "I kept running into the same problem.",
                            working,
                            metrics,
                            current_action="Failed: no progress",
                        )
                        return
                    if hints:
                        guidance = "\n\n".join(hints)
                        working.next_action = "recover with a different strategy"
                        recovering = True
                        await BUS.publish(task_id, "retry", "Choosing a recovery strategy", guidance[:1500], stage="diagnose")
                        messages.append(internal_user_message(guidance))
                        expert = await self._maybe_consult_expert(
                            task_id,
                            working,
                            prompt,
                            consecutive_failures,
                            failures_by_tool,
                            profile_name,
                            settings,
                            verifying,
                            failure_kinds=failure_kinds,
                            last_tool=last_failed_tool,
                            last_observation=last_failed_observation,
                        )
                        if expert:
                            messages.append(
                                internal_user_message(
                                    "Expert 27B analysis (execute this plan with tools; do not wait):\n" + expert,
                                )
                            )
                    elif verifying and verify_tool_rounds >= policy.max_verify_tools:
                        force_final = True
                        messages.append(internal_user_message(STOP_AND_REPORT))
                    elif not verifying and tool_rounds >= policy.force_verify_after:
                        verifying = True
                        working.next_action = "independent verification"
                        await self._update(task_id, stage="verify", current_action="Independent verification")
                        await BUS.publish(task_id, "stage", "Independent verification pass", stage="verify")
                        messages.append(internal_user_message(VERIFY_PROMPT))
                    elif same_tool_streak >= 3 and not verifying:
                        verifying = True
                        await BUS.publish(task_id, "stage", "Independent verification pass", stage="verify")
                        messages.append(internal_user_message(VERIFY_PROMPT))
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
                        messages.append(internal_user_message(best_of_n_select_prompt(plan_candidates)))
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
                    messages.append(internal_user_message(format_selected_plan(chosen)))
                    continue

                if policy.critic_pass and not critic_done and not verifying:
                    critic_done = True
                    critic_turn = True
                    await BUS.publish(task_id, "stage", "Critiquing plan", stage="plan")
                    messages.append(internal_user_message(CRITIC_PROMPT))
                    continue
                if not tools_used:
                    messages.append(
                        internal_user_message(
                            "Now execute the plan with tools. Do not conclude until the end state exists on disk or in the environment.",
                        )
                    )
                    continue
                if not verifying:
                    verifying = True
                    working.next_action = "independent verification"
                    await self._update(task_id, stage="verify", current_action="Independent verification", compact_memory=working.dumps())
                    await BUS.publish(task_id, "stage", "Independent verification pass", stage="verify")
                    messages.append(internal_user_message(VERIFY_PROMPT))
                    continue
                if (policy.require_verify_tools or skill_requires_verify) and verify_tool_rounds == 0:
                    if not evidence_from_working(working).verified:
                        messages.append(internal_user_message(VERIFY_REQUIRED_PROMPT))
                        continue
                working.verified = True
                verification = content or "Independent verification pass completed; acceptance criteria checked."
                await self._update(task_id, compact_memory=working.dumps(), verification=verification)
                if await self._complete(task_id, messages, content or verification, verification, working, metrics):
                    return
                continue
            await self._fail_task(
                task_id,
                "Step limit reached before verification",
                working,
                metrics,
                current_action="Failed: step limit",
            )
        except asyncio.CancelledError:
            await self._update(task_id, status="cancelled", stage="cancelled", **metrics.as_fields())
            await complete_coding_route(task_id, "cancelled")
            await self._release_lazy_vision()
            raise
        except Exception as exc:
            await self._fail_task(task_id, str(exc), working, metrics)
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
        grant_id: str | None = None,
    ) -> str:
        authz = _tool_authorization(
            name,
            arguments,
            approved=approved,
            profile_id=profile_id,
            grant_id=grant_id,
            task_id=task_id,
        )
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
            grant_id=grant_id,
        )
        return text

    async def _ensure_owner_memory(self, task_id: str, prompt: str, working: WorkingState) -> bool:
        """Write a remember-request before the model loop. False means the task already failed."""
        from ..memory.owner_facts import is_memory_store_request, remember_owner_fact

        if not is_memory_store_request(prompt) or working.memory_stored:
            return True
        outcome = await remember_owner_fact(prompt, task_id=task_id)
        working.memory_stored = bool(outcome.get("stored"))
        detail = (
            f"Stored: {outcome.get('content') or ''}"
            if working.memory_stored
            else (outcome.get("repo_error") or outcome.get("vault_error") or "memory write failed")
        )
        await self._update(
            task_id,
            compact_memory=working.dumps(),
            current_action="Remembered fact stored" if working.memory_stored else "Memory store failed",
        )
        await BUS.publish(
            task_id,
            "progress" if working.memory_stored else "error",
            "Remembered fact stored" if working.memory_stored else "Could not store the fact",
            str(detail)[:1500],
            stage="act",
        )
        if working.memory_stored:
            return True
        await self._fail_task(
            task_id,
            "I could not store that fact, so this task did not succeed.",
            working,
            None,
            current_action="Failed: memory was not stored",
        )
        return False

    def _note_memory_tool(self, working: WorkingState, name: str, arguments: dict[str, Any], success: bool) -> None:
        if not success or name != "vault_memory":
            return
        action = str((arguments or {}).get("action") or "").strip().lower()
        if action in {"create", "append", "edit"}:
            working.memory_stored = True

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
        grant_id: str | None = None,
    ) -> tuple[str, str | None]:
        from .instruction_gate import tool_write_denied

        async with SessionLocal() as session:
            task_row = await session.get(Task, task_id)
            owner_prompt = (task_row.prompt if task_row else "") or ""
        denied_write = tool_write_denied(name, arguments, owner_prompt)
        if denied_write:
            await BUS.publish(task_id, "error", "File write refused", denied_write[:1500], stage="act")
            return denied_write, None
        # Prefer gate_tool_call (via _tool_authorization) so existing hooks/tests that
        # monkeypatch app.agent.loop.gate_tool_call still observe the deny/allow boundary.
        authz = _tool_authorization(
            name,
            arguments,
            approved=approved,
            profile_id=profile_id,
            grant_id=grant_id,
            task_id=task_id,
        )
        if not authz.allowed:
            return _authorization_observation(authz), None
        decision = _side_effect_decision(
            name,
            arguments,
            grant_id=grant_id,
            task_id=task_id,
            profile_id=profile_id,
            park_if_needed=False,
        )
        if grant_id and name != "reverse_engineer":
            from ..policy.approval_grant import consume_grant

            try:
                consume_grant(grant_id)
            except KeyError:
                pass
        consume_once_grants(permission_ids_for_tool(name, arguments))
        started = datetime.now(timezone.utc)

        # RFC-0031: capture restorable prior_state BEFORE mutation when required.
        prior_state: dict[str, Any] = {
            "kind": "metadata_only",
            "target": decision.effect.target,
            "tool_name": name,
            "action": decision.effect.action,
            "restorable": False,
        }
        needs_snapshot = bool(decision.effect.snapshot_required) or (
            decision.effect.side_effecting
            and decision.effect.reversibility.value in {"REVERSIBLE", "COMPENSATABLE"}
            and name in {"filesystem", "settings", "config"}
        )
        if needs_snapshot and decision.allowed:
            try:
                prior_state = capture_prior_for_effect(
                    name,
                    action=decision.effect.action,
                    arguments=arguments if isinstance(arguments, dict) else {},
                    snapshot_required=bool(decision.effect.snapshot_required),
                )
            except Exception as exc:  # noqa: BLE001 — fail closed when snapshot required
                if decision.effect.snapshot_required:
                    log.error(
                        "rfc0031 snapshot_required capture failed tool=%s action=%s task=%s: %s",
                        name,
                        decision.effect.action,
                        task_id,
                        exc,
                    )
                    try:
                        await BUS.publish(
                            task_id,
                            "error",
                            "Undo snapshot capture failed",
                            str(exc)[:1500],
                            stage="act",
                        )
                    except Exception:
                        pass
                    REGISTRY._context.pop("approval_grant_id", None)
                    return (
                        "ERROR: Reversible action blocked — could not capture undo snapshot: "
                        f"{exc}\n"
                        + json.dumps(
                            {
                                "rfc0031": {
                                    "code": "snapshot_capture_failed",
                                    "tool": name,
                                    "action": decision.effect.action,
                                    "snapshot_required": True,
                                }
                            }
                        ),
                        None,
                    )
                log.warning(
                    "rfc0031 prior capture skipped tool=%s action=%s: %s",
                    name,
                    decision.effect.action,
                    exc,
                )

        async def _run_tool_inner() -> tuple[str, str | None, bool, str]:
            async with SessionLocal() as session:
                task = await session.get(Task, task_id)
                security_role = getattr(task, "security_role", "") if task else ""
            # RFC-0197 purple: no parallel red+blue tools — only active phase set.
            if security_role == "purple-team" and name in {"hexstrike_operator", "hexstrike_defensive"}:
                from ..security.security_agents import load_purple_state, mode_tools

                purple = load_purple_state(task_id)
                if purple.locked:
                    return "ERROR: purple phase is locked after owner stop", None, False, "purple_locked"
                allowed = set(mode_tools("purple-team", purple_phase=purple.phase))
                if name not in allowed:
                    return (
                        f"ERROR: tool {name} is not allowed in purple {purple.phase} phase "
                        "(no parallel red+blue tools)",
                        None,
                        False,
                        "purple_phase_tool_denied",
                    )
            REGISTRY._context["task_id"] = task_id
            REGISTRY._context["approved"] = bool(grant_id) or approved
            REGISTRY._context["approval_grant_id"] = grant_id or ""
            REGISTRY._context["security_role"] = security_role or ""
            if name == "read_ingress":
                result = await REGISTRY.execute(name, arguments, task_id=task_id)
            elif security_role:
                result = await REGISTRY.execute(name, arguments, security_role=security_role)
            else:
                result = await REGISTRY.execute(name, arguments)
            attach = None
            if isinstance(result.data, dict):
                attach = result.data.get("attach_image")
                if not attach and result.data.get("path"):
                    if name == "screenshot" or (name == "browser" and arguments.get("action") == "screenshot"):
                        attach = result.data.get("path")
            return result.text(), attach, result.success, result.error

        arg_digest = hashlib.sha256(
            f"{name}:{json.dumps(arguments, sort_keys=True)}".encode()
        ).hexdigest()[:24]
        # Position makes the key a *step*, not a command: a crash resumes at the same
        # ordinal (records are written after execution) and reuses the committed
        # effect, while a live repeat — e.g. re-checking whether an app is running —
        # executes again instead of returning a stale observation.
        async with SessionLocal() as session:
            ordinal = await session.scalar(
                select(func.count()).select_from(ToolCallRecord).where(ToolCallRecord.task_id == task_id)
            )
        step_key = f"tool:{name}:{arg_digest}:{int(ordinal or 0)}"

        task_status = await get_task_status(task_id)
        if task_status is None:
            text, attach, success, error = await run_with_think_aloud(
                task_id,
                context=f"Running {name}",
                operation=_run_tool_inner,
            )
        else:
            predecessor = await last_committed_step_key(task_id)
            predecessors = [predecessor] if predecessor else []
            text, attach = await run_tool_step(
                task_id,
                step_key,
                name,
                arguments,
                predecessor_keys=predecessors,
                operation=_run_tool_inner,
            )
            success = not text.startswith("ERROR:")
            error = ""
            if text.startswith("ERROR:"):
                error = text.split("\n", 1)[0].replace("ERROR:", "").strip()
        duration = (datetime.now(timezone.utc) - started).total_seconds() * 1000
        if metrics is not None:
            metrics.note_tool(duration, schema_error=schema_error)
        async with SessionLocal() as session:
            session.add(
                ToolCallRecord(
                    task_id=task_id,
                    tool_name=name,
                    arguments_json=json.dumps(arguments),
                    output=text[:20000],
                    success=success,
                    error=error,
                    duration_ms=duration,
                )
            )
            if name == "git" and arguments.get("action") == "checkpoint":
                session.add(
                    Checkpoint(task_id=task_id, kind="git", path=arguments.get("path") or "", note=text[:500])
                )
            await session.commit()
        if success and decision.allowed:
            undo_note = ""
            try:
                action_name = str(decision.effect.action or "").strip().lower()
                args = arguments if isinstance(arguments, dict) else {}
                source_path = str(args.get("path") or decision.effect.target or "").strip()
                dest_path = str(args.get("destination") or args.get("to") or "").strip()
                # Live undo precondition compares against this digest at undo time.
                digest_path = dest_path if action_name in {"copy", "move", "rename"} and dest_path else source_path
                post_digest = hashlib.sha256(
                    f"{name}:{action_name}:{digest_path or decision.effect.target}:{text[:200]}".encode()
                ).hexdigest()[:32]
                if digest_path:
                    try:
                        p = Path(digest_path).expanduser()
                        if p.is_file():
                            post_digest = hashlib.sha256(p.read_bytes()).hexdigest()
                        elif p.is_dir():
                            hasher = hashlib.sha256()
                            for item in sorted(p.rglob("*")):
                                if item.is_file():
                                    rel = item.relative_to(p).as_posix()
                                    hasher.update(f"{rel}:{item.stat().st_size}".encode())
                            post_digest = hasher.hexdigest()
                        elif not p.exists() and action_name == "delete":
                            post_digest = "missing"
                    except OSError:
                        pass
                record = register_post_success_undo(
                    decision,
                    prior_state=prior_state,
                    post_state={
                        "target": decision.effect.target,
                        "kind": prior_state.get("kind"),
                        "digest_path": digest_path or decision.effect.target,
                        "destination_path": dest_path or prior_state.get("destination_path"),
                        "expected_digest": post_digest,
                    },
                    task_id=task_id,
                    run_id=task_id,
                    step_key=step_key,
                )
                if record is None and decision.effect.snapshot_required:
                    raise RuntimeError("snapshot_required action produced no undo record")
            except Exception as exc:  # noqa: BLE001 — never silent swallow
                log.exception(
                    "rfc0031 undo registration failed tool=%s action=%s task=%s step=%s",
                    name,
                    decision.effect.action,
                    task_id,
                    step_key,
                )
                try:
                    await BUS.publish(
                        task_id,
                        "error",
                        "Undo registration failed",
                        str(exc)[:1500],
                        stage="act",
                    )
                except Exception:
                    pass
                undo_note = (
                    "\nERROR: Undo registration failed after successful side effect: "
                    f"{exc}\n"
                    + json.dumps(
                        {
                            "rfc0031": {
                                "code": "undo_registration_failed",
                                "tool": name,
                                "action": decision.effect.action,
                                "snapshot_required": bool(decision.effect.snapshot_required),
                                "step_key": step_key,
                            }
                        }
                    )
                )
                # Surface into the tool observation so the owner/agent sees it.
                text = f"{text}{undo_note}"
                success = False if decision.effect.snapshot_required else success
                error = str(exc) if decision.effect.snapshot_required else error
        REGISTRY._context.pop("approval_grant_id", None)
        return text, attach

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
        failure_kinds: list[str] | None = None,
        last_tool: str = "",
        last_observation: str = "",
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
            failure_kinds=list(failure_kinds or []),
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
        fallback = canned_method_switch_plan(last_tool or "python", last_observation)
        await BUS.publish(
            task_id,
            "progress",
            "Expert consult skipped; using method-switch plan",
            (advice.reason or "unavailable")[:800],
            stage="diagnose",
        )
        return fallback


AGENT = AgentRuntime()
