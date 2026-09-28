"""Measured per-class provider quality for the Quartermaster (RFC-0171).

Provider confidence is not accuracy: an encoder can be confidently wrong on a
decision class it was never trained for. After Laya warms up, both Laya and the
rules adapter answer the same labeled Anzu fixtures; the Quartermaster only
routes a class to Laya where Laya's measured accuracy beats rules.
"""

from __future__ import annotations

import logging
import threading
import time
from dataclasses import dataclass
from typing import Callable

from .adapters import rules
from .types import Answer, Question
from ..security.red_scenarios import HARM as _HARM
from ..security.red_scenarios import SCENARIOS as _HARM_SCENARIOS

log = logging.getLogger("jarvis.decision.calibration")

_TOOLS = Question(
    id="tool_select",
    type="choice",
    prompt="Which tool does this request need?",
    choices=("filesystem", "git", "browser", "none"),
)
_SPEAK = Question(
    id="speak_class",
    type="choice",
    prompt="Is the upcoming assistant reply social small-talk or technical?",
    choices=("social", "technical"),
)
_ESCALATE = Question(
    id="escalate",
    type="boolean",
    prompt="Does this need a stronger model than the current orchestrator should answer?",
)


@dataclass(frozen=True)
class Fixture:
    decision_class: str
    question: Question
    state: dict
    expected: object


FIXTURES: tuple[Fixture, ...] = (
    Fixture("tool_selection", _TOOLS, {"user_message": "open C:/notes/todo.txt and read it to me"}, "filesystem"),
    Fixture("tool_selection", _TOOLS, {"user_message": "list the files in my downloads folder"}, "filesystem"),
    Fixture("tool_selection", _TOOLS, {"user_message": "commit my changes and push the branch"}, "git"),
    Fixture("tool_selection", _TOOLS, {"user_message": "show the diff of the last commit"}, "git"),
    Fixture("tool_selection", _TOOLS, {"user_message": "open the bbc news website"}, "browser"),
    Fixture("tool_selection", _TOOLS, {"user_message": "go to github.com and find the laya repo"}, "browser"),
    Fixture("tool_selection", _TOOLS, {"user_message": "open steam"}, "none"),
    Fixture("tool_selection", _TOOLS, {"user_message": "what's up, how are you"}, "none"),
    Fixture("tool_selection", _TOOLS, {"user_message": "tell me a joke"}, "none"),
    Fixture("speak_class", _SPEAK, {"user_message": "good morning! how did you sleep?"}, "social"),
    Fixture("speak_class", _SPEAK, {"user_message": "thanks, that was lovely"}, "social"),
    Fixture("speak_class", _SPEAK, {"user_message": "why does this pytest traceback show a KeyError"}, "technical"),
    Fixture("speak_class", _SPEAK, {"user_message": "refactor the api client to use async"}, "technical"),
    Fixture("complexity_escalation", _ESCALATE, {"user_message": "hi there"}, False),
    Fixture("complexity_escalation", _ESCALATE, {"user_message": "what time is it"}, False),
    Fixture(
        "complexity_escalation",
        _ESCALATE,
        {"user_message": "design a distributed consensus protocol and prove it tolerates partitions"},
        True,
    ),
    Fixture(
        "complexity_escalation",
        _ESCALATE,
        {"user_message": "debug this production incident across three services and write the migration"},
        True,
    ),
) + tuple(
    Fixture("harm_veto", _HARM, {"user_message": prompt}, "cancel" if cancel else "allow")
    for prompt, cancel in _HARM_SCENARIOS
)

_LOCK = threading.Lock()
_ACCURACY: dict[tuple[str, str], float] = {}
_MEASURED_AT: float | None = None

AnswerFn = Callable[[dict, list[Question], str], dict[str, Answer]]


def _correct(answer: Answer | None, expected: object) -> bool:
    return answer is not None and answer.value == expected


def measure(provider: str, answer_fn: AnswerFn) -> dict[str, float]:
    """Accuracy per decision class for ``provider`` on the labeled fixtures."""
    totals: dict[str, list[int]] = {}
    for fixture in FIXTURES:
        try:
            answers = answer_fn(fixture.state, [fixture.question], fixture.decision_class)
            hit = _correct(answers.get(fixture.question.id), fixture.expected)
        except Exception as exc:  # noqa: BLE001 — a failing provider scores zero
            log.info("calibration %s/%s failed: %s", provider, fixture.decision_class, exc)
            hit = False
        bucket = totals.setdefault(fixture.decision_class, [0, 0])
        bucket[0] += int(hit)
        bucket[1] += 1
    return {cls: hits / count for cls, (hits, count) in totals.items()}


def _rules_answers(state: dict, questions: list[Question], decision_class: str) -> dict[str, Answer]:
    return rules.decide(state=state, questions=questions, decision_class=decision_class).answers


def calibrate(
    laya_answer_fn: AnswerFn,
    jev_answer_fn: AnswerFn | None = None,
) -> dict[str, dict[str, float]]:
    """Measure Laya, optional Jev, and rules on the same labeled fixtures."""
    global _MEASURED_AT
    laya = measure("laya", laya_answer_fn)
    rules_scores = measure("rules", _rules_answers)
    jev = measure("jev", jev_answer_fn) if jev_answer_fn is not None else {}
    with _LOCK:
        for cls, value in laya.items():
            _ACCURACY[(cls, "laya")] = value
        for cls, value in rules_scores.items():
            _ACCURACY[(cls, "rules")] = value
        for cls, value in jev.items():
            _ACCURACY[(cls, "jev")] = value
        _MEASURED_AT = time.time()
    log.info("Calibration: laya=%s jev=%s rules=%s", laya, jev, rules_scores)
    out = {"laya": laya, "rules": rules_scores}
    if jev:
        out["jev"] = jev
    return out


def accuracy(decision_class: str, provider: str) -> float | None:
    with _LOCK:
        return _ACCURACY.get((decision_class, provider))


def laya_qualified(decision_class: str) -> bool:
    """Laya stays eligible unless a measurement showed it is unusable on that class.

    Rules accuracy is recorded for a fair comparison, not as a gate that blocks Laya.
    """
    with _LOCK:
        laya = _ACCURACY.get((decision_class, "laya"))
    if laya is None:
        return True
    return laya >= 0.25


def snapshot() -> dict[str, object]:
    with _LOCK:
        rows: dict[str, dict[str, float]] = {}
        for (cls, provider), value in sorted(_ACCURACY.items()):
            rows.setdefault(cls, {})[provider] = round(value, 3)
        return {"measured_at": _MEASURED_AT, "fixtures": len(FIXTURES), "accuracy": rows}


def reset() -> None:
    global _MEASURED_AT
    with _LOCK:
        _ACCURACY.clear()
        _MEASURED_AT = None
