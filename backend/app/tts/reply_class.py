from __future__ import annotations

import re
from typing import Callable, Literal

ReplySpeechClass = Literal["social", "technical"]

_CLASSIFIER_HOOK: Callable[[str, str | None], ReplySpeechClass | None] | None = None

_FENCED_CODE_RE = re.compile(r"```")
_TRACEBACK_RE = re.compile(r"Traceback \(most recent call last\)", re.IGNORECASE)
_FILE_LINE_TRACE_RE = re.compile(r'^\s*File "[^"]+", line \d+', re.MULTILINE)
_PLAN_SHAPE_RE = re.compile(
    r"(?im)^\s*(?:PLAN|END STATE|ACCEPTANCE|WORKING STATE|THOUGHT PROCESS)\s*:",
)
_TOOL_DUMP_SHAPE_RE = re.compile(
    r"(?im)^\s*(?:Tool|tool)\s+(?:output|result|call)\s*:",
)
_SOCIAL_USER_HINTS = re.compile(
    r"(?i)\b("
    r"weather|temperature|forecast|rain|sunny|cloud|degrees|"
    r"hello|hi\b|hey\b|good morning|good afternoon|good evening|"
    r"how are you|what time|time is it|tell me a joke|thanks|thank you"
    r")\b",
)
_TECHNICAL_BODY_HINTS = re.compile(
    r"(?i)\b("
    r"traceback|stack trace|syntaxerror|typeerror|exception|"
    r"```|HTTP/\d|api error|status code \d{3}|"
    r"def\s+\w+\(|class\s+\w+|import\s+\w+"
    r")\b",
)


def register_reply_classifier_hook(
    hook: Callable[[str, str | None], ReplySpeechClass | None] | None,
) -> None:
    """Optional tiny classifier; when absent or when it returns None, heuristics apply."""
    global _CLASSIFIER_HOOK
    _CLASSIFIER_HOOK = hook


def classify_reply_for_speech(
    text: str,
    *,
    user_prompt: str | None = None,
) -> ReplySpeechClass:
    """Classify assistant output before TTS (RFC-0075). Unit-testable heuristics."""
    cleaned = (text or "").strip()
    if not cleaned:
        return "social"

    if _CLASSIFIER_HOOK is not None:
        try:
            hooked = _CLASSIFIER_HOOK(cleaned, user_prompt)
        except Exception:
            hooked = None
        if hooked in {"social", "technical"}:
            return hooked

    if (
        _TRACEBACK_RE.search(cleaned)
        or _FILE_LINE_TRACE_RE.search(cleaned)
        or _FENCED_CODE_RE.search(cleaned)
        or _PLAN_SHAPE_RE.search(cleaned)
        or _TOOL_DUMP_SHAPE_RE.search(cleaned)
        or _TECHNICAL_BODY_HINTS.search(cleaned)
    ):
        return "technical"

    if len(cleaned) > 1400:
        return "technical"

    user = (user_prompt or "").strip()
    if user and _SOCIAL_USER_HINTS.search(user):
        if len(cleaned) <= 900 and cleaned.count("```") == 0:
            return "social"

    if len(cleaned) <= 420 and cleaned.count("```") == 0:
        lines = [line for line in cleaned.splitlines() if line.strip()]
        if len(lines) <= 8:
            return "social"

    return "technical"
