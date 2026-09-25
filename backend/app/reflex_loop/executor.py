"""Reflex fast-loop executor: decide → freshness → act → verify.

Never executes model-generated selectors, coordinates, JS, or shell.
TYPE_TEXT is the only default path that invokes text generation.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable
import logging
import time

from .adapters import build_browser_action_frame, build_desktop_action_frame
from .reflex_client import (
    BROWSER_OP_TARGET_CLASS,
    DecisionQuestion,
    DecisionResult,
    ReflexDecideClient,
    get_reflex_decide_client,
)
from .sandbox import DEFAULT_SANDBOX, SandboxPosture, gate_decision_payload
from .schema import (
    ActionFrame,
    ActionNode,
    MUTATING_OPERATIONS,
    Operation,
    ReflexDecision,
    SurfaceKind,
)
from .text_gen import TextGenerator, generate_bounded_text
from .verification import (
    DEFAULT_MAX_AGE_MS,
    check_frame_freshness,
    resolve_target,
    target_changed,
    verify_postcondition,
)

log = logging.getLogger("jarvis.reflex_loop.executor")

ObserveFn = Callable[[], Awaitable[ActionFrame] | ActionFrame]
ActFn = Callable[[Operation, ActionNode, dict[str, Any]], Awaitable[dict[str, Any]] | dict[str, Any]]


@dataclass
class LoopStepRecord:
    step: int
    frame_id: str
    decision: dict[str, Any]
    success: bool
    reason: str = ""
    protocol_calls: int = 0
    model_calls: int = 0
    recovery: bool = False


@dataclass
class ReflexLoopResult:
    success: bool
    done: bool = False
    blocked: bool = False
    reason: str = ""
    steps: list[LoopStepRecord] = field(default_factory=list)
    model_calls: int = 0
    protocol_calls: int = 0
    recovery_count: int = 0
    wall_time_ms: float = 0.0
    final_frame: ActionFrame | None = None
    decisions: list[dict[str, Any]] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return {
            "success": self.success,
            "done": self.done,
            "blocked": self.blocked,
            "reason": self.reason,
            "model_calls": self.model_calls,
            "protocol_calls": self.protocol_calls,
            "recovery_count": self.recovery_count,
            "wall_time_ms": self.wall_time_ms,
            "steps": [
                {
                    "step": s.step,
                    "frame_id": s.frame_id,
                    "decision": s.decision,
                    "success": s.success,
                    "reason": s.reason,
                    "protocol_calls": s.protocol_calls,
                    "model_calls": s.model_calls,
                    "recovery": s.recovery,
                }
                for s in self.steps
            ],
            "decisions": list(self.decisions),
        }


def parse_reflex_decision(result: DecisionResult) -> ReflexDecision | None:
    """Map a Reflex Lane DecisionResult into a typed ReflexDecision. Fail closed."""
    if not result.ok:
        return None
    answers = result.answers or {}
    op_raw = answers.get("operation") or answers.get("op")
    target_raw = answers.get("target_id") or answers.get("target")
    done = bool(answers.get("done", False))
    blocked = bool(answers.get("blocked", False)) or bool(answers.get("block", False))
    if op_raw is None and done:
        op_raw = Operation.DONE.value
    if op_raw is None and blocked:
        op_raw = Operation.BLOCK.value
    if op_raw is None:
        return None
    try:
        operation = Operation(str(op_raw).strip().upper())
    except ValueError:
        return None
    target_id = None if target_raw in (None, "", "none", "null") else str(target_raw)
    if operation in {Operation.DONE, Operation.BLOCK}:
        done = operation == Operation.DONE or done
        blocked = operation == Operation.BLOCK or blocked
        target_id = None
    return ReflexDecision(
        operation=operation,
        target_id=target_id,
        done=done,
        blocked=blocked,
        reason=str(answers.get("reason") or result.error or ""),
        confidence=float(answers.get("confidence") or result.confidence or 0.0),
        text_hint=str(answers.get("text_hint") or answers.get("text") or ""),
        provider=result.provider or result.source,
    )


def build_op_target_questions(frame: ActionFrame, goal: str) -> list[DecisionQuestion]:
    ops = sorted({op.value for node in frame.nodes for op in node.supported_operations})
    ops.extend([Operation.DONE.value, Operation.BLOCK.value])
    target_ids = [n.target_id for n in frame.nodes] + ["none"]
    return [
        DecisionQuestion(
            id="operation",
            kind="choice",
            prompt=f"Choose one operation toward goal: {goal[:300]}",
            options=tuple(dict.fromkeys(ops)),
        ),
        DecisionQuestion(
            id="target_id",
            kind="choice",
            prompt="Choose target_id from the current frame, or none for DONE/BLOCK",
            options=tuple(target_ids),
        ),
        DecisionQuestion(
            id="done",
            kind="boolean",
            prompt="Is the goal already satisfied?",
        ),
        DecisionQuestion(
            id="block",
            kind="boolean",
            prompt="Should the loop stop because the goal cannot proceed safely?",
        ),
    ]


class ReflexLoopExecutor:
    """Shared fast semantic action loop for browser and desktop."""

    def __init__(
        self,
        *,
        observe: ObserveFn,
        act: ActFn,
        decide_client: ReflexDecideClient | None = None,
        text_generator: TextGenerator | None = None,
        sandbox: SandboxPosture = DEFAULT_SANDBOX,
        max_age_ms: float = DEFAULT_MAX_AGE_MS,
        permission_gate: Callable[[ReflexDecision, ActionFrame], str | None] | None = None,
    ) -> None:
        self.observe = observe
        self.act = act
        self.decide_client = decide_client or get_reflex_decide_client()
        self.text_generator = text_generator
        self.sandbox = sandbox
        self.max_age_ms = max_age_ms
        # Safety/approval stays outside the decision model.
        self.permission_gate = permission_gate

    async def _observe(self) -> ActionFrame:
        result = self.observe()
        if hasattr(result, "__await__"):
            return await result  # type: ignore[misc]
        return result  # type: ignore[return-value]

    async def _act(self, operation: Operation, node: ActionNode, payload: dict[str, Any]) -> dict[str, Any]:
        result = self.act(operation, node, payload)
        if hasattr(result, "__await__"):
            return await result  # type: ignore[misc]
        return result  # type: ignore[return-value]

    async def run(self, goal: str, *, max_steps: int | None = None) -> ReflexLoopResult:
        started = time.perf_counter()
        limit = max_steps if max_steps is not None else self.sandbox.max_steps
        outcome = ReflexLoopResult(success=False)
        goal_text = (goal or "").strip()
        if not goal_text:
            outcome.reason = "goal is required"
            outcome.wall_time_ms = (time.perf_counter() - started) * 1000.0
            return outcome

        for step_idx in range(limit):
            frame = await self._observe()
            outcome.protocol_calls += 1  # observe is a protocol/native call
            outcome.final_frame = frame

            decide_result = self.decide_client.decide(
                {
                    "goal": goal_text,
                    "frame": frame.compact_state(),
                    "frame_id": frame.frame_id,
                },
                build_op_target_questions(frame, goal_text),
                BROWSER_OP_TARGET_CLASS,
                deadline_ms=100,
                privacy="local_only",
            )
            # Reflex decide is not a generative LLM call; only TYPE_TEXT counts as model_calls.
            decision = parse_reflex_decision(decide_result)
            if decision is None:
                outcome.reason = decide_result.error or "Reflex Lane refused or returned unparseable decision"
                outcome.steps.append(
                    LoopStepRecord(
                        step=step_idx,
                        frame_id=frame.frame_id,
                        decision=decide_result.as_dict(),
                        success=False,
                        reason=outcome.reason,
                    )
                )
                break

            outcome.decisions.append(decision.as_dict())
            gate = gate_decision_payload(decision, posture=self.sandbox)
            if not gate.ok:
                outcome.reason = f"sandbox refused decision: {gate.reason}"
                outcome.blocked = True
                outcome.steps.append(
                    LoopStepRecord(
                        step=step_idx,
                        frame_id=frame.frame_id,
                        decision=decision.as_dict(),
                        success=False,
                        reason=outcome.reason,
                    )
                )
                break

            if self.permission_gate is not None:
                denied = self.permission_gate(decision, frame)
                if denied:
                    outcome.reason = f"permission denied: {denied}"
                    outcome.blocked = True
                    outcome.steps.append(
                        LoopStepRecord(
                            step=step_idx,
                            frame_id=frame.frame_id,
                            decision=decision.as_dict(),
                            success=False,
                            reason=outcome.reason,
                        )
                    )
                    break

            if decision.operation == Operation.BLOCK or decision.blocked:
                outcome.blocked = True
                outcome.reason = decision.reason or "Reflex Lane blocked"
                outcome.steps.append(
                    LoopStepRecord(
                        step=step_idx,
                        frame_id=frame.frame_id,
                        decision=decision.as_dict(),
                        success=False,
                        reason=outcome.reason,
                    )
                )
                break

            if decision.operation == Operation.DONE or decision.done:
                outcome.done = True
                outcome.success = True
                outcome.reason = decision.reason or "done"
                outcome.steps.append(
                    LoopStepRecord(
                        step=step_idx,
                        frame_id=frame.frame_id,
                        decision=decision.as_dict(),
                        success=True,
                        reason=outcome.reason,
                    )
                )
                break

            fresh = check_frame_freshness(frame, expected_frame_id=frame.frame_id, max_age_ms=self.max_age_ms)
            if not fresh.ok:
                outcome.recovery_count += 1
                outcome.steps.append(
                    LoopStepRecord(
                        step=step_idx,
                        frame_id=frame.frame_id,
                        decision=decision.as_dict(),
                        success=False,
                        reason=fresh.reason,
                        recovery=True,
                    )
                )
                continue

            node, resolve_reason = resolve_target(frame, decision.target_id)
            if node is None:
                outcome.reason = f"reject before execute: {resolve_reason}"
                outcome.steps.append(
                    LoopStepRecord(
                        step=step_idx,
                        frame_id=frame.frame_id,
                        decision=decision.as_dict(),
                        success=False,
                        reason=outcome.reason,
                    )
                )
                break

            if not node.supports(decision.operation):
                outcome.reason = (
                    f"operation {decision.operation.value} not supported by target {node.target_id} "
                    f"(role={node.role})"
                )
                outcome.steps.append(
                    LoopStepRecord(
                        step=step_idx,
                        frame_id=frame.frame_id,
                        decision=decision.as_dict(),
                        success=False,
                        reason=outcome.reason,
                    )
                )
                break

            # Re-observe and confirm target fingerprint before mutate.
            pre_frame = await self._observe()
            outcome.protocol_calls += 1
            fresh2 = check_frame_freshness(
                pre_frame,
                expected_app_or_page_id=frame.app_or_page_id,
                max_age_ms=self.max_age_ms,
            )
            if not fresh2.ok:
                outcome.recovery_count += 1
                outcome.steps.append(
                    LoopStepRecord(
                        step=step_idx,
                        frame_id=pre_frame.frame_id,
                        decision=decision.as_dict(),
                        success=False,
                        reason=fresh2.reason,
                        recovery=True,
                    )
                )
                continue

            pre_node = pre_frame.node_by_id(decision.target_id or "")
            if pre_node is None:
                # Try fingerprint match if ids renumbered.
                for candidate in pre_frame.nodes:
                    if candidate.fingerprint == node.fingerprint:
                        pre_node = candidate
                        break
            drift = target_changed(node, pre_node)
            if drift:
                outcome.reason = f"reject changed target: {drift}"
                outcome.recovery_count += 1
                outcome.steps.append(
                    LoopStepRecord(
                        step=step_idx,
                        frame_id=pre_frame.frame_id,
                        decision=decision.as_dict(),
                        success=False,
                        reason=outcome.reason,
                        recovery=True,
                    )
                )
                continue
            assert pre_node is not None

            act_payload: dict[str, Any] = {"goal": goal_text, "frame_id": pre_frame.frame_id}
            step_model_calls = 0
            typed_text: str | None = None

            if decision.operation == Operation.TYPE_TEXT:
                validation = await generate_bounded_text(
                    goal_text,
                    field_name=pre_node.name,
                    hint=decision.text_hint,
                    generator=self.text_generator,
                    max_chars=self.sandbox.max_typed_chars,
                )
                step_model_calls = 1 if self.text_generator is not None else 0
                outcome.model_calls += step_model_calls
                if not validation.ok:
                    outcome.reason = f"TYPE_TEXT validation failed: {validation.reason}"
                    outcome.steps.append(
                        LoopStepRecord(
                            step=step_idx,
                            frame_id=pre_frame.frame_id,
                            decision=decision.as_dict(),
                            success=False,
                            reason=outcome.reason,
                            model_calls=step_model_calls,
                        )
                    )
                    break
                typed_text = validation.text
                act_payload["text"] = typed_text

            try:
                act_result = await self._act(decision.operation, pre_node, act_payload)
            except Exception as exc:
                outcome.reason = f"act failed: {exc}"
                outcome.steps.append(
                    LoopStepRecord(
                        step=step_idx,
                        frame_id=pre_frame.frame_id,
                        decision=decision.as_dict(),
                        success=False,
                        reason=outcome.reason,
                        model_calls=step_model_calls,
                    )
                )
                break

            outcome.protocol_calls += int(act_result.get("protocol_calls") or 1)

            if decision.operation in MUTATING_OPERATIONS:
                post_frame = await self._observe()
                outcome.protocol_calls += 1
                outcome.final_frame = post_frame
                post = verify_postcondition(
                    decision.operation,
                    prior_node=pre_node,
                    post_frame=post_frame,
                    target_id=pre_node.target_id,
                    typed_text=typed_text,
                )
                if not post.ok:
                    outcome.recovery_count += 1
                    outcome.steps.append(
                        LoopStepRecord(
                            step=step_idx,
                            frame_id=post_frame.frame_id,
                            decision=decision.as_dict(),
                            success=False,
                            reason=f"postcondition failed: {post.reason}",
                            protocol_calls=int(act_result.get("protocol_calls") or 1),
                            model_calls=step_model_calls,
                            recovery=True,
                        )
                    )
                    # Recovery: continue loop with fresh observation rather than fake success.
                    continue
                outcome.steps.append(
                    LoopStepRecord(
                        step=step_idx,
                        frame_id=post_frame.frame_id,
                        decision=decision.as_dict(),
                        success=True,
                        reason=post.reason,
                        protocol_calls=int(act_result.get("protocol_calls") or 1),
                        model_calls=step_model_calls,
                    )
                )
            else:
                outcome.steps.append(
                    LoopStepRecord(
                        step=step_idx,
                        frame_id=pre_frame.frame_id,
                        decision=decision.as_dict(),
                        success=True,
                        reason="non-mutating ok",
                        protocol_calls=int(act_result.get("protocol_calls") or 1),
                        model_calls=step_model_calls,
                    )
                )
        else:
            outcome.reason = f"max_steps={limit} exhausted without DONE"

        outcome.wall_time_ms = (time.perf_counter() - started) * 1000.0
        return outcome


def frame_from_surface(
    surface: SurfaceKind,
    nodes: list[Any],
    *,
    identity: str = "",
    title: str = "",
) -> ActionFrame:
    if surface == SurfaceKind.BROWSER:
        return build_browser_action_frame(nodes if isinstance(nodes, list) else [], url=identity, title=title)
    return build_desktop_action_frame(nodes, app_id=identity, window_title=title)
