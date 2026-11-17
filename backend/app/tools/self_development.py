"""ANZU chat controls for the owner's local development scheduler (RFC-0211)."""
from __future__ import annotations

import hashlib
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
# Configure fails closed (CoS ruling): any negation or retraction word anywhere in the owner's own
# words refuses every setting change in that message. Matched on normalized text (lower case,
# apostrophes dropped so "don't"/"don’t"/"dont" are one word, other punctuation as spaces).
_RETRACTION = re.compile(
    r"\b(?:not|never|no|nope|nah|cannot|"
    r"dont|doesnt|didnt|wont|wouldnt|cant|couldnt|shouldnt|isnt|arent|wasnt|werent|havent|hasnt|hadnt|"
    r"mustnt|neednt|mightnt|shant|aint|"
    r"actually|kidding|jk|nvm|nm|cancel\w*|stop\w*|nevermind|never\s+mind|scratch\s+that|forget\s+it|wait\w*|"
    r"hold\s+off|hold\s+on|hang\s+on|one\s+sec\w*|on\s+second\s+thoughts?|second\s+thoughts?|ignore\s+that|"
    r"disregard\w*|belay\w*|leave\s+it|maybe\s+later|later|undo\w*|instead|rather)\b")
# Apostrophe-like marks people type for "don't" (', ’, ‘, ´ on NL/DE keyboards, `, ′, ʹ, ʻ, ʼ, ＇).
_APOSTROPHE_MARKS = "'\u2019\u2018\u00b4`\u2032\u02b9\u02bb\u02bc\uff07"
# The interval number must be the object of the interval phrase: "interval to 15", "interval of
# 15 minutes", "interval: 15 min", "make the interval 15", "every 15 minutes".
_MINUTE_UNIT = r"(?:minutes?|minuten|minuut|mins?|m)"
_INTERVAL_VALUE = re.compile(
    r"\binterval\s*(?:(?:to|of|at|is|=|:)\s*|be\s+|should\s+be\s+)?(?<![\w.,])(\d+)(?![.,]\d)"
    # H4: only a minute unit may follow the number (an allowlist); any other word after it
    # ("15 weeks", "15 ms", "15 uur") is not read as minutes.
    rf"(?:\s*{_MINUTE_UNIT}\b|(?!\s*[^\W\d_]|\d))"
    rf"|\bevery\s+(?<![\w.,])(\d+)\s*{_MINUTE_UNIT}\b", re.I)
# Every number in the request, with an optional unit ("15m", "15 min", "2 hours") so the unit
# forms _INTERVAL_VALUE accepts count as that one number.
_NUMBER = re.compile(r"(?<![\w.,])(\d+(?:[.,]\d+)?)(?:\s*(?:minutes?|mins?|m|hours?|hrs?|h)\b)?(?![\w])", re.I)
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
        matches = [(True, m) for m in _ENABLE.finditer(own)] + [(False, m) for m in _DISABLE.finditer(own)]
        if not matches:
            return False
        directions = {direction for direction, _ in matches}
        return directions == {value}
    if key == "interval_minutes":
        if isinstance(value, bool) or not isinstance(value, int):
            return False
        bound = {int(next(g for g in m.groups() if g)) for m in _INTERVAL_VALUE.finditer(own)}
        numbers = {n.group(1) for n in _NUMBER.finditer(own)}
        # Exactly one number in the request, and it is the interval's: two numbers or a number
        # tied to something else ("run for 30 minutes, keep the interval") is ambiguous.
        return bound == {int(value)} and len(numbers) == 1
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


def retraction(text: str) -> str:
    """The first negation or retraction word anywhere in ``text``, or ''.

    Run on the owner's RAW message (H1): quotes, code and ``>`` lines are not stripped, so a
    "don't" the owner quoted or set in code still refuses. Every apostrophe variant is dropped
    and "do n't" / "don t" are joined (H2) before matching.
    """
    lowered = (text or "").lower()
    for mark in _APOSTROPHE_MARKS:
        lowered = lowered.replace(mark, "")
    lowered = re.sub(r"\b(\w+?)\s+nt\b", r"\1nt", lowered)   # "do nt" -> "dont"
    lowered = re.sub(r"\b(\w+n)\s+t\b", r"\1t", lowered)     # "don t" -> "dont"
    normalized = re.sub(r"\s+", " ", re.sub(r"[^a-z0-9\s]", " ", lowered))
    found = _RETRACTION.search(normalized)
    return found.group(0) if found else ""


