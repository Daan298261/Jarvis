from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any

from sqlalchemy import select

from ..config import AppSettings, load_settings
from ..db.models import CodingUsageSample
from ..db.session import SessionLocal
from .catalog import probe_cursor_models

LOCAL_SUCCESS_KEEP_THRESHOLD = 0.80
LOCAL_MIN_SAMPLES = 3
LOCAL_RECENT_FAILURES_TO_ESCALATE = 3


@dataclass
class WorkerRecommendation:
    worker: str
    model: str
    tier: str
    complexity: int
    reason: str
    paid: bool
    fallback: str
    historical: dict[str, Any]

    def as_prompt(self) -> str:
        return (
            "Software-development worker routing:\n"
            f"- Selected worker: {self.worker} ({self.model})\n"
            f"- Tier: {self.tier}\n"
            f"- Estimated complexity: {self.complexity}/100\n"
            f"- Reason: {self.reason}\n"
            f"- Fallback if this fails verification: {self.fallback}\n"
            "- A worker claiming success is never completion. Jarvis must independently verify.\n"
            "- Do not escalate merely because a paid model may produce prettier code."
        )


def estimate_complexity(prompt: str, task_class: str = "") -> int:
    text = (prompt or "").lower()
    score = 18
    klass = (task_class or "").lower()
    if klass == "software engineering":
        score += 18
    cheap = ("rename", "typo", "comment", "docs", "documentation", "bump version", "format", "formatter")
    if any(token in text for token in cheap):
        score -= 12
    if any(token in text for token in ("multi-file", "several files", "across the repo", "refactor")):
        score += 18
    if any(token in text for token in ("architecture", "redesign", "migrate", "schema", "distributed")):
        score += 28
    if any(token in text for token in ("test", "pytest", "unit test", "fix")):
        score += 8
    if any(token in text for token in ("ambiguous", "unknown", "investigate", "root cause")):
        score += 12
    if len(text) > 1200:
        score += 10
    return max(0, min(100, score))


def _historical_for_class(rows: list[CodingUsageSample], task_class: str) -> dict[str, Any]:
    matching = [row for row in rows if (row.task_class or "") == (task_class or "")]
    local = [row for row in matching if row.worker == "local"]
    composer = [row for row in matching if "composer" in (row.model or "") or (row.worker == "cursor_acp" and "grok" not in (row.model or ""))]
    local_n = len(local)
    local_ok = sum(1 for row in local if row.verified_success)
    local_chrono = sorted(local, key=lambda row: row.id)
    recent_local = local_chrono[-LOCAL_RECENT_FAILURES_TO_ESCALATE:]
    recent_local_failures = len(recent_local) == LOCAL_RECENT_FAILURES_TO_ESCALATE and all(
        not row.verified_success for row in recent_local
    )
    return {
        "samples": len(matching),
        "local_samples": local_n,
        "local_success_rate": round(local_ok / local_n, 3) if local_n else None,
        "composer_samples": len(composer),
        "composer_success_rate": (
            round(sum(1 for row in composer if row.verified_success) / len(composer), 3) if composer else None
        ),
        "recent_local_failures": recent_local_failures,
    }


async def _history(task_class: str) -> dict[str, Any]:
    async with SessionLocal() as session:
        rows = (await session.execute(select(CodingUsageSample).order_by(CodingUsageSample.id))).scalars().all()
    return _historical_for_class(list(rows), task_class)


