"""Local fallbacks and Jev composition rules (RFC-0116)."""

from __future__ import annotations

import re
from typing import Iterable

_COMPLEX_HINTS = re.compile(
    r"(?i)\b("
    r"architect|refactor|distributed|migrate|security review|hexstrike|"
    r"implement|debug|traceback|multi-file|production incident"
    r")\b",
)
_EXPERT_HINTS = re.compile(
    r"(?i)\b("
    r"exploit|red team|kernel|formal proof|compiler|consensus protocol|"
    r"high.?consequence|destroy|wipe cluster"
    r")\b",
)
_BASIC_HINTS = re.compile(
    r"(?i)\b(hello|hi\b|hey\b|thanks|thank you|what time|weather|joke)\b",
)


def local_complexity_tier(prompt: str) -> int:
    text = (prompt or "").strip()
    if not text:
        return 1
    if _EXPERT_HINTS.search(text) or len(text) > 4000:
        return 4
    if _COMPLEX_HINTS.search(text) or len(text) > 1200:
        return 3
    if _BASIC_HINTS.search(text) and len(text) < 160:
        return 1
    return 2


def apply_complexity_tier(local_tier: int, jev_score: float | None) -> int:
    """Jev may raise a hard-rule tier. It must almost never lower one."""
    baseline = max(1, min(4, int(local_tier or 1)))
    if jev_score is None:
        return baseline
    raised = max(1, min(4, int(round(float(jev_score)))))
    return max(baseline, raised)


def should_escalate(
    local_escalate: bool,
    jev_noul: float | None,
    *,
    confidence: float | None = None,
    threshold: float = 0.7,
) -> bool:
    if local_escalate:
        return True
    if jev_noul is None:
        return False
    if confidence is not None and confidence < 0.45:
        return True
    return float(jev_noul) >= threshold


def approval_popup_required(
    *,
    policy_requires: bool,
    policy_deny: bool,
    jev_noul: float | None = None,
    confidence: float | None = None,
) -> bool:
    """Deterministic deny wins. Required RFC-0110 popup cannot be skipped. Low-confidence Jev asks."""
    if policy_deny:
        return False
    if policy_requires:
        return True
    if jev_noul is None:
        return False
    if confidence is not None and confidence < 0.5:
        return True
    return float(jev_noul) >= 0.5


def rerank_tools(prompt: str, candidates: Iterable[str]) -> list[str]:
    local = [name for name in candidates if name]
    if not local:
        return []
    from .surfaces import answer_value, privacy_for_tier, select_tools
    from .tier import resolve_status

    status = resolve_status()
    result = select_tools(
        user_message=prompt,
        candidates=local,
        privacy=privacy_for_tier(str(status.get("decision_tier") or "local")),
    )
    selected = answer_value(result, "tool_select")
    if not selected or selected == "none" or selected not in local:
        return local
    return [selected, *[name for name in local if name != selected]]
