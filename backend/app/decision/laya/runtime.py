"""Laya local runtime — in-process, warm when enabled (RFC-0171).

The managed backend wraps the pinned ``laya`` multilingual Agent:

* the checkpoint loads once on a background thread (never per request) and the
  enabled flag persists so it re-warms after a restart;
* every inference runs on one dedicated worker thread and ``decide_local`` waits
  at most the caller's deadline — a slow CPU forward pass falls back instead of
  stalling the turn, and a second request never queues behind a running one;
* input is measured with the real tokenizer before each call. Oversized state is
  scanned in windows (``predict_long``) when the measured per-window cost fits the
  deadline, otherwise compressed to one window — Laya itself would silently
  truncate to 1,024 tokens;
* choice questions are shortlisted to what the 256-token option head can keep
  distinct (above that, Laya's options collapse into identical token spans).

A labeled test fixture is served by a separate lexical backend and is always
reported as ``fixture``; it is never presented as the encoder.
"""

from __future__ import annotations

import json
import logging
import re
import threading
import time
from concurrent.futures import Future, ThreadPoolExecutor
from concurrent.futures import TimeoutError as FutureTimeout
from dataclasses import dataclass, field
from typing import Any, Callable

from . import pins
from ..intake import compress_text, count_tokens
from ..types import Answer, Question

log = logging.getLogger("jarvis.decision.laya")

_LOCK = threading.Lock()
MAX_CHOICE_OPTIONS = 16
SCORE_LEVELS = 5
# Question rows and special tokens also consume the window beside the option head.
_STATE_TOKEN_MARGIN = 48
_ENABLED_FLAG = "enabled.json"


@dataclass
class LayaRuntimeState:
    enabled: bool = False
    warm: bool = False
    loading: bool = False
    load_error: str = ""
    fixture: bool = False
    version: str = "laya-managed"
    device: str = ""
    loaded_at: float | None = None
    load_ms: float | None = None
    last_infer_ms: float | None = None
    window_ms_ewma: float | None = None
    busy: bool = False
    bind: str = "127.0.0.1"
    port: int | None = None  # in-process only
    manifest: dict[str, Any] = field(default_factory=dict)


_STATE = LayaRuntimeState()
_AGENT: Any = None
_EXECUTOR: ThreadPoolExecutor | None = None
_LOAD_THREAD: threading.Thread | None = None
_DECIDE_FN: Callable[..., dict[str, Answer]] | None = None  # test injection


def set_decide_fn(fn) -> None:
    """Tests may inject a labeled Laya decide transport. Production leaves this None."""
    global _DECIDE_FN
    _DECIDE_FN = fn


def _executor() -> ThreadPoolExecutor:
    global _EXECUTOR
    with _LOCK:
        if _EXECUTOR is None:
            _EXECUTOR = ThreadPoolExecutor(max_workers=1, thread_name_prefix="laya")
        return _EXECUTOR


def reset_runtime() -> None:
    global _DECIDE_FN, _AGENT
    with _LOCK:
        _STATE.enabled = False
        _STATE.warm = False
        _STATE.loading = False
        _STATE.load_error = ""
        _STATE.fixture = False
        _STATE.version = "laya-managed"
        _STATE.device = ""
        _STATE.loaded_at = None
        _STATE.load_ms = None
        _STATE.last_infer_ms = None
        _STATE.window_ms_ewma = None
        _STATE.busy = False
        _STATE.port = None
        _STATE.manifest = {}
        _AGENT = None
        _DECIDE_FN = None


def _persist_enabled(enabled: bool, warm: bool) -> None:
    try:
        (pins.install_root() / _ENABLED_FLAG).write_text(
            json.dumps({"enabled": enabled, "warm": warm}), encoding="utf-8"
        )
    except OSError as exc:
        log.warning("Could not persist Laya enabled flag: %s", exc)


