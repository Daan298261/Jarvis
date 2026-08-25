"""Software-development worker router.

Jarvis stays the supervisor. Paid Cursor/ACP workers are catalogued but not
invoked until they report a live connection. Historical verified success can
override a static complexity score so cheap local work stays local.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import asdict, dataclass, field
from typing import Any

from sqlalchemy import select

from ..db.models import CodingWorkerOutcome
from ..db.session import SessionLocal
from .planning import classify_task


@dataclass
class WorkerDescriptor:
    id: str
    name: str
    tier: int
    cost_class: str
    available: bool
    status: str
    detail: str
    input_usd_per_mtok: float = 0.0
    output_usd_per_mtok: float = 0.0


@dataclass
class WorkerResult:
    success: bool
    worker_id: str
    files_changed: list[str] = field(default_factory=list)
    commands_executed: list[str] = field(default_factory=list)
    tests_run: list[str] = field(default_factory=list)
    reported_result: str = ""
    errors: list[str] = field(default_factory=list)
    session_id: str = ""
    model: str = ""
    estimated_cost_usd: float = 0.0
    usage: dict[str, Any] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class EscalationContext:
    goal: str
    acceptance_criteria: list[str]
    task_class: str
    relevant_files: list[str]
    current_diff: str
    failing_tests: str
    important_logs: str
    attempted_strategies: list[str]
    reason: str

    def as_prompt_block(self) -> str:
        criteria = "\n".join(f"- {c}" for c in self.acceptance_criteria) or "- (none captured)"
        files = "\n".join(f"- {p}" for p in self.relevant_files[:20]) or "- (none)"
        attempts = "\n".join(f"- {s}" for s in self.attempted_strategies) or "- (none)"
        return (
            "Escalation package (compact — do not dump the full trajectory):\n"
            f"Goal: {self.goal}\n"
            f"Task class: {self.task_class}\n"
            f"Reason: {self.reason}\n"
            f"Acceptance criteria:\n{criteria}\n"
            f"Relevant files:\n{files}\n"
            f"Current diff:\n{(self.current_diff or '(none)')[:4000]}\n"
            f"Failing tests:\n{(self.failing_tests or '(none)')[:2000]}\n"
            f"Important logs:\n{(self.important_logs or '(none)')[:2000]}\n"
            f"Attempted strategies:\n{attempts}\n"
        )


class SoftwareDevelopmentWorker(ABC):
    descriptor: WorkerDescriptor

    @abstractmethod
    async def verify_connection(self) -> bool:
        raise NotImplementedError

    @abstractmethod
    async def start_task(self, prompt: str, context: dict[str, Any] | None = None) -> WorkerResult:
        raise NotImplementedError

    async def continue_task(self, session_id: str, prompt: str) -> WorkerResult:
        return WorkerResult(False, self.descriptor.id, errors=["continue_task is not available"])

    async def inspect_task(self, session_id: str) -> WorkerResult:
        return WorkerResult(False, self.descriptor.id, errors=["inspect_task is not available"])

    async def cancel_task(self, session_id: str) -> WorkerResult:
        return WorkerResult(True, self.descriptor.id, reported_result="cancelled locally")

    async def send_feedback(self, session_id: str, feedback: str) -> WorkerResult:
        return WorkerResult(False, self.descriptor.id, errors=["send_feedback is not available"])

    async def get_changes(self, session_id: str) -> WorkerResult:
        return WorkerResult(True, self.descriptor.id, files_changed=[])

    async def get_status(self, session_id: str) -> WorkerResult:
        return WorkerResult(self.descriptor.available, self.descriptor.id, reported_result=self.descriptor.status)

    async def get_cost_usage(self, session_id: str) -> dict[str, Any]:
        return {"estimated_cost_usd": 0.0, "worker": self.descriptor.id}

    async def get_model(self) -> str:
        return self.descriptor.id

    async def set_model(self, model: str) -> None:
        return None


class DeterministicToolsWorker(SoftwareDevelopmentWorker):
    descriptor = WorkerDescriptor(
        id="deterministic_tools",
        name="Deterministic tools",
        tier=0,
        cost_class="free",
        available=True,
        status="ready",
        detail="JSON edits, formatters, renames, known builds/tests, and learned skills. No coding model.",
    )

    async def verify_connection(self) -> bool:
        return True

    async def start_task(self, prompt: str, context: dict[str, Any] | None = None) -> WorkerResult:
        return WorkerResult(
            True,
            self.descriptor.id,
            reported_result="Use native filesystem/terminal/python/git tools. Do not call a paid coding worker.",
            model="none",
        )


class LocalJarvisCodingWorker(SoftwareDevelopmentWorker):
    descriptor = WorkerDescriptor(
        id="local_jarvis",
        name="Local Jarvis coding worker",
        tier=1,
        cost_class="free",
        available=True,
        status="ready",
        detail="Primary local model (9B when migrated, otherwise the loaded profile). Incremental AI cost is zero.",
    )

    async def verify_connection(self) -> bool:
        return True

    async def start_task(self, prompt: str, context: dict[str, Any] | None = None) -> WorkerResult:
        return WorkerResult(
            True,
            self.descriptor.id,
            reported_result=(
                "Execute with Jarvis native tools. Independently verify. "
                "Escalate only after two materially different local failures."
            ),
            model="local-primary",
        )


class _UnconnectedPaidWorker(SoftwareDevelopmentWorker):
    async def verify_connection(self) -> bool:
        return False

    async def start_task(self, prompt: str, context: dict[str, Any] | None = None) -> WorkerResult:
        return WorkerResult(
            False,
            self.descriptor.id,
            errors=[
                f"{self.descriptor.name} is catalogued but not connected. "
                "Jarvis will stay on the local coding worker until credentials/ACP are wired."
            ],
            model=self.descriptor.id,
        )


class ComposerWorker(_UnconnectedPaidWorker):
    descriptor = WorkerDescriptor(
        id="composer",
        name="Cursor Composer 2.5 Standard",
        tier=2,
        cost_class="paid-default",
        available=False,
        status="not_connected",
        detail="Default paid coding worker. Do not use Fast pricing for unattended development.",
        input_usd_per_mtok=0.50,
        output_usd_per_mtok=2.50,
    )


class CheapAlternativeWorker(_UnconnectedPaidWorker):
    descriptor = WorkerDescriptor(
        id="cheap_alternative",
        name="Optional low-cost third-party coder",
        tier=2,
        cost_class="paid-optional",
        available=False,
        status="not_connected",
        detail="Configurable catalog slot for Luna/Flash-class models when they are cheaper for the same success.",
    )


class GrokWorker(_UnconnectedPaidWorker):
    descriptor = WorkerDescriptor(
        id="grok",
        name="Cursor Grok 4.6 Standard",
        tier=3,
        cost_class="paid-hard",
        available=False,
        status="not_connected",
        detail="Difficult architecture, long-horizon, or Composer failures. Not the default.",
        input_usd_per_mtok=2.00,
        output_usd_per_mtok=6.00,
    )


class FrontierWorker(_UnconnectedPaidWorker):
    descriptor = WorkerDescriptor(
        id="frontier",
        name="Frontier specialist",
        tier=4,
        cost_class="paid-exception",
        available=False,
        status="not_connected",
        detail="Most expensive coding/reasoning model. Only after lower tiers fail or the user asks for maximum quality.",
    )


class CursorACPWorker(_UnconnectedPaidWorker):
    descriptor = WorkerDescriptor(
        id="cursor_acp",
        name="Cursor ACP worker",
        tier=2,
        cost_class="paid-default",
        available=False,
        status="not_wired",
        detail="Transport for Composer/Grok. Not wired; Jarvis must not depend on Cursor-specific logic elsewhere.",
    )


WORKERS: dict[str, SoftwareDevelopmentWorker] = {
    worker.descriptor.id: worker
    for worker in (
        DeterministicToolsWorker(),
        LocalJarvisCodingWorker(),
        ComposerWorker(),
        CheapAlternativeWorker(),
        GrokWorker(),
        FrontierWorker(),
        CursorACPWorker(),
    )
}

TIER_ORDER = ("deterministic_tools", "local_jarvis", "composer", "grok", "frontier")

_SOFTWARE_HINTS = (
    "code",
    "python",
    "refactor",
    "pytest",
    "compile",
    "repository",
    "source",
    "bug",
    "fix this",
    "implement",
    "function",
    "typescript",
    "frontend",
    "backend",
)


def is_software_task(prompt: str, task_class: str | None = None) -> bool:
    cls = (task_class or classify_task(prompt) or "").lower()
    if cls == "software engineering":
        return True
    text = (prompt or "").lower()
    return any(hint in text for hint in _SOFTWARE_HINTS)


def score_complexity(prompt: str, *, files_hint: int = 0, previous_failures: int = 0) -> int:
    text = (prompt or "").lower()
    score = 28
    if any(token in text for token in ("rename", "typo", "comment", "readme", "docs", "documentation")):
        score -= 12
    if any(token in text for token in ("bump version", "format", "prettier", "ruff", "run tests", "regenerate")):
        score -= 18
    if any(token in text for token in ("json", "config", "yaml")) and "architect" not in text:
        score -= 8
    if files_hint >= 8 or "multi-file" in text or "multiple files" in text:
        score += 18
    elif files_hint >= 3:
        score += 10
    if any(token in text for token in ("schema", "database", "migration", "sql")):
        score += 14
    if any(token in text for token in ("security", "auth", "crypto", "permission")):
        score += 14
    architecture_hits = sum(
        1 for token in ("architect", "subsystem", "concurrency", "distributed", "scheduler") if token in text
    )
    if architecture_hits:
        score += 18 + min(16, architecture_hits * 8)
    if any(token in text for token in ("ambiguous", "investigate", "unknown", "subtle")):
        score += 10
    if previous_failures:
        score += min(24, previous_failures * 12)
    return max(0, min(100, score))


def _static_worker_id(score: int) -> str:
    if score <= 20:
        return "deterministic_tools"
    if score <= 40:
        return "local_jarvis"
    if score <= 70:
        return "composer"
    if score <= 90:
        return "grok"
    return "frontier"


async def historical_local_override(task_class: str) -> dict[str, Any] | None:
    if not task_class:
        return None
    async with SessionLocal() as session:
        rows = (
            await session.execute(
                select(CodingWorkerOutcome)
                .where(CodingWorkerOutcome.task_class == task_class)
                .where(CodingWorkerOutcome.worker_id == "local_jarvis")
                .order_by(CodingWorkerOutcome.created_at.desc())
                .limit(12)
            )
        ).scalars().all()
    if len(rows) < 3:
        return None
    verified = sum(1 for row in rows if row.outcome == "verified_success")
    rate = verified / len(rows)
    if rate >= 0.8:
        return {"samples": len(rows), "success_rate": round(rate, 4), "override": True}
    return {"samples": len(rows), "success_rate": round(rate, 4), "override": False}


def fallback_available(worker_id: str) -> str:
    """Paid workers are not connected here; keep execution on an available worker."""
    worker = WORKERS.get(worker_id)
    if worker and worker.descriptor.available:
        return worker_id
    if worker_id in {"composer", "cheap_alternative", "cursor_acp"}:
        return "local_jarvis"
    if worker_id in {"grok", "frontier"}:
        return "local_jarvis"
    return "local_jarvis"


async def route_coding_task(
    prompt: str,
    *,
    task_class: str | None = None,
    files_hint: int = 0,
    previous_failures: int = 0,
) -> dict[str, Any]:
    cls = task_class or classify_task(prompt)
    score = score_complexity(prompt, files_hint=files_hint, previous_failures=previous_failures)
    static_id = _static_worker_id(score)
    history = await historical_local_override(cls)
    selected_id = static_id
    override_reason = ""
    if history and history.get("override") and score < 85:
        selected_id = "local_jarvis"
        override_reason = (
            f"Local worker verified {history['success_rate']*100:.0f}% of {history['samples']} "
            "similar tasks; keep work local."
        )
    execute_id = fallback_available(selected_id)
    paid_blocked = selected_id != execute_id
    selected = WORKERS[selected_id].descriptor
    execute = WORKERS[execute_id].descriptor
    next_id = escalate_worker(execute_id)
    return {
        "software_task": True,
        "task_class": cls,
        "complexity": score,
        "static_worker": selected_id,
        "selected_worker": selected_id,
        "execute_worker": execute_id,
        "paid_worker_blocked": paid_blocked,
        "historical": history,
        "override_reason": override_reason,
        "selected": asdict(selected),
        "execute": asdict(execute),
        "escalation_worker": next_id,
        "max_local_attempts": 2,
        "reason": override_reason
        or (
            f"Complexity {score} maps to {selected.name}. "
            + (
                f"{selected.name} is not connected, so Jarvis executes as {execute.name}."
                if paid_blocked
                else "Execute on that worker and independently verify."
            )
        ),
    }


def escalate_worker(current_id: str) -> str | None:
    if current_id not in TIER_ORDER:
        current_id = "local_jarvis"
    index = TIER_ORDER.index(current_id)
    if index + 1 >= len(TIER_ORDER):
        return None
    return TIER_ORDER[index + 1]


def compact_escalation(
    *,
    goal: str,
    acceptance_criteria: list[str],
    task_class: str,
    reason: str,
    relevant_files: list[str] | None = None,
    current_diff: str = "",
    failing_tests: str = "",
    important_logs: str = "",
    attempted_strategies: list[str] | None = None,
) -> EscalationContext:
    return EscalationContext(
        goal=goal,
        acceptance_criteria=list(acceptance_criteria or []),
        task_class=task_class,
        relevant_files=list(relevant_files or []),
        current_diff=current_diff,
        failing_tests=failing_tests,
        important_logs=important_logs,
        attempted_strategies=list(attempted_strategies or []),
        reason=reason,
    )


def format_routing_block(decision: dict[str, Any]) -> str:
    execute = decision.get("execute") or {}
    selected = decision.get("selected") or {}
    lines = [
        "Software-development routing:",
        f"- complexity: {decision.get('complexity')}",
        f"- preferred worker: {selected.get('name')} ({selected.get('id')}, tier {selected.get('tier')})",
        f"- execute now: {execute.get('name')} ({execute.get('id')})",
        f"- reason: {decision.get('reason')}",
        f"- escalate after {decision.get('max_local_attempts', 2)} different local failures to: {decision.get('escalation_worker')}",
        "- A worker claiming success is never completion. Jarvis must independently test and inspect.",
        "- Do not pay for a coding worker when deterministic tools or the local worker can finish it.",
    ]
    if decision.get("paid_worker_blocked"):
        lines.append("- Paid Composer/Grok/ACP are not connected in this runtime; do not pretend they ran.")
    return "\n".join(lines)


def list_workers() -> list[dict[str, Any]]:
    return [asdict(worker.descriptor) for worker in WORKERS.values()]


async def record_coding_outcome(
    *,
    task_id: str,
    task_class: str,
    worker_id: str,
    complexity: int,
    outcome: str,
    verification: str = "",
    estimated_cost_usd: float = 0.0,
    duration_seconds: float = 0.0,
) -> None:
    async with SessionLocal() as session:
        session.add(
            CodingWorkerOutcome(
                task_id=task_id,
                task_class=task_class or "",
                worker_id=worker_id,
                complexity=int(complexity or 0),
                outcome=outcome,
                verification=verification or "",
                estimated_cost_usd=float(estimated_cost_usd or 0),
                duration_seconds=float(duration_seconds or 0),
            )
        )
        await session.commit()


async def worker_stats() -> list[dict[str, Any]]:
    async with SessionLocal() as session:
        rows = (await session.execute(select(CodingWorkerOutcome))).scalars().all()
    by_worker: dict[str, dict[str, Any]] = {}
    for row in rows:
        bucket = by_worker.setdefault(
            row.worker_id,
            {"worker_id": row.worker_id, "tasks": 0, "verified": 0, "failed": 0, "cost_usd": 0.0},
        )
        bucket["tasks"] += 1
        if row.outcome == "verified_success":
            bucket["verified"] += 1
        elif row.outcome in {"failed", "escalated"}:
            bucket["failed"] += 1
        bucket["cost_usd"] += float(row.estimated_cost_usd or 0)
    out = []
    for bucket in by_worker.values():
        tasks = bucket["tasks"] or 1
        verified = bucket["verified"]
        cost = bucket["cost_usd"]
        out.append(
            {
                **bucket,
                "success_rate": round(verified / tasks, 4),
                "cost_per_verified_task": round(cost / verified, 4) if verified else None,
            }
        )
    return out
