"""Deterministic benchmark: Reflex loop vs current Anzu computer/browser loop."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any
import time

from .adapters import build_browser_action_frame, build_desktop_action_frame
from .executor import ReflexLoopExecutor, ReflexLoopResult
from .reflex_client import DecisionQuestion, DecisionResult, ReflexDecideClient
from .schema import ActionFrame, ActionNode, Operation, SurfaceKind


@dataclass
class LoopMetrics:
    label: str
    model_calls: int = 0
    protocol_calls: int = 0
    wall_time_ms: float = 0.0
    success: bool = False
    recovery_count: int = 0
    steps: int = 0
    reason: str = ""

    def as_dict(self) -> dict[str, Any]:
        return {
            "label": self.label,
            "model_calls": self.model_calls,
            "protocol_calls": self.protocol_calls,
            "wall_time_ms": self.wall_time_ms,
            "success": self.success,
            "recovery_count": self.recovery_count,
            "steps": self.steps,
            "reason": self.reason,
        }


@dataclass
class BenchmarkTask:
    """Identical task fixture for both loops."""

    task_id: str
    goal: str
    surface: SurfaceKind
    # Ordered list of frames the environment will present (observe sequence).
    frames: list[list[dict[str, Any]]]
    # Scripted correct decisions for the reflex lane (one per step until DONE).
    scripted_decisions: list[dict[str, Any]]
    identity: str = "fixture"
    title: str = "Fixture"


@dataclass
class BenchmarkComparison:
    task_id: str
    reflex: LoopMetrics
    anzu: LoopMetrics

    def as_dict(self) -> dict[str, Any]:
        return {
            "task_id": self.task_id,
            "reflex": self.reflex.as_dict(),
            "anzu": self.anzu.as_dict(),
            "reflex_fewer_model_calls": self.reflex.model_calls <= self.anzu.model_calls,
            "reflex_fewer_protocol_calls": self.reflex.protocol_calls <= self.anzu.protocol_calls,
        }


class ScriptedDecideClient:
    """Deterministic Reflex Lane stand-in for benchmarks/tests (not Jev/Laya)."""

    def __init__(self, decisions: list[dict[str, Any]]) -> None:
        self._decisions = list(decisions)
        self._index = 0

    def decide(
        self,
        state: dict[str, Any],
        questions: list[DecisionQuestion],
        decision_class: str,
        *,
        deadline_ms: int = 100,
        privacy: str = "local_only",
    ) -> DecisionResult:
        del state, questions, decision_class, deadline_ms, privacy
        if self._index >= len(self._decisions):
            return DecisionResult(
                ok=True,
                answers={"operation": Operation.DONE.value, "done": True},
                provider="scripted",
                source="benchmark",
                confidence=1.0,
            )
        answers = dict(self._decisions[self._index])
        self._index += 1
        return DecisionResult(
            ok=True,
            answers=answers,
            provider="scripted",
            source="benchmark",
            confidence=float(answers.get("confidence") or 1.0),
        )


class ScriptedWorld:
    """In-memory UI that advances as actions succeed — shared by both loops."""

    def __init__(self, task: BenchmarkTask) -> None:
        self.task = task
        self.frame_index = 0
        self.protocol_calls = 0
        self.model_calls = 0
        self.typed: dict[str, str] = {}
        self.clicked: list[str] = []

    def _raw_nodes(self) -> list[dict[str, Any]]:
        if not self.task.frames:
            return []
        idx = min(self.frame_index, len(self.task.frames) - 1)
        nodes = [dict(n) for n in self.task.frames[idx]]
        for node in nodes:
            tid_name = str(node.get("name") or "")
            if tid_name in self.typed:
                node["value"] = self.typed[tid_name]
        return nodes

    def observe_frame(self) -> ActionFrame:
        self.protocol_calls += 1
        nodes = self._raw_nodes()
        if self.task.surface == SurfaceKind.BROWSER:
            return build_browser_action_frame(
                nodes,
                url=self.task.identity,
                title=self.task.title,
                page_id=self.task.identity,
            )
        return build_desktop_action_frame(
            nodes,
            app_id=self.task.identity,
            window_title=self.task.title,
        )

    async def act(self, operation: Operation, node: ActionNode, payload: dict[str, Any]) -> dict[str, Any]:
        self.protocol_calls += 1
        if operation == Operation.CLICK:
            self.clicked.append(node.name)
            # Advance world to next frame when possible.
            if self.frame_index < len(self.task.frames) - 1:
                self.frame_index += 1
        elif operation == Operation.TYPE_TEXT:
            text = str(payload.get("text") or "")
            self.typed[node.name] = text
        elif operation == Operation.CLEAR:
            self.typed[node.name] = ""
        elif operation == Operation.TOGGLE:
            # Flip checked in current frame copy via typed overlay marker.
            pass
        return {"protocol_calls": 1, "ok": True}


async def run_reflex_on_task(task: BenchmarkTask) -> tuple[LoopMetrics, ReflexLoopResult]:
    world = ScriptedWorld(task)
    client = ScriptedDecideClient(task.scripted_decisions)

    async def observe() -> ActionFrame:
        return world.observe_frame()

    executor = ReflexLoopExecutor(
        observe=observe,
        act=world.act,
        decide_client=client,
        text_generator=None,  # use goal/hint extraction — counts as 0 model calls
        max_age_ms=60_000.0,  # fixtures are synthetic; age not under test here
    )
    result = await executor.run(task.goal)
    metrics = LoopMetrics(
        label="reflex",
        model_calls=result.model_calls,
        protocol_calls=result.protocol_calls,
        wall_time_ms=result.wall_time_ms,
        success=result.success,
        recovery_count=result.recovery_count,
        steps=len(result.steps),
        reason=result.reason,
    )
    return metrics, result


async def run_anzu_baseline_on_task(task: BenchmarkTask) -> LoopMetrics:
    """Simulate the current Anzu computer/browser loop cost model.

    Current path: each step tends to call a generative model (plan/selector) plus
    multiple protocol calls (screenshot/snapshot + act + verify scrape). This is
    a deterministic cost model over the same task fixtures — not a live LLM.
    """
    started = time.perf_counter()
    world = ScriptedWorld(task)
    model_calls = 0
    success = False
    reason = ""
    steps = 0
    recovery = 0

    for decision in task.scripted_decisions:
        steps += 1
        # Baseline: one generative model call per step to invent action/selector.
        model_calls += 1
        world.model_calls += 1
        # Baseline protocol: screenshot/snapshot + resolve + act (+ often re-snapshot).
        world.observe_frame()
        world.observe_frame()
        frame = world.observe_frame()
        op_raw = str(decision.get("operation") or "").upper()
        try:
            operation = Operation(op_raw)
        except ValueError:
            recovery += 1
            reason = f"baseline could not parse operation {op_raw}"
            continue
        if operation in {Operation.DONE, Operation.BLOCK}:
            success = operation == Operation.DONE
            reason = "done" if success else "blocked"
            break
        target_id = decision.get("target_id")
        node = frame.node_by_id(str(target_id)) if target_id else None
        if node is None:
            recovery += 1
            reason = "baseline target miss"
            continue
        payload: dict[str, Any] = {}
        if operation == Operation.TYPE_TEXT:
            # Baseline also burns a model call to generate text.
            model_calls += 1
            payload["text"] = str(decision.get("text_hint") or "baseline-text")
        await world.act(operation, node, payload)
        world.observe_frame()  # postcondition scrape
    else:
        reason = "baseline exhausted scripted decisions without DONE"
        # If last decision was implicit success via completing actions, check clicked/typed.
        if world.clicked or world.typed:
            success = True
            reason = "baseline completed scripted actions"

    return LoopMetrics(
        label="anzu_baseline",
        model_calls=model_calls,
        protocol_calls=world.protocol_calls,
        wall_time_ms=(time.perf_counter() - started) * 1000.0,
        success=success,
        recovery_count=recovery,
        steps=steps,
        reason=reason,
    )


async def compare_loops(task: BenchmarkTask) -> BenchmarkComparison:
    reflex_metrics, _ = await run_reflex_on_task(task)
    anzu_metrics = await run_anzu_baseline_on_task(task)
    return BenchmarkComparison(task_id=task.task_id, reflex=reflex_metrics, anzu=anzu_metrics)


def default_benchmark_tasks() -> list[BenchmarkTask]:
    """Byte-stable fixtures for CI — browser form fill + desktop button click."""
    browser_nodes_start = [
        {"role": "textbox", "name": "Email", "value": "", "dom_id": "email"},
        {"role": "textbox", "name": "Password", "value": "", "dom_id": "password"},
        {"role": "button", "name": "Sign in", "dom_id": "submit"},
    ]
    browser_nodes_done = [
        {"role": "button", "name": "Sign out", "dom_id": "logout"},
    ]
    desktop_nodes = [
        {"name": "Save", "control_type": "Button", "automation_id": "saveBtn", "enabled": True},
        {"name": "Cancel", "control_type": "Button", "automation_id": "cancelBtn", "enabled": True},
    ]
    return [
        BenchmarkTask(
            task_id="browser_signin_type_and_click",
            goal='Type "user@example.com" into Email then click Sign in',
            surface=SurfaceKind.BROWSER,
            identity="https://example.test/login",
            title="Login",
            frames=[browser_nodes_start, browser_nodes_start, browser_nodes_done],
            scripted_decisions=[
                {"operation": "TYPE_TEXT", "target_id": "t0", "text_hint": "user@example.com"},
                {"operation": "CLICK", "target_id": "t2"},
                {"operation": "DONE", "done": True},
            ],
        ),
        BenchmarkTask(
            task_id="desktop_click_save",
            goal="Click the Save button",
            surface=SurfaceKind.DESKTOP,
            identity="Notepad",
            title="Untitled - Notepad",
            frames=[desktop_nodes, desktop_nodes],
            scripted_decisions=[
                {"operation": "CLICK", "target_id": "t0"},
                {"operation": "DONE", "done": True},
            ],
        ),
    ]


async def run_benchmark_suite(tasks: list[BenchmarkTask] | None = None) -> dict[str, Any]:
    suite = tasks if tasks is not None else default_benchmark_tasks()
    comparisons = [await compare_loops(task) for task in suite]
    return {
        "suite": "rfc0172_reflex_vs_anzu",
        "tasks": [c.as_dict() for c in comparisons],
        "summary": {
            "count": len(comparisons),
            "reflex_successes": sum(1 for c in comparisons if c.reflex.success),
            "anzu_successes": sum(1 for c in comparisons if c.anzu.success),
            "total_reflex_model_calls": sum(c.reflex.model_calls for c in comparisons),
            "total_anzu_model_calls": sum(c.anzu.model_calls for c in comparisons),
            "total_reflex_protocol_calls": sum(c.reflex.protocol_calls for c in comparisons),
            "total_anzu_protocol_calls": sum(c.anzu.protocol_calls for c in comparisons),
        },
    }
