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


_APOSTROPHES = str.maketrans({"\u2019": "'", "\u2018": "'", "\u02bc": "'", "\uff07": "'"})


def own_words(text: str) -> str:
    """The owner's own words: quotes, `>` quotes and code removed; smart apostrophes made plain."""
    # Quotes are stripped first so a ‘quoted’ span still counts as quoted, then phone
    # keyboards' ’ becomes ' so "I’m back" reads as "I'm back".
    return _QUOTED.sub(" ", text or "").translate(_APOSTROPHES)


def away_intent(text: str) -> str:
    """'activate', 'deactivate' or '' for the owner's own words; quoted text never counts."""
    own = own_words(text)
    if any(p.search(own) for p in _DEACTIVATE):
        return "deactivate"
    if any(p.search(own) for p in _ACTIVATE):
        return "activate"
    return ""


_REORDER = re.compile(r"\b(?:next|first|last|top|bottom|move|up|down|before|after|earlier|later|sooner|reorder|priorit\w*|deprioritis\w*|deprioritiz\w*)\b", re.I)
_UNDO = re.compile(r"\b(?:undo|revert|put (?:it|that|them) back)\b", re.I)
_QUEUE = re.compile(r"\b(?:queue|add|schedule|develop|implement|work on|pick up|build)\b", re.I)
_UNQUEUE = re.compile(r"\b(?:unqueue|dequeue|remove|drop|skip|cancel|take .* off)\b", re.I)
_RUN = re.compile(r"\b(?:run|start|launch|kick off|begin)\b", re.I)
_RUN_OBJECT = re.compile(r"\b(?:mission|development|self[- ]?dev\w*|rfc|ticket|task|scheduler)\b", re.I)
_CONFIGURE = re.compile(r"\b(?:set|change|switch|use|configure|enable|disable|turn (?:on|off)|every|interval)\b", re.I)
# Settings only the Self-development page may change: releasing Grokbot's reservation must be
# explicit (or come from a trusted lease coordinator), and repointing the repository is not a
# chat-level change.
_PAGE_ONLY = {"resource_hold": "the reservation", "repo": "the repository"}


# Settings chat may change, each tied to the owner's words for that exact key and value. Every
# other DevelopmentConfig field (failure_limit, max_repairs, base_ref, review_model, run and CI
# limits, Ollama URL, Drive tools) belongs to the Self-development page; failure_limit and
# max_repairs guard the failure breaker, so a chat request can never lift a tripped breaker.
_CHAT_SETTINGS = ("enabled", "interval_minutes", "coder_model", "vision_model")
_SCHEDULER = r"(?:self[- ]?dev\w*|(?:the\s+)?(?:development|dev)\s+scheduler|scheduler|self[- ]?development)"
_ENABLE = re.compile(rf"\b(?:enable|turn\s+on|switch\s+on|activate|resume|start)\s+(?:the\s+|my\s+|your\s+)?{_SCHEDULER}", re.I)
_DISABLE = re.compile(rf"\b(?:disable|turn\s+off|switch\s+off|deactivate|pause|stop)\s+(?:the\s+|my\s+|your\s+)?{_SCHEDULER}", re.I)
_ROLE = {"coder_model": re.compile(r"\bcod(?:er|ing)\b", re.I), "vision_model": re.compile(r"\bvision\b", re.I)}
# A model name ends at whitespace or sentence punctuation; tags, versions and quant suffixes are part of it.
_NAME_EDGE = r"[\w.:/@+-]"


def whole_number(own: str, number: int) -> bool:
    return bool(re.search(rf"(?<![\w.,]){int(number)}(?![\w]|[.,]\d)", own))


