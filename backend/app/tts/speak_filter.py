from __future__ import annotations

import re
from typing import Literal

from ..agent.compaction import WORKING_STATE_MARKER

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


def filter_text_for_speech(text: str, *, source: str = "chat") -> str:
    """Keep only speakable conversational text (RFC-0070 / RFC-0061).

    Preview and explicit direct speak endpoints may bypass heavy filtering.
    """
    cleaned = (text or "").strip()
    if not cleaned:
        return ""

    if source in {"preview", "direct"}:
        return cleaned

    cleaned = _strip_plan_and_working_state(cleaned)
    cleaned = _FENCED_CODE_RE.sub("", cleaned)
    cleaned = _INLINE_CODE_RE.sub("", cleaned)
    cleaned = _URL_RE.sub("", cleaned)

    if source not in {"think_aloud", "greeting", "launch"}:
        cleaned = re.sub(r"(?im)^#+\s.*$", "", cleaned)
        cleaned = re.sub(r"(?im)^\s*[-*]\s+(?:step|todo|action)\b.*$", "", cleaned)

    cleaned = re.sub(r"\n{3,}", "\n\n", cleaned)
    cleaned = re.sub(r"[ \t]{2,}", " ", cleaned)
    return cleaned.strip()
