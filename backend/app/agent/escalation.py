from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from ..inference.manager import InferenceManager
from ..inference.profiles import model_paths, resolve_profile
from ..providers.base import ChatMessage, ChatResult, ModelProvider
from .planning import WorkingState

EXPERT_SYSTEM = (
    "You are the Jarvis Expert model. You do not execute tools. "
    "Given a compact brief, produce a focused analysis and the next concrete plan. "
    "Do not request the full trajectory. Prefer deterministic tools (API/CLI/library) over GUI/vision. "
    "If the primary agent already tried an approach, do not recommend repeating it."
)


@dataclass
class EscalationBrief:
    goal: str = ""
    acceptance_criteria: list[str] = field(default_factory=list)
    observations: list[str] = field(default_factory=list)
    failed_approaches: list[str] = field(default_factory=list)
    relevant_files: list[str] = field(default_factory=list)
    unresolved_problem: str = ""
    reason: str = ""
    task_class: str = ""

    def as_prompt(self) -> str:
        criteria = "\n".join(f"- {item}" for item in self.acceptance_criteria) or "- (not captured)"
        observations = "\n".join(f"- {item}" for item in self.observations[-8:]) or "- none"
        failed = "\n".join(f"- {item}" for item in self.failed_approaches[-8:]) or "- none"
        files = "\n".join(f"- {item}" for item in self.relevant_files[-8:]) or "- none"
        return (
            "Expert consult. Do not execute tools. Return:\n"
            "ANALYSIS:\n...\nNEXT PLAN:\n1. ...\nAVOID:\n- ...\n\n"
            f"Reason for escalation: {self.reason or 'unspecified'}\n"
            f"Task class: {self.task_class or 'mixed'}\n"
            f"Goal: {self.goal or '(same as the user request)'}\n"
            f"Acceptance criteria:\n{criteria}\n"
            f"Important observations:\n{observations}\n"
            f"Failed approaches:\n{failed}\n"
            f"Relevant files:\n{files}\n"
            f"Unresolved problem: {self.unresolved_problem or '(see failures)'}\n"
        )


@dataclass
class EscalationResult:
    advised: bool
    skipped: bool
    reason: str
    advice: str = ""
    swapped: bool = False
    brief: EscalationBrief | None = None


def brief_from_working(working: WorkingState, reason: str, prompt: str = "") -> EscalationBrief:
    files: list[str] = []
    for snippet in working.observations + working.recent_tool_outputs:
        if ": " in snippet:
            files.append(snippet.split(":", 1)[0][:80])
    return EscalationBrief(
        goal=working.goal or (prompt.strip().splitlines()[0][:240] if prompt else ""),
        acceptance_criteria=list(working.acceptance_criteria),
        observations=list(working.observations[-8:]),
        failed_approaches=list(working.known_failures[-8:]),
        relevant_files=[item for item in files if item][:8],
        unresolved_problem=working.current_state or working.next_action or reason,
        reason=reason,
        task_class=working.task_class,
    )


def _prompt_asks_for_expert(text: str) -> bool:
    lowered = (text or "").lower()
    needles = (
        "expert model",
        "use the 27b",
        "use 27b",
        "maximum-quality",
        "maximum quality",
        "escalate to expert",
        "second opinion",
        "architect this",
        "architecture decision",
    )
    return any(needle in lowered for needle in needles)


def should_escalate(
    *,
    prompt: str = "",
    consecutive_failures: int = 0,
    same_tool_streak: int = 0,
    critic_text: str = "",
    already_escalated: bool = False,
    step_count: int = 0,
    verifying: bool = False,
) -> str | None:
    """Return an escalation reason, or None.

    Long-running tasks are not a reason by themselves.
    """
    if already_escalated or verifying:
        return None
    if _prompt_asks_for_expert(prompt) and consecutive_failures == 0 and same_tool_streak == 0 and step_count <= 1:
        return "user_requested_expert"
    if consecutive_failures >= 3:
        return "repeated_failure"
    if same_tool_streak >= 4:
        return "stuck_strategy"
    critic = (critic_text or "").lower()
    if critic and any(word in critic for word in ("not confident", "low confidence", "unsure", "contradict")):
        return "critic_uncertainty"
    if step_count >= 40:
        # Step limit is handled by the runtime; length alone must not escalate.
        return None
    return None


def expert_available() -> bool:
    paths = model_paths()
    quality = resolve_profile("quality")
    return (paths["root"] / quality.filename).exists()


async def consult_expert(
    brief: EscalationBrief,
    *,
    provider: ModelProvider | None = None,
    manager: InferenceManager | None = None,
    settings: Any | None = None,
    allow_swap: bool = False,
) -> EscalationResult:
    chat: ModelProvider | None = provider
    if chat is None and manager is not None:
        chat = manager.provider
    if chat is None:
        return EscalationResult(
            advised=False,
            skipped=True,
            reason=brief.reason or "no provider",
            advice="Expert consult skipped: no model provider is loaded.",
            brief=brief,
        )

    original_profile = ""
    swapped = False
    if allow_swap and manager is not None and settings is not None and expert_available():
        original_profile = manager.state.profile or settings.inference.profile
        if original_profile != "quality":
            try:
                await manager.load(settings, "quality")
                chat = manager.provider or chat
                swapped = True
            except Exception as exc:
                return EscalationResult(
                    advised=False,
                    skipped=True,
                    reason=brief.reason,
                    advice=f"Expert consult skipped: could not load quality/27B profile ({exc}).",
                    brief=brief,
                )

    result: ChatResult = await chat.chat(
        [
            ChatMessage(role="system", content=EXPERT_SYSTEM),
            ChatMessage(role="user", content=brief.as_prompt()),
        ],
        tools=None,
        thinking=True,
        max_tokens=900,
    )
    advice = (result.content or "").strip() or (result.reasoning or "").strip()
    if swapped and manager is not None and settings is not None and original_profile:
        try:
            await manager.load(settings, original_profile)
        except Exception:
            pass
    return EscalationResult(
        advised=bool(advice),
        skipped=False,
        reason=brief.reason,
        advice=advice or "Expert returned an empty analysis.",
        swapped=swapped,
        brief=brief,
    )


def format_expert_message(result: EscalationResult) -> str:
    return (
        "Expert consult completed. Follow this focused advice; do not repeat failed approaches. "
        "Do not escalate again unless a new distinct failure appears.\n\n"
        f"{result.advice}"
    )
