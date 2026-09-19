"""Backward-compatible re-exports; prefer ``app.agent.background_verify``."""

from __future__ import annotations

from ..agent.background_verify import (
    materially_different,
    schedule_background_verification,
    verify_reply,
)

__all__ = ["materially_different", "schedule_background_verification", "verify_reply"]