def asked_setting(own: str, key: str, value: Any) -> bool:
    """True when the owner's own words ask for exactly ``key = value``."""
    if key == "enabled":
        if not isinstance(value, bool):
            return False
        on, off = bool(_ENABLE.search(own)), bool(_DISABLE.search(own))
        return (on and not off) if value else (off and not on)
    if key == "interval_minutes":
        if isinstance(value, bool) or not isinstance(value, int):
            return False
        n = int(value)
        near_interval = re.search(rf"\b(?:interval|every)\b[^.\n]{{0,30}}?(?<![\w.,]){n}(?![\w]|[.,]\d)\s*(?:minutes?|mins?|m)?\b", own, re.I)
        as_minutes = re.search(rf"(?<![\w.,]){n}\s*(?:minutes?|mins?)\b", own, re.I)
        return bool(near_interval or (as_minutes and re.search(r"\b(?:interval|every)\b", own, re.I)))
    if key in _ROLE:
        if not isinstance(value, str) or not value.strip():
            return False
        exact = re.compile(rf"(?<!{_NAME_EDGE}){re.escape(value.strip())}(?!{_NAME_EDGE})", re.I)
        if not exact.search(own):
            return False
        rest = exact.sub(" ", own)  # "qwen3-coder" must not count as naming the coder role
        other = "vision_model" if key == "coder_model" else "coder_model"
        return bool(_ROLE[key].search(rest)) and not _ROLE[other].search(rest)
    return False


def undo_target(own: str, moved: list[dict[str, Any]]) -> bool:
    """The owner's undo names this reorder: one of its moved tasks, or the upcoming list's last reorder."""
    if any(mentions_item(own, item) for item in moved):
        return True
    return bool(re.search(r"\b(?:undo|revert)\s+(?:my|the|that|your)\s+(?:last\s+|latest\s+)?(?:reorder\w*|re-order\w*|move|pin)\b", own, re.I)
                or re.search(r"\bupcoming\s+(?:list|order|tasks)\b", own, re.I))


def mentions_item(own: str, item: dict[str, Any] | None) -> bool:
    if not item:
        return False
    lowered = own.lower()
    if item.get("id") and item["id"].lower() in lowered:
        return True
    number = item.get("rfc") or ""
    if not number:
        found = re.search(r"\brfc[-_ ]?0*(\d{1,5})\b", f"{item.get('title', '')} {item.get('path', '')}", re.I)
        number = found.group(1) if found else ""
    if number and re.search(rf"(?:\brfc[-_ ]?|#)0*{int(number)}\b", lowered):
        return True
    title = (item.get("title") or "").strip().lower()
    return len(title) >= 4 and title in lowered


