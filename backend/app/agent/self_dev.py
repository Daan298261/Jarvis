from __future__ import annotations

import json
import re
import subprocess
import sys
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from ..config import data_dir, load_settings, repo_root
from .worktrees import (
    WorktreeError,
    WorktreeSpec,
    checkpoint_commit,
    create_worktree,
    current_commit,
    diff_summary,
    discard_worktree,
    get_worktree,
    list_worktrees,
    refuse_trusted_merge,
    resolve_repo,
    worktree_status,
)

STOP_FILE_NAME = "STOP_JARVIS"
SESSION_NAME = "session.json"


class KillSwitchActive(RuntimeError):
    """Emergency stop is on; new autonomous work must not start."""


@dataclass
class PytestCounts:
    passed: int = 0
    failed: int = 0
    errors: int = 0
    skipped: int = 0
    ok: bool = False
    command: str = ""
    output: str = ""
    returncode: int = 0

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


def stop_file() -> Path:
    return data_dir() / STOP_FILE_NAME


def session_path() -> Path:
    root = data_dir() / "self_dev"
    root.mkdir(parents=True, exist_ok=True)
    return root / SESSION_NAME


def kill_switch_active() -> bool:
    return stop_file().exists()


def kill_switch_reason() -> str:
    path = stop_file()
    if not path.exists():
        return ""
    try:
        return path.read_text(encoding="utf-8").strip()
    except OSError:
        return "Emergency stop file present"


def activate_kill_switch(reason: str = "Emergency stop") -> dict[str, Any]:
    stamp = datetime.now(timezone.utc).isoformat()
    text = f"{reason.strip() or 'Emergency stop'}\n{stamp}\n"
    stop_file().write_text(text, encoding="utf-8")
    session = load_session()
    if session:
        session["status"] = "stopped"
        session["kill_switch"] = True
        session["kill_reason"] = reason
        session["ended_at"] = stamp
        save_session(session)
    try:
        from .loop import AGENT

        for task_id in list(AGENT._tasks):
            AGENT.cancel(task_id)
    except Exception:
        pass
    return snapshot()


def clear_kill_switch() -> dict[str, Any]:
    path = stop_file()
    if path.exists():
        path.unlink()
    session = load_session()
    if session and session.get("status") == "stopped":
        session["kill_switch"] = False
        session["status"] = "idle" if not session.get("worktree_id") else "running"
        save_session(session)
    return snapshot()


def load_session() -> dict[str, Any]:
    path = session_path()
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}
    return data if isinstance(data, dict) else {}


def save_session(payload: dict[str, Any]) -> None:
    session_path().write_text(json.dumps(payload, indent=2), encoding="utf-8")


def budget_from_settings() -> dict[str, Any]:
    settings = load_settings()
    cfg = getattr(settings, "self_dev", None)
    return {
        "max_duration_hours": float(getattr(cfg, "max_duration_hours", 12) or 12),
        "max_paid_spend_eur": float(getattr(cfg, "max_paid_spend_eur", 0) or 0),
        "max_paid_invocations": int(getattr(cfg, "max_paid_invocations", 0) or 0),
        "max_consecutive_failures": int(getattr(cfg, "max_consecutive_failures", 3) or 3),
        "experimental_port": int(getattr(cfg, "experimental_port", 4781) or 4781),
        "auto_merge": bool(getattr(cfg, "auto_merge", False)),
    }


def default_usage() -> dict[str, Any]:
    return {
        "paid_spend_eur": 0.0,
        "paid_invocations": 0,
        "consecutive_failures": 0,
        "tasks_attempted": 0,
        "tasks_completed": 0,
        "tasks_failed": 0,
        "commits": [],
        "models_used": ["local"],
        "human_intervention": "none",
    }


def counts_from(data: Any) -> PytestCounts:
    if isinstance(data, PytestCounts):
        return data
    payload = data or {}
    return PytestCounts(
        passed=int(payload.get("passed") or 0),
        failed=int(payload.get("failed") or 0),
        errors=int(payload.get("errors") or 0),
        skipped=int(payload.get("skipped") or 0),
        ok=bool(payload.get("ok")),
        command=str(payload.get("command") or ""),
        output=str(payload.get("output") or ""),
        returncode=int(payload.get("returncode") or 0),
    )


