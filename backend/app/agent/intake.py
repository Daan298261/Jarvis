"""Owner-message intake: measure a long paste, then answer directly, compress it,
or run it as ordered agent tasks.

1. Measure the message against the worker context budget (conservative estimate).
2. Within budget → ``direct``.
3. Over budget → structure (list items / imperative lines) decides clear cases;
   a Laya ``intake_strategy`` decision breaks ambiguous ties when warm:
   * ``compress`` — one body of material to digest: budget-sized segments are
     condensed in order into one brief (RFC-0182 ``condense_segments``, nothing
     skipped), and the full text is saved so the worker can read exact passages;
   * ``sequential`` — several instructions to carry out in order: the text is split
     into parts that run as chained agent tasks. Part N+1 is submitted when part N
     completes and receives part N's result, so the whole paste never has to fit
     in one context.

Chains are persisted under ``data/intake_chains`` and every part uses a stable
``request_id`` (``intake-<chain>-<n>``), so a restart or a duplicate terminal event
cannot fire a part twice.
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
import threading
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from ..config import data_dir
from ..decision.intake import estimate_tokens, split_segments
from ..inference.prompt_budget import estimate_text_tokens
from .segmented_input import SEGMENT_CHARS as SEGMENT_MIN_CHARS

log = logging.getLogger("jarvis.agent.intake")

# Share of the worker context the owner's message may use (system prompt, history
# and the reply need the rest).
USER_SHARE = 0.45
MIN_BUDGET_TOKENS = 1024
MAX_SEQUENTIAL_PARTS = 8
CARRYOVER_CHARS = 1800
INTAKE_DECISION_DEADLINE_MS = 1500.0

_LIST_ITEM = re.compile(r"(?m)^\s*(?:\d+[.)]|[-*•]|step\s+\d+[:.)]?)\s+\S", re.IGNORECASE)
_IMPERATIVE = re.compile(
    r"(?im)^\s*(?:please\s+)?(?:add|build|change|check|create|delete|deploy|fix|implement|install|"
    r"make|move|refactor|remove|rename|run|send|set|test|update|write)\b"
)
_CHAIN_LOCK = threading.Lock()


@dataclass
class IntakePlan:
    strategy: str  # "direct" | "compress" | "sequential"
    tokens: int
    budget_tokens: int
    text: str
    segments: list[str] = field(default_factory=list)
    decided_by: str = "rules"
    reason: str = ""
    original_path: str = ""

    def as_dict(self) -> dict[str, Any]:
        return {
            "strategy": self.strategy,
            "tokens": self.tokens,
            "budget_tokens": self.budget_tokens,
            "segments": len(self.segments),
            "decided_by": self.decided_by,
            "reason": self.reason,
            "original_path": self.original_path,
        }


def budget_for_context(context_tokens: int) -> int:
    return max(MIN_BUDGET_TOKENS, int(max(0, context_tokens) * USER_SHARE))


def _structure(text: str) -> tuple[int, int]:
    return len(_LIST_ITEM.findall(text)), len(_IMPERATIVE.findall(text))


def _rules_strategy(text: str) -> tuple[str, str]:
    items, imperatives = _structure(text)
    if items >= 3 or imperatives >= 3:
        return "sequential", f"{items} list items / {imperatives} imperative lines"
    return "compress", "single body of material"


def _decide_strategy(text: str) -> tuple[str, str, str]:
    """Return (strategy, decided_by, reason).

    Clear structure decides on its own. Laya's base checkpoint is near chance
    zero-shot on typed decisions (upstream "Honest limits"), so it only breaks
    ties when the structural signal is ambiguous.
    """
    rules_choice, rules_reason = _rules_strategy(text)
    items, imperatives = _structure(text)
    if max(items, imperatives) >= 3 or (items == 0 and imperatives == 0):
        return rules_choice, "rules", rules_reason
    try:
        from ..decision.laya import runtime as laya_runtime
        from ..decision.types import Question

        if not laya_runtime.is_ready():
            return rules_choice, "rules", rules_reason
        question = Question(
            id="intake_strategy",
            type="choice",
            prompt="How should this long message be handled?",
            choices=("compress", "sequential"),
            descriptions=(
                "one body of material (document, log, notes) to read, summarize or answer questions about",
                "several separate instructions or tasks the owner wants carried out one after another",
            ),
        )
        answers = laya_runtime.decide_document(
            text, [question], deadline_ms=INTAKE_DECISION_DEADLINE_MS
        )
        answer = answers.get("intake_strategy")
        if answer is not None and answer.value in {"compress", "sequential"}:
            confidence = answer.confidence if answer.confidence is not None else 0.0
            if confidence >= 0.6:
                return str(answer.value), "laya", f"Laya confidence {confidence:.2f}"
            return rules_choice, "rules", f"{rules_reason}; Laya unsure ({confidence:.2f})"
    except Exception as exc:  # noqa: BLE001 — intake must never block the turn
        log.info("Laya intake decision unavailable: %s", exc)
    return rules_choice, "rules", rules_reason


def _save_original(text: str) -> Path:
    root = data_dir() / "intake"
    root.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    path = root / f"owner_paste_{stamp}_{uuid.uuid4().hex[:8]}.txt"
    path.write_text(text, encoding="utf-8")
    return path


def plan_owner_intake(text: str, *, context_tokens: int) -> IntakePlan:
    cleaned = (text or "").strip()
    tokens = estimate_text_tokens(cleaned)
    budget = budget_for_context(context_tokens)
    if tokens <= budget:
        return IntakePlan("direct", tokens, budget, cleaned, reason="fits the worker context")

    strategy, decided_by, reason = _decide_strategy(cleaned)
    # Budget in characters under the same conservative estimator the worker uses.
    budget_chars = max(512, int(len(cleaned) * budget / max(1, tokens)))
    if strategy == "sequential":
        segments = split_segments(cleaned, budget_chars)
        if 1 < len(segments) <= MAX_SEQUENTIAL_PARTS:
            return IntakePlan(
                "sequential", tokens, budget, cleaned, segments=segments, decided_by=decided_by, reason=reason
            )
        reason = f"{reason}; {len(segments)} parts exceeds {MAX_SEQUENTIAL_PARTS}, compressing instead"

    # RFC-0182 condenses every segment in order (none skipped). Segments are sized to
    # the measured budget, not a fixed 2,600 chars, so a huge paste costs a few passes.
    original = _save_original(cleaned)
    return IntakePlan(
        "compress",
        tokens,
        budget,
        cleaned,
        segments=split_segments(cleaned, max(SEGMENT_MIN_CHARS, budget_chars)),
        decided_by=decided_by,
        reason=reason,
        original_path=str(original),
    )


# ---------------------------------------------------------------------------
# Sequential chains


def _chains_root() -> Path:
    root = data_dir() / "intake_chains"
    root.mkdir(parents=True, exist_ok=True)
    return root


def _chain_path(chain_id: str) -> Path:
    if not re.fullmatch(r"[0-9a-f]{12}", chain_id):
        raise ValueError("invalid chain id")
    return _chains_root() / f"{chain_id}.json"


def _load_chain(chain_id: str) -> dict[str, Any] | None:
    try:
        path = _chain_path(chain_id)
    except ValueError:
        return None
    if not path.is_file():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def _save_chain(chain: dict[str, Any]) -> None:
    path = _chain_path(chain["id"])
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(chain, indent=2), encoding="utf-8")
    tmp.replace(path)


def part_request_id(chain_id: str, index: int) -> str:
    return f"intake-{chain_id}-{index}"


def _parse_request_id(task_id: str) -> tuple[str, int] | None:
    match = re.fullmatch(r"intake-([0-9a-f]{12})-(\d+)", task_id or "")
    if not match:
        return None
    return match.group(1), int(match.group(2))


def part_prompt(chain: dict[str, Any], index: int, previous_result: str = "") -> str:
    total = len(chain["segments"])
    lines = [
        f"Part {index} of {total} of a long owner request, handled in order.",
    ]
    if previous_result:
        lines.append(f"Result of part {index - 1}:\n{previous_result[:CARRYOVER_CHARS]}")
    if index == total:
        lines.append("This is the final part: finish it, then give the owner one combined answer for all parts.")
    else:
        lines.append("Do only this part. Later parts follow automatically; do not anticipate them.")
    lines.append(f"--- Part {index} ---\n{chain['segments'][index - 1]}")
    return "\n\n".join(lines)


async def _submit_part(chain: dict[str, Any], index: int, previous_result: str = "") -> str:
    from .loop import AGENT

    task = await AGENT.create_task(
        part_prompt(chain, index, previous_result),
        request_id=part_request_id(chain["id"], index),
    )
    return task.id


async def start_sequential_chain(plan: IntakePlan, *, conversation_id: str = "") -> dict[str, Any]:
    chain_id = uuid.uuid4().hex[:12]
    chain = {
        "id": chain_id,
        "conversation_id": conversation_id,
        "status": "running",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "segments": plan.segments,
        "current": 1,
        "task_ids": [],
        "decided_by": plan.decided_by,
    }
    with _CHAIN_LOCK:
        _save_chain(chain)
    task_id = await _submit_part(chain, 1)
    with _CHAIN_LOCK:
        chain["task_ids"].append(task_id)
        _save_chain(chain)
    return chain


async def advance_chain(task_id: str, *, status: str, result: str = "") -> str | None:
    """Submit the next part after part N completes. Returns the next task id, if any."""
    parsed = _parse_request_id(task_id)
    if parsed is None:
        return None
    chain_id, index = parsed
    with _CHAIN_LOCK:
        chain = _load_chain(chain_id)
        if chain is None or chain.get("status") != "running" or chain.get("current") != index:
            return None
        if status != "completed":
            chain["status"] = "stopped"
            chain["stopped_reason"] = f"part {index} {status}"
            _save_chain(chain)
            return None
        if index >= len(chain["segments"]):
            chain["status"] = "completed"
            _save_chain(chain)
            return None
        chain["current"] = index + 1
        _save_chain(chain)
    try:
        next_id = await _submit_part(chain, index + 1, result)
    except Exception as exc:  # noqa: BLE001 — e.g. kill switch; record and stop
        with _CHAIN_LOCK:
            chain["status"] = "stopped"
            chain["stopped_reason"] = f"could not submit part {index + 1}: {exc}"[:400]
            _save_chain(chain)
        return None
    with _CHAIN_LOCK:
        chain["task_ids"].append(next_id)
        _save_chain(chain)
    return next_id


def on_task_terminal(task_id: str, *, status: str, result: str = "") -> None:
    """Called from the agent loop when a task reaches a terminal status."""
    if _parse_request_id(task_id) is None:
        return
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        return
    loop.create_task(advance_chain(task_id, status=status, result=result))


def chain_status(chain_id: str) -> dict[str, Any] | None:
    chain = _load_chain(chain_id)
    if chain is None:
        return None
    return {key: value for key, value in chain.items() if key != "segments"} | {
        "parts": len(chain.get("segments") or []),
    }


__all__ = [
    "IntakePlan",
    "advance_chain",
    "budget_for_context",
    "chain_status",
    "estimate_tokens",
    "on_task_terminal",
    "part_prompt",
    "plan_owner_intake",
    "start_sequential_chain",
]
