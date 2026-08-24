from __future__ import annotations

from dataclasses import dataclass

# Deterministic inspect/status actions that should not spend reasoning tokens.
SIMPLE_ACTIONS: dict[str, frozenset[str]] = {
    "filesystem": frozenset(
        {"read", "list", "stat", "hash", "search", "compare", "recent", "exists"}
    ),
    "git": frozenset({"status", "diff", "log", "branch"}),
    "terminal": frozenset({"inspect"}),
    "docker": frozenset({"ps", "images"}),
    "web_fetch": frozenset({"get"}),
}

COMPLEX_TASK_CLASSES = frozenset(
    {
        "software engineering",
        "system administration",
        "long-horizon autonomous",
        "windows gui",
        "multimodal",
    }
)


@dataclass(frozen=True)
class ThinkingDecision:
    enabled: bool
    reason: str


def should_think(
    *,
    profile_thinking: bool,
    execution_mode: str = "balanced",
    force_final: bool = False,
    verifying: bool = False,
    tools_used: bool = False,
    consecutive_failures: int = 0,
    last_tool: str = "",
    last_action: str = "",
    awaiting_plan_selection: bool = False,
    critic_pending: bool = False,
    task_class: str = "",
) -> ThinkingDecision:
    """Selective reasoning: spend thinking tokens only when they change the next action.

    Profile `thinking=False` (Fast) is a hard ceiling. Balanced/Quality keep the
    llama.cpp reasoning parser available and toggle `enable_thinking` per request.
    """
    if force_final:
        return ThinkingDecision(False, "final report")
    if not profile_thinking:
        return ThinkingDecision(False, "profile thinking off")

    mode = (execution_mode or "balanced").strip().lower()
    task = (task_class or "").strip().lower()

    if not tools_used or awaiting_plan_selection:
        return ThinkingDecision(True, "planning")
    if critic_pending:
        return ThinkingDecision(True, "critic pass")
    if consecutive_failures >= 1:
        return ThinkingDecision(True, "recovery after failure")

    if verifying:
        if mode == "reliable":
            return ThinkingDecision(True, "consequential verification")
        return ThinkingDecision(False, "routine verification")

    if _is_simple_followup(last_tool, last_action) and consecutive_failures == 0:
        return ThinkingDecision(False, "deterministic tool follow-up")

    if task in COMPLEX_TASK_CLASSES:
        return ThinkingDecision(True, "complex task class")

    if mode == "reliable":
        return ThinkingDecision(True, "reliable mode")
    if mode == "fast":
        return ThinkingDecision(False, "fast execution")

    return ThinkingDecision(False, "routine tool step")


def _is_simple_followup(tool: str, action: str) -> bool:
    allowed = SIMPLE_ACTIONS.get((tool or "").strip().lower())
    if not allowed:
        return False
    act = (action or "").strip().lower()
    if not act:
        return True
    return act in allowed
