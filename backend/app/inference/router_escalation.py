"""RFC-0115 placeholder: model escalation when context capacity is insufficient."""

from __future__ import annotations

from typing import Any

from ..config import AppSettings
from .profiles import ModelProfile
from .prompt_budget import PromptBudget


async def escalate_for_context_capacity(
    settings: AppSettings,
    profile: ModelProfile,
    budget: PromptBudget,
) -> bool:
    """Return True when a stronger/eligible model was activated (RFC-0115 implements routing)."""
    _ = (settings, profile, budget)
    return False
