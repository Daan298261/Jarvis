"""Spoken progress and outcomes for agent tasks, in plain language.

While a task runs the owner hears short updates ("Opening Steam.") instead of
silence; when it ends they hear one natural sentence about what happened. Tool
output and raw errors are never spoken: failures are mapped to what a person
would say ("I couldn't find an app called Steam on this PC.").
"""

from __future__ import annotations

import re
import threading
import time
from dataclasses import dataclass, field
from typing import Any

from ..tts.speech_safe import speech_safe

PROGRESS_MIN_GAP_S = 6.0
MAX_PROGRESS_LINES = 6
OUTCOME_MAX_CHARS = 240


@dataclass
class _TaskVoice:
    last_at: float = 0.0
    last_phrase: str = ""
    spoken: int = 0
    phrases: set[str] = field(default_factory=set)


_LOCK = threading.Lock()
_TASKS: dict[str, _TaskVoice] = {}


def _app_name(arguments: dict[str, Any]) -> str:
    name = str(arguments.get("name") or "").strip()
    return " ".join(word.capitalize() if word.islower() else word for word in name.split())


def progress_phrase(tool: str, arguments: dict[str, Any] | None) -> str | None:
    """One natural sentence describing what Jarvis is about to do, or None to stay quiet."""
    args = arguments or {}
    action = str(args.get("action") or "").strip().lower()
    name = (tool or "").strip().lower()
    if name == "apps":
        app = _app_name(args) or "that app"
        return {
            "open": f"Opening {app}.",
            "close": f"Closing {app}.",
            "find": f"Looking for {app}.",
            "running": f"Checking whether {app} is running.",
        }.get(action or "open")
    if name == "filesystem":
        if action in {"write", "append", "edit", "replace", "create"}:
            return "Saving that now."
        if action in {"list", "tree", "search", "find"}:
            return "Looking through the folder."
        if action in {"read", "read_lines"}:
            return "Reading that file."
        return None
    return {
        "terminal": "Running that on the PC.",
        "python": "Working it out.",
        "browser": "Checking online.",
        "browser_use": "Checking online.",
        "web_fetch": "Checking online.",
        "git": "Checking the repository.",
        "verify_code": "Running the tests.",
        "desktop": "Working in the app.",
        "reflex_computer_use": "Working in the app.",
        "ufo": "Working in the app.",
        "screenshot": "Taking a look at the screen.",
        "office": "Working on the document.",
    }.get(name)


def should_speak_progress(task_id: str, phrase: str, *, now: float | None = None) -> bool:
    """Throttle: a gap between lines, no repeats, a cap per task."""
    stamp = time.monotonic() if now is None else now
    with _LOCK:
        voice = _TASKS.setdefault(task_id, _TaskVoice())
        if voice.spoken >= MAX_PROGRESS_LINES or phrase in voice.phrases:
            return False
        if voice.spoken and stamp - voice.last_at < PROGRESS_MIN_GAP_S:
            return False
        voice.last_at = stamp
        voice.last_phrase = phrase
        voice.spoken += 1
        voice.phrases.add(phrase)
        return True


def forget_task(task_id: str) -> None:
    with _LOCK:
        _TASKS.pop(task_id, None)


_FAILURE_PATTERNS: tuple[tuple[re.Pattern[str], str], ...] = (
    (re.compile(r"No installed app matches '([^']+)'", re.I), "I couldn't find an app called {0} on this PC."),
    (re.compile(r"No running app matches '([^']+)'", re.I), "{0} doesn't seem to be running."),
    (re.compile(r"(.+?) did not start", re.I), "I asked Windows to open {0}, but it didn't start."),
    (re.compile(r"access denied|needs the elevated backend|requires administrator", re.I),
     "Windows wouldn't let me do that without administrator rights."),
    (re.compile(r"outside allowed directories", re.I), "That location is outside what I'm allowed to use."),
    (re.compile(r"needs your approval|requires? (?:owner )?approval|permission", re.I),
     "I need your permission before I do that."),
    (re.compile(r"step limit|same problem|identical .*blocked", re.I),
     "I couldn't finish that; I kept running into the same problem."),
    (re.compile(r"timed out|timeout|took too long", re.I), "That took too long, so I stopped."),
    (re.compile(r"jinja|prompt template|no user query|returned no text|model is not loaded|inference|context", re.I),
     "The language model stopped responding properly, so I couldn't finish that."),
    (re.compile(r"laya cancelled|harm check was unsure", re.I),
     "I stopped that because it looked harmful."),
    (re.compile(r"cancel", re.I), "Okay, I stopped."),
)


def plain_failure(error: str) -> str:
    text = (error or "").strip()
    for pattern, template in _FAILURE_PATTERNS:
        match = pattern.search(text)
        if match:
            groups = [group.strip() for group in match.groups() if group]
            return template.format(*groups) if groups else template
    return "I couldn't finish that."


def _first_sentences(text: str, limit: int = OUTCOME_MAX_CHARS) -> str:
    spoken = speech_safe(text)
    if not spoken:
        return ""
    sentences = re.split(r"(?<=[.!?])\s+", spoken)
    out = ""
    for sentence in sentences:
        piece = sentence.strip()
        if not piece:
            continue
        candidate = f"{out} {piece}".strip() if out else piece
        if out and len(candidate) > limit:
            break
        out = candidate
        if len(out) >= limit:
            break
    if out and out[-1] not in ".!?":
        out += "."
    return out[:limit]


def outcome_phrase(
    *,
    success: bool,
    result: str = "",
    error: str = "",
    cancelled: bool = False,
) -> str:
    if cancelled:
        return "Okay, I stopped."
    if not success:
        spoken = speech_safe(plain_failure(error or result))
        return spoken or "I couldn't finish that."
    spoken = _first_sentences(result)
    return spoken or "That's done."


async def speak_progress(task_id: str, tool: str, arguments: dict[str, Any] | None = None) -> None:
    phrase = progress_phrase(tool, arguments)
    if not phrase or not should_speak_progress(task_id, phrase):
        return
    spoken = speech_safe(phrase)
    if not spoken:
        return
    from .chat_delivery import publish_owner_text

    await publish_owner_text(spoken, title="Jarvis", source="task_chat", speak=True)


async def speak_outcome(
    task_id: str,
    *,
    success: bool,
    result: str = "",
    error: str = "",
    cancelled: bool = False,
) -> None:
    phrase = outcome_phrase(success=success, result=result, error=error, cancelled=cancelled)
    forget_task(task_id)
    spoken = speech_safe(phrase)
    if not spoken:
        return
    from .chat_delivery import publish_owner_text

    await publish_owner_text(spoken, title="Jarvis", source="task_chat", speak=True)