def parse_pytest_output(text: str, returncode: int, command: str = "") -> PytestCounts:
    counts = PytestCounts(command=command, output=(text or "")[-4000:], returncode=returncode)
    blob = text or ""
    for label, attr in (("passed", "passed"), ("failed", "failed"), ("skipped", "skipped")):
        match = re.search(rf"(\d+)\s+{label}", blob)
        if match:
            setattr(counts, attr, int(match.group(1)))
    errors = re.search(r"(\d+)\s+errors?", blob)
    if errors:
        counts.errors = int(errors.group(1))
    counts.ok = returncode == 0 and counts.failed == 0 and counts.errors == 0
    return counts


def run_pytest(cwd: str | Path, extra_args: list[str] | None = None, timeout: int = 180) -> PytestCounts:
    args = [sys.executable, "-m", "pytest", "-q", "--tb=line", *(extra_args or [])]
    try:
        proc = subprocess.run(
            args,
            cwd=str(cwd),
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
        text = (proc.stdout or "") + "\n" + (proc.stderr or "")
        return parse_pytest_output(text, proc.returncode or 0, command=" ".join(args))
    except subprocess.TimeoutExpired as exc:
        text = (exc.stdout or "") + "\n" + (exc.stderr or "") if isinstance(exc.stdout, str) else "timed out"
        counts = parse_pytest_output(str(text), 1, command=" ".join(args))
        counts.ok = False
        counts.errors = max(counts.errors, 1)
        counts.output = f"pytest timed out after {timeout}s\n{counts.output}"
        return counts


def evaluate_gate(before: PytestCounts, after: PytestCounts) -> dict[str, Any]:
    reasons: list[str] = []
    if after.passed == 0 and after.failed == 0 and after.errors == 0:
        reasons.append("No tests were collected")
    if not after.ok:
        reasons.append("New tests did not pass")
    if after.passed < before.passed:
        reasons.append("Old tests regressed (pass count dropped)")
    if after.failed > before.failed or after.errors > before.errors:
        reasons.append("Unexplained regression (failures increased)")
    passed = not reasons
    return {
        "passed": passed,
        "reasons": reasons,
        "tests_before": before.as_dict(),
        "tests_after": after.as_dict(),
        "unexplained_regression": any("regression" in item.lower() for item in reasons),
        "merge_allowed": False,
        "note": "Trial mode never auto-merges into the trusted branch.",
    }


def experimental_launch_plan(worktree_path: str | Path | None = None) -> dict[str, Any]:
    settings = load_settings()
    budget = budget_from_settings()
    trusted_port = int(settings.bind_port or 4780)
    experimental_port = int(budget["experimental_port"] or (trusted_port + 1))
    if experimental_port == trusted_port:
        experimental_port = trusted_port + 1
    cwd = str(Path(worktree_path).resolve() if worktree_path else repo_root())
    command = (
        f"JARVIS_SKIP_MODEL=1 PYTHONPATH=backend {sys.executable} -m uvicorn app.main:app "
        f"--host 127.0.0.1 --port {experimental_port} --app-dir backend"
    )
    return {
        "trusted": f"{settings.bind_host}:{trusted_port}",
        "experimental": f"127.0.0.1:{experimental_port}",
        "working_directory": cwd,
        "command": command,
        "note": "Launch the candidate from the isolated worktree so the trusted instance on the original port stays up.",
    }


def budget_exhausted(session: dict[str, Any] | None = None) -> str:
    state = session or load_session()
    if not state:
        return ""
    budget = state.get("budget") or budget_from_settings()
    usage = state.get("usage") or default_usage()
    started = state.get("started_at")
    if started:
        try:
            start = datetime.fromisoformat(started.replace("Z", "+00:00"))
            elapsed_h = (datetime.now(timezone.utc) - start).total_seconds() / 3600
            if elapsed_h >= float(budget.get("max_duration_hours") or 12):
                return "Maximum trial duration reached"
        except ValueError:
            pass
    max_spend = float(budget.get("max_paid_spend_eur") or 0)
    if max_spend > 0 and float(usage.get("paid_spend_eur") or 0) >= max_spend:
        return "Paid AI spend limit reached; continue with local workers only"
    max_paid = int(budget.get("max_paid_invocations") or 0)
    if max_paid > 0 and int(usage.get("paid_invocations") or 0) >= max_paid:
        return "Paid worker invocation limit reached"
    max_fail = int(budget.get("max_consecutive_failures") or 3)
    if max_fail > 0 and int(usage.get("consecutive_failures") or 0) >= max_fail:
        return "Maximum consecutive failures reached"
    return ""


def can_dispatch_paid(session: dict[str, Any] | None = None) -> bool:
    if kill_switch_active():
        return False
    state = session or load_session() or {}
    budget = state.get("budget") or budget_from_settings()
    usage = state.get("usage") or default_usage()
    max_spend = float(budget.get("max_paid_spend_eur") or 0)
    max_paid = int(budget.get("max_paid_invocations") or 0)
    if max_spend <= 0 and max_paid <= 0:
        return False
    if max_spend > 0 and float(usage.get("paid_spend_eur") or 0) >= max_spend:
        return False
    if max_paid > 0 and int(usage.get("paid_invocations") or 0) >= max_paid:
        return False
    reason = budget_exhausted(state)
    if reason and "local workers" not in reason.lower():
        return False
    return True


def record_usage(kind: str, amount_eur: float = 0.0) -> dict[str, Any]:
    session = load_session() or empty_session()
    usage = session.setdefault("usage", default_usage())
    if kind == "paid":
        usage["paid_invocations"] = int(usage.get("paid_invocations") or 0) + 1
        usage["paid_spend_eur"] = round(float(usage.get("paid_spend_eur") or 0) + float(amount_eur or 0), 4)
    elif kind == "task_attempt":
        usage["tasks_attempted"] = int(usage.get("tasks_attempted") or 0) + 1
    elif kind == "task_success":
        usage["tasks_completed"] = int(usage.get("tasks_completed") or 0) + 1
        usage["consecutive_failures"] = 0
    elif kind == "task_failure":
        usage["tasks_failed"] = int(usage.get("tasks_failed") or 0) + 1
        usage["consecutive_failures"] = int(usage.get("consecutive_failures") or 0) + 1
    save_session(session)
    return session


def empty_session() -> dict[str, Any]:
    return {
        "id": "",
        "status": "idle",
        "mode": "self_development",
        "started_at": None,
        "ended_at": None,
        "source_repo": "",
        "source_commit": "",
        "worktree_id": "",
        "worktree_path": "",
        "branch": "",
        "baseline_tests": PytestCounts().as_dict(),
        "latest_gate": None,
        "budget": budget_from_settings(),
        "usage": default_usage(),
        "kill_switch": False,
        "report": None,
    }


def start_trial(repo: str | Path | None = None, run_baseline: bool = True, pytest_timeout: int = 180) -> dict[str, Any]:
    if kill_switch_active():
        raise KillSwitchActive("Emergency stop is active (data/STOP_JARVIS). Clear it before starting a trial.")
    source = resolve_repo(repo)
    spec = create_worktree(source)
    baseline = PytestCounts(ok=True, command="skipped")
    if run_baseline:
        baseline = run_pytest(spec.path, timeout=pytest_timeout)
    session = empty_session()
    session.update(
        {
            "id": uuid.uuid4().hex[:12],
            "status": "running",
            "started_at": datetime.now(timezone.utc).isoformat(),
            "source_repo": str(source),
            "source_commit": spec.start_commit,
            "worktree_id": spec.id,
            "worktree_path": spec.path,
            "branch": spec.branch,
            "baseline_tests": baseline.as_dict(),
            "experimental_launch": experimental_launch_plan(spec.path),
        }
    )
    save_session(session)
    return session


def run_verification_gate(worktree_id: str | None = None, pytest_timeout: int = 180) -> dict[str, Any]:
    session = load_session()
    spec_id = worktree_id or (session or {}).get("worktree_id")
    if not spec_id:
        raise WorktreeError("No isolated worktree is active")
    spec = get_worktree(spec_id)
    before = counts_from((session or {}).get("baseline_tests"))
    after = run_pytest(spec.path, timeout=pytest_timeout)
    gate = evaluate_gate(before, after)
    diff = diff_summary(spec.path, since=spec.start_commit)
    gate["diff"] = diff
    gate["worktree_id"] = spec.id
    gate["branch"] = spec.branch
    gate["start_commit"] = spec.start_commit
    gate["end_commit"] = current_commit(Path(spec.path))
    if session:
        session["latest_gate"] = gate
        save_session(session)
    return gate


def build_report(session: dict[str, Any] | None = None) -> dict[str, Any]:
    state = session or load_session() or empty_session()
    usage = state.get("usage") or default_usage()
    started = state.get("started_at")
    ended = state.get("ended_at") or datetime.now(timezone.utc).isoformat()
    duration = 0.0
    if started:
        try:
            start = datetime.fromisoformat(str(started).replace("Z", "+00:00"))
            finish = datetime.fromisoformat(str(ended).replace("Z", "+00:00"))
            duration = max(0.0, (finish - start).total_seconds())
        except ValueError:
            duration = 0.0
    gate = state.get("latest_gate") or {}
    before = (gate.get("tests_before") or state.get("baseline_tests") or {})
    after = gate.get("tests_after") or {}
    completed = int(usage.get("tasks_completed") or 0)
    per_hour = round(completed / (duration / 3600), 3) if duration else 0.0
    paid = float(usage.get("paid_spend_eur") or 0)
    per_euro = round(completed / paid, 3) if paid else None
    candidate = []
    if gate.get("passed") and state.get("branch"):
        candidate = [state["branch"]]
    diff = gate.get("diff") or (diff_summary(state["worktree_path"]) if state.get("worktree_path") else {})
    report = {
        "duration_seconds": round(duration, 1),
        "worker_time_seconds": round(duration, 1),
        "models_used": list(usage.get("models_used") or ["local"]),
        "estimated_paid_cost_eur": paid,
        "tasks_attempted": int(usage.get("tasks_attempted") or 0),
        "tasks_completed": completed,
        "tasks_failed": int(usage.get("tasks_failed") or 0),
        "commits_created": list(usage.get("commits") or []),
        "tests_before": before,
        "tests_after": after,
        "regressions": gate.get("reasons") or [],
        "performance_changes": "not measured in this trial",
        "human_intervention": usage.get("human_intervention") or "none",
        "recommended_merge_candidates": candidate,
        "experiment_branch": state.get("branch") or "",
        "starting_commit": state.get("source_commit") or "",
        "ending_commit": gate.get("end_commit") or "",
        "diff_summary": diff.get("stat") or "",
        "verified_useful_work_per_hour": per_hour,
        "verified_useful_work_per_euro": per_euro,
        "kill_switch": kill_switch_active(),
        "auto_merge": False,
    }
    state["report"] = report
    state["ended_at"] = ended
    if state.get("status") == "running":
        state["status"] = "completed"
    save_session(state)
    return report


def snapshot() -> dict[str, Any]:
    session = load_session() or empty_session()
    session["kill_switch"] = kill_switch_active()
    session["kill_reason"] = kill_switch_reason()
    session["budget_stop_reason"] = budget_exhausted(session)
    session["can_dispatch_paid"] = can_dispatch_paid(session)
    session["worktrees"] = list_worktrees()
    session["experimental_launch"] = session.get("experimental_launch") or experimental_launch_plan(
        session.get("worktree_path")
    )
    return session


def require_not_stopped() -> None:
    if kill_switch_active():
        raise KillSwitchActive(
            "Emergency stop is active (data/STOP_JARVIS). "
            "New autonomous work is blocked until POST /api/self-dev/resume."
        )
    reason = budget_exhausted()
    if reason and "local workers" not in reason.lower():
        if "duration" in reason.lower() or "failures" in reason.lower():
            raise KillSwitchActive(reason)
