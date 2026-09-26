"""Run and independently score real ANZU agent-suite tasks on selected local profiles."""

from __future__ import annotations

import asyncio
import uuid
from pathlib import Path
from typing import Any

from sqlalchemy import select

from ..agent.agent_benchmark import (
    CASES, check_case, format_prompt, get_case, metrics_from_task,
    prepare_case, record_case_result, summarize_results,
)
from ..agent.loop import AGENT
from ..config import data_dir, load_settings
from ..db.models import Task, ToolCallRecord
from ..db.session import SessionLocal
from .profiles import declared_profiles
from .manager import MANAGER

_JOBS: dict[str, dict[str, Any]] = {}
_RUNNING: asyncio.Task | None = None


def live_suite_status(job_id: str) -> dict[str, Any] | None:
    return _JOBS.get(job_id)


async def start_live_suite(*, profiles: list[str], case_ids: list[str] | None = None) -> dict[str, Any]:
    global _RUNNING
    if _RUNNING is not None and not _RUNNING.done():
        raise RuntimeError("An agent suite is already running")
    allowed = {profile.name for profile in declared_profiles()}
    if not profiles or any(name not in allowed for name in profiles):
        raise ValueError("Select one or more known model profiles")
    selected = [get_case(case_id) for case_id in case_ids] if case_ids else list(CASES)
    if not selected:
        raise ValueError("Select at least one agent-suite case")
    job_id = uuid.uuid4().hex
    job = {"id": job_id, "status": "running", "profiles": profiles, "cases_total": len(selected) * len(profiles),
           "cases_finished": 0, "current": "", "results": [], "summary": {}, "error": ""}
    _JOBS[job_id] = job
    _RUNNING = asyncio.create_task(_run_live_suite(job, selected))
    return dict(job)


async def _run_live_suite(job: dict[str, Any], cases: list) -> None:
    try:
        seen_models: dict[str, str] = {}
        for profile in job["profiles"]:
            await MANAGER.load(load_settings(), profile)
            if MANAGER.state.profile != profile or not MANAGER.state.loaded:
                raise RuntimeError(f"Could not load requested profile {profile}")
            for case in cases:
                workspace = data_dir() / "agent-suite" / "live" / job["id"] / profile / case.id
                context = prepare_case(case, workspace)
                job["current"] = f"{profile}: {case.id}"
                task = await AGENT.create_task(format_prompt(case, context), profile=profile, execution_mode="balanced")
                runner = AGENT._tasks.get(task.id)
                if runner is None:
                    raise RuntimeError("Agent task did not start")
                try:
                    await asyncio.wait_for(asyncio.shield(runner), timeout=900)
                except asyncio.TimeoutError:
                    AGENT.cancel(task.id)
                    await asyncio.sleep(0)
                async with SessionLocal() as session:
                    stored = await session.get(Task, task.id)
                    calls = (await session.execute(select(ToolCallRecord).where(ToolCallRecord.task_id == task.id))).scalars().all()
                if stored is None:
                    raise RuntimeError("Agent task vanished before scoring")
                if stored.profile != profile or MANAGER.state.profile != profile:
                    raise RuntimeError(
                        f"Benchmark requested {profile}, but task ran profile {stored.profile} "
                        f"with runtime {MANAGER.state.profile}; comparison stopped"
                    )
                actual_model = str(getattr(MANAGER.provider, "model", "") or "")
                if not actual_model:
                    raise RuntimeError("Benchmark cannot identify the model that ran this task")
                other = next((name for name, model in seen_models.items() if name != profile and model == actual_model), None)
                if other:
                    raise RuntimeError(f"Profiles {other} and {profile} resolved to the same model ({actual_model}); comparison stopped")
                seen_models[profile] = actual_model
                needed_approval = bool(stored.waiting_for_confirmation)
                if needed_approval:
                    await AGENT.confirm_task(task.id, approved=False)
                passed, notes = check_case(case, workspace, context)
                metrics = metrics_from_task(stored, list(calls))
                metrics["success"] = bool(passed and stored.status == "completed")
                metrics["human_intervention"] = bool(needed_approval or stored.human_interventions)
                metrics["verification_result"] = notes
                metrics["first_response_ms"] = float(stored.first_response_ms) if stored.first_response_ms and stored.first_response_ms > 0 else None
                await record_case_result(case=case, metrics=metrics, profile=profile, source="live",
                                         workspace=str(workspace), notes=f"task={task.id}; model={actual_model}; first_response_ms={metrics['first_response_ms']}; status={stored.status}; {notes}")
                job["results"].append({"profile": profile, "case_id": case.id, "task_id": task.id,
                                       "success": metrics["success"], "status": stored.status, "actual_model": actual_model, "notes": notes,
                                       "metrics": metrics})
                job["cases_finished"] += 1
        job["summary"] = {profile: summarize_results([row["metrics"] for row in job["results"] if row["profile"] == profile])
                          for profile in job["profiles"]}
        job["status"] = "completed"
    except Exception as exc:
        job["error"] = str(exc)[:500]
        job["status"] = "failed"
    finally:
        job["current"] = ""