def owner_asked(text: str, action: str, *, item: dict[str, Any] | None = None, changes: dict[str, Any] | None = None,
                moved: list[dict[str, Any]] | None = None) -> str:
    """'' when the owner's own message asks for ``action``; otherwise why it does not count.

    Owner authority comes only from the owner's own words (or the Self-development page),
    never from a model argument, an RFC, or tool output.
    """
    own = own_words(text)
    if action == "move":
        ok = bool(_REORDER.search(own)) and mentions_item(own, item)
        return "" if ok else "Reordering as you needs your own request naming that task (for example \"do RFC-0211 next\"), or a drag in the Upcoming list"
    if action == "undo":
        ok = bool(_UNDO.search(own)) and undo_target(own, moved or [])
        return "" if ok else "Undoing your order needs your own request naming that reorder or task (for example \"undo moving RFC-0211 to the top\"), or the Undo button in the Upcoming list"
    if action == "queue":
        return "" if _QUEUE.search(own) and mentions_item(own, item) else "Queueing a ticket needs your own request naming it, or the Self-development page"
    if action == "unqueue":
        return "" if _UNQUEUE.search(own) and mentions_item(own, item) else "Removing a queued ticket needs your own request naming it, or the Self-development page"
    if action == "run":
        # The owner names the exact task that would start (id, RFC number or title), like N2's undo.
        ok = bool(_RUN.search(own)) and mentions_item(own, item)
        return "" if ok else "Starting a development mission needs your own request naming that task (for example \"start RFC-0211\"), or Run in Self-development"
    if action == "configure":
        changes = changes or {}
        for key, label in _PAGE_ONLY.items():
            if key in changes:
                return f"Change {label} on the Self-development page"
        if not changes:
            return "Nothing to change"
        if not _CONFIGURE.search(own):
            return "Changing the scheduler settings needs your own request, or the Self-development page"
        for key, value in changes.items():
            if not asked_setting(own, key, value):
                return f"Your message does not ask for {key} = {json.dumps(value)}"
        return ""
    return "Unknown control"


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
        "latest reorder. scan/queue/unqueue/run/stop/configure manage individual RFC revisions. Acting as the owner "
        "(actor=owner, queue, unqueue, run, configure) works only when the owner's own latest message asks for that "
        "exact change; run starts the next queued task (or item_id) only when the owner's message names that task by "
        "id, RFC number or title. The reservation and repository can only be changed on the Self-development page."
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
        from ..agent.development_queue import moved_items as q_moved, next_eligible
        from ..agent.development_scheduler import DEVELOPMENT, DevelopmentConfig
        # A worker cannot recursively schedule more workers from an RFC/tool result.
        if os.environ.get("ANZU_DEVELOPMENT_MISSION"):
            return ToolResult(False, "", error="Development missions cannot control the owner's scheduler")
        try:
            if actor not in {"owner", "anzu"}:
                raise ValueError("actor must be owner or anzu")
            needs_owner = action in {"away_on", "away_off", "queue", "unqueue", "run", "configure"} or (action in {"move", "undo"} and actor == "owner")
            owner_text = ""
            if needs_owner:
                if not _task_id:
                    raise ValueError("This control needs the owner's own request in chat or the Self-development page")
                owner_text = await latest_owner_message(_task_id)
            if action in {"away_on", "away_off"}:
                wanted = "activate" if action == "away_on" else "deactivate"
                if away_intent(owner_text) != wanted:
                    raise ValueError("Away Mode changes only when you ask directly in your own message or use the Away Mode switch")
            elif needs_owner:
                current = DEVELOPMENT.state()
                item = current["items"].get(item_id) if item_id else None
                if action in {"queue", "unqueue", "move", "run"} and item_id and item is None:
                    raise ValueError("Unknown task")
                if action == "run" and not item_id:
                    # The task Run would start: the next owner-queued, eligible one.
                    item = next_eligible(current, automatic=False)[0]
                changes = None
                if action == "configure":
                    unknown = sorted(set(config or {}) - set(_CHAT_SETTINGS) - set(_PAGE_ONLY))
                    if unknown:
                        raise ValueError(f"{', '.join(unknown)} can only be changed on the Self-development page")
                    changes = {k: v for k, v in (config or {}).items() if current["config"].get(k) != v}
                moved = None
                if action == "undo":
                    entry = next((h for h in current.get("queue_history", []) if h.get("id") == history_id), None)
                    if entry is None:
                        raise ValueError("That change is no longer in the history")
                    moved_ids = entry.get("pinned") or sorted(q_moved(entry.get("before", []), entry.get("after", [])))
                    moved = [current["items"][i] for i in moved_ids if i in current["items"]]
                refusal = owner_asked(owner_text, action, item=item, changes=changes, moved=moved)
                if refusal:
                    raise ValueError(refusal)
            if action == "status": result = DEVELOPMENT.public()
            elif action == "scan": result = await DEVELOPMENT.scan()
            elif action in {"queue", "unqueue"}: result = await DEVELOPMENT.select(item_id, revision, action == "queue")
            elif action == "run":
                await DEVELOPMENT.scan()
                # Bound to the task the owner named; launch refuses if the queue moved in between.
                result = await DEVELOPMENT.launch(expected=item["id"])
            elif action == "stop": result = await DEVELOPMENT.stop()
            elif action == "configure":
                # A chat change never clears the failure breaker; that is the page's explicit resume.
                result = await DEVELOPMENT.configure(DevelopmentConfig.model_validate({**DEVELOPMENT.state()["config"], **(config or {})}), resume=False)
            elif action in {"away_on", "away_off"}:
                result = await DEVELOPMENT.set_away(action == "away_on", actor="owner", reason="You said you are back")
            elif action == "upcoming":
                result = DEVELOPMENT.queue_view(DEVELOPMENT.state())
            elif action in {"move", "undo"}:
                if expected_revision is None:
                    raise ValueError("Read the upcoming list first and pass its revision as expected_revision")
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
