"""One-shot HexStrike suite load overview (RFC-0119). Product-level copy only."""
from __future__ import annotations

from .chat_delivery import publish_owner_text

HEXSTRIKE_LOAD_OVERVIEW = (
    "HexStrike is Jarvis's embedded operator suite for security tooling on this PC. "
    "When it is loaded I can install and repair the local HexStrike runtime, show which tools "
    "are available, run the operator jobs you ask for, and bring logs and artifacts back into "
    "Daybreak and this chat. It binds to loopback only. "
    "I will not walk through exploits, payloads, or attack steps."
)

_overview_published_for_pid: int | None = None


def reset_hexstrike_overview_state() -> None:
    global _overview_published_for_pid
    _overview_published_for_pid = None


async def maybe_publish_hexstrike_load_overview(*, process_pid: int | None) -> bool:
    """Publish the canned overview once per successful suite process start."""
    global _overview_published_for_pid
    if process_pid is None:
        return False
    if _overview_published_for_pid == process_pid:
        return False
    _overview_published_for_pid = process_pid
    await publish_owner_text(
        HEXSTRIKE_LOAD_OVERVIEW,
        title="HexStrike",
        kind="hexstrike_overview",
        source="hexstrike_suite",
        speak=True,
    )
    return True
