"""Software-development worker router.

Selects the cheapest sufficiently capable coding worker, records the decision,
and never treats a worker-reported success as task completion. Paid Cursor /
frontier workers are catalogued but stay unconfigured until credentials exist.
"""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass, field
from typing import Any, Protocol

from sqlalchemy import select

from ..db.models import CodingRoute, utcnow
from ..db.session import SessionLocal

DETERMINISTIC_HINTS = (
    "rename file",
    "bump version",
    "format",
    "run tests",
    "run pytest",
    "run the test",
    "json value",
    "update json",
    "regenerate",
    "known skill",
)

LOCAL_HINTS = (
    "documentation",
    "readme",
    "docstring",
    "unit test",
    "add a test",
    "small",
    "typo",
    "config",
    "one file",
    "simple",
    "exception",
)

COMPOSER_HINTS = (
    "feature",
    "multi-file",
    "refactor",
    "frontend",
    "backend",
    "database",
    "endpoint",
    "implement",
    "migration",
)

GROK_HINTS = (
    "architecture",
    "multi-module",
    "concurrency",
    "distributed",
    "subtle",
    "long-horizon",
    "ambiguous",
    "cross-cutting",
)

FRONTIER_HINTS = (
    "maximum quality",
    "use grok",
    "use opus",
    "use gpt-5",
    "security-critical",
    "irreversible",
)

TIER_RANGES = (
    (0, 20, 0, "deterministic", "native-tools"),
    (21, 40, 1, "local", "local-jarvis-coding"),
    (41, 70, 2, "composer", "cursor-composer-2.5"),
    (71, 90, 3, "grok", "cursor-grok-4.6"),
    (91, 100, 4, "frontier", "frontier-specialist"),
)


class SoftwareDevelopmentWorker(Protocol):
    id: str
    name: str
    tier: int
    available: bool
    status: str

    def describe(self) -> dict[str, Any]:
        ...

    async def verify_connection(self) -> bool:
        ...


@dataclass
class LocalJarvisCodingWorker:
    id: str = "local-jarvis-coding"
    name: str = "Local Jarvis coding worker"
    tier: int = 1
    available: bool = True
    status: str = "ready"
    detail: str = "In-process Qwen/tool agent. Independent verification is still required."

    def describe(self) -> dict[str, Any]:
        return asdict(self)

    async def verify_connection(self) -> bool:
        return True

    async def start_task(self, prompt: str) -> dict[str, Any]:
        return {
            "accepted": True,
            "worker_reported_success": False,
            "independent_verification_required": True,
            "note": "Execute via the Jarvis supervisor loop; do not trust this worker's self-report.",
        }


@dataclass
class UnavailableCodingWorker:
    id: str
    name: str
    tier: int
    detail: str
    available: bool = False
    status: str = "not_configured"

    def describe(self) -> dict[str, Any]:
        return asdict(self)

    async def verify_connection(self) -> bool:
        return False


def coding_worker_catalog() -> list[dict[str, Any]]:
    workers: list[SoftwareDevelopmentWorker] = [
        LocalJarvisCodingWorker(),
        UnavailableCodingWorker(
            "native-tools",
            "Deterministic native tools",
            0,
            "Filesystem/terminal/python/git with no coding model. Used for Tier 0 work.",
        ),
        UnavailableCodingWorker(
            "cursor-composer-2.5",
            "Cursor Composer 2.5 Standard",
            2,
            "Default paid coding worker when configured. Not wired; stay on the local worker.",
        ),
        UnavailableCodingWorker(
            "cursor-grok-4.6",
            "Cursor Grok 4.6 Standard",
            3,
            "Difficult architecture/debug escalation. Not wired.",
        ),
        UnavailableCodingWorker(
            "frontier-specialist",
            "Frontier specialist",
            4,
            "Expensive exception path only. Not wired.",
        ),
    ]
    # native-tools is always available as a routing target even without a process.
    catalog = []
    for worker in workers:
        item = worker.describe()
        if item["id"] == "native-tools":
            item["available"] = True
            item["status"] = "ready"
        catalog.append(item)
    return catalog


