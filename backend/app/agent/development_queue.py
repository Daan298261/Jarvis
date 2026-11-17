"""RFC-0211 shared upcoming-work queue: backlog metadata, ordering, eligibility.

Pure functions over the development scheduler's persisted state. The scheduler owns
locking and persistence; everything here is deterministic so the owner panel, the
chat tool and Away Mode dispatch see the same order and the same waiting reasons.
"""
from __future__ import annotations

import re
import time
import uuid
from typing import Any

OWNER = "owner"
ANZU = "anzu"
ACTORS = {OWNER, ANZU}

# Item statuses that mean the item is in an active delivery pipeline.
ACTIVE_STATUSES = {"running", "testing", "reviewing", "repairing", "approved", "publishing", "waiting_ci", "merging", "merged"}
# Merged but the development build has not passed yet: never re-implemented, dependents still wait.
MERGED_STATUSES = {"merged", "build_failed"}
# Terminal delivery outcomes for one revision.
DONE_STATUSES = {"delivered", "completed"}
# Attempt outcomes that need the owner before the same revision is tried again.
ATTENTION_STATUSES = {"failed", "verification_failed", "review_rejected", "timed_out", "needs_attention", "stopped", "interrupted"}
GONE_STATUSES = {"unavailable", "needs_refresh"}

PRIORITY_RE = re.compile(r"(?im)^\W*priority\W*:\W*P\s*([0-5])")
DEPENDS_RE = re.compile(r"(?im)^\W*depends\s+on\W*:(.*)$")
RFC_REF_RE = re.compile(r"RFC[- ]?(\d{4})", re.I)
ACCEPTANCE_RE = re.compile(r"(?im)^(?:#+\s*acceptance\b|\*\*acceptance\b|\W*-?\s*acceptance\s*:)")


def rfc_number(text: str) -> str:
    match = RFC_REF_RE.search(text or "")
    return match.group(1) if match else ""


def ticket_metadata(title: str, content: str, *, path: str = "") -> dict[str, Any]:
    """Priority (P0 highest), dependencies and acceptance criteria from the ticket text."""
    priority = PRIORITY_RE.search(content)
    depends: list[str] = []
    for line in DEPENDS_RE.findall(content):
        depends.extend(f"RFC-{number}" for number in RFC_REF_RE.findall(line))
    number = ""
    if path:
        match = re.match(r"docs/rfcs/(\d{4})-", path)
        number = match.group(1) if match else ""
    number = number or rfc_number(title)
    return {
        "priority": int(priority.group(1)) if priority else 3,
        "depends": sorted(set(depends) - ({f"RFC-{number}"} if number else set())),
        "rfc": number,
        "acceptance": bool(ACCEPTANCE_RE.search(content)),
    }


def plan_items(text: str) -> list[dict[str, Any]]:
    """Unchecked, actionable entries of JARVIS_MASTER_PLAN.md §58 (DEVELOPMENT QUEUE)."""
    start = re.search(r"(?m)^## 58\. DEVELOPMENT QUEUE\s*$", text)
    if not start:
        return []
    rest = text[start.end():]
    end = re.search(r"(?m)^## \d+\.", rest)
    section = rest[: end.start()] if end else rest
    out = []
    priority = 3
    lines = section.splitlines()
    index = 0
    while index < len(lines):
        line = lines[index]
        heading = re.match(r"^### P([0-5])\b", line)
        if heading:
            priority = int(heading.group(1))
        entry = re.match(r"^- \[( |x|X)\] (.+)$", line)
        if not entry:
            index += 1
            continue
        block = [line]
        index += 1
        while index < len(lines) and lines[index].startswith("  "):
            block.append(lines[index])
            index += 1
        if entry.group(1) != " ":
            continue
        body = "\n".join(block)
        status = re.search(r"(?im)^\s*-\s*Status:\s*([A-Z ]+)", body)
        out.append({
            "title": entry.group(2).strip(),
            "content": body,
            "priority": priority,
            "plan_status": (status.group(1).strip() if status else "TODO"),
            "acceptance": bool(re.search(r"(?im)^\s*-\s*Acceptance:\s*\S", body)),
        })
    return out


def item_sort_key(item: dict[str, Any]) -> tuple:
    """Explicit priority first, then deterministic oldest-first."""
    return (int(item.get("priority", 3)), float(item.get("created_at", 0)), item.get("id", ""))


def candidates(state: dict[str, Any]) -> list[str]:
    """Items that belong in the upcoming list (not finished, not gone, not active)."""
    return [i["id"] for i in state["items"].values()
            if i.get("status") not in DONE_STATUSES | GONE_STATUSES | ACTIVE_STATUSES | MERGED_STATUSES]


