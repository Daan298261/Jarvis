"""Goal Runtime public package (thin facade; RFC-0016 owns full lifecycle)."""

from __future__ import annotations

from .runtime import suggest_skills_for_goal

__all__ = ["suggest_skills_for_goal"]
