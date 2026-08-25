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
from ..providers.base import ChatMessage, parse_tool_arguments
from ..tools.registry import REGISTRY
from ..tools.safety import RiskLevel, confirmation_detail, needs_confirmation
from .artifacts import image_paths_from_prompt, missing_outputs, outputs_ready
from .autonomy import resolve_autonomy
from .browser_workflows import format_workflow_hint, record_from_tracker
from .compaction import compact_history, deserialize_messages, ensure_single_system, serialize_messages, working_memory_text
from .completion import CompletionTracker
from .execution import CRITIC_PROMPT, ready_to_complete, resolve_mode
from .prompts import CONTINUE_PROMPT, FOLLOW_UP_NUDGE, SYSTEM_PROMPT
from .recovery import RecoveryTracker
from .resume import conversation_from_task, hydrate_tracker, replay_tool_messages
from .routing import classify_task
from .skills import format_skill_hint
from .trajectories import format_trajectory_hint, record_trajectory
from .verify import inspect_artifacts


def _environment_block(settings: AppSettings, execution_mode: str = "balanced", autonomy: str | None = None) -> str:
    home = Path.home()
    allowed = "\n".join(f"- {p}" for p in (settings.allowed_directories or []))
    mode = resolve_mode(execution_mode)
    auto = resolve_autonomy(autonomy or settings.autonomy)
    return (
        "\n\nEnvironment:\n"
        f"- Windows user profile: {home}\n"
        f"- Desktop: {home / 'Desktop'}\n"
        f"- Documents: {home / 'Documents'}\n"
        f"- Autonomy: {auto.label} — {auto.description} Confirms {auto.confirms}. "
        "Even Autonomous mode must pause before disk format, partition wipe, destroying backups, "
        "mass deletion outside the task, credential changes, money/purchases, disabling security, "
        "or unsolicited external send.\n"
        f"- Execution mode: {mode.label} ({mode.description} This is the agent loop, not the model profile.)\n"
        f"- Allowed directories:\n{allowed or '- (defaults)'}\n"
        "Never use a different username than the profile above.\n"
    )


def _image_part(path: str) -> dict[str, Any]:
    data = Path(path).read_bytes()
    b64 = base64.b64encode(data).decode("ascii")
    mime = "image/png" if path.lower().endswith(".png") else "image/jpeg"
    return {"type": "image_url", "image_url": {"url": f"data:{mime};base64,{b64}"}}


def _image_message(path: str, prompt: str = "Inspect this image and use it to decide the next action.") -> ChatMessage:
    return ChatMessage(
        role="user",
        content=[
            {"type": "text", "text": prompt + f"\nImage path: {path}"},
            _image_part(path),
        ],
    )


