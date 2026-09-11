from __future__ import annotations

import re
from typing import Literal

from ..agent.compaction import WORKING_STATE_MARKER
from .reply_class import ReplySpeechClass, classify_reply_for_speech

SpeakSource = Literal[
    "chat",
    "owner_chat",
    "task_chat",
    "launch",
    "greeting",
    "think_aloud",
    "preview",
    "direct",
]

_URL_RE = re.compile(r"https?://[^\s\])>]+", re.IGNORECASE)
_FENCED_CODE_RE = re.compile(r"```[\s\S]*?```", re.MULTILINE)
_INLINE_CODE_RE = re.compile(r"`[^`\n]+`")
_PLAN_BOARD_RE = re.compile(
    r"(?im)^\s*(?:PLAN|END STATE|ACCEPTANCE|WORKING STATE|THOUGHT PROCESS|SHOW WORK)\s*:.*$",
)
_TOOL_DUMP_RE = re.compile(r"(?im)^\s*(?:Tool|tool)\s+(?:output|result|call)\s*:.*$")
_FINAL_REPLY_PREFIX_RE = re.compile(
    r"(?is)^\s*(?:final\s+(?:reply|answer)|assistant)\s*:\s*",
)
_REASONING_LINE_RE = re.compile(
    r"(?im)^\s*(?:reasoning|thought\s+process|internal\s+monologue|chain\s+of\s+thought)\s*:.*$",
)
_ThinkOpen = "<" + "think"
_ThinkClose = "</" + "think>"
_RedactedClose = "</" + "redacted_thinking>"
_THINK_BLOCK_RE = re.compile(
    "(?is)" + _ThinkOpen + r"[^>]*>.*?(?:" + _ThinkClose + "|" + _RedactedClose + ")",
)
_THINK_OPEN_RE = re.compile("(?is)" + _ThinkOpen + r"[^>]*>.*$")
_MD_LINK_RE = re.compile(r"\[([^\]]+)\]\([^)]+\)")
_ORPHAN_MD_RESIDUE_RE = re.compile(r"\[[^\]]*\]|\]\([^)]*\)")
_TRACEBACK_BLOCK_RE = re.compile(
    r"(?is)Traceback \(most recent call last\):[\s\S]*?(?:\n\n|\Z)",
)
_STACK_LINE_RE = re.compile(r'^\s*File "[^"]+", line \d+.*$', re.MULTILINE)

_ONES = (
    "zero",
    "one",
    "two",
    "three",
    "four",
    "five",
    "six",
    "seven",
    "eight",
    "nine",
    "ten",
    "eleven",
    "twelve",
    "thirteen",
    "fourteen",
    "fifteen",
    "sixteen",
    "seventeen",
    "eighteen",
    "nineteen",
)
_TENS = ("", "", "twenty", "thirty", "forty", "fifty", "sixty", "seventy", "eighty", "ninety")


def _int_to_words(n: int) -> str:
    if n < 0:
        return str(n)
    if n < 20:
        return _ONES[n]
    if n < 100:
        tens, ones = divmod(n, 10)
        if ones == 0:
            return _TENS[tens]
        return f"{_TENS[tens]}-{_ONES[ones]}"
    if n < 1000:
        hundreds, rem = divmod(n, 100)
        head = f"{_ONES[hundreds]} hundred"
        if rem == 0:
            return head
        return f"{head} {_int_to_words(rem)}"
    return str(n)


def _strip_plan_and_working_state(text: str) -> str:
    if WORKING_STATE_MARKER in text:
        text = text.split(WORKING_STATE_MARKER, 1)[0]
    lines = []
    for line in text.splitlines():
        if _PLAN_BOARD_RE.match(line):
            continue
        if _TOOL_DUMP_RE.match(line):
            continue
        lines.append(line)
    return "\n".join(lines)