def _count_hints(text: str, hints: tuple[str, ...]) -> int:
    return sum(1 for hint in hints if hint in text)


def score_complexity(
    prompt: str,
    *,
    task_class: str = "",
    files_hint: int = 0,
    has_tests: bool | None = None,
    previous_failures: int = 0,
    architecture_impact: bool = False,
    security_relevant: bool = False,
) -> int:
    text = (prompt or "").lower()
    score = 28
    if task_class in {"software engineering", "long-horizon autonomous"}:
        score += 8
    score += min(25, files_hint * 6)
    if has_tests is False:
        score += 8
    if has_tests is True:
        score -= 4
    score += min(20, previous_failures * 8)
    if architecture_impact:
        score += 18
    if security_relevant or "security" in text or "auth" in text or "permission" in text:
        score += 10
    score += _count_hints(text, COMPOSER_HINTS) * 6
    score += _count_hints(text, GROK_HINTS) * 10
    score += _count_hints(text, FRONTIER_HINTS) * 16
    if _count_hints(text, DETERMINISTIC_HINTS) and files_hint <= 1:
        score = min(score, 18)
    if _count_hints(text, LOCAL_HINTS) and files_hint <= 2 and not architecture_impact:
        score = min(score, 36)
    if re.search(r"\b(one file|single file|typo|rename)\b", text):
        score = min(score, 22)
    return max(0, min(100, score))


def tier_for_score(score: int) -> dict[str, Any]:
    value = max(0, min(100, int(score)))
    for low, high, tier, name, worker_id in TIER_RANGES:
        if low <= value <= high:
            return {
                "score": value,
                "tier": tier,
                "tier_name": name,
                "intended_worker": worker_id,
                "range": [low, high],
            }
    return {"score": value, "tier": 1, "tier_name": "local", "intended_worker": "local-jarvis-coding", "range": [21, 40]}


@dataclass
class CodingRouteDecision:
    score: int
    tier: int
    tier_name: str
    intended_worker: str
    selected_worker: str
    fallback_worker: str = "local-jarvis-coding"
    paid_worker_available: bool = False
    independent_verification_required: bool = True
    worker_success_is_insufficient: bool = True
    reason: str = ""
    catalog: list[dict[str, Any]] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        data = asdict(self)
        return data


def _available_ids(catalog: list[dict[str, Any]]) -> set[str]:
    return {item["id"] for item in catalog if item.get("available")}


def route_software_task(
    prompt: str,
    *,
    task_class: str = "",
    files_hint: int = 0,
    has_tests: bool | None = None,
    previous_failures: int = 0,
    architecture_impact: bool = False,
    security_relevant: bool = False,
) -> CodingRouteDecision:
    catalog = coding_worker_catalog()
    available = _available_ids(catalog)
    scored = tier_for_score(
        score_complexity(
            prompt,
            task_class=task_class,
            files_hint=files_hint,
            has_tests=has_tests,
            previous_failures=previous_failures,
            architecture_impact=architecture_impact,
            security_relevant=security_relevant,
        )
    )
    intended = scored["intended_worker"]
    selected = intended if intended in available else "local-jarvis-coding"
    if scored["tier"] == 0:
        selected = "native-tools"
    paid = intended not in {"native-tools", "local-jarvis-coding"}
    reason = (
        f"Complexity {scored['score']} maps to tier {scored['tier']} ({scored['tier_name']}) / {intended}."
    )
    if selected != intended:
        reason += f" {intended} is unavailable, so Jarvis stays on {selected}."
    reason += " A worker claiming success is never enough; Jarvis verifies independently."
    return CodingRouteDecision(
        score=scored["score"],
        tier=scored["tier"],
        tier_name=scored["tier_name"],
        intended_worker=intended,
        selected_worker=selected,
        fallback_worker="local-jarvis-coding",
        paid_worker_available=paid and intended in available,
        reason=reason,
        catalog=catalog,
    )


