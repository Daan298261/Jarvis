from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from ..config import AppSettings
from ..inference.profiles import expert_profile, resolve_profile
from ..providers.base import ChatMessage, ChatResult
from .planning import WorkingState
from .prompts import EXPERT_CONSULT_PROMPT

QUALITY_PHRASES = (
    "use the expert",
    "expert model",
    "maximum quality",
    "max quality",
    "deep analysis",
    "second opinion",
    "architecture decision",
)

ARCHITECTURE_PHRASES = (
    "architecture",
    "redesign",
    "system design",
    "migrate the",
    "whole codebase",
)


@dataclass
class EscalationDecision:
    should_escalate: bool
    reason: str = ""


def user_requests_expert(prompt: str | None) -> bool:
    text = (prompt or "").lower()
    return any(phrase in text for phrase in QUALITY_PHRASES)


def architecture_task(task_class: str | None, prompt: str | None) -> bool:
    text = (prompt or "").lower()
    if (task_class or "").lower() != "software engineering":
        return False
    return any(phrase in text for phrase in ARCHITECTURE_PHRASES)


def contradictory_observations(observations: list[str]) -> bool:
    text = " ".join(observations[-6:]).lower()
    missing = "not found" in text or "does not exist" in text or "no such file" in text
    present = "exists" in text or "wrote" in text or "created" in text
    return missing and present


def should_escalate(
    *,
    prompt: str = "",
    task_class: str = "",
    consecutive_failures: int = 0,
    distinct_failed_tools: int = 0,
    critic_rejected: bool = False,
    observations: list[str] | None = None,
    already_escalated: bool = False,
) -> EscalationDecision:
    """Escalate for genuine difficulty, not because a task is merely long."""
    if already_escalated:
        return EscalationDecision(False, "")
    if user_requests_expert(prompt):
        return EscalationDecision(True, "user requested maximum-quality analysis")
    if architecture_task(task_class, prompt) and consecutive_failures >= 1:
        return EscalationDecision(True, "architecture-level task after a failed strategy")
    if consecutive_failures >= 3:
        return EscalationDecision(True, "repeated reasoning/tool failure")
    if distinct_failed_tools >= 3:
        return EscalationDecision(True, "multiple failed strategies")
    if critic_rejected:
        return EscalationDecision(True, "critic confidence below threshold")
    if contradictory_observations(observations or []):
        return EscalationDecision(True, "contradictory observations")
    return EscalationDecision(False, "")


def expert_packet(working: WorkingState, problem: str) -> str:
    """Compact consult payload. Do not dump the full trajectory."""
    criteria = "\n".join(f"- {item}" for item in working.acceptance_criteria[:8]) or "- (not yet captured)"
    failures = "\n".join(f"- {item}" for item in working.known_failures[-6:]) or "- none recorded"
    observations = "\n".join(f"- {item}" for item in working.observations[-6:]) or "- none"
    plan = "\n".join(f"{i}. {step}" for i, step in enumerate(working.plan[:8], 1)) or "(none)"
    return (
        f"GOAL: {working.goal or '(same as user request)'}\n"
        f"TASK CLASS: {working.task_class or 'mixed'}\n"
        f"ACCEPTANCE CRITERIA:\n{criteria}\n"
        f"CURRENT PLAN:\n{plan}\n"
        f"IMPORTANT OBSERVATIONS:\n{observations}\n"
        f"FAILED APPROACHES:\n{failures}\n"
        f"UNRESOLVED PROBLEM: {problem}\n"
    )


def same_gguf(primary_name: str, expert_name: str) -> bool:
    primary = resolve_profile(primary_name)
    expert = resolve_profile(expert_name) if expert_name in {"fast", "balanced", "quality", "expert"} else expert_profile()
    return primary.filename == expert.filename and primary.quant == expert.quant


async def consult_expert(
    settings: AppSettings,
    packet: str,
    primary_profile: str,
    *,
    provider: Any | None = None,
) -> str:
    """Ask Expert for a focused plan, then restore the primary profile when a swap happened."""
    from ..inference.manager import MANAGER

    expert = expert_profile()
    chat = provider or MANAGER.provider
    swapped = False
    if chat is None:
        return "Expert consult skipped: no model provider is loaded."
    try:
        if not same_gguf(primary_profile, expert.name):
            await MANAGER.load(settings, expert.name, context_size=expert.context_size, force=True)
            swapped = True
            chat = MANAGER.provider or chat
    except Exception:
        swapped = False
        chat = provider or MANAGER.provider
    if chat is None:
        return "Expert consult skipped: expert model is not available."
    messages = [
        ChatMessage(role="system", content="You are Jarvis Expert. Compact analysis only. Do not call tools."),
        ChatMessage(role="user", content=packet + "\n\n" + EXPERT_CONSULT_PROMPT),
    ]
    try:
        result: ChatResult = await chat.chat(
            messages,
            tools=None,
            temperature=0.4,
            thinking=True,
            max_tokens=800,
        )
        content = (result.content or "").strip() or (result.reasoning or "").strip()
    except Exception as exc:
        content = f"Expert consult failed: {exc}"
    if swapped:
        try:
            await MANAGER.load(settings, primary_profile)
        except Exception:
            pass
    return content or "(expert returned an empty analysis)"
