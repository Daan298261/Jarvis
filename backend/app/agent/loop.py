from __future__ import annotations

import asyncio
import base64
import hashlib
import json
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from ..config import AppSettings, load_settings
from ..db.models import Checkpoint, Task, ToolCallRecord, utcnow
from ..db.session import SessionLocal
from ..events import BUS
from ..inference.manager import MANAGER
from ..inference.profiles import resolve_profile
from ..providers.base import ChatMessage, ChatResult, parse_tool_arguments
from ..tools.exposure import ToolExposure
from ..tools.registry import REGISTRY
from ..tools.safety import RiskLevel, needs_confirmation
from .compaction import compact_history, deserialize_messages, serialize_messages
from .escalation import brief_from_working, consult_expert, format_expert_message, should_escalate
from .planning import (
    WorkingState,
    best_of_n_plan_prompt,
    best_of_n_select_prompt,
    classify_task,
    format_selected_plan,
    parse_plan_block,
    parse_plan_candidates,
    resolve_execution_policy,
    select_best_plan,
)
from .recovery import recovery_hint
from .skills import as_prompt_block as skills_prompt_block
from .skills import bind_parameters, instantiate_steps, promote_from_trajectories, relevant_skills, steps_are_executable
from .trajectory import as_prompt_block, record_trajectory, relevant_trajectories
from .prompts import (
    CONTINUE_PROMPT,
    CRITIC_PROMPT,
    PLAN_PROMPT,
    STOP_AND_REPORT,
    SYSTEM_PROMPT,
    VERIFY_PROMPT,
    VERIFY_REQUIRED_PROMPT,
)


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