def status() -> dict[str, Any]:
    ok, reason, manifest = pins.verify_installed(allow_fixture=True)
    with _LOCK:
        return {
            "provider": "laya",
            "installed": ok,
            "install_error": reason,
            "package_version": pins.package_version(),
            "enabled": _STATE.enabled,
            "warm": _STATE.warm and _STATE.enabled,
            "loading": _STATE.loading,
            "load_error": _STATE.load_error,
            "fixture": bool(_STATE.fixture or (manifest or {}).get("fixture")),
            "version": _STATE.version,
            "device": _STATE.device,
            "bind": _STATE.bind,
            "port": _STATE.port,
            "loopback_only": True,
            "license": pins.LAYA_LICENSE,
            "source_url": pins.LAYA_SOURCE_URL,
            "max_len": pins.LAYA_MAX_LEN,
            "head_max_len": pins.LAYA_HEAD_MAX_LEN,
            "last_infer_ms": _STATE.last_infer_ms,
            "window_ms_ewma": _STATE.window_ms_ewma,
            "load_ms": _STATE.load_ms,
            "loaded_at": _STATE.loaded_at,
            "busy": _STATE.busy,
            "pin_manifest": pins.pin_manifest(),
        }


def _load_agent() -> None:
    """Background load of the pinned checkpoint; Laya re-verifies digests before parsing weights."""
    global _AGENT
    started = time.perf_counter()
    try:
        import laya  # type: ignore[import-not-found]

        directory = pins.model_dir()
        if directory is None:
            raise RuntimeError("Managed Laya model_dir is missing")
        agent = laya.load(str(directory), expected_sha256=pins.expected_digests())
        # One warm-up pass so the first owner decision does not pay graph/kernel setup.
        agent.predict("warm up", {"ready": {"type": "noul", "instructions": "Is this a test?"}})
        _calibrate(agent)
        device = str(getattr(agent, "device", "") or "")
        with _LOCK:
            _AGENT = agent
            _STATE.warm = True
            _STATE.loading = False
            _STATE.load_error = ""
            _STATE.device = device
            _STATE.version = f"laya-{pins.LAYA_PACKAGE_VERSION}@{pins.LAYA_REVISION[:12]}"
            _STATE.loaded_at = time.time()
            _STATE.load_ms = (time.perf_counter() - started) * 1000.0
        log.info("Laya warm on %s in %.0f ms", device or "default device", _STATE.load_ms)
    except Exception as exc:  # noqa: BLE001 — surfaced in status, never raised into a turn
        with _LOCK:
            _AGENT = None
            _STATE.warm = False
            _STATE.loading = False
            _STATE.load_error = str(exc)[:400]
        log.warning("Laya warm-up failed: %s", exc)


def _calibrate(agent: Any) -> None:
    """Measure Laya against rules on labeled fixtures before it serves any class."""
    from .. import calibration

    def _answer(state: dict[str, Any], questions: list[Question], _decision_class: str) -> dict[str, Answer]:
        payload, effective = _to_laya_questions(questions, state)
        return _from_laya_answers(agent.predict(state, payload).get("answers") or {}, effective)

    try:
        calibration.calibrate(_answer)
    except Exception as exc:  # noqa: BLE001 — uncalibrated Laya stays gated by confidence/bounds
        log.warning("Laya calibration failed: %s", exc)


def _start_load() -> None:
    global _LOAD_THREAD
    with _LOCK:
        if _STATE.loading or (_STATE.warm and _AGENT is not None):
            return
        _STATE.loading = True
        _STATE.load_error = ""
    _LOAD_THREAD = threading.Thread(target=_load_agent, name="laya-warm", daemon=True)
    _LOAD_THREAD.start()


def wait_until_warm(timeout_s: float = 120.0) -> bool:
    thread = _LOAD_THREAD
    if thread is not None:
        thread.join(timeout=timeout_s)
    with _LOCK:
        return _STATE.warm


def enable(*, warm: bool = True, allow_fixture: bool = True) -> dict[str, Any]:
    ok, reason, manifest = pins.verify_installed(allow_fixture=allow_fixture)
    if not ok:
        raise RuntimeError(reason or "Laya install invalid")
    fixture = bool((manifest or {}).get("fixture"))
    with _LOCK:
        _STATE.enabled = True
        _STATE.fixture = fixture
        _STATE.manifest = dict(manifest or {})
        _STATE.bind = "127.0.0.1"
        _STATE.port = None
        if fixture:
            _STATE.warm = bool(warm)
            _STATE.version = "laya-fixture"
            _STATE.loaded_at = time.time()
    if not fixture:
        _persist_enabled(True, bool(warm))
        if warm:
            _start_load()
    return status()


def install_and_enable(*, warm: bool = True, token: str | None = None) -> dict[str, Any]:
    pins.install_managed(token=token)
    return enable(warm=warm, allow_fixture=False)


