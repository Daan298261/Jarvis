"""Blue-team watcher: revoke/rollback when a tool outcome is clearly bad."""

from __future__ import annotations

import logging
from typing import Any

from ..tools.safety import is_destructive_operation

log = logging.getLogger("jarvis.security.blue_watch")

_RECENT: list[dict[str, Any]] = []


def note_tool_outcome(
    task_id: str,
    tool: str,
    arguments: dict[str, Any] | None,
    observation: str,
    *,
    failed: bool,
) -> dict[str, Any] | None:
    """If a destructive step failed or reports damage, request rollback."""
    args = arguments or {}
    command = str(args.get("command") or "")
    destructive = is_destructive_operation(tool, args, command)
    text = (observation or "").lower()
    damaged = (failed and destructive) or ("access denied" in text and destructive)
    if not damaged:
        return None
    event = {
        "task_id": task_id,
        "tool": tool,
        "failed": failed,
        "destructive": destructive,
        "action": "rollback_requested",
        "detail": (observation or "")[:400],
    }
    _RECENT.append(event)
    del _RECENT[:-20]
    log.warning("blue watcher rollback requested for task %s tool %s", task_id, tool)
    return event


def recent_events() -> list[dict[str, Any]]:
    return list(_RECENT)
