"""RFC-0120: coding + 3D execution contract (real tool calls, not chat-only completion)."""

from __future__ import annotations

import re
import shutil
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .coding_workers import is_software_task, start_coding_task
from .worktrees import WorktreeError, get_coding_task, update_coding_task

_EDIT_ACTIONS = frozenset({"write", "edit", "copy", "move", "rename", "delete"})
_EDIT_TOOLS = frozenset({"filesystem", "git", "code_worker"})
_RUN_TOOLS = frozenset({"terminal", "python", "code_worker"})
_VERIFY_TOOLS = frozenset({"verify_code"})
_TEST_CMD_RE = re.compile(
    r"(?i)\b(pytest|npm\s+test|pnpm\s+test|yarn\s+test|cargo\s+test|go\s+test|dotnet\s+test|mvn\s+test|gradle\s+test|make\s+test|ctest)\b"
)
_3D_MARKERS = (
    "blender",
    "openscad",
    "open scad",
    "3d model",
    "3d print",
    "mesh",
    ".stl",
    ".obj",
    ".glb",
    ".blend",
    ".scad",
    "cadquery",
    "freecad",
)
_DCC_TOOLS = frozenset({"blender", "openscad", "freecad"})


@dataclass
class CodingExecutionEvidence:
    edit: bool = False
    run: bool = False
    verified: bool = False
    dcc_success: bool = False
    dcc_missing_binary: bool = False
    tool_log: list[dict[str, Any]] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return {
            "edit": self.edit,
            "run": self.run,
            "verified": self.verified,
            "dcc_success": self.dcc_success,
            "dcc_missing_binary": self.dcc_missing_binary,
            "tool_log": list(self.tool_log),
        }

    @classmethod
    def from_dict(cls, raw: dict[str, Any] | None) -> "CodingExecutionEvidence":
        if not isinstance(raw, dict):
            return cls()
        log = raw.get("tool_log") or []
        if not isinstance(log, list):
            log = []
        return cls(
            edit=bool(raw.get("edit")),
            run=bool(raw.get("run")),
            verified=bool(raw.get("verified")),
            dcc_success=bool(raw.get("dcc_success")),
            dcc_missing_binary=bool(raw.get("dcc_missing_binary")),
            tool_log=[item for item in log if isinstance(item, dict)],
        )


def is_3d_modelling_task(prompt: str, task_class: str | None = None) -> bool:
    text = (prompt or "").lower()
    if not text.strip():
        return False
    if (task_class or "").strip().lower() in {"multimodal", "mixed", "long-horizon autonomous"}:
        if any(marker in text for marker in _3D_MARKERS):
            return True
    return any(marker in text for marker in _3D_MARKERS)


def applies_coding_execution_contract(prompt: str, task_class: str | None = None) -> bool:
    if (task_class or "").strip().lower() in {"software engineering", "long-horizon autonomous"}:
        return True
    return is_software_task(prompt, task_class)


def applies_3d_execution_contract(prompt: str, task_class: str | None = None) -> bool:
    return is_3d_modelling_task(prompt, task_class)


def init_coding_execution(working: Any) -> None:
    working.coding_execution = CodingExecutionEvidence().as_dict()


def evidence_from_working(working: Any) -> CodingExecutionEvidence:
    return CodingExecutionEvidence.from_dict(getattr(working, "coding_execution", None))


def _git_edits(arguments: dict[str, Any]) -> bool:
    action = str(arguments.get("action") or "").strip().lower()
    return action in {"commit", "checkpoint", "apply", "merge"}


def _filesystem_edits(arguments: dict[str, Any]) -> bool:
    action = str(arguments.get("action") or "").strip().lower()
    return action in _EDIT_ACTIONS


def _terminal_runs(arguments: dict[str, Any]) -> tuple[bool, bool]:
    command = str(arguments.get("command") or "")
    if not command.strip():
        return False, False
    is_test = bool(_TEST_CMD_RE.search(command))
    return True, is_test


def _python_runs(arguments: dict[str, Any]) -> tuple[bool, bool]:
    code = str(arguments.get("code") or arguments.get("command") or "")
    if not code.strip():
        return False, False
    is_test = "pytest" in code.lower() or "unittest" in code.lower()
    return True, is_test


def _missing_binary_observation(observation: str) -> bool:
    lowered = (observation or "").lower()
    return "not installed" in lowered or "install blender" in lowered or "install openscad" in lowered