class AgentRuntime:
    def __init__(self) -> None:
        self._tasks: dict[str, asyncio.Task] = {}
        self._cancel = set()

    async def create_task(
        self,
        prompt: str,
        autonomy: str | None = None,
        profile: str | None = None,
        execution_mode: str | None = None,
    ) -> Task:
        settings = load_settings()
        mode = execution_mode or settings.execution_mode or "balanced"
        task = Task(
            id=str(uuid.uuid4()),
            title=prompt.strip().splitlines()[0][:120],
            prompt=prompt,
            status="queued",
            stage="queued",
            autonomy=autonomy or settings.autonomy,
            profile=profile or settings.inference.profile,
            execution_mode=mode,
            task_class=classify_task(prompt),
        )
        async with SessionLocal() as session:
            session.add(task)
            await session.commit()
        runner = asyncio.create_task(self._run(task.id, continue_existing=False))
        self._tasks[task.id] = runner
        return task

    async def continue_task(self, task_id: str, prompt: str | None = None) -> Task:
        async with SessionLocal() as session:
            task = await session.get(Task, task_id)
            if not task:
                raise KeyError(task_id)
            if prompt:
                task.prompt = task.prompt + "\n\nFollow-up: " + prompt
            task.status = "queued"
            task.waiting_for_confirmation = False
            task.updated_at = utcnow()
            await session.commit()
        runner = asyncio.create_task(self._run(task_id, continue_existing=True, extra_prompt=prompt))
        self._tasks[task_id] = runner
        return task

    async def confirm_task(self, task_id: str, approved: bool) -> Task:
        async with SessionLocal() as session:
            task = await session.get(Task, task_id)
            if not task:
                raise KeyError(task_id)
            if not approved:
                task.status = "cancelled"
                task.stage = "cancelled"
                task.waiting_for_confirmation = False
                await session.commit()
                await BUS.publish(task_id, "cancelled", "User rejected the pending action")
                return task
            payload = json.loads(task.confirmation_payload or "{}")
            task.waiting_for_confirmation = False
            task.status = "running"
            await session.commit()
        runner = asyncio.create_task(self._run(task_id, continue_existing=True, pending_tool=payload))
        self._tasks[task_id] = runner
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
    ) -> None:
        await self._update(
            task_id,
            status="completed",
            stage="completed",
            result=content,
            conversation_json=serialize_messages(messages),
            verification=verification,
            current_action="Completed",
            current_tool="",
        )
        if working is not None:
            await record_trajectory(task_id, working, "completed")
            for skill in await promote_from_trajectories():
                await BUS.publish(task_id, "progress", f"Promoted reusable skill: {skill.name}", skill.description[:800])
        await BUS.publish(task_id, "completed", "Task completed", content[:2000], stage="completed")

    async def _run(
        self,
        task_id: str,
        continue_existing: bool,
        extra_prompt: str | None = None,
        pending_tool: dict[str, Any] | None = None,
    ) -> None:
        settings = load_settings()
        REGISTRY.apply_settings(settings)
        exposure = ToolExposure("mixed")
        REGISTRY.bind_exposure(exposure)
        fields = {
            "status": "running",
            "stage": "understand",
            "current_action": "Understanding the request",
            "waiting_for_confirmation": False,
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
        exposure = ToolExposure(working.task_class)
        REGISTRY.bind_exposure(exposure)
        policy = resolve_execution_policy(execution_mode)
        profile = resolve_profile(profile_name)
        plan_prompt = best_of_n_plan_prompt(policy.best_of_n) if policy.best_of_n > 1 else PLAN_PROMPT
        if not MANAGER.provider or not MANAGER.state.loaded:
            await BUS.publish(task_id, "stage", "Loading local model", stage="model")
            await MANAGER.load(settings, profile_name)
        provider = MANAGER.provider
        assert provider is not None

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
        same_tool_streak = 0
        force_final = False
        plan_candidates: list = []
        awaiting_plan_selection = False
        best_of_n_complete = policy.best_of_n <= 1
        skill_requires_verify = False
        escalated = False
        expert_on_request = should_escalate(prompt=prompt, step_count=0) == "user_requested_expert"

        if existing and continue_existing:
            messages = existing
            if extra_prompt:
                messages.append(ChatMessage(role="user", content=CONTINUE_PROMPT + "\n\n" + extra_prompt))
            else:
                messages.append(ChatMessage(role="user", content=CONTINUE_PROMPT))
        else:
            system_prompt = SYSTEM_PROMPT + _environment_block(settings)
            matched_skills = await relevant_skills(working.task_class, working.goal)
            skills = skills_prompt_block(matched_skills)
            if skills:
                system_prompt += "\n\n" + skills
                await BUS.publish(task_id, "progress", "Applying a known skill", skills[:1500], stage="understand")
            lessons = as_prompt_block(await relevant_trajectories(working.task_class, working.goal))
            if lessons:
                system_prompt += "\n\n" + lessons
                await BUS.publish(task_id, "progress", "Recalled similar earlier tasks", lessons[:1500], stage="understand")
            messages = [
                ChatMessage(role="system", content=system_prompt),
                ChatMessage(role="user", content=prompt + "\n\n" + plan_prompt),
            ]
            for skill in matched_skills:
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
                    if needs_confirmation(autonomy, risk, command):
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
            result_text = await self._execute_tool(task_id, pending_tool["name"], pending_tool["arguments"], autonomy, settings)
            messages.append(
                ChatMessage(
                    role="tool",
                    name=pending_tool["name"],
                    tool_call_id=pending_tool.get("id") or "confirmed",
                    content=result_text,
                )
            )
            tools_used = True

        try:
            for _step in range(max_steps):
                if task_id in self._cancel:
                    await self._update(task_id, status="cancelled", stage="cancelled", current_action="Cancelled")
                    await BUS.publish(task_id, "cancelled", "Task cancelled")
                    return
                await self._update(
                    task_id,
                    stage="verify" if verifying else "act",
                    current_action="Waiting on model",
                    compact_memory=working.dumps(),
                    execution_mode=execution_mode,
                    task_class=working.task_class,
                )
                await BUS.publish(
                    task_id,
                    "model",
                    "Writing final report" if force_final else ("Verifying result" if verifying else ("Model is thinking" if profile.thinking else "Model is responding")),
                    stage="verify" if verifying else "act",
                )
                messages = compact_history(messages, working_state_block=working.as_prompt_block())
                exposed = None if force_final else REGISTRY.openai_tools(exposure.names())
                try:
                    result: ChatResult = await asyncio.wait_for(
                        provider.chat(
                            messages,
                            tools=exposed,
                            temperature=profile.temperature,
                            top_p=profile.top_p,
                            top_k=profile.top_k,
                            thinking=False if force_final or verifying else (profile.thinking and not verifying),
                            max_tokens=400 if force_final else 1024,
                        ),
                        timeout=90 if force_final else 180,
                    )
                except TimeoutError:
                    if tools_used and verifying:
                        content = (
                            "The model timed out while writing the final report. "
                            "Actions already executed are in the activity log; verify files from that log."
                        )
                        await self._complete(task_id, messages, content, "Timed out after verification tools ran.", working)
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
                    )
                    await record_trajectory(task_id, working, "failed")
                    await BUS.publish(task_id, "failed", "Task ended after model timeout", content, stage="failed")
                    return
                await MANAGER.record_timings(result.timings)
                if result.reasoning:
                    await BUS.publish(task_id, "progress", "Reasoning complete", result.reasoning[-1500:], stage="act")

                if force_final:
                    content = (result.content or "").strip() or (
                        "Task finished. The tool log contains the actions that were taken and verified."
                    )
                    messages.append(ChatMessage(role="assistant", content=content, reasoning_content=result.reasoning or None))
                    working.verified = True
                    await self._update(task_id, compact_memory=working.dumps())
                    await self._complete(task_id, messages, content, content, working)
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
                        arguments = parse_tool_arguments(call["function"]["arguments"])
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
                        if needs_confirmation(autonomy, risk, command):
                            await self._update(
                                task_id,
                                status="waiting",
                                waiting_for_confirmation=True,
                                confirmation_payload=json.dumps({"id": call["id"], "name": name, "arguments": arguments}),
                                current_action=f"Waiting for confirmation: {name}",
                                conversation_json=serialize_messages(messages),
                                compact_memory=working.dumps(),
                            )
                            await BUS.publish(task_id, "confirm", f"Confirmation required for {name}", json.dumps(arguments)[:1500], stage="act")
                            return
                        await self._update(task_id, current_tool=name, current_action=f"Running {name}")
                        await BUS.publish(task_id, "tool", f"Running {name}", json.dumps(arguments)[:1500], stage="act")
                        observation, attach = await self._execute_tool_ex(task_id, name, arguments, autonomy, settings)
                        failed = "ERROR:" in observation or observation.lower().startswith("error")
                        if failed:
                            consecutive_failures += 1
                            failures_by_tool[name] = failures_by_tool.get(name, 0) + 1
                            hints.append(recovery_hint(name, observation, failures_by_tool[name]))
                            await BUS.publish(task_id, "error", f"{name} failed", observation[:1500], stage="diagnose")
                        else:
                            consecutive_failures = 0
                            failures_by_tool.pop(name, None)
                            await BUS.publish(task_id, "observation", f"{name} finished", observation[:1500], stage="observe")
                        working.note_tool(name, observation, not failed)
                        messages.append(ChatMessage(role="tool", name=name, tool_call_id=call["id"], content=observation))
                        if attach:
                            messages.append(_image_message(attach))
                    if hints:
                        guidance = "\n\n".join(hints)
                        working.next_action = "recover with a different strategy"
                        await BUS.publish(task_id, "retry", "Choosing a recovery strategy", guidance[:1500], stage="diagnose")
                        messages.append(ChatMessage(role="user", content=guidance))
                        reason = should_escalate(
                            prompt=prompt,
                            consecutive_failures=consecutive_failures,
                            same_tool_streak=same_tool_streak,
                            already_escalated=escalated,
                            verifying=verifying,
                        )
                        if reason:
                            brief = brief_from_working(working, reason, prompt)
                            expert = await consult_expert(
                                brief,
                                provider=provider,
                                manager=MANAGER,
                                settings=settings,
                                allow_swap=False,
                            )
                            escalated = True
                            await BUS.publish(task_id, "progress", "Expert consult", (expert.advice or "")[:1500], stage="diagnose")
                            messages.append(ChatMessage(role="user", content=format_expert_message(expert)))
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

                if expert_on_request and not escalated:
                    brief = brief_from_working(working, "user_requested_expert", prompt)
                    expert = await consult_expert(
                        brief,
                        provider=provider,
                        manager=MANAGER,
                        settings=settings,
                        allow_swap=False,
                    )
                    escalated = True
                    expert_on_request = False
                    await BUS.publish(task_id, "progress", "Expert consult", (expert.advice or "")[:1500], stage="plan")
                    messages.append(ChatMessage(role="user", content=format_expert_message(expert)))

                if policy.critic_pass and not critic_done and not verifying:
                    critic_done = True
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
                await self._complete(task_id, messages, content or verification, verification, working)
                return
            await self._update(task_id, status="failed", stage="failed", error="Step limit reached before verification")
            await record_trajectory(task_id, working, "failed")
            await BUS.publish(task_id, "failed", "Step limit reached", stage="failed")
        except asyncio.CancelledError:
            await self._update(task_id, status="cancelled", stage="cancelled")
            raise
        except Exception as exc:
            await self._update(task_id, status="failed", stage="failed", error=str(exc))
            await record_trajectory(task_id, working, "failed")
            await BUS.publish(task_id, "failed", "Task failed", str(exc), stage="failed")

    async def _execute_tool(
        self, task_id: str, name: str, arguments: dict[str, Any], autonomy: str, settings: AppSettings
    ) -> str:
        text, _ = await self._execute_tool_ex(task_id, name, arguments, autonomy, settings)
        return text

    async def _execute_tool_ex(
        self, task_id: str, name: str, arguments: dict[str, Any], autonomy: str, settings: AppSettings
    ) -> tuple[str, str | None]:
        started = datetime.now(timezone.utc)
        result = await REGISTRY.execute(name, arguments)
        duration = (datetime.now(timezone.utc) - started).total_seconds() * 1000
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
            attach = result.data.get("attach_image") or (
                result.data.get("path") if name in {"screenshot", "browser"} and result.data.get("attach_image") else result.data.get("attach_image")
            )
        return result.text(), attach


AGENT = AgentRuntime()
