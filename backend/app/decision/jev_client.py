"""Real TypeSafe System One HTTP client (RFC-0116). Never reports connected without a live/fixture HTTP 200."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable

import httpx

TYPESAFE_SYSTEMONE_URL = "https://api.typesafe.ai/v1/systemone"
TYPESAFE_MODEL = "jev-latest"
PROBE_TIMEOUT_S = 8.0
DECIDE_TIMEOUT_S = 12.0

HttpPost = Callable[[str, dict[str, str], dict[str, Any], float], tuple[int, dict[str, Any] | None, str]]
_HTTP_POST: HttpPost | None = None
_FIXTURE_LABEL = False


class JevHttpError(RuntimeError):
    def __init__(self, message: str, *, status_code: int | None = None) -> None:
        super().__init__(message)
        self.status_code = status_code


def set_http_post(fn: HttpPost | None, *, fixture: bool = False) -> None:
    """Tests inject a labeled fixture transport. Production never uses this."""
    global _HTTP_POST, _FIXTURE_LABEL
    _HTTP_POST = fn
    _FIXTURE_LABEL = bool(fn) and fixture


def using_labeled_fixture() -> bool:
    return bool(_FIXTURE_LABEL and _HTTP_POST is not None)


def reset_http_post() -> None:
    set_http_post(None, fixture=False)


def _default_http_post(
    url: str,
    headers: dict[str, str],
    body: dict[str, Any],
    timeout: float,
) -> tuple[int, dict[str, Any] | None, str]:
    try:
        with httpx.Client(timeout=timeout, follow_redirects=True) as client:
            response = client.post(url, headers=headers, json=body)
    except httpx.TimeoutException as exc:
        raise JevHttpError("TypeSafe Jev probe timed out", status_code=None) from exc
    except httpx.HTTPError as exc:
        raise JevHttpError(f"TypeSafe Jev unreachable: {exc}", status_code=None) from exc
    payload: dict[str, Any] | None = None
    try:
        parsed = response.json()
        if isinstance(parsed, dict):
            payload = parsed
    except ValueError:
        payload = None
    return response.status_code, payload, (response.text or "")[:400]


def post_systemone(
    *,
    api_key: str,
    state: dict[str, Any],
    questions: dict[str, Any],
    timeout: float = DECIDE_TIMEOUT_S,
) -> dict[str, Any]:
    key = str(api_key or "").strip()
    if not key:
        raise JevHttpError("TypeSafe API key is missing", status_code=401)
    headers = {
        "Authorization": f"Bearer {key}",
        "Content-Type": "application/json",
        "Accept": "application/json",
    }
    body = {"model": TYPESAFE_MODEL, "state": state, "questions": questions}
    poster = _HTTP_POST or _default_http_post
    status, payload, raw = poster(TYPESAFE_SYSTEMONE_URL, headers, body, timeout)
    if status in {401, 403}:
        raise JevHttpError("TypeSafe rejected the API key", status_code=status)
    if status in {429, 529}:
        raise JevHttpError(f"TypeSafe overloaded ({status})", status_code=status)
    if status >= 400:
        detail = ""
        if isinstance(payload, dict):
            detail = str(payload.get("error") or payload.get("message") or "")[:200]
        raise JevHttpError(detail or f"TypeSafe HTTP {status}: {raw}", status_code=status)
    if not isinstance(payload, dict):
        raise JevHttpError("TypeSafe returned a non-object body", status_code=status)
    answers = payload.get("answers") if isinstance(payload.get("answers"), dict) else payload
    if not isinstance(answers, dict) or not answers:
        raise JevHttpError("TypeSafe response had no typed answers", status_code=status)
    return {
        "status_code": status,
        "model": str(payload.get("model") or TYPESAFE_MODEL),
        "answers": answers,
        "raw": payload,
        "fixture": using_labeled_fixture(),
    }


def probe_key(api_key: str) -> dict[str, Any]:
    return post_systemone(
        api_key=api_key,
        state={"probe": True, "product": "jarvis"},
        questions={"ready": {"type": "noul", "question": "Is this TypeSafe Jev session usable?"}},
        timeout=PROBE_TIMEOUT_S,
    )


@dataclass(frozen=True)
class ParsedAnswer:
    question_id: str
    primitive: str
    value: Any
    confidence: float | None


def parse_answer(question_id: str, payload: Any) -> ParsedAnswer | None:
    if not isinstance(payload, dict):
        return None
    primitive = str(payload.get("type") or "").strip().lower()
    confidence_raw = payload.get("confidence")
    try:
        confidence = float(confidence_raw) if confidence_raw is not None else None
    except (TypeError, ValueError):
        confidence = None
    if primitive == "choice":
        choice = str(payload.get("choice") or "").strip()
        if not choice:
            return None
        return ParsedAnswer(question_id, "choice", choice, confidence)
    if primitive == "score":
        try:
            score = float(payload.get("score"))
        except (TypeError, ValueError):
            return None
        return ParsedAnswer(question_id, "score", score, confidence)
    if primitive == "noul":
        try:
            noul = float(payload.get("noul"))
        except (TypeError, ValueError):
            return None
        return ParsedAnswer(question_id, "noul", noul, confidence)
    return None