def recommend_from_history(
    prompt: str,
    task_class: str,
    history: dict[str, Any],
    settings: AppSettings | None = None,
) -> WorkerRecommendation:
    cfg = (settings or load_settings()).coding
    complexity = estimate_complexity(prompt, task_class)
    local_rate = history.get("local_success_rate")
    local_n = int(history.get("local_samples") or 0)
    keep_local = (
        local_rate is not None
        and local_rate >= LOCAL_SUCCESS_KEEP_THRESHOLD
        and local_n >= LOCAL_MIN_SAMPLES
        and not history.get("recent_local_failures")
    )
    composer = cfg.composer_model
    grok = cfg.grok_model
    if cfg.allow_fast_variants is False:
        if composer.endswith("-fast"):
            composer = composer.removesuffix("-fast")
        if grok.endswith("-fast"):
            grok = grok.removesuffix("-fast")

    if history.get("recent_local_failures") and complexity >= 30:
        return WorkerRecommendation(
            worker="cursor_acp",
            model=composer,
            tier="paid_default",
            complexity=complexity,
            reason="Local worker failed the last three similar tasks. Escalate to Composer.",
            paid=True,
            fallback=grok,
            historical=history,
        )
    if keep_local and complexity < 90:
        return WorkerRecommendation(
            worker="local",
            model="local-qwen",
            tier="local",
            complexity=complexity,
            reason=(
                f"Local worker verified success rate {local_rate:.0%} on {local_n} similar tasks. "
                "Keep work local."
            ),
            paid=False,
            fallback=composer,
            historical=history,
        )
    if complexity < 28:
        return WorkerRecommendation(
            worker="deterministic",
            model="local-qwen",
            tier="deterministic",
            complexity=complexity,
            reason="Change looks mechanical. Prefer native tools/scripts before any coding model.",
            paid=False,
            fallback="local",
            historical=history,
        )
    if complexity < 58:
        return WorkerRecommendation(
            worker="local",
            model="local-qwen",
            tier="local",
            complexity=complexity,
            reason="Clear, low-ambiguity software work. Use the local coding worker first.",
            paid=False,
            fallback=composer,
            historical=history,
        )
    if complexity < 86:
        return WorkerRecommendation(
            worker="cursor_acp",
            model=composer,
            tier="paid_default",
            complexity=complexity,
            reason="Routine multi-file or moderately hard work. Default paid worker is Composer Standard.",
            paid=True,
            fallback=grok,
            historical=history,
        )
    specialist = cfg.specialist_model or grok
    return WorkerRecommendation(
        worker="cursor_acp",
        model=specialist if complexity >= 95 and cfg.specialist_model else grok,
        tier="difficult" if complexity < 95 else "specialist",
        complexity=complexity,
        reason="High ambiguity or architecture-level work. Escalate past Composer.",
        paid=True,
        fallback=specialist if specialist != grok else composer,
        historical=history,
    )


async def recommend_worker(prompt: str, task_class: str, settings: AppSettings | None = None) -> WorkerRecommendation:
    history = await _history(task_class)
    return recommend_from_history(prompt, task_class, history, settings)


async def recommendation_prompt_block(prompt: str, task_class: str) -> str:
    rec = await recommend_worker(prompt, task_class)
    probe = probe_cursor_models()
    extra = ""
    if rec.paid and probe.get("status") != "found":
        extra = (
            "\n- Cursor ACP is not_connected in this environment. Stay on the local worker and "
            "do not invent a paid session."
        )
    return rec.as_prompt() + extra


def workers_snapshot(settings: AppSettings | None = None) -> list[dict[str, Any]]:
    probe = probe_cursor_models(settings)
    cursor_status = probe.get("status") or "not_connected"
    return [
        {
            "id": "deterministic",
            "name": "Deterministic tools",
            "status": "ready",
            "detail": "JSON/version bumps, formatters, known scripts, tests. No coding model.",
        },
        {
            "id": "local",
            "name": "LocalJarvisCodingWorker",
            "status": "ready",
            "detail": "Supervisor loop on the local Qwen model. Independent verification still required.",
        },
        {
            "id": "cursor_acp",
            "name": "CursorACPWorker",
            "status": cursor_status,
            "detail": probe.get("note"),
        },
        {
            "id": "openhands",
            "name": "OpenHandsWorker",
            "status": "not_integrated",
            "detail": "Future adapter. Jarvis still verifies.",
        },
    ]


def recommendation_dict(rec: WorkerRecommendation) -> dict[str, Any]:
    return asdict(rec)
