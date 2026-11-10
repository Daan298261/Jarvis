"""ANZU chat controls for the owner's local development scheduler (RFC-0211)."""
from __future__ import annotations

import json
import os
import re
from typing import Any

from .base import RiskLevel, Tool, ToolResult

_QUOTED = re.compile(r"```.*?```|`[^`]*`|\"[^\"]*\"|“[^”]*”|‘[^’]*’|(?<!\w)'[^\n]*?'(?!\w)|^[ \t]*>[^\n]*$", re.S | re.M)
_ACTIVATE = (
    re.compile(r"\b(?:i'?m|i am|im)\s+(?:afk|away)\b.*\bdevelop\s+(?:yourself|anzu)\b", re.I | re.S),
    re.compile(r"\b(?:turn on|enable|start|activate|switch on)\s+(?:the\s+)?away\s+mode\b", re.I),
)
_DEACTIVATE = (
    re.compile(r"\b(?:i'?m|i am|im)\s+back\b", re.I),
    re.compile(r"\bstop\s+developing\b", re.I),
    re.compile(r"\b(?:turn off|disable|stop|deactivate|switch off|end)\s+(?:the\s+)?away\s+mode\b", re.I),
)


def away_intent(text: str) -> str:
    """'activate', 'deactivate' or '' for the owner's own words; quoted text never counts."""
    own = _QUOTED.sub(" ", text or "")
    if any(p.search(own) for p in _DEACTIVATE):
        return "deactivate"
    if any(p.search(own) for p in _ACTIVATE):
        return "activate"
    return ""


async def latest_owner_message(task_id: str) -> str:
    """The owner's latest message in this task, never tool output or agent instructions."""
    from ..agent.compaction import deserialize_messages
    from ..db.models import Task
    from ..db.session import SessionLocal

    async with SessionLocal() as session:
        task = await session.get(Task, task_id)
    if task is None:
        return ""
    for message in reversed(deserialize_messages(task.conversation_json)):
        if message.role == "user" and message.audience != "internal" and isinstance(message.content, str):
            return message.content
        if message.role == "user" and isinstance(message.content, list) and message.audience != "internal":
            return "\n".join(part.get("text", "") for part in message.content if part.get("type") == "text")
    return task.prompt


class SelfDevelopmentTool(Tool):
    name = "self_development"
    description = (
        "Control ANZU's self-development scheduler. away_on / away_off switch Away Mode (develop ANZU) and only work "
        "when the owner directly asked in their own message (\"I'm AFK, go develop yourself\" / \"I'm back\"). "
        "upcoming shows the active task and the ordered upcoming list; move reorders it (owner instructions such as "
        "\"do this next\" use actor=owner; your own re-prioritisation uses actor=anzu with a reason); undo reverts the "
        "latest reorder. scan/queue/unqueue/run/stop/configure manage individual RFC revisions."
    )
    risk = RiskLevel.MEDIUM
    parameters = {"type": "object", "properties": {
        "action": {"type": "string", "enum": ["status", "scan", "queue", "unqueue", "run", "stop", "configure", "away_on", "away_off", "upcoming", "move", "undo"]},
        "item_id": {"type": "string"}, "revision": {"type": "string"},
        "position": {"type": "integer", "description": "Target index in the upcoming list for move (0 = next)"},
        "actor": {"type": "string", "enum": ["owner", "anzu"]},
        "reason": {"type": "string"},
        "history_id": {"type": "string"},
        "expected_revision": {"type": "integer", "description": "Upcoming-list revision from the last upcoming/status result"},
        "config": {"type": "object", "properties": {"enabled": {"type": "boolean"}, "resource_hold": {"type": "string"}, "repo": {"type": "string"}, "interval_minutes": {"type": "integer"}, "coder_model": {"type": "string"}, "vision_model": {"type": "string"}}},
    }, "required": ["action"]}

    async def execute(self, action: str, item_id: str = "", revision: str = "", config: dict[str, Any] | None = None,
                      position: int | None = None, actor: str = "anzu", reason: str = "", history_id: str = "",
                      expected_revision: int | None = None, _task_id: str | None = None, **_: Any):
        from ..agent.development_scheduler import DEVELOPMENT, DevelopmentConfig
        # A worker cannot recursively schedule more workers from an RFC/tool result.
        if os.environ.get("ANZU_DEVELOPMENT_MISSION"):
            return ToolResult(False, "", error="Development missions cannot control the owner's scheduler")
        try:
            needs_owner = action in {"away_on", "away_off"} or (action in {"move", "undo"} and actor == "owner")
            if needs_owner:
                if not _task_id:
                    raise ValueError("This control needs the owner's own request in chat or the switch in Self-development")
            if action in {"away_on", "away_off"}:
                wanted = "activate" if action == "away_on" else "deactivate"
                if away_intent(await latest_owner_message(_task_id)) != wanted:
                    raise ValueError("Away Mode changes only when you ask directly in your own message or use the Away Mode switch")
            if action == "status": result = DEVELOPMENT.public()
            elif action == "scan": result = await DEVELOPMENT.scan()
            elif action in {"queue", "unqueue"}: result = await DEVELOPMENT.select(item_id, revision, action == "queue")
            elif action == "run":
                await DEVELOPMENT.scan()
                result = await DEVELOPMENT.launch()
            elif action == "stop": result = await DEVELOPMENT.stop()
            elif action == "configure":
                result = await DEVELOPMENT.configure(DevelopmentConfig.model_validate({**DEVELOPMENT.state()["config"], **(config or {})}))
            elif action in {"away_on", "away_off"}:
                result = await DEVELOPMENT.set_away(action == "away_on", actor="owner", reason="You said you are back")
            elif action == "upcoming":
                result = DEVELOPMENT.queue_view(DEVELOPMENT.state())
            elif action in {"move", "undo"}:
                if expected_revision is None:
                    raise ValueError("Read the upcoming list first and pass its revision as expected_revision")
                if actor not in {"owner", "anzu"}:
                    raise ValueError("actor must be owner or anzu")
                if action == "move":
                    if position is None:
                        raise ValueError("position is required to move a task")
                    result = await DEVELOPMENT.move(item_id, to=position, expected_revision=expected_revision, actor=actor, reason=reason)
                else:
                    result = await DEVELOPMENT.undo(history_id, expected_revision=expected_revision, actor=actor)
            else: raise ValueError("Unknown scheduler action")
            return ToolResult(True, json.dumps(result, ensure_ascii=False, default=str), data=result)
        except (ValueError, RuntimeError) as exc:
            return ToolResult(False, "", error=str(exc))