def disable() -> dict[str, Any]:
    global _AGENT
    with _LOCK:
        was_fixture = _STATE.fixture
        _STATE.enabled = False
        _STATE.warm = False
        _AGENT = None
    if not was_fixture:
        _persist_enabled(False, False)
    return status()


def restore_on_startup() -> dict[str, Any] | None:
    """Re-enable and warm a managed install the owner previously enabled."""
    flag = pins.install_root() / _ENABLED_FLAG
    if not flag.is_file():
        return None
    try:
        data = json.loads(flag.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if not data.get("enabled"):
        return None
    try:
        return enable(warm=bool(data.get("warm", True)), allow_fixture=False)
    except RuntimeError as exc:
        log.warning("Laya not restored at startup: %s", exc)
        return None


def is_ready() -> bool:
    with _LOCK:
        if not _STATE.enabled or not _STATE.warm:
            return False
        if not _STATE.fixture and _AGENT is None:
            return False
        if _STATE.busy:
            return False
    ok, _reason, _manifest = pins.verify_installed(allow_fixture=True)
    return ok


# ---------------------------------------------------------------------------
# Question / answer translation


def _state_text(state: dict[str, Any]) -> str:
    return json.dumps(state, ensure_ascii=False, sort_keys=True, default=str)


def _shortlist(question: Question, state: dict[str, Any]) -> Question:
    if len(question.choices) <= MAX_CHOICE_OPTIONS:
        return question
    hints = {
        str(state.get(key) or "")
        for key in ("preferred_profile", "active_persona", "suggested_operation", "suggested_target_id")
    }
    haystack = _state_text(state).lower()
    words = set(re.findall(r"[^\W_]{3,}", haystack))
    criteria = question.choice_criteria()

    def _score(item: tuple[int, str]) -> tuple[float, int]:
        index, choice = item
        if choice in hints or choice == "none":
            return (-1e9, index)
        named = 100.0 if re.search(rf"(?<![\w-]){re.escape(choice.lower())}(?![\w-])", haystack) else 0.0
        tokens = set(re.findall(r"[^\W_]{3,}", f"{choice} {criteria[choice]}".lower()))
        return (-(named + len(tokens & words)), index)

    ranked = sorted(enumerate(question.choices), key=_score)[:MAX_CHOICE_OPTIONS]
    keep = [choice for _index, choice in sorted(ranked)]
    return Question(
        id=question.id,
        type=question.type,
        prompt=question.prompt,
        choices=tuple(keep),
        min_score=question.min_score,
        max_score=question.max_score,
        descriptions=tuple(criteria[choice] for choice in keep),
    )


def _to_laya_questions(questions: list[Question], state: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Question]]:
    payload: dict[str, Any] = {}
    effective: dict[str, Question] = {}
    for question in questions:
        q = _shortlist(question, state) if question.type == "choice" else question
        effective[q.id] = q
        if q.type == "choice":
            payload[q.id] = {"type": "choice", "instructions": q.prompt, "criteria": q.choice_criteria()}
        elif q.type == "score":
            payload[q.id] = {
                "type": "score",
                "instructions": q.prompt,
                "criteria": [
                    f"level {i + 1} of {SCORE_LEVELS} ({'lowest' if i == 0 else 'highest' if i == SCORE_LEVELS - 1 else 'intermediate'})"
                    for i in range(SCORE_LEVELS)
                ],
            }
        else:
            payload[q.id] = {"type": "noul", "instructions": q.prompt}
    return payload, effective


def _from_laya_answers(raw: dict[str, Any], effective: dict[str, Question]) -> dict[str, Answer]:
    answers: dict[str, Answer] = {}
    for qid, question in effective.items():
        row = raw.get(qid)
        if not isinstance(row, dict):
            continue
        confidence = row.get("answer_confidence", row.get("confidence"))
        try:
            conf = float(confidence) if confidence is not None else None
        except (TypeError, ValueError):
            conf = None
        if question.type == "choice":
            choice = row.get("choice")
            if isinstance(choice, str) and choice in question.choices:
                answers[qid] = Answer(qid, "choice", choice, conf)
        elif question.type == "score":
            try:
                level = float(row.get("score"))
            except (TypeError, ValueError):
                continue
            fraction = max(0.0, min(1.0, level / (SCORE_LEVELS - 1)))
            value = question.min_score + fraction * (question.max_score - question.min_score)
            answers[qid] = Answer(qid, "score", value, conf)
        else:
            try:
                noul = float(row.get("noul"))
            except (TypeError, ValueError):
                continue
            if question.type == "boolean":
                answers[qid] = Answer(qid, "boolean", noul >= 0.5, conf)
            else:
                answers[qid] = Answer(qid, "noul", max(0.0, min(1.0, noul)), conf)
    return answers


