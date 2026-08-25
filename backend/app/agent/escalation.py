from __future__ import annotations

import json
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select

from ..db.models import EscalationPackage, Task, ToolCallRecord
from ..db.session import SessionLocal
from .planning import WorkingState
from .recovery import classify_failure

MAX_PACKAGE_CHARS = 8000
MAX_LOG_SNIPPET = 900
PATH_KEYS = ("path", "destination", "working_directory", "file", "cwd")


@dataclass
class EscalationContext:
    """Compact package passed to the next coding worker. Never a raw transcript dump."""

    id: str
    task_id: str
    goal: str
    acceptance_criteria: list[str] = field(default_factory=list)
    task_class: str = ""
    relevant_files: list[str] = field(default_factory=list)
    current_diff: str = ""
    failing_tests: str = ""
    important_logs: str = ""
    attempted_strategies: list[str] = field(default_factory=list)
    reason: str = ""
    created_at: str = ""

    def as_prompt(self) -> str:
        criteria = "\n".join(f"- {item}" for item in self.acceptance_criteria) or "- (same as the request)"
        files = "\n".join(f"- {path}" for path in self.relevant_files[:12]) or "- (none captured)"
        strategies = "\n".join(f"- {item}" for item in self.attempted_strategies[:12]) or "- (none)"
        body = (
            "EscalationContext — compact state for the next coding worker. "
            "Do not assume the previous worker succeeded.\n\n"
            f"Goal: {self.goal}\n"
            f"Task class: {self.task_class or 'mixed'}\n"
            f"Reason for escalation: {self.reason or 'repeated failure'}\n"
            f"Acceptance criteria:\n{criteria}\n"
            f"Relevant files:\n{files}\n"
            f"Attempted strategies:\n{strategies}\n"
            f"Current diff:\n{self.current_diff or '(not captured)'}\n"
            f"Failing tests:\n{self.failing_tests or '(none captured)'}\n"
            f"Important logs:\n{self.important_logs or '(none)'}\n"
        )
        return body[:MAX_PACKAGE_CHARS]

    def as_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["prompt"] = self.as_prompt()
        return payload


def _extract_paths(arguments: dict[str, Any]) -> list[str]:
    paths: list[str] = []
    for key in PATH_KEYS:
        value = arguments.get(key)
        if isinstance(value, str) and value.strip():
            paths.append(value.strip())
    return paths


def _looks_like_test_failure(text: str) -> bool:
    lowered = (text or "").lower()
    markers = ("failed", "error:", "assertionerror", "traceback", "pytest", "failed to", "exit_code=")
    return any(marker in lowered for marker in markers) and any(
        token in lowered for token in ("test", "pytest", "assert", "failed", "error")
    )


def context_from_working(
    task_id: str,
    working: WorkingState,
    *,
    reason: str = "",
    relevant_files: list[str] | None = None,
    current_diff: str = "",
    failing_tests: str = "",
    important_logs: str = "",
    attempted_strategies: list[str] | None = None,
) -> EscalationContext:
    return EscalationContext(
        id=str(uuid.uuid4()),
        task_id=task_id,
        goal=working.goal or "",
        acceptance_criteria=list(working.acceptance_criteria),
        task_class=working.task_class or "",
        relevant_files=list(dict.fromkeys(relevant_files or [])),
        current_diff=(current_diff or "")[:2000],
        failing_tests=(failing_tests or "")[:2000],
        important_logs=(important_logs or "")[:2000],
        attempted_strategies=list(attempted_strategies or []),
        reason=reason or (working.known_failures[-1] if working.known_failures else "escalation requested"),
        created_at=datetime.now(timezone.utc).isoformat(),
    )


async def build_escalation_package(task_id: str, working: WorkingState, reason: str = "") -> EscalationContext | None:
    async with SessionLocal() as session:
        task = await session.get(Task, task_id)
        if not task:
            return None
        calls = (
            await session.execute(
                select(ToolCallRecord).where(ToolCallRecord.task_id == task_id).order_by(ToolCallRecord.id)
            )
        ).scalars().all()

    files: list[str] = []
    strategies: list[str] = []
    diffs: list[str] = []
    test_bits: list[str] = []
    logs: list[str] = []
    last_failure = reason
    for call in calls:
        if call.tool_name and call.tool_name not in strategies:
            strategies.append(call.tool_name)
        try:
            arguments = json.loads(call.arguments_json or "{}")
        except json.JSONDecodeError:
            arguments = {}
        if isinstance(arguments, dict):
            files.extend(_extract_paths(arguments))
        blob = (call.output or call.error or "")[:MAX_LOG_SNIPPET]
        if call.tool_name == "git" and "diff" in (arguments.get("action") or ""):
            diffs.append(blob)
        if not call.success:
            kind = classify_failure(call.error or call.output)
            last_failure = last_failure or f"{call.tool_name} failed ({kind})"
            logs.append(f"{call.tool_name}: {blob}")
            if _looks_like_test_failure(call.output or call.error or ""):
                test_bits.append(blob)
        elif call.tool_name in {"python", "terminal"} and _looks_like_test_failure(call.output or ""):
            test_bits.append(blob)

    if not last_failure and working.known_failures:
        last_failure = working.known_failures[-1]
    goal = working.goal or (task.prompt.strip().splitlines()[0][:240] if task.prompt else "")
    working.goal = working.goal or goal
    working.acceptance_criteria = working.acceptance_criteria or [
        line for line in (task.acceptance_criteria or "").splitlines() if line.strip()
    ]
    working.task_class = working.task_class or task.task_class
    return context_from_working(
        task_id,
        working,
        reason=last_failure or "repeated failure",
        relevant_files=files,
        current_diff="\n\n".join(diffs)[:2000],
        failing_tests="\n\n".join(test_bits)[:2000],
        important_logs="\n\n".join(logs[-4:])[:2000],
        attempted_strategies=strategies,
    )


async def persist_escalation_package(package: EscalationContext) -> EscalationContext:
    async with SessionLocal() as session:
        session.add(
            EscalationPackage(
                id=package.id,
                task_id=package.task_id,
                task_class=package.task_class,
                goal=package.goal[:400],
                reason=package.reason[:400],
                payload_json=json.dumps(asdict(package), ensure_ascii=False),
            )
        )
        await session.commit()
    return package


async def list_escalation_packages(limit: int = 20) -> list[dict[str, Any]]:
    async with SessionLocal() as session:
        rows = (
            await session.execute(
                select(EscalationPackage).order_by(EscalationPackage.created_at.desc()).limit(limit)
            )
        ).scalars().all()
    out: list[dict[str, Any]] = []
    for row in rows:
        try:
            payload = json.loads(row.payload_json or "{}")
        except json.JSONDecodeError:
            payload = {"id": row.id, "task_id": row.task_id, "goal": row.goal, "reason": row.reason}
        out.append(payload)
    return out


async def get_escalation_package(package_id: str) -> dict[str, Any] | None:
    async with SessionLocal() as session:
        row = await session.get(EscalationPackage, package_id)
        if not row:
            return None
        try:
            return json.loads(row.payload_json or "{}")
        except json.JSONDecodeError:
            return {"id": row.id, "task_id": row.task_id, "goal": row.goal, "reason": row.reason}
