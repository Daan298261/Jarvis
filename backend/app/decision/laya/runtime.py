"""Laya local runtime — loopback-only / in-process, warm when enabled (RFC-0171)."""

from __future__ import annotations

import re
import threading
import time
from dataclasses import dataclass, field
from typing import Any

from . import pins
from ..types import Answer, Question

_LOCK = threading.Lock()


@dataclass
class LayaRuntimeState:
    enabled: bool = False
    warm: bool = False
    fixture: bool = False
    version: str = "laya-managed"
    loaded_at: float | None = None
    last_infer_ms: float | None = None
    bind: str = "127.0.0.1"
    port: int | None = None  # None => in-process only
    manifest: dict[str, Any] = field(default_factory=dict)


_STATE = LayaRuntimeState()
_DECIDE_FN = None  # test injection


def set_decide_fn(fn) -> None:
    """Tests may inject a labeled Laya decide transport. Production leaves this None."""
    global _DECIDE_FN
    _DECIDE_FN = fn


def reset_runtime() -> None:
    global _DECIDE_FN
    with _LOCK:
        _STATE.enabled = False
        _STATE.warm = False
        _STATE.fixture = False
        _STATE.loaded_at = None
        _STATE.last_infer_ms = None
        _STATE.port = None
        _STATE.manifest = {}
        _DECIDE_FN = None


def status() -> dict[str, Any]:
    ok, reason, manifest = pins.verify_installed(allow_fixture=True)
    with _LOCK:
        return {
            "provider": "laya",
            "installed": ok,
            "install_error": reason,
            "enabled": _STATE.enabled,
            "warm": _STATE.warm and _STATE.enabled,
            "fixture": bool(_STATE.fixture or (manifest or {}).get("fixture")),
            "version": _STATE.version,
            "bind": _STATE.bind,
            "port": _STATE.port,
            "loopback_only": True,
            "license": pins.LAYA_LICENSE,
            "source_url": pins.LAYA_SOURCE_URL,
            "last_infer_ms": _STATE.last_infer_ms,
            "loaded_at": _STATE.loaded_at,
            "pin_manifest": pins.pin_manifest(),
        }


def enable(*, warm: bool = True, allow_fixture: bool = True) -> dict[str, Any]:
    ok, reason, manifest = pins.verify_installed(allow_fixture=allow_fixture)
    if not ok:
        raise RuntimeError(reason or "Laya install invalid")
    with _LOCK:
        _STATE.enabled = True
        _STATE.warm = bool(warm)
        _STATE.fixture = bool((manifest or {}).get("fixture"))
        _STATE.manifest = dict(manifest or {})
        _STATE.loaded_at = time.time()
        _STATE.bind = "127.0.0.1"
        _STATE.port = None  # in-process; never bind 0.0.0.0
    return status()


def disable() -> dict[str, Any]:
    with _LOCK:
        _STATE.enabled = False
        _STATE.warm = False
    return status()


def is_ready() -> bool:
    with _LOCK:
        if not _STATE.enabled or not _STATE.warm:
            return False
    ok, _reason, _manifest = pins.verify_installed(allow_fixture=True)
    return ok


def _heuristic_decide(state: dict[str, Any], questions: list[Question]) -> dict[str, Answer]:
    """
    In-process warm path when managed checkpoint is installed.
    Uses compact lexical encoding — not generative LLM. Fixture installs are labeled.
    """
    prompt = str(state.get("user_message") or state.get("prompt") or "")
    tokens = set(re.findall(r"[a-z0-9_]{3,}", prompt.lower()))
    answers: dict[str, Answer] = {}
    for question in questions:
        if question.type == "choice":
            best = question.choices[0] if question.choices else ""
            best_score = -1.0
            for choice in question.choices:
                choice_tokens = set(re.findall(r"[a-z0-9_]{3,}", choice.lower()))
                score = len(tokens & choice_tokens)
                # Also match against state hints
                if choice == state.get("preferred_profile") or choice == state.get("suggested_operation"):
                    score += 5
                if choice == state.get("suggested_target_id"):
                    score += 5
                if score > best_score:
                    best_score = score
                    best = choice
            conf = 0.55 if best_score <= 0 else min(0.95, 0.55 + 0.1 * best_score)
            answers[question.id] = Answer(question.id, "choice", best, conf)
        elif question.type == "score":
            excerpt = ""
            excerpts = state.get("excerpts")
            if isinstance(excerpts, dict):
                excerpt = str(excerpts.get(question.id) or "")
            hay = set(re.findall(r"[a-z0-9_]{3,}", excerpt.lower()))
            overlap = (len(tokens & hay) / max(1, len(tokens))) if tokens else 0.2
            lo, hi = question.min_score, question.max_score
            value = lo + (hi - lo) * max(0.0, min(1.0, overlap))
            answers[question.id] = Answer(question.id, "score", value, 0.7)
        elif question.type == "boolean":
            # Probability-ish from keyword density
            positive = any(t in prompt.lower() for t in ("yes", "need", "escalate", "approve", "done"))
            answers[question.id] = Answer(question.id, "boolean", positive, 0.6)
        else:
            answers[question.id] = Answer(question.id, "noul", 0.45, 0.55)
    return answers


def decide_local(
    *,
    state: dict[str, Any],
    questions: list[Question],
    decision_class: str,
    deadline_ms: float,
) -> tuple[dict[str, Answer], float, bool]:
    if not is_ready():
        raise RuntimeError("Laya runtime is not warm/enabled")
    started = time.perf_counter()
    if _DECIDE_FN is not None:
        answers = _DECIDE_FN(state=state, questions=questions, decision_class=decision_class)
        elapsed = (time.perf_counter() - started) * 1000.0
        if elapsed > deadline_ms:
            raise TimeoutError(f"Laya fixture exceeded deadline ({elapsed:.1f}ms > {deadline_ms}ms)")
        with _LOCK:
            _STATE.last_infer_ms = elapsed
        return answers, elapsed, True
    # Simulate non-autoregressive encoder latency budget without cold-loading.
    answers = _heuristic_decide(state, questions)
    elapsed = (time.perf_counter() - started) * 1000.0
    if elapsed > deadline_ms:
        raise TimeoutError(f"Laya exceeded deadline ({elapsed:.1f}ms > {deadline_ms}ms)")
    with _LOCK:
        _STATE.last_infer_ms = elapsed
    return answers, elapsed, _STATE.fixture
