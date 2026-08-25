"""P0.9 — representative autonomous-task suite and report builder.

Live Windows/GPU execution is optional. The catalog, metric schema, and
aggregation run without a model so the portal can show the suite immediately.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select

from ..db.models import AgentBenchmarkResult, utcnow
from ..db.session import SessionLocal


@dataclass(frozen=True)
class AgentTaskSpec:
    id: str
    title: str
    category: str
    prompt: str
    acceptance: tuple[str, ...]
    tools: tuple[str, ...]
    live_requires: str = ""
    notes: str = ""


# At least 20 realistic Jarvis tasks covering the P0.9 examples.
SUITE: tuple[AgentTaskSpec, ...] = (
    AgentTaskSpec(
        id="fs-organize",
        title="Filesystem organization",
        category="filesystem",
        prompt="Create a dated archive folder and move matching log files into it without deleting originals.",
        acceptance=("archive folder exists", "source files remain or were moved as specified", "no files outside the workspace were touched"),
        tools=("filesystem",),
    ),
    AgentTaskSpec(
        id="py-broken-project",
        title="Broken Python project diagnosis",
        category="software engineering",
        prompt="A small Python project fails its tests. Diagnose the exception, patch the code, and re-run tests.",
        acceptance=("failing test identified", "code changed", "tests pass after the fix"),
        tools=("filesystem", "python", "terminal"),
    ),
    AgentTaskSpec(
        id="git-modify",
        title="Git repository modification",
        category="software engineering",
        prompt="Create a git checkpoint, edit one tracked file, and leave a recoverable backup branch.",
        acceptance=("checkpoint branch exists", "working tree still has the intended edit", "status is inspectable"),
        tools=("git", "filesystem"),
    ),
    AgentTaskSpec(
        id="shell-troubleshoot",
        title="PowerShell / shell troubleshooting",
        category="shell",
        prompt="A shell command fails because a tool is missing from PATH. Detect the failure and use a working alternative.",
        acceptance=("failure classified", "alternative command ran", "verification output captured"),
        tools=("terminal",),
        notes="On Linux use bash; on Windows use PowerShell.",
    ),
    AgentTaskSpec(
        id="browser-nav",
        title="Browser navigation",
        category="browser automation",
        prompt="Open example.com, read the page title, and confirm it contains Example Domain.",
        acceptance=("page loaded", "title verified"),
        tools=("browser",),
        live_requires="Playwright Chromium",
    ),
    AgentTaskSpec(
        id="unfamiliar-site",
        title="Unfamiliar website interaction",
        category="browser automation",
        prompt="Open a previously unseen documentation page, find one heading, and extract the first paragraph.",
        acceptance=("URL opened", "heading captured", "paragraph captured"),
        tools=("browser", "web_fetch"),
        live_requires="network",
    ),
    AgentTaskSpec(
        id="tool-failure-recovery",
        title="Deliberate tool failure and recovery",
        category="recovery",
        prompt="Attempt a browser action that cannot succeed, then recover with web_fetch instead of repeating the same call.",
        acceptance=("first call failed", "recovery used a different tool", "result obtained"),
        tools=("browser", "web_fetch"),
    ),
    AgentTaskSpec(
        id="screenshot-interpret",
        title="Screenshot interpretation",
        category="multimodal",
        prompt="Capture a screenshot of the current desktop or browser tab and describe the visible window title.",
        acceptance=("image captured", "description references visible UI"),
        tools=("screenshot", "browser"),
        live_requires="display or browser viewport",
    ),
    AgentTaskSpec(
        id="multi-step-research",
        title="Multi-step research",
        category="research",
        prompt="Look up two public sources about llama.cpp GGUF quantization and write a short comparison file.",
        acceptance=("at least two sources fetched", "comparison file written", "claims cite the fetches"),
        tools=("web_fetch", "filesystem"),
        live_requires="network",
    ),
    AgentTaskSpec(
        id="document-processing",
        title="Document processing",
        category="document processing",
        prompt="Create a markdown report from three short notes and keep the originals untouched.",
        acceptance=("report exists", "originals unchanged", "report contains all three notes"),
        tools=("filesystem",),
    ),
    AgentTaskSpec(
        id="multi-tool",
        title="Multi-tool autonomous task",
        category="long-horizon autonomous",
        prompt="List a folder, run a Python checksum of one file, and write the hash next to a git status snapshot.",
        acceptance=("list succeeded", "hash written", "git status captured"),
        tools=("filesystem", "python", "git"),
    ),
    AgentTaskSpec(
        id="verify-after-code",
        title="Verification after code modification",
        category="software engineering",
        prompt="Change a function's return value, then independently read the file and run a unit test before declaring success.",
        acceptance=("code changed", "independent read or test ran", "success not claimed from memory"),
        tools=("filesystem", "python"),
    ),
    AgentTaskSpec(
        id="json-transform",
        title="JSON data transform",
        category="data processing",
        prompt="Read a JSON array, keep only records with status=active, and write pretty-printed output.",
        acceptance=("output JSON is valid", "inactive records removed", "source file unchanged"),
        tools=("filesystem", "python"),
    ),
    AgentTaskSpec(
        id="csv-summarize",
        title="CSV summarization",
        category="data processing",
        prompt="Summarize a CSV by grouping one column and writing totals to a new file.",
        acceptance=("summary file exists", "totals match the source", "source CSV unchanged"),
        tools=("filesystem", "python"),
    ),
    AgentTaskSpec(
        id="web-fetch-api",
        title="HTTP research fetch",
        category="research",
        prompt="GET a public HTTP URL, record status and content-type, and save a truncated body.",
        acceptance=("HTTP status recorded", "body truncated if long", "file:// URLs rejected if attempted"),
        tools=("web_fetch", "filesystem"),
        live_requires="network",
    ),
    AgentTaskSpec(
        id="office-export",
        title="Office document export",
        category="office",
        prompt="Create a new Word or Excel file with a title row and save it under Documents.",
        acceptance=("file exists", "title content present", "originals not overwritten unless asked"),
        tools=("office",),
        live_requires="Windows Microsoft Office",
    ),
    AgentTaskSpec(
        id="docker-inspect",
        title="Docker inspection",
        category="system administration",
        prompt="If Docker is installed, list images; otherwise report unavailable without inventing containers.",
        acceptance=("ps/images ran or unavailable reported", "run without an image is refused"),
        tools=("docker",),
    ),
    AgentTaskSpec(
        id="named-desktop-ui",
        title="Named-control desktop UI",
        category="windows gui",
        prompt="Open Notepad via named window/control lookup. Coordinate click only if named lookup fails.",
        acceptance=("named lookup attempted first", "coordinates are last resort"),
        tools=("desktop",),
        live_requires="Windows native UI",
    ),
    AgentTaskSpec(
        id="skill-replay",
        title="Parameterized skill replay",
        category="filesystem",
        prompt="Run a previously promoted skill that copies a file, then verify the destination hash.",
        acceptance=("skill steps executed", "destination exists", "hash matches source"),
        tools=("filesystem",),
    ),
    AgentTaskSpec(
        id="recovery-permissions",
        title="Permission failure routing",
        category="recovery",
        prompt="Attempt a write outside allowed directories, classify the failure, and complete the work inside the sandbox instead.",
        acceptance=("blocked write diagnosed", "no identical retry of the blocked path", "sandbox write verified"),
        tools=("filesystem",),
    ),
)


REQUIRED_CATEGORIES = {
    "filesystem",
    "software engineering",
    "shell",
    "browser automation",
    "recovery",
    "multimodal",
    "research",
    "document processing",
    "long-horizon autonomous",
    "data processing",
    "office",
    "system administration",
    "windows gui",
}


@dataclass
class TaskMetrics:
    task_id: str
    profile: str = ""
    success: bool = False
    human_intervention: bool = False
    total_seconds: float = 0.0
    model_seconds: float = 0.0
    tool_seconds: float = 0.0
    model_calls: int = 0
    tool_calls: int = 0
    retries: int = 0
    schema_errors: int = 0
    incorrect_actions: int = 0
    verification: str = ""
    notes: str = ""

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


def list_suite() -> list[dict[str, Any]]:
    return [
        {
            "id": spec.id,
            "title": spec.title,
            "category": spec.category,
            "prompt": spec.prompt,
            "acceptance": list(spec.acceptance),
            "tools": list(spec.tools),
            "live_requires": spec.live_requires,
            "notes": spec.notes,
        }
        for spec in SUITE
    ]


def get_task(task_id: str) -> AgentTaskSpec | None:
    for spec in SUITE:
        if spec.id == task_id:
            return spec
    return None


def suite_coverage() -> dict[str, Any]:
    categories = {spec.category for spec in SUITE}
    missing = sorted(REQUIRED_CATEGORIES - categories)
    return {
        "task_count": len(SUITE),
        "categories": sorted(categories),
        "required_categories_present": not missing,
        "missing_required_categories": missing,
    }


def compare_profiles(rows: list[dict[str, Any]]) -> dict[str, Any]:
    """Primary metric: successful autonomous tasks per hour of wall clock."""
    by_profile: dict[str, dict[str, Any]] = {}
    for row in rows:
        key = row.get("profile") or "unknown"
        bucket = by_profile.setdefault(
            key,
            {
                "profile": key,
                "tasks": 0,
                "successes": 0,
                "failures": 0,
                "human_interventions": 0,
                "total_seconds": 0.0,
                "first_pass": 0,
                "tool_calls": 0,
                "schema_errors": 0,
                "incorrect_actions": 0,
            },
        )
        bucket["tasks"] += 1
        success = bool(row.get("success"))
        if success:
            bucket["successes"] += 1
            if int(row.get("retries") or 0) == 0 and int(row.get("incorrect_actions") or 0) == 0:
                bucket["first_pass"] += 1
        else:
            bucket["failures"] += 1
        if row.get("human_intervention"):
            bucket["human_interventions"] += 1
        bucket["total_seconds"] += float(row.get("total_seconds") or 0)
        bucket["tool_calls"] += int(row.get("tool_calls") or 0)
        bucket["schema_errors"] += int(row.get("schema_errors") or 0)
        bucket["incorrect_actions"] += int(row.get("incorrect_actions") or 0)

    reports = []
    for bucket in by_profile.values():
        hours = bucket["total_seconds"] / 3600 if bucket["total_seconds"] else 0.0
        successes = bucket["successes"]
        tasks = bucket["tasks"] or 1
        reports.append(
            {
                **bucket,
                "successful_tasks_per_hour": round(successes / hours, 3) if hours else None,
                "first_pass_rate": round(bucket["first_pass"] / tasks, 4),
                "success_rate": round(successes / tasks, 4),
                "tool_call_accuracy": round(
                    1 - (bucket["schema_errors"] + bucket["incorrect_actions"]) / max(bucket["tool_calls"], 1),
                    4,
                ),
            }
        )
    reports.sort(key=lambda item: (item["success_rate"], item["successful_tasks_per_hour"] or 0), reverse=True)
    return {
        "primary_metric": "successful autonomous tasks per hour of wall-clock time",
        "profiles": reports,
        "winner": reports[0]["profile"] if reports else None,
        "selection_rule": "Do not pick a default from tokens/sec alone. Prefer verified task throughput.",
    }


def empty_report() -> dict[str, Any]:
    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "suite": list_suite(),
        "coverage": suite_coverage(),
        "results": [],
        "comparison": compare_profiles([]),
        "live_status": "catalog only — run on the Windows desktop with a loaded model to fill results",
    }


async def record_result(metrics: TaskMetrics) -> AgentBenchmarkResult:
    spec = get_task(metrics.task_id)
    async with SessionLocal() as session:
        row = AgentBenchmarkResult(
            task_key=metrics.task_id,
            title=spec.title if spec else metrics.task_id,
            category=spec.category if spec else "",
            profile=metrics.profile,
            success=metrics.success,
            human_intervention=metrics.human_intervention,
            total_seconds=metrics.total_seconds,
            model_seconds=metrics.model_seconds,
            tool_seconds=metrics.tool_seconds,
            model_calls=metrics.model_calls,
            tool_calls=metrics.tool_calls,
            retries=metrics.retries,
            schema_errors=metrics.schema_errors,
            incorrect_actions=metrics.incorrect_actions,
            verification=metrics.verification,
            notes=metrics.notes,
        )
        session.add(row)
        await session.commit()
        await session.refresh(row)
        return row


def _row_dict(row: AgentBenchmarkResult) -> dict[str, Any]:
    return {
        "id": row.id,
        "task_id": row.task_key,
        "title": row.title,
        "category": row.category,
        "profile": row.profile,
        "success": row.success,
        "human_intervention": row.human_intervention,
        "total_seconds": row.total_seconds,
        "model_seconds": row.model_seconds,
        "tool_seconds": row.tool_seconds,
        "model_calls": row.model_calls,
        "tool_calls": row.tool_calls,
        "retries": row.retries,
        "schema_errors": row.schema_errors,
        "incorrect_actions": row.incorrect_actions,
        "verification": row.verification,
        "notes": row.notes,
        "created_at": row.created_at.isoformat() if row.created_at else None,
    }


async def list_results(limit: int = 200) -> list[dict[str, Any]]:
    async with SessionLocal() as session:
        rows = (
            await session.execute(
                select(AgentBenchmarkResult).order_by(AgentBenchmarkResult.created_at.desc()).limit(limit)
            )
        ).scalars().all()
    return [_row_dict(row) for row in rows]


async def build_report() -> dict[str, Any]:
    results = await list_results()
    return {
        "generated_at": utcnow().isoformat(),
        "suite": list_suite(),
        "coverage": suite_coverage(),
        "results": results,
        "comparison": compare_profiles(results),
        "live_status": (
            "results recorded"
            if results
            else "catalog only — run on the Windows desktop with a loaded model to fill results"
        ),
    }