# ---------------------------------------------------------------------------
# Input sizing


# Beyond this the exact count cannot change the decision (it is far over one window);
# a scaled sample keeps measuring a multi-megabyte paste cheap.
_EXACT_COUNT_MAX_CHARS = 40_000


def _token_counter() -> Callable[[str], int] | None:
    agent = _AGENT
    tok = getattr(agent, "tok", None) if agent is not None else None
    if tok is None:
        return None

    def _count(text: str) -> int:
        sample = text if len(text) <= _EXACT_COUNT_MAX_CHARS else text[:_EXACT_COUNT_MAX_CHARS]
        # verbose=False: measuring a long paste is intentional, not an overflow.
        ids = tok(sample, add_special_tokens=False, verbose=False)["input_ids"]
        if sample is text:
            return len(ids)
        return int(len(ids) * len(text) / len(sample)) + 1

    return _count


def state_token_budget() -> int:
    return pins.LAYA_MAX_LEN - pins.LAYA_HEAD_MAX_LEN - _STATE_TOKEN_MARGIN


def plan_input(state: dict[str, Any], *, deadline_ms: float) -> dict[str, Any]:
    """Measure the state and pick ``single`` / ``windowed`` / ``compressed``."""
    text = _state_text(state)
    counter = _token_counter()
    tokens = count_tokens(text, counter)
    budget = state_token_budget()
    if tokens <= budget:
        return {"strategy": "single", "tokens": tokens, "budget": budget}
    windows = -(-tokens // budget)
    with _LOCK:
        per_window = _STATE.window_ms_ewma
    if per_window is not None and windows * per_window <= deadline_ms * 0.8:
        return {"strategy": "windowed", "tokens": tokens, "budget": budget, "windows": windows}
    return {"strategy": "compressed", "tokens": tokens, "budget": budget, "windows": windows}


def _compress_state(state: dict[str, Any], budget_tokens: int, focus: str) -> dict[str, Any]:
    """Shrink string fields (largest first) until the serialized state fits the token budget."""
    counter = _token_counter()
    out = dict(state)
    for _ in range(6):
        tokens = count_tokens(_state_text(out), counter)
        if tokens <= budget_tokens:
            break
        strings = sorted(
            ((key, value) for key, value in out.items() if isinstance(value, str) and len(value) > 120),
            key=lambda item: len(item[1]),
            reverse=True,
        )
        if not strings:
            break
        key, value = strings[0]
        ratio = budget_tokens / max(1, tokens)
        out[key] = compress_text(value, max(120, int(len(value) * ratio * 0.9)), focus=focus).text
    return out


# ---------------------------------------------------------------------------
# Inference


def _fixture_decide(state: dict[str, Any], questions: list[Question]) -> dict[str, Answer]:
    """Labeled lexical stand-in for tests; never presented as the encoder."""
    prompt = str(state.get("user_message") or state.get("prompt") or "")
    tokens = set(re.findall(r"[a-z0-9_]{3,}", prompt.lower()))
    answers: dict[str, Answer] = {}
    for question in questions:
        if question.type == "choice":
            best, best_score = question.choices[0], -1.0
            for choice in question.choices:
                score = float(len(tokens & set(re.findall(r"[a-z0-9_]{3,}", choice.lower()))))
                if choice in {state.get("preferred_profile"), state.get("suggested_operation"), state.get("suggested_target_id")}:
                    score += 5
                if score > best_score:
                    best, best_score = choice, score
            answers[question.id] = Answer(question.id, "choice", best, 0.55 if best_score <= 0 else min(0.95, 0.55 + 0.1 * best_score))
        elif question.type == "score":
            excerpts = state.get("excerpts")
            excerpt = str(excerpts.get(question.id) or "") if isinstance(excerpts, dict) else ""
            hay = set(re.findall(r"[a-z0-9_]{3,}", excerpt.lower()))
            overlap = (len(tokens & hay) / max(1, len(tokens))) if tokens else 0.2
            value = question.min_score + (question.max_score - question.min_score) * max(0.0, min(1.0, overlap))
            answers[question.id] = Answer(question.id, "score", value, 0.7)
        elif question.type == "boolean":
            # Terminal/state flags follow explicit state; never inferred from goal wording.
            answers[question.id] = Answer(question.id, "boolean", bool(state.get(question.id)), 0.6)
        else:
            answers[question.id] = Answer(question.id, "noul", 0.45, 0.55)
    return answers


def _run_agent(state: dict[str, Any], payload: dict[str, Any], strategy: str) -> tuple[dict[str, Any], float, int]:
    agent = _AGENT
    if agent is None:
        raise RuntimeError("Laya agent is not loaded")
    started = time.perf_counter()
    if strategy == "windowed":
        result = agent.predict_long(state, payload)
    else:
        result = agent.predict(state, payload)
    elapsed = (time.perf_counter() - started) * 1000.0
    usage = result.get("usage") if isinstance(result, dict) else {}
    windows = int((usage or {}).get("windows") or 1)
    return result, elapsed, windows


def decide_local(
    *,
    state: dict[str, Any],
    questions: list[Question],
    decision_class: str,
    deadline_ms: float,
) -> tuple[dict[str, Answer], float, bool]:
    if not is_ready():
        raise RuntimeError("Laya runtime is not warm/enabled or is busy")
    started = time.perf_counter()
    with _LOCK:
        fixture = _STATE.fixture
    if _DECIDE_FN is not None or fixture:
        if _DECIDE_FN is not None:
            answers = _DECIDE_FN(state=state, questions=questions, decision_class=decision_class)
        else:
            answers = _fixture_decide(state, questions)
        elapsed = (time.perf_counter() - started) * 1000.0
        if elapsed > deadline_ms:
            raise TimeoutError(f"Laya fixture exceeded deadline ({elapsed:.1f}ms > {deadline_ms}ms)")
        with _LOCK:
            _STATE.last_infer_ms = elapsed
        return answers, elapsed, True

    plan = plan_input(state, deadline_ms=deadline_ms)
    focus = " ".join(q.prompt for q in questions)
    model_state = state if plan["strategy"] != "compressed" else _compress_state(state, plan["budget"], focus)
    payload, effective = _to_laya_questions(questions, model_state)

    with _LOCK:
        if _STATE.busy:
            raise RuntimeError("Laya busy with a previous request")
        _STATE.busy = True

    def _job() -> tuple[dict[str, Any], float, int]:
        try:
            return _run_agent(model_state, payload, plan["strategy"])
        finally:
            with _LOCK:
                _STATE.busy = False

    future: Future = _executor().submit(_job)
    remaining_s = max(0.001, (deadline_ms - (time.perf_counter() - started) * 1000.0) / 1000.0)
    try:
        raw, infer_ms, windows = future.result(timeout=remaining_s)
    except FutureTimeout as exc:
        future.add_done_callback(_record_late_timing)
        raise TimeoutError(
            f"Laya exceeded deadline ({deadline_ms:.0f}ms, strategy={plan['strategy']}, tokens={plan['tokens']})"
        ) from exc
    _record_timing(infer_ms, windows)
    answers = _from_laya_answers((raw or {}).get("answers") or {}, effective)
    elapsed = (time.perf_counter() - started) * 1000.0
    return answers, elapsed, False


def _record_timing(infer_ms: float, windows: int) -> None:
    per_window = infer_ms / max(1, windows)
    with _LOCK:
        _STATE.last_infer_ms = infer_ms
        prior = _STATE.window_ms_ewma
        _STATE.window_ms_ewma = per_window if prior is None else 0.8 * prior + 0.2 * per_window


def _record_late_timing(future: Future) -> None:
    """A timed-out pass still teaches the planner how slow this host is."""
    try:
        _raw, infer_ms, windows = future.result()
    except Exception:  # noqa: BLE001
        return
    _record_timing(infer_ms, windows)


def decide_document(
    text: str,
    questions: list[Question],
    *,
    deadline_ms: float = 15000.0,
    extra_state: dict[str, Any] | None = None,
) -> dict[str, Answer]:
    """Long-document decision outside the hot path (e.g. owner-chat intake).

    Uses the same sizing: windowed scan when affordable, otherwise compressed.
    Raises on unavailability/timeout so callers can fall back to rules.
    """
    state = {"document": text, **(extra_state or {})}
    answers, _elapsed, _fixture = decide_local(
        state=state,
        questions=questions,
        decision_class="intake_strategy",
        deadline_ms=deadline_ms,
    )
    return answers