def _skipped_tool_messages(calls: list[dict[str, Any]], start: int, reason: str) -> list[ChatMessage]:
    out: list[ChatMessage] = []
    for call in calls[start:]:
        name = (call.get("function") or {}).get("name") or "unknown"
        out.append(
            ChatMessage(
                role="tool",
                name=name,
                tool_call_id=call.get("id") or "",
                content=reason,
            )
        )
    return out


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
        mode = resolve_mode(execution_mode or settings.execution_mode)
        auto = resolve_autonomy(autonomy or settings.autonomy)
        route = classify_task(prompt)
        task = Task(
            id=str(uuid.uuid4()),
            title=prompt.strip().splitlines()[0][:120],
            prompt=prompt,
            status="queued",
            stage="queued",
            autonomy=auto.name,
            profile=profile or settings.inference.profile,
            execution_mode=mode.name,
            task_class=route.task_class,
            selected_worker=route.worker,
            plan_json=route.to_json(),
        )
        async with SessionLocal() as session:
            session.add(task)
            await session.commit()
        runner = asyncio.create_task(self._run(task.id, continue_existing=False))
        self._tasks[task.id] = runner
        return task

    async def continue_task(self, task_id: str, prompt: str | None = None) -> Task:
        running = self._tasks.get(task_id)
        if running and not running.done():
            async with SessionLocal() as session:
                task = await session.get(Task, task_id)
                if not task:
                    raise KeyError(task_id)
                return task
        async with SessionLocal() as session:
            task = await session.get(Task, task_id)
            if not task:
                raise KeyError(task_id)
            if task.waiting_for_confirmation:
                await session.commit()
                return task
            if prompt:
                task.prompt = task.prompt + "\n\nFollow-up: " + prompt
            task.status = "queued"
            task.stage = "queued"
            task.error = ""
            task.finished_at = None
            task.waiting_for_confirmation = False
            task.current_action = "Resuming from saved state"
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
            if task.started_at and fields.get("status") in {"completed", "failed", "cancelled"}:
                task.finished_at = utcnow()
                started = task.started_at
                finished = task.finished_at
                if started.tzinfo is None:
                    started = started.replace(tzinfo=timezone.utc)
                if finished.tzinfo is None:
                    finished = finished.replace(tzinfo=timezone.utc)
                task.duration_seconds = (finished - started).total_seconds()
            await session.commit()

    async def _complete_after_verify(
        self,
        task_id: str,
        messages: list[ChatMessage],
        tracker: CompletionTracker,
        user_prompt: str,
        reason: str,
        model_content: str = "",
        allow_repair: bool = False,
    ) -> bool:
        """Inspect artifacts on disk. Returns True if the task ended."""
        await self._update(task_id, stage="verify", current_action="Independent verification")
        await BUS.publish(task_id, "verify", "Inspecting results on disk", stage="verify")
        result = inspect_artifacts(tracker, user_prompt)
        if result.ok:
            extra = result.summary()
            content = (model_content or "").strip() or tracker.synthesize_report(user_prompt)
            if extra:
                content = content.rstrip() + "\n\nIndependent verification:\n" + extra
            verification = "\n".join(part for part in (reason, extra) if part).strip()
            messages.append(ChatMessage(role="assistant", content=content))
            await self._update(
                task_id,
                status="completed",
                stage="completed",
                result=content,
                conversation_json=serialize_messages(messages),
                verification=verification or "Independent verification passed.",
                current_action="Completed",
                current_tool="",
            )
            await BUS.publish(task_id, "completed", "Task completed", content[:2000], stage="completed")
            task_class = None
            worker = None
            async with SessionLocal() as session:
                stored = await session.get(Task, task_id)
                if stored:
                    task_class = getattr(stored, "task_class", None)
                    worker = getattr(stored, "selected_worker", None)
            try:
                record_from_tracker(user_prompt, tracker)
            except Exception:
                pass
            try:
                record_trajectory(user_prompt, tracker, task_class=task_class, worker=worker)
            except Exception:
                pass
            return True
        if allow_repair:
            messages.append(ChatMessage(role="user", content=result.repair_prompt()))
            await self._update(
                task_id,
                conversation_json=serialize_messages(messages),
                current_action="Verification failed; repairing",
                current_tool="",
            )
            await BUS.publish(task_id, "verify", "Independent verification failed", result.summary(), stage="verify")
            return False
        fail_text = result.summary()
        await self._update(
            task_id,
            status="failed",
            stage="failed",
            error="Independent verification failed",
            result=fail_text,
            verification=fail_text,
            conversation_json=serialize_messages(messages),
            current_action="Failed verification",
            current_tool="",
        )
        await BUS.publish(task_id, "failed", "Independent verification failed", fail_text[:2000], stage="failed")
        return True

    async def _run(
        self,
        task_id: str,
        continue_existing: bool,
        extra_prompt: str | None = None,
        pending_tool: dict[str, Any] | None = None,
    ) -> None:
        settings = load_settings()
        REGISTRY.apply_settings(settings)
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
            autonomy = resolve_autonomy(task.autonomy).name
            profile_name = task.profile
            mode = resolve_mode(getattr(task, "execution_mode", None) or settings.execution_mode)
            existing = deserialize_messages(task.conversation_json)
        route = classify_task(prompt)
        await self._update(
            task_id,
            task_class=route.task_class,
            selected_worker=route.worker,
            plan_json=route.to_json(),
            current_action=f"Classified as {route.label}",
        )
        await BUS.publish(
            task_id,
            "route",
            f"{route.label} via {route.worker_label}",
            route.prompt_hint(),
            stage="understand",
        )
        profile = resolve_profile(profile_name)
        env_block = _environment_block(settings, mode.name, autonomy)
        if not await MANAGER.ready_for_profile(profile):
            await BUS.publish(task_id, "stage", "Loading local model", stage="model")
            await MANAGER.load(settings, profile_name)
        provider = MANAGER.provider
        assert provider is not None

        if existing and continue_existing:
            messages = existing
            if extra_prompt:
                messages.append(ChatMessage(role="user", content=CONTINUE_PROMPT + "\n\n" + extra_prompt))
            else:
                messages.append(ChatMessage(role="user", content=CONTINUE_PROMPT))
        elif continue_existing:
            messages = conversation_from_task(task, env_block, mode.plan_prompt)
            messages = await replay_tool_messages(task_id, messages)
            if extra_prompt:
                messages.append(ChatMessage(role="user", content=CONTINUE_PROMPT + "\n\n" + extra_prompt))
            else:
                messages.append(ChatMessage(role="user", content=CONTINUE_PROMPT))
        else:
            user_content: Any = prompt + "\n\n" + mode.plan_prompt
            hint = format_workflow_hint(prompt)
            if hint:
                user_content = user_content + "\n\n" + hint
            skill_hint = format_skill_hint(prompt, route.task_class)
            if skill_hint:
                user_content = user_content + "\n\n" + skill_hint
            traj_hint = format_trajectory_hint(prompt, route.task_class)
            if traj_hint:
                user_content = user_content + "\n\n" + traj_hint
            user_content = user_content + "\n\n" + route.prompt_hint()
            images = image_paths_from_prompt(prompt)
            if images:
                parts: list[dict[str, Any]] = [{"type": "text", "text": user_content}]
                for image_path in images:
                    parts.append(_image_part(image_path))
                user_content = parts
            messages = [
                ChatMessage(role="system", content=SYSTEM_PROMPT + env_block),
                ChatMessage(role="user", content=user_content),
            ]

        tracker = CompletionTracker()
        recovery = RecoveryTracker(
            fail_after_tool=mode.recovery_fail_after,
            fail_after_streak=mode.recovery_fail_streak,
        )
        recent_hashes: list[str] = []
        max_steps = mode.max_steps
        tools_used = False
        consecutive_failures = 0
        tool_rounds = 0
        last_tool_name = ""
        same_tool_streak = 0
        plan_nudges = 0
        repairs_used = 0
        awaiting_repair = False
        template_retries = 0
        critic_injected = False
        follow_up = bool(continue_existing and extra_prompt)
        baseline_steps = 0
        if continue_existing:
            await hydrate_tracker(task_id, tracker)
            tools_used = bool(tracker.steps) or any(message.role == "tool" for message in messages)
            baseline_steps = len(tracker.steps)
        await self._update(task_id, conversation_json=serialize_messages(messages))

        def session_mutated() -> bool:
            return any(
                step.kind == "mutate" and step.success and not step.blocked
                for step in tracker.steps[baseline_steps:]
            )

        def can_complete() -> bool:
            return (not follow_up) or session_mutated()

        async def finish(reason: str, model_content: str = "", allow_repair: bool = True) -> bool:
            nonlocal repairs_used, awaiting_repair
            ended = await self._complete_after_verify(
                task_id,
                messages,
                tracker,
                prompt,
                reason,
                model_content=model_content,
                allow_repair=allow_repair and repairs_used < mode.max_repairs,
            )
            if not ended:
                repairs_used += 1
                awaiting_repair = True
            return ended

        if pending_tool:
            result_text, _, pending_ok = await self._execute_tool_ex(
                task_id, pending_tool["name"], pending_tool["arguments"], autonomy, settings
            )
            tracker.record(pending_tool["name"], pending_tool["arguments"], pending_ok, result_text)
            recovery.record(pending_tool["name"], pending_tool["arguments"], pending_ok, result_text)
            messages.append(
                ChatMessage(
                    role="tool",
                    name=pending_tool["name"],
                    tool_call_id=pending_tool.get("id") or "confirmed",
                    content=result_text,
                )
            )

        try:
            for _step in range(max_steps):
                if task_id in self._cancel:
                    await self._update(task_id, status="cancelled", stage="cancelled", current_action="Cancelled")
                    await BUS.publish(task_id, "cancelled", "Task cancelled")
                    return
                if ready_to_complete(tracker, prompt, mode) and not awaiting_repair:
                    if not can_complete():
                        pass
                    elif await finish(tracker.reason):
                        return
                    else:
                        continue
                use_thinking = bool(mode.allow_thinking and profile.thinking and repairs_used == 0)
                await self._update(task_id, stage="act", current_action="Waiting on model")
                await BUS.publish(
                    task_id,
                    "model",
                    "Model is thinking" if use_thinking else "Model is responding",
                    stage="act",
                )
                messages = ensure_single_system(compact_history(messages, goal=prompt))
                tool_schemas = recovery.tools_for_next_round(route.filter_schemas(REGISTRY.openai_tools()))
                try:
                    result = await asyncio.wait_for(
                        provider.chat(
                            messages,
                            tools=tool_schemas,
                            temperature=profile.temperature,
                            top_p=profile.top_p,
                            top_k=profile.top_k,
                            thinking=use_thinking,
                            max_tokens=2048,
                        ),
                        timeout=180,
                    )
                except TimeoutError:
                    if can_complete() and (tracker.artifact_mutates() or tools_used):
                        await finish(
                            "Model timed out after tool work; completing from tool evidence.",
                            allow_repair=False,
                        )
                        return
                    if follow_up and not session_mutated():
                        messages.append(ChatMessage(role="user", content=FOLLOW_UP_NUDGE))
                        continue
                    await self._update(
                        task_id,
                        status="failed",
                        stage="failed",
                        error="Model timed out before any successful work",
                        current_action="Failed",
                        current_tool="",
                    )
                    await BUS.publish(task_id, "failed", "Model timed out", stage="failed")
                    return
                except Exception as exc:
                    err = str(exc)
                    if "System message must be at the beginning" in err and template_retries < 2:
                        template_retries += 1
                        messages = ensure_single_system(messages)
                        await BUS.publish(task_id, "retry", "Retrying after chat-template error", err[:500], stage="diagnose")
                        continue
                    raise
                await MANAGER.record_timings(result.timings)
                if result.tool_calls:
                    tools_used = True
                    tool_rounds += 1
                    names = [c.get("function", {}).get("name") or "" for c in result.tool_calls]
                    primary = names[0] if names else ""
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
                    pending_images: list[str] = []
                    skip_remaining = ""
                    for call_index, call in enumerate(result.tool_calls):
                        if skip_remaining:
                            break
                        name = call["function"]["name"]
                        arguments = parse_tool_arguments(call["function"]["arguments"])
                        signature = hashlib.sha256(f"{name}:{json.dumps(arguments, sort_keys=True)}".encode()).hexdigest()
                        if recent_hashes[-3:].count(signature) >= 2:
                            observation = "Repeated identical failing/identical tool call blocked. Choose a different strategy."
                            await BUS.publish(task_id, "retry", "Blocked identical retry", observation, stage="diagnose")
                            messages.append(ChatMessage(role="tool", name=name, tool_call_id=call["id"], content=observation))
                            tracker.record(name, arguments, False, observation, blocked=True)
                            plan = recovery.record(name, arguments, False, observation, blocked=True)
                            if plan:
                                messages.extend(_skipped_tool_messages(result.tool_calls, call_index + 1, "Skipped; recovery switched strategy."))
                                messages.append(ChatMessage(role="user", content=plan.prompt))
                                await BUS.publish(task_id, "retry", f"Switching strategy away from {name}", plan.prompt[:1500], stage="diagnose")
                                skip_remaining = "recovery"
                            continue
                        recent_hashes.append(signature)
                        tool_meta = REGISTRY.tools.get(name)
                        risk = tool_meta.risk if tool_meta else RiskLevel.MEDIUM
                        command = arguments.get("command") if isinstance(arguments, dict) else None
                        if needs_confirmation(autonomy, risk, command):
                            detail = confirmation_detail(autonomy, risk, name, command if isinstance(command, str) else None)
                            payload = {"id": call["id"], "name": name, "arguments": arguments, "reason": detail}
                            await self._update(
                                task_id,
                                status="waiting",
                                waiting_for_confirmation=True,
                                confirmation_payload=json.dumps(payload),
                                current_action=f"Waiting for confirmation: {name}",
                                conversation_json=serialize_messages(messages),
                            )
                            await BUS.publish(
                                task_id,
                                "confirm",
                                f"Confirmation required for {name}",
                                (detail + " " + json.dumps(arguments))[:1500],
                                stage="act",
                            )
                            return
                        await self._update(task_id, current_tool=name, current_action=f"Running {name}")
                        await BUS.publish(task_id, "tool", f"Running {name}", json.dumps(arguments)[:1500], stage="act")
                        observation, attach, success = await self._execute_tool_ex(task_id, name, arguments, autonomy, settings)
                        tracker.record(name, arguments, success, observation)
                        plan = recovery.record(name, arguments, success, observation)
                        if not success:
                            consecutive_failures += 1
                            await BUS.publish(task_id, "error", f"{name} failed", observation[:1500], stage="diagnose")
                            if plan:
                                messages.append(ChatMessage(role="tool", name=name, tool_call_id=call["id"], content=observation))
                                messages.extend(_skipped_tool_messages(result.tool_calls, call_index + 1, "Skipped; recovery switched strategy."))
                                messages.append(ChatMessage(role="user", content=plan.prompt))
                                await BUS.publish(task_id, "retry", f"Switching strategy away from {name}", plan.prompt[:1500], stage="diagnose")
                                if attach:
                                    pending_images.append(attach)
                                skip_remaining = "recovery"
                                continue
                        else:
                            consecutive_failures = 0
                            await BUS.publish(task_id, "observation", f"{name} finished", observation[:1500], stage="observe")
                        messages.append(ChatMessage(role="tool", name=name, tool_call_id=call["id"], content=observation))
                        if attach:
                            pending_images.append(attach)
                    for image_path in pending_images:
                        messages.append(_image_message(image_path))
                    awaiting_repair = False
                    persisted = {
                        "conversation_json": serialize_messages(messages),
                        "retries": consecutive_failures,
                        "current_action": f"Ran {primary}" if primary else "Observed tools",
                    }
                    memory = working_memory_text(messages)
                    if memory:
                        persisted["compact_memory"] = memory
                    await self._update(task_id, **persisted)
                    if ready_to_complete(tracker, prompt, mode) and can_complete():
                        if await finish(tracker.reason):
                            return
                        continue
                    still_missing = missing_outputs(prompt)
                    if still_missing and tool_rounds in set(mode.missing_file_nudge_rounds):
                        messages.append(
                            ChatMessage(
                                role="user",
                                content=(
                                    "Requested output files are still missing:\n- "
                                    + "\n- ".join(still_missing)
                                    + "\nCreate those files now. Do not stop."
                                ),
                            )
                        )
                    if (
                        mode.critic_after_rounds
                        and tool_rounds == mode.critic_after_rounds
                        and not critic_injected
                    ):
                        critic_injected = True
                        messages.append(ChatMessage(role="user", content=CRITIC_PROMPT))
                    if (
                        can_complete()
                        and same_tool_streak >= mode.same_tool_streak_limit
                        and tracker.artifact_mutates()
                        and consecutive_failures == 0
                        and outputs_ready(prompt)
                    ):
                        if await finish("Stopped a same-tool poll loop after the work already ran."):
                            return
                        continue
                    if (
                        can_complete()
                        and tool_rounds >= mode.tool_round_budget
                        and (tracker.artifact_mutates() or tools_used)
                        and outputs_ready(prompt)
                    ):
                        if await finish("Reached the tool-round budget after successful work."):
                            return
                        continue
                    continue

                content = (result.content or "").strip()
                if not tools_used:
                    plan_nudges += 1
                    messages.append(ChatMessage(role="assistant", content=content, reasoning_content=result.reasoning or None))
                    if plan_nudges >= 2:
                        await self._update(
                            task_id,
                            status="failed",
                            stage="failed",
                            error="Model did not use tools",
                            result=content,
                            current_action="Failed",
                        )
                        await BUS.publish(task_id, "failed", "Model did not use tools", content[:1500], stage="failed")
                        return
                    messages.append(
                        ChatMessage(
                            role="user",
                            content="Now execute the plan with tools. Do not conclude until the end state exists on disk or in the environment.",
                        )
                    )
                    continue
                if not can_complete():
                    messages.append(ChatMessage(role="assistant", content=content, reasoning_content=result.reasoning or None))
                    messages.append(ChatMessage(role="user", content=FOLLOW_UP_NUDGE))
                    continue
                if await finish(
                    "Model returned a final report without further tool calls.",
                    model_content=content,
                ):
                    return
                continue
            if can_complete() and (tracker.artifact_mutates() or tools_used):
                await finish("Step limit reached; completing from tool evidence.", allow_repair=False)
            else:
                await self._update(task_id, status="failed", stage="failed", error="Step limit reached before any tool work")
                await BUS.publish(task_id, "failed", "Step limit reached", stage="failed")
        except asyncio.CancelledError:
            await self._update(task_id, status="cancelled", stage="cancelled")
            raise
        except Exception as exc:
            if can_complete() and tracker.artifact_mutates():
                await finish(
                    f"Recovered from an internal error after successful work: {exc}",
                    allow_repair=False,
                )
                return
            await self._update(task_id, status="failed", stage="failed", error=str(exc))
            await BUS.publish(task_id, "failed", "Task failed", str(exc), stage="failed")

    async def _execute_tool(
        self, task_id: str, name: str, arguments: dict[str, Any], autonomy: str, settings: AppSettings
    ) -> str:
        text, _, _ = await self._execute_tool_ex(task_id, name, arguments, autonomy, settings)
        return text

    async def _execute_tool_ex(
        self, task_id: str, name: str, arguments: dict[str, Any], autonomy: str, settings: AppSettings
    ) -> tuple[str, str | None, bool]:
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
            attach = result.data.get("attach_image")
            if not attach and name in {"screenshot", "browser"}:
                path = result.data.get("path")
                if path and str(path).lower().endswith((".png", ".jpg", ".jpeg", ".webp", ".gif")):
                    attach = path
        return result.text(), attach, result.success


AGENT = AgentRuntime()