def plan_order(state: dict[str, Any]) -> list[str]:
    """Automatic planning that never moves an owner pin.

    Pinned items keep their absolute position; unpinned candidates fill the remaining
    slots in priority / oldest-first order. Finished or vanished items leave the list.
    """
    pool = set(candidates(state))
    current = [i for i in state.get("order", []) if i in pool]
    pins = {i for i in state.get("pins", []) if i in pool}
    pinned_positions = {pos: item for pos, item in enumerate(current) if item in pins}
    unpinned = sorted((state["items"][i] for i in pool if i not in pins), key=item_sort_key)
    result: list[str] = []
    feed = iter(i["id"] for i in unpinned)
    total = len(pool)
    for position in range(total):
        if position in pinned_positions:
            result.append(pinned_positions[position])
        else:
            nxt = next(feed, None)
            if nxt is not None:
                result.append(nxt)
    # Pins whose old position is past the end (the list shrank) keep their relative order at the tail.
    result.extend(item for pos, item in sorted(pinned_positions.items()) if item not in result)
    result.extend(feed)
    return result


def _record(state: dict[str, Any], actor: str, reason: str, before: list[str], after: list[str]) -> dict[str, Any]:
    entry = {"id": uuid.uuid4().hex[:12], "actor": actor, "reason": reason[:300], "before": before,
             "after": after, "at": time.time(), "revision": state.get("queue_revision", 0) + 1}
    history = state.setdefault("queue_history", [])
    history.append(entry)
    del history[:-50]
    state["order"] = after
    state["queue_revision"] = entry["revision"]
    return entry


def replan(state: dict[str, Any]) -> bool:
    """Apply automatic planning; records a history entry only when the order changed."""
    before = list(state.get("order", []))
    after = plan_order(state)
    if after == before:
        return False
    state["pins"] = [i for i in state.get("pins", []) if i in after]
    common = [i for i in before if i in after]
    if common == [i for i in after if i in before]:
        # Tasks only arrived or left: new revision, but nothing for the owner to undo.
        state["order"] = after
        state["queue_revision"] = state.get("queue_revision", 0) + 1
        return True
    _record(state, ANZU, "Backlog refreshed", before, after)
    return True


def reorder(state: dict[str, Any], order: list[str], *, expected_revision: int, actor: str, reason: str, moved: str = "") -> dict[str, Any]:
    """Atomic, revision-checked reorder of the full upcoming list."""
    if actor not in ACTORS:
        raise ValueError("Unknown actor")
    if int(expected_revision) != int(state.get("queue_revision", 0)):
        raise StaleQueue("The upcoming list changed; refresh and try again")
    current = list(state.get("order", []))
    if sorted(order) != sorted(current) or len(set(order)) != len(order):
        raise ValueError("Reorder must contain exactly the current upcoming tasks (no additions, removals or duplicates)")
    if order == current:
        return {"changed": False}
    pins = set(state.get("pins", []))
    if actor == ANZU:
        if not reason.strip():
            raise ValueError("ANZU must give a reason when it reorders upcoming work")
        moved_pins = [i for i in pins if order.index(i) != current.index(i)]
        if moved_pins:
            raise ValueError("Owner-ordered tasks are pinned; ANZU cannot move them until you release them")
    else:
        # Pin the tasks the owner actually moved: the named one, or those outside the
        # longest run that kept its relative order.
        added = ({moved} if moved else moved_items(current, order)) - pins
        pins |= added
    state["pins"] = [i for i in order if i in pins]
    entry = _record(state, actor, reason or "Reordered by owner", current, list(order))
    entry["pinned"] = sorted(added) if actor == OWNER else []
    return {"changed": True, "history_id": entry["id"]}


def moved_items(before: list[str], after: list[str]) -> set[str]:
    """Items not in the longest increasing subsequence of their old positions."""
    positions = [before.index(i) for i in after]
    best: list[list[int]] = []
    for index, value in enumerate(positions):
        chain = max((c for c in best if positions[c[-1]] < value), key=len, default=[])
        best.append(chain + [index])
    keep = {after[i] for i in max(best, key=len, default=[])}
    return {i for i in after if i not in keep}


def move(state: dict[str, Any], item_id: str, *, to: int | None = None, delta: int = 0, expected_revision: int, actor: str, reason: str) -> dict[str, Any]:
    current = list(state.get("order", []))
    if item_id not in current:
        raise ValueError("That task is not in the upcoming list")
    index = current.index(item_id)
    target = to if to is not None else index + delta
    target = max(0, min(len(current) - 1, int(target)))
    order = [i for i in current if i != item_id]
    order.insert(target, item_id)
    return reorder(state, order, expected_revision=expected_revision, actor=actor, reason=reason, moved=item_id)


