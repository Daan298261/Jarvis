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
_TOOL_XML_BLOCK_RE = re.compile(r"(?is)<\s*tool_call\b[^>]*>.*?<\s*/\s*tool_call\s*>")
_TOOL_XML_UNCLOSED_RE = re.compile(r"(?is)<\s*tool_call\b[^>]*>.*\Z")
_FUNCTION_EQ_TAG_RE = re.compile(r"(?is)<\s*/?\s*function\s*=[^>]*>")
_PARAMETER_EQ_TAG_RE = re.compile(r"(?is)<\s*/?\s*parameter\s*=[^>]*>")
_ARG_XML_TAG_RE = re.compile(r"(?is)<\s*/?\s*arg_(?:key|value)\s*>[^<]*")
_GENERIC_TAG_RE = re.compile(r"</?[A-Za-z][\w:.-]*(?:\s+[^<>]*)?>")
_JSON_TOOL_BLOB_RE = re.compile(
    r"(?is)\{\s*\"(?:name|function)\"\s*:\s*\"[^\"]+\".*?\}",
)
_TOOL_DEBRIS_RE = re.compile(
    r"(?i)\b(?:tool[_\s-]*call|function\s*=\s*\w+|parameter\s*=\s*\w+|arg_key|arg_value)\b",
)
_SHORT_ACK_RE = re.compile(
    r"(?i)^(one moment|just a moment|allow me a moment|let me check|"
    r"i(?:'|')?ll check|checking now|very well(?:[, ]+sir)?|"
    r"certainly|of course|right away|shall i (?:continue|proceed))[.!?]?$"
)
_CODEISH_LINE_RE = re.compile(
    r"(?x)^\s*(?:"
    r"(?:def|class|import|from|return)\s+\S"
    r"|[\$>]?\s*(?:git|npm|npx|pip|pytest|python|python3|pwsh|cmd)\s+\S"
    r"|[\w./\\-]+\.(?:py|ts|tsx|js|json|ps1|exe|md)\b"
    r"|[{}\[\];]+\s*$"
    r")",
)
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


def contains_tool_markup(text: str) -> bool:
    """True when the model is emitting tool XML / JSON rather than owner prose."""
    sample = text or ""
    if _TOOL_XML_BLOCK_RE.search(sample) or _TOOL_XML_UNCLOSED_RE.search(sample):
        return True
    if _FUNCTION_EQ_TAG_RE.search(sample) or _PARAMETER_EQ_TAG_RE.search(sample):
        return True
    if _TOOL_DEBRIS_RE.search(sample) and ("<" in sample or "=" in sample):
        return True
    return False


def _strip_tool_markup(text: str) -> str:
    cleaned = _TOOL_XML_BLOCK_RE.sub("\n", text)
    cleaned = _TOOL_XML_UNCLOSED_RE.sub("\n", cleaned)
    cleaned = _FUNCTION_EQ_TAG_RE.sub(" ", cleaned)
    cleaned = _PARAMETER_EQ_TAG_RE.sub(" ", cleaned)
    cleaned = _ARG_XML_TAG_RE.sub(" ", cleaned)
    cleaned = _JSON_TOOL_BLOB_RE.sub(" ", cleaned)
    cleaned = _GENERIC_TAG_RE.sub(" ", cleaned)
    cleaned = _TOOL_DEBRIS_RE.sub(" ", cleaned)
    return cleaned


def _is_speakable_sentence(sentence: str) -> bool:
    stripped = sentence.strip()
    if _SHORT_ACK_RE.match(stripped):
        return True
    if len(stripped) < 12:
        return False
    words = [part for part in re.split(r"\s+", stripped) if part]
    if len(words) < 3:
        return False
    if _CODEISH_LINE_RE.match(stripped):
        return False
    if _TOOL_DEBRIS_RE.search(stripped):
        return False
    letters = sum(1 for char in stripped if char.isalpha())
    if letters < 8 or letters / max(len(stripped), 1) < 0.5:
        return False
    if stripped.count("=") >= 1 and ("parameter" in stripped.lower() or "function" in stripped.lower()):
        return False
    symbolish = sum(1 for char in stripped if char in "{}[]<>;`/\\")
    if symbolish >= 3:
        return False
    return True


def _spoken_summary(text: str, *, reply_class: ReplySpeechClass) -> str:
    """Keep on-screen prose; drop code and internals. Technical turns stay short."""
    chunks = [part.strip() for part in re.split(r"(?<=[.!?])\s+|\n+", text) if part.strip()]
    keep: list[str] = []
    for chunk in chunks:
        line = chunk.strip().strip("`").strip()
        if not line or _CODEISH_LINE_RE.match(line):
            continue
        if not _is_speakable_sentence(line if line.endswith((".", "!", "?")) else f"{line}."):
            continue
        if not line.endswith((".", "!", "?")):
            line = f"{line}."
        keep.append(line)
        if reply_class == "technical" and len(keep) >= 3:
            break
        if reply_class == "social" and len(keep) >= 4:
            break
    if not keep:
        collapsed = re.sub(r"\s+", " ", text).strip()
        probe = collapsed if collapsed.endswith((".", "!", "?")) else f"{collapsed}."
        if _is_speakable_sentence(probe):
            keep.append(probe)
    joined = " ".join(keep)
    limit = 280 if reply_class == "technical" else 420
    if len(joined) > limit:
        cut = joined[:limit].rsplit(" ", 1)[0].rstrip(",;:")
        joined = f"{cut}." if cut else ""
    return joined.strip()


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
    cleaned = _strip_tool_markup(cleaned)
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

    cleaned = _spoken_summary(cleaned, reply_class=speech_class)
    if not cleaned:
        return ""

    return rewrite_for_speech(cleaned, reply_class=speech_class)