def retraction_refusal(text: str) -> str:
    word = retraction(text)
    if not word:
        return ""
    return (f"Your message includes \"{word}\", so I won't change the scheduler from it. Send the change as a plain "
            "request (for example \"enable the self-development scheduler\"), or use the Self-development page")


# ---- Owner approval (CoS ruling): consent is the owner's tap on the ApprovalGrant card -----------
# Every chat-initiated scheduler change parks an RFC-0031 approval whose target is the hash of the
# exact change shown on the card; the tool acts only with a matching, unexpired, unused grant.
APPROVAL_ACTIONS = frozenset({"configure", "run", "move", "queue", "unqueue", "undo"})


def pending_change(arguments: dict[str, Any]) -> dict[str, Any] | None:
    """The exact change a chat call would make, resolved against the current scheduler state.

    ``None`` when the call is incomplete or not a chat-allowed change (the tool then refuses
    with its own reason, and no approval card is shown).
    """
    from ..agent.development_queue import moved_items, next_eligible
    from ..agent.development_scheduler import DEVELOPMENT

    args = arguments if isinstance(arguments, dict) else {}
    action = str(args.get("action") or "")
    if action not in APPROVAL_ACTIONS:
        return None
    state = DEVELOPMENT.state()

    def item_ref(item_id):
        item = state["items"].get(item_id or "")
        return {"item_id": item["id"], "title": item.get("title", "")} if item else None

    if action == "configure":
        config = args.get("config")
        if not isinstance(config, dict) or not config or set(config) - set(_CHAT_SETTINGS):
            return None
        changes = {k: [state["config"].get(k), v] for k, v in sorted(config.items()) if state["config"].get(k) != v}
        return {"action": action, "set": changes} if changes else None
    if action == "run":
        item = state["items"].get(args.get("item_id") or "") if args.get("item_id") else next_eligible(state, automatic=False)[0]
        return {"action": action, **item_ref(item["id"]), "revision": item.get("revision", "")} if item else None
    if action in {"queue", "unqueue"}:
        ref = item_ref(args.get("item_id"))
        return {"action": action, **ref, "revision": str(args.get("revision") or "")} if ref else None
    expected = args.get("expected_revision")
    if not isinstance(expected, int) or isinstance(expected, bool):
        return None
    actor = str(args.get("actor") or "anzu")
    if action == "move":
        ref, position = item_ref(args.get("item_id")), args.get("position")
        if not ref or not isinstance(position, int) or isinstance(position, bool):
            return None
        return {"action": action, **ref, "to": position, "actor": actor, "queue_revision": expected}
    entry = next((h for h in state.get("queue_history", []) if h.get("id") == args.get("history_id")), None)
    if not entry:
        return None
    moved = entry.get("pinned") or sorted(moved_items(entry.get("before", []), entry.get("after", [])))
    return {"action": action, "history_id": entry["id"], "actor": actor, "queue_revision": expected,
            "moved": [{"item_id": i, "title": state["items"].get(i, {}).get("title", "")} for i in moved]}


def approval_target(change: dict[str, Any]) -> str:
    return hashlib.sha256(json.dumps(change, sort_keys=True, separators=(",", ":"), default=str).encode()).hexdigest()


