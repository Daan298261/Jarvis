from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable, Iterable

from .planning import WorkingState

LoadFn = Callable[[str], Awaitable[Any]]
UnloadFn = Callable[[], Awaitable[Any]]
ChatFn = Callable[[list[dict[str, Any]]], Awaitable[Any]]


@dataclass
class EscalationSignals:
    consecutive_failures: int = 0
    failed_tools: Iterable[str] = field(default_factory=list)
    task_class: str = ""
    user_requested_expert: bool = False
    architecture_task: bool = False
    critic_low_confidence: bool = False
    already_consulted: int = 0


@dataclass
class ExpertBrief:
    goal: str
    acceptance_criteria: list[str]
    observations: list[str]
    failed_approaches: list[str]
    unresolved_problem: str
    relevant_files: list[str]
    task_class: str = ""

    def as_prompt(self) -> str:
        criteria = "\n".join(f"- {item}" for item in self.acceptance_criteria) or "- (not captured)"
        failed = "\n".join(f"- {item}" for item in self.failed_approaches[-6:]) or "- none recorded"
        observed = "\n".join(f"- {item}" for item in self.observations[-6:]) or "- none"
        files = "\n".join(f"- {item}" for item in self.relevant_files[:8]) or "- none named"
        return (
            "You are the Expert 27B advisor. Do not execute tools. Produce a focused analysis "
            "and a concrete next plan the smaller primary model can carry out.\n\n"
            f"Goal: {self.goal or '(same as the user request)'}\n"
            f"Task class: {self.task_class or 'mixed'}\n"
            f"Acceptance criteria:\n{criteria}\n"
            f"Important observations:\n{observed}\n"
            f"Failed approaches:\n{failed}\n"
            f"Relevant files:\n{files}\n"
            f"Unresolved problem: {self.unresolved_problem}\n\n"
            "Reply with:\n"
            "ANALYSIS:\n"
            "NEXT PLAN:\n"
            "1. ...\n"
            "PITFALLS:\n"
            "- ..."
        )


@dataclass
class ExpertAdvice:
    used: bool
    content: str = ""
    reason: str = ""
    primary_restored: bool = True


_EXPERT_PROMPT_MARKERS = ("expert model", "maximum quality", "use 27b", "escalate to expert", "second opinion")
_ARCHITECTURE_MARKERS = ("architecture", "redesign", "system design", "refactor the whole")


def user_requested_expert(prompt: str) -> bool:
    text = (prompt or "").lower()
    return any(marker in text for marker in _EXPERT_PROMPT_MARKERS)


def looks_like_architecture(prompt: str, task_class: str = "") -> bool:
    text = f"{prompt or ''} {task_class or ''}".lower()
    return any(marker in text for marker in _ARCHITECTURE_MARKERS)


def should_escalate(signals: EscalationSignals) -> bool:
    """Escalate only when the primary model is stuck, not because a task is long."""
    if signals.already_consulted >= 1:
        return False
    if signals.user_requested_expert:
        return True
    failed = {name for name in signals.failed_tools if name}
    if signals.consecutive_failures >= 3 and len(failed) >= 2:
        return True
    if signals.architecture_task and signals.consecutive_failures >= 2:
        return True
    if signals.critic_low_confidence and signals.consecutive_failures >= 2:
        return True
    return False


def build_expert_brief(working: WorkingState, unresolved: str = "") -> ExpertBrief:
    files: list[str] = []
    for snippet in working.observations + working.recent_tool_outputs:
        if ":" in snippet:
            # keep short path-like tokens from tool output without dumping traces
            tail = snippet.split(":", 1)[-1]
            for token in tail.replace("\\", "/").split():
                if "/" in token and len(token) < 180:
                    files.append(token.strip(".,;\"'"))
                    break
    problem = unresolved or working.next_action or working.current_state or "primary model is stuck"
    return ExpertBrief(
        goal=working.goal,
        acceptance_criteria=list(working.acceptance_criteria),
        observations=list(working.observations[-6:]),
        failed_approaches=list(working.known_failures[-6:]),
        unresolved_problem=problem,
        relevant_files=files[:8],
        task_class=working.task_class,
    )


async def consult_expert(
    brief: ExpertBrief,
    *,
    primary_profile: str,
    expert_profile: str = "expert",
    load: LoadFn,
    unload: UnloadFn,
    chat: ChatFn | None,
) -> ExpertAdvice:
    """Unload the primary model, ask Expert 27B, then restore the primary.

    Live model files are optional: missing GGUFs return used=False instead of crashing.
    """
    if chat is None:
        return ExpertAdvice(False, reason="no chat provider available for expert consult")
    try:
        await unload()
        await load(expert_profile)
    except Exception as exc:
        try:
            await load(primary_profile)
        except Exception:
            return ExpertAdvice(False, reason=str(exc), primary_restored=False)
        return ExpertAdvice(False, reason=str(exc), primary_restored=True)
    content = ""
    try:
        result = await chat(
            [
                {"role": "system", "content": "You are Jarvis Expert. Answer with ANALYSIS / NEXT PLAN / PITFALLS only."},
                {"role": "user", "content": brief.as_prompt()},
            ]
        )
        content = getattr(result, "content", None) or str(result)
    except Exception as exc:
        content = ""
        reason = str(exc)
    else:
        reason = "expert consult completed"
    restored = True
    try:
        await unload()
        await load(primary_profile)
    except Exception as exc:
        restored = False
        reason = f"{reason}; failed to restore primary: {exc}"
    if not content:
        return ExpertAdvice(False, reason=reason, primary_restored=restored)
    return ExpertAdvice(True, content=content.strip(), reason=reason, primary_restored=restored)


_PACKAGES: dict[str, dict[str, Any]] = {}


def build_escalation_package(working: WorkingState, unresolved: str = "") -> dict[str, Any]:
    brief = build_expert_brief(working, unresolved=unresolved)
    return {
        "goal": brief.goal,
        "acceptance_criteria": brief.acceptance_criteria,
        "observations": brief.observations,
        "failed_approaches": brief.failed_approaches,
        "unresolved_problem": brief.unresolved_problem,
        "relevant_files": brief.relevant_files,
        "task_class": brief.task_class,
    }


async def persist_escalation_package(package: dict[str, Any], package_id: str | None = None) -> dict[str, Any]:
    ident = package_id or f"esc-{len(_PACKAGES) + 1}"
    stored = {"id": ident, **package}
    _PACKAGES[ident] = stored
    return stored


async def list_escalation_packages() -> list[dict[str, Any]]:
    return list(_PACKAGES.values())


async def get_escalation_package(package_id: str) -> dict[str, Any] | None:
    return _PACKAGES.get(package_id)