def release_pin(state: dict[str, Any], item_id: str, *, expected_revision: int) -> dict[str, Any]:
    if int(expected_revision) != int(state.get("queue_revision", 0)):
        raise StaleQueue("The upcoming list changed; refresh and try again")
    if item_id not in state.get("pins", []):
        raise ValueError("That task is not pinned")
    state["pins"] = [i for i in state["pins"] if i != item_id]
    before = list(state.get("order", []))
    after = plan_order(state)
    entry = _record(state, OWNER, "Released owner order", before, after)
    return {"changed": before != after, "history_id": entry["id"]}


def undo(state: dict[str, Any], history_id: str, *, expected_revision: int, actor: str) -> dict[str, Any]:
    if int(expected_revision) != int(state.get("queue_revision", 0)):
        raise StaleQueue("The upcoming list changed; refresh and try again")
    history = state.get("queue_history", [])
    entry = next((h for h in history if h["id"] == history_id), None)
    if not entry:
        raise ValueError("That change is no longer in the history")
    if entry is not history[-1]:
        raise ValueError("Only the latest change can be undone")
    if actor == ANZU and entry["actor"] == OWNER:
        raise ValueError("ANZU cannot undo your ordering")
    pool = set(candidates(state))
    restored = [i for i in entry["before"] if i in pool] + [i for i in state["order"] if i not in entry["before"]]
    if entry["actor"] == OWNER:
        # Undoing an owner reorder drops the pins that reorder created.
        created = set(entry.get("pinned", []))
        state["pins"] = [i for i in state.get("pins", []) if i not in created]
    result = _record(state, actor, f"Undo: {entry['reason']}", list(state["order"]), restored)
    return {"changed": True, "history_id": result["id"]}


class StaleQueue(ValueError):
    """A reorder/undo raced another client; the caller must refresh."""


def dependency_waiting(state: dict[str, Any], item: dict[str, Any]) -> list[str]:
    """Dependencies that are still open in the backlog (not delivered or evidenced complete)."""
    evidence = state.get("evidence", {})
    merged = evidence.get("merged", {})
    open_items = {i.get("rfc"): i for i in state["items"].values() if i.get("rfc")}
    waiting = []
    for dep in item.get("depends", []):
        number = dep.split("-")[-1]
        other = open_items.get(number)
        if number in merged:
            continue
        if other is None or other.get("status") in DONE_STATUSES:
            continue
        waiting.append(dep)
    return waiting


def waiting_reason(state: dict[str, Any], item: dict[str, Any], *, automatic: bool) -> str:
    """Why this item cannot be dispatched now ("" when eligible).

    ``automatic`` is Away Mode selection; manual (owner-queued) dispatch skips the
    evidence-based exclusions the owner explicitly overrode but never the safety gates.
    """
    status = item.get("status", "available")
    if status in GONE_STATUSES:
        return "Source changed or unavailable; scan again" if status == "unavailable" else "Drive source needs a fresh read"
    if status in ACTIVE_STATUSES:
        return "In progress"
    if status in DONE_STATUSES:
        return "Already delivered"
    if status in MERGED_STATUSES:
        return "Merged; waiting for a passing development build"
    if status in ATTENTION_STATUSES and item.get("attempted_revision") == item.get("revision"):
        return f"Last attempt at this revision ended {status.replace('_', ' ')}; queue it again to retry"
    deps = dependency_waiting(state, item)
    if deps:
        return "Waiting for " + ", ".join(deps)
    if not automatic:
        return "" if status == "queued" and item.get("approved_revision") == item.get("revision") else "Not queued"
    evidence = state.get("evidence", {})
    if item.get("rfc") and item["rfc"] in evidence.get("merged", {}):
        return f"Delivered by PR #{evidence['merged'][item['rfc']]}"
    if item.get("rfc") and item["rfc"] in evidence.get("open", {}):
        return f"Claimed by open PR #{evidence['open'][item['rfc']]}"
    if not item.get("acceptance"):
        return "Blocked: the ticket has no acceptance criteria"
    if item.get("kind") == "drive" and not item.get("maps_to"):
        return "Blocked: this Drive document does not map to a repository RFC"
    if item.get("kind") == "drive" and item.get("maps_to"):
        return f"Duplicate of repository {item['maps_to']}"
    if item.get("kind") == "plan" and item.get("plan_status", "TODO") != "TODO":
        return f"Plan status is {item['plan_status']}"
    return ""


def next_eligible(state: dict[str, Any], *, automatic: bool) -> tuple[dict[str, Any] | None, list[dict[str, Any]]]:
    """First eligible item in queue order plus the waiting explanation for every upcoming item."""
    explained = []
    chosen = None
    for item_id in state.get("order", []):
        item = state["items"].get(item_id)
        if not item:
            continue
        reason = waiting_reason(state, item, automatic=automatic)
        explained.append({"id": item_id, "reason": reason})
        if chosen is None and not reason:
            chosen = item
    return chosen, explained