def describe_change(change: dict[str, Any]) -> str:
    """What the owner's tap approves, in words, for the existing approval card (desktop and phone)."""
    action = change["action"]
    task = f"{change.get('item_id', '')} \u2014 {change.get('title', '')}".strip(" \u2014")
    if action == "configure":
        parts = []
        for key, (old, new) in change["set"].items():
            if key == "enabled":
                parts.append("turn the self-development scheduler " + ("on" if new else "off"))
            else:
                parts.append(f"change {key} from {json.dumps(old)} to {json.dumps(new)}")
        return "Self-development: " + "; ".join(parts)
    if action == "run":
        return f"Self-development: start a development mission for {task} (revision {change.get('revision', '')})"
    if action == "queue":
        return f"Self-development: queue {task} (revision {change.get('revision', '')})"
    if action == "unqueue":
        return f"Self-development: remove {task} from the queue"
    who = "as you" if change.get("actor") == "owner" else "as ANZU"
    if action == "move":
        return f"Self-development: move {task} to position {change['to'] + 1} of the upcoming list ({who})"
    moved = ", ".join(f"{m['item_id']} \u2014 {m['title']}" for m in change.get("moved", [])) or "no tasks"
    return f"Self-development: undo the upcoming-list change {change['history_id']} ({who}; it moved {moved})"


async def spend_approval(change: dict[str, Any], task_id: str | None, grant_id: str | None) -> None:
    """Raise unless ``grant_id`` is the owner's tap for exactly ``change`` in this task; then spend it."""
    from ..agent.development_scheduler import DEVELOPMENT
    from ..policy.approval_grant import action_id_for, consume_grant, validate_grant_for_action

    target = approval_target(change)
    action_id = action_id_for("self_development", change["action"], target, task_id=task_id)
    grant = validate_grant_for_action(grant_id, action_id=action_id, tool_name="self_development", target=target)
    if grant is None:
        raise ValueError(f"This needs your approval: {describe_change(change)}. Approve it on the approval card on your PC "
                         "or phone; nothing was changed")
    await DEVELOPMENT.claim_grant(grant["id"])
    consume_grant(grant["id"])


def mentions_item(own: str, item: dict[str, Any] | None, *, hash_number: bool = True) -> bool:
    """The owner's words name ``item`` by id, RFC number or full title.

    ``hash_number=False`` (runs, per CoS) stops "#N" from naming an RFC, so "run the tests on
    PR #9011" never names RFC-9011; move and queue keep accepting "#N".
    """
    if not item:
        return False
    lowered = own.lower()
    # The id is a whole token: "charlie2" or "<id>ff" never names "charlie" or "<id>".
    if item.get("id") and re.search(rf"(?<![a-z0-9]){re.escape(item['id'].lower())}(?![a-z0-9])", lowered):
        return True
    number = item.get("rfc") or ""
    if not number:
        found = re.search(r"\brfc[-_ ]?0*(\d{1,5})\b", f"{item.get('title', '')} {item.get('path', '')}", re.I)
        number = found.group(1) if found else ""
    prefix = r"(?:\brfc[-_ ]?|#)" if hash_number else r"\brfc[-_ ]?"
    if number and re.search(rf"{prefix}0*{int(number)}\b", lowered):
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
    if action in {"move", "queue", "unqueue", "run"}:
        # H5: the fail-closed negation/retraction pre-filter applies to these too ("don't start RFC-0211").
        refusal = retraction_refusal(text)
        if refusal:
            return refusal
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
        ok = bool(_RUN.search(own)) and mentions_item(own, item, hash_number=False)
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
        refusal = retraction_refusal(text)  # H1: on the raw message, quotes and code included
        if refusal:
            return refusal
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
                      expected_revision: int | None = None, _task_id: str | None = None, _grant_id: str | None = None, **_: Any):
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
            if action in APPROVAL_ACTIONS:
                if action in {"move", "undo"} and expected_revision is None:
                    raise ValueError("Read the upcoming list first and pass its revision as expected_revision")
                if action == "move" and position is None:
                    raise ValueError("position is required to move a task")
                change = pending_change({"action": action, "item_id": item_id, "revision": revision, "config": config,
                                         "position": position, "actor": actor, "history_id": history_id,
                                         "expected_revision": expected_revision})
                if change is None:
                    raise ValueError("That change is incomplete or can't be made from chat; check the task and arguments, "
                                     "or use the Self-development page")
                # The words above can only refuse; the owner's tap on the approval card is the consent.
                await spend_approval(change, _task_id, _grant_id)
                if action == "run":
                    item = DEVELOPMENT.state()["items"].get(change["item_id"])
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
