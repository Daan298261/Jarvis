from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ThinkingDecision:
    enabled: bool
    reason: str


# Turns that are cheap, already-decided work.
_ROUTINE_PHASES = {"act", "final"}
# Turns where extra reasoning is usually worth the tokens.
_REASONING_PHASES = {"plan", "select", "critic", "recover"}


def should_think(
    *,
    profile_thinking: bool,
    execution_mode: str = "balanced",
    phase: str = "act",
    consecutive_failures: int = 0,
    same_tool_streak: int = 0,
    tool_rounds: int = 0,
) -> ThinkingDecision:
    """Decide whether this model turn should spend reasoning tokens.

    Profile.thinking is a permission, not a mandate. Fast profiles stay off
    except after repeated failure. Balanced/quality think for planning,
    recovery, and Reliable-mode verification — not for every filesystem call.
    """
    mode = (execution_mode or "balanced").strip().lower()
    stage = (phase or "act").strip().lower()

    if stage == "final":
        return ThinkingDecision(False, "final report does not need thinking")

    if consecutive_failures >= 1:
        stage = "recover"
    elif same_tool_streak >= 2:
        stage = "recover"

    if not profile_thinking:
        if consecutive_failures >= 2 and mode != "fast":
            return ThinkingDecision(True, "recovery after repeated failure")
        return ThinkingDecision(False, "profile thinking off")

    if stage in _REASONING_PHASES:
        return ThinkingDecision(True, f"{stage} needs stronger reasoning")

    if stage == "verify":
        if mode == "reliable":
            return ThinkingDecision(True, "consequential verification")
        return ThinkingDecision(False, "routine verification")

    if stage in _ROUTINE_PHASES:
        if mode == "reliable" and tool_rounds == 0:
            return ThinkingDecision(True, "first reliable action")
        return ThinkingDecision(False, "routine tool work")

    return ThinkingDecision(False, "default off")


def infer_phase(
    *,
    force_final: bool,
    verifying: bool,
    awaiting_plan_selection: bool,
    best_of_n_complete: bool,
    tools_used: bool,
    consecutive_failures: int,
    critic_pending: bool = False,
) -> str:
    """Map agent-loop flags to a thinking phase."""
    if force_final:
        return "final"
    if consecutive_failures:
        return "recover"
    if verifying:
        return "verify"
    if awaiting_plan_selection:
        return "select"
    if critic_pending:
        return "critic"
    if not best_of_n_complete or not tools_used:
        return "plan"
    return "act"
