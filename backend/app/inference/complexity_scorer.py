"""RFC-0115 deterministic question complexity baseline (rules before Ornith)."""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from ..agent.escalation import looks_like_architecture, user_requested_expert

_TIER4_MARKERS = (
    "large refactor",
    "refactor the whole",
    "security analysis",
    "difficult security",
    "highest quality",
    "expert model",
    "maximum quality",
)
_TIER3_MARKERS = (
    "architecture",
    "system design",
    "debugging",
    "spanning subsystems",
    "coding plan",
    "long-context",
    "ambiguous technical",
    "across multiple sources",
    "refactor",
    "pytest",
    "unit test",
)
_CAPABILITIES_PROMPT = re.compile(
    r"(?i)\b(capabilit(y|ies)|implementation status|fully implemented|half.?baked|what(?:'s| is) working)\b",
)
_SYSTEM_INSPECTION = re.compile(
    r"(?i)\b(jarvis|codebase|repository|source code|current state of|how much of)\b",
)
_TIER1_MARKERS = (
    "what time",
    "weather",
    "hello",
    "hi ",
    "thanks",
    "thank you",
    "schedule",
    "remind me",
)
_SIMPLE_UI = re.compile(r"(?i)\b(open|close|show|hide)\s+(notepad|folder|file|settings)\b")


@dataclass
class ComplexityResult:
    tier: int
    minimum_answer_tier: int
    hard_rule: bool
    signals: list[str] = field(default_factory=list)
    prefer_tool: bool = False
    task_class_hint: str = ""

    def as_dict(self) -> dict:
        return {
            "tier": self.tier,
            "minimum_answer_tier": self.minimum_answer_tier,
            "hard_rule": self.hard_rule,
            "signals": list(self.signals),
            "prefer_tool": self.prefer_tool,
            "task_class_hint": self.task_class_hint,
        }


def score_question_complexity(
    user_message: str,
    *,
    task_class: str = "",
    recent_turn_count: int = 0,
    vision_requested: bool = False,
    prior_failures: int = 0,
) -> ComplexityResult:
    text = (user_message or "").strip()
    lowered = text.lower()
    signals: list[str] = []
    tier = 1
    hard = False
    prefer_tool = False
    task_hint = ""

    if not text:
        return ComplexityResult(tier=1, minimum_answer_tier=0, hard_rule=False, signals=["empty"])

    if user_requested_expert(text) or any(m in lowered for m in _TIER4_MARKERS):
        tier = 4
        hard = True
        signals.append("expert-intent")
    elif prior_failures >= 2:
        tier = max(tier, 4)
        hard = True
        signals.append("repeated-failure")
    elif looks_like_architecture(text, task_class) or any(m in lowered for m in _TIER3_MARKERS):
        tier = 3
        hard = True
        signals.append("architecture-or-complex")
    elif _CAPABILITIES_PROMPT.search(text) and _SYSTEM_INSPECTION.search(text):
        tier = 2
        hard = True
        prefer_tool = True
        task_hint = "system-inspection"
        signals.append("capabilities-grounding")
    elif vision_requested or "screenshot" in lowered:
        tier = max(tier, 2)
        hard = True
        prefer_tool = True
        signals.append("vision-or-screenshot")
    elif len(text) > 1200 or recent_turn_count > 12:
        tier = max(tier, 3)
        hard = True
        signals.append("long-context-pressure")
    elif len(text) > 280 or "?" in text and len(text) > 80:
        tier = max(tier, 2)
        signals.append("explanatory-question")
    elif any(m in lowered for m in _TIER1_MARKERS) or _SIMPLE_UI.search(text):
        tier = 1
        signals.append("trivial")
    else:
        tier = 2
        signals.append("default-general")

    minimum = tier if hard and tier >= 2 else 0
    return ComplexityResult(
        tier=tier,
        minimum_answer_tier=minimum,
        hard_rule=hard,
        signals=signals,
        prefer_tool=prefer_tool,
        task_class_hint=task_hint,
    )