def note_contract_tool(
    working: Any,
    name: str,
    arguments: dict[str, Any],
    observation: str,
    *,
    success: bool,
) -> None:
    if not success:
        if name in _DCC_TOOLS and _missing_binary_observation(observation):
            ev = evidence_from_working(working)
            ev.dcc_missing_binary = True
            working.coding_execution = ev.as_dict()
        return
    ev = evidence_from_working(working)
    entry = {
        "tool": name,
        "arguments": arguments,
        "observation": (observation or "")[:2000],
    }
    ev.tool_log = (ev.tool_log + [entry])[-40:]
    if name in _EDIT_TOOLS:
        if name == "filesystem" and _filesystem_edits(arguments):
            ev.edit = True
        elif name == "git" and _git_edits(arguments):
            ev.edit = True
        elif name == "code_worker" and str(arguments.get("action") or "") == "delegate":
            ev.edit = True
    if name in _RUN_TOOLS:
        if name == "terminal":
            ran, is_test = _terminal_runs(arguments)
            if ran:
                ev.run = True
            if is_test:
                ev.verified = True
        elif name == "python":
            ran, is_test = _python_runs(arguments)
            if ran:
                ev.run = True
            if is_test:
                ev.verified = True
        elif name == "code_worker" and str(arguments.get("action") or "") == "delegate":
            ev.run = True
    if name in _VERIFY_TOOLS:
        ev.verified = True
    if name in _DCC_TOOLS:
        ev.dcc_success = True
    working.coding_execution = ev.as_dict()


def contract_satisfied(working: Any, prompt: str, task_class: str | None = None) -> bool:
    ev = evidence_from_working(working)
    if applies_3d_execution_contract(prompt, task_class):
        if ev.dcc_missing_binary:
            return False
        if not ev.dcc_success:
            return False
    if not applies_coding_execution_contract(prompt, task_class):
        return True
    return ev.edit and ev.run and ev.verified


def contract_completion_blocked_message(working: Any, prompt: str, task_class: str | None = None) -> str:
    ev = evidence_from_working(working)
    missing: list[str] = []
    if applies_coding_execution_contract(prompt, task_class):
        if not ev.edit:
            missing.append("a real edit via filesystem or git on the worktree (not chat-only source)")
        if not ev.run:
            missing.append("a run via terminal or python (install, script, or command)")
        if not ev.verified:
            missing.append("verify_code or an explicit project test command via terminal/python")
    if applies_3d_execution_contract(prompt, task_class):
        if ev.dcc_missing_binary:
            return (
                "A local DCC binary is missing. Report the install CTA from the tool result to the owner. "
                "Do not claim the mesh or .blend was produced."
            )
        if not ev.dcc_success:
            missing.append("a successful blender or openscad tool call that wrote the export to disk")
    listed = "\n".join(f"- {item}" for item in missing) or "- required tool evidence"
    return (
        "RFC-0120: this task cannot complete from chat text alone.\n"
        f"Still missing:\n{listed}\n"
        "Use RFC-0107 tool search, then call the matched tools. Record diff, commands, and verifier output."
    )


def persist_execution_evidence(task_id: str, working: Any) -> None:
    ev = evidence_from_working(working)
    if not any((ev.edit, ev.run, ev.verified, ev.dcc_success, ev.tool_log)):
        return
    try:
        record = get_coding_task(task_id)
    except WorktreeError:
        return
    payload = dict(record.tests or {})
    payload["rfc0120"] = ev.as_dict()
    update_coding_task(task_id, tests=payload)


def ensure_coding_worktree(task_id: str, source: str | Path | None = None) -> str | None:
    """Bind an RFC-0005 worktree when a git repo exists under allowed paths (not the Jarvis dev checkout by default)."""
    try:
        record = get_coding_task(task_id)
        return record.worktree_path
    except WorktreeError:
        pass
    if not shutil.which("git"):
        return None
    from ..config import load_settings, repo_root

    candidates: list[Path] = []
    if source:
        candidates.append(Path(source))
    settings = load_settings()
    for item in settings.allowed_directories or []:
        candidates.append(Path(item))
    trusted_dev = repo_root().resolve()
    for root in candidates:
        resolved = root.expanduser().resolve()
        if not (resolved / ".git").exists():
            continue
        if resolved == trusted_dev:
            continue
        try:
            payload = start_coding_task(task_id, source=resolved)
            return str(payload.get("worktree_path") or "")
        except WorktreeError:
            continue
    return None


def orchestrator_must_not_execute_coding(task_class: str, prompt: str) -> bool:
    """RFC-0115: Ornith / front_responder must not be the coding or 3D worker."""
    return applies_coding_execution_contract(prompt, task_class) or applies_3d_execution_contract(
        prompt, task_class
    )


def bump_complexity_for_coding_contract(
    result: Any,
    *,
    task_class: str,
    prompt: str,
) -> Any:
    """Raise minimum answer tier so tier-1 orchestrator lanes do not own coding/3D work."""
    if not orchestrator_must_not_execute_coding(task_class, prompt):
        return result
    tier = max(int(result.tier or 1), 2)
    minimum = max(int(result.minimum_answer_tier or 0), 2)
    signals = list(result.signals or [])
    if "rfc-0120-coding-worker" not in signals:
        signals.append("rfc-0120-coding-worker")
    result.tier = tier
    result.minimum_answer_tier = minimum
    result.hard_rule = True
    result.prefer_tool = True
    result.signals = signals
    return result