def format_route_prompt(decision: CodingRouteDecision) -> str:
    return (
        "Software-development routing:\n"
        f"- Complexity score: {decision.score}/100\n"
        f"- Intended tier: {decision.tier} {decision.tier_name} ({decision.intended_worker})\n"
        f"- Selected worker: {decision.selected_worker}\n"
        f"- Paid worker available: {decision.paid_worker_available}\n"
        "- Independent verification required: yes\n"
        "- Worker-reported success is not completion.\n"
        f"- {decision.reason}"
    )


def should_route(task_class: str, prompt: str) -> bool:
    if (task_class or "") in {"software engineering", "long-horizon autonomous"}:
        return True
    text = (prompt or "").lower()
    markers = ("pytest", "refactor", "source code", "repository", "pull request", "unit test", "implement")
    return any(marker in text for marker in markers)


async def record_coding_route(task_id: str, decision: CodingRouteDecision) -> CodingRoute:
    row = CodingRoute(
        task_id=task_id,
        complexity=decision.score,
        tier=decision.tier,
        tier_name=decision.tier_name,
        intended_worker=decision.intended_worker,
        selected_worker=decision.selected_worker,
        fallback_worker=decision.fallback_worker,
        paid_worker_available=decision.paid_worker_available,
        reason=decision.reason,
        independent_verification_required=True,
    )
    async with SessionLocal() as session:
        session.add(row)
        await session.commit()
        await session.refresh(row)
        return row


async def complete_coding_route(task_id: str, outcome: str, verification: str = "") -> None:
    async with SessionLocal() as session:
        row = (
            await session.execute(
                select(CodingRoute).where(CodingRoute.task_id == task_id).order_by(CodingRoute.id.desc())
            )
        ).scalars().first()
        if not row:
            return
        row.outcome = outcome
        row.verification = (verification or "")[:4000]
        row.updated_at = utcnow()
        await session.commit()


async def route_coding_task(prompt: str, *, task_class: str = "") -> dict[str, Any]:
    decision = route_software_task(prompt, task_class=task_class)
    return {
        "complexity": decision.score,
        "execute_worker": decision.selected_worker,
        "intended_worker": decision.intended_worker,
        "tier": decision.tier,
        "tier_name": decision.tier_name,
        "reason": decision.reason,
    }


def format_routing_block(routing: dict[str, Any]) -> str:
    return (
        "Software-development routing:\n"
        f"- Complexity score: {routing.get('complexity', 0)}/100\n"
        f"- Intended tier: {routing.get('tier')} {routing.get('tier_name')} ({routing.get('intended_worker')})\n"
        f"- Selected worker: {routing.get('execute_worker')}\n"
        "- Independent verification required: yes\n"
        "- Worker-reported success is not completion.\n"
        f"- {routing.get('reason', '')}"
    )


async def record_coding_outcome(
    *,
    task_id: str,
    task_class: str,
    worker_id: str,
    complexity: int,
    outcome: str,
    verification: str = "",
    duration_seconds: float = 0,
) -> None:
    from ..coding.usage import record_usage

    verified = outcome == "completed" and bool(verification.strip())
    await record_usage(
        task_id=task_id,
        worker=worker_id,
        model=worker_id,
        task_class=task_class,
        complexity=complexity,
        duration_seconds=duration_seconds,
        verified_success=verified,
        first_attempt_success=verified and outcome == "completed",
    )


async def list_coding_routes(limit: int = 50) -> list[dict[str, Any]]:
    async with SessionLocal() as session:
        rows = (
            await session.execute(select(CodingRoute).order_by(CodingRoute.created_at.desc()).limit(limit))
        ).scalars().all()
    return [
        {
            "id": row.id,
            "task_id": row.task_id,
            "complexity": row.complexity,
            "tier": row.tier,
            "tier_name": row.tier_name,
            "intended_worker": row.intended_worker,
            "selected_worker": row.selected_worker,
            "paid_worker_available": row.paid_worker_available,
            "independent_verification_required": row.independent_verification_required,
            "outcome": row.outcome,
            "reason": row.reason,
            "created_at": row.created_at.isoformat() if row.created_at else None,
        }
        for row in rows
    ]