def _strip_markdown_emphasis_and_lists(text: str) -> str:
    cleaned = text
    cleaned = re.sub(r"\*\*([^*]+)\*\*", r"\1", cleaned)
    cleaned = re.sub(r"\*([^*]+)\*", r"\1", cleaned)
    cleaned = re.sub(r"__([^_]+)__", r"\1", cleaned)
    cleaned = re.sub(r"_([^_]+)_", r"\1", cleaned)
    cleaned = re.sub(r"\*+", " ", cleaned)
    cleaned = re.sub(r"(?m)^\s*[-*+]\s+", "", cleaned)
    cleaned = re.sub(r"(?m)^\s*\d+\.\s+", "", cleaned)
    return cleaned


def _rewrite_numbers_for_social_speech(text: str) -> str:
    def _time_match(match: re.Match[str]) -> str:
        hour = int(match.group(1))
        minute = int(match.group(2))
        if minute == 0 and hour >= 13:
            return f"{_int_to_words(hour)} hundred hours"
        if minute == 0 and 1 <= hour <= 12:
            return f"{_int_to_words(hour)} o'clock"
        if minute == 0:
            return f"{_int_to_words(hour)} hundred hours"
        return f"{_int_to_words(hour)} {_int_to_words(minute)}"

    cleaned = re.sub(r"\b(\d{1,2}):(\d{2})\b", _time_match, text)

    def _number_match(match: re.Match[str]) -> str:
        return _int_to_words(int(match.group(0)))

    cleaned = re.sub(r"\b\d{1,3}\b", _number_match, cleaned)
    cleaned = re.sub(r"°C\b", " degrees Celsius", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"°F\b", " degrees Fahrenheit", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"°", " degrees", cleaned)
    return cleaned


def rewrite_for_speech(text: str, *, reply_class: ReplySpeechClass) -> str:
    """Post-filter rewrite: social gets spoken numbers; both paths lose vocalized markup."""
    cleaned = _strip_markdown_emphasis_and_lists(text)
    if reply_class == "social":
        cleaned = _rewrite_numbers_for_social_speech(cleaned)
    cleaned = re.sub(r"\s+", " ", cleaned)
    return cleaned.strip()


def filter_text_for_speech(
    text: str,
    *,
    source: str = "chat",
    reply_class: ReplySpeechClass | None = None,
    user_prompt: str | None = None,
) -> str:
    """Keep only speakable conversational text (RFC-0070 / RFC-0075).

    Preview and explicit direct speak endpoints may bypass heavy filtering.
    """
    cleaned = (text or "").strip()
    if not cleaned:
        return ""

    if source in {"preview", "direct"}:
        return cleaned

    speech_class = reply_class or classify_reply_for_speech(cleaned, user_prompt=user_prompt)

    cleaned = _strip_plan_and_working_state(cleaned)
    cleaned = _FINAL_REPLY_PREFIX_RE.sub("", cleaned)
    cleaned = _THINK_BLOCK_RE.sub("", cleaned)
    cleaned = _THINK_OPEN_RE.sub("", cleaned)
    cleaned = _TRACEBACK_BLOCK_RE.sub("", cleaned)
    cleaned = _STACK_LINE_RE.sub("", cleaned)
    cleaned = _FENCED_CODE_RE.sub("", cleaned)
    cleaned = _INLINE_CODE_RE.sub("", cleaned)
    cleaned = _MD_LINK_RE.sub(lambda m: m.group(1), cleaned)
    cleaned = _URL_RE.sub("", cleaned)
    cleaned = _ORPHAN_MD_RESIDUE_RE.sub("", cleaned)
    cleaned = re.sub(r"\(\s*\)", "", cleaned)

    if source in {"chat", "owner_chat", "task_chat"}:
        lines = []
        for line in cleaned.splitlines():
            if _REASONING_LINE_RE.match(line):
                continue
            lines.append(line)
        cleaned = "\n".join(lines)

    if source not in {"think_aloud", "greeting", "launch"}:
        cleaned = re.sub(r"(?im)^#+\s.*$", "", cleaned)
        cleaned = re.sub(r"(?im)^\s*[-*]\s+(?:step|todo|action)\b.*$", "", cleaned)

    cleaned = re.sub(r"\n{3,}", "\n\n", cleaned)
    cleaned = re.sub(r"[ \t]{2,}", " ", cleaned)
    cleaned = cleaned.strip()

    if not cleaned:
        return ""

    return rewrite_for_speech(cleaned, reply_class=speech_class)
