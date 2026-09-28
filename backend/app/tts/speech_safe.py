"""Last-mile text normalization for the voice: nothing unpronounceable reaches TTS.

Every synthesis request passes through ``speech_safe`` regardless of caller, so a
path, markdown emphasis, or a leaked reasoning trace is never read out as
"backslash asterisk asterisk".
"""

from __future__ import annotations

import re
from urllib.parse import urlparse

from ..providers.completion_text import strip_reasoning_preamble

_FENCED = re.compile(r"```[\s\S]*?(?:```|\Z)")
_INLINE_CODE = re.compile(r"`([^`\n]*)`")
_URL = re.compile(r"https?://[^\s)\]>\"']+", re.IGNORECASE)
_WIN_PATH = re.compile(r"(?:\b[A-Za-z]:[\\/]|\\\\)(?:[^\s\"'<>|\\/]+(?: \(x86\))?[\\/]?)+")
_POSIX_PATH = re.compile(r"(?<![\w.])(?:~|\.{1,2})?/(?:[\w.-]+/)+[\w.-]*")
_MD_LINK = re.compile(r"\[([^\]]+)\]\([^)]*\)")
_HEADING = re.compile(r"(?m)^\s{0,3}#{1,6}\s*")
_BULLET = re.compile(r"(?m)^\s*(?:[-*+•]|\d+[.)])\s+")
_QUOTE = re.compile(r"(?m)^\s*>\s?")
_TABLE_RULE = re.compile(r"(?m)^\s*\|?[\s:|-]{3,}\|?\s*$")
_EMPHASIS = re.compile(r"(\*{1,3}|_{2,3}|~~)(?=\S)(.+?)(?<=\S)\1")
_SYMBOLS = re.compile(r"[\\*_#`~^|<>{}\[\]=]+")
_SPACES = re.compile(r"[ \t]+")


def _path_name(match: re.Match[str]) -> str:
    """Speak a path as the thing it names: C:\\...\\Steam\\steam.exe -> steam."""
    parts = [part for part in re.split(r"[\\/]+", match.group(0)) if part and not part.endswith(":")]
    if not parts:
        return ""
    last = re.sub(r"\.(exe|lnk|url|dll|bat|cmd|ps1|py|json|txt|log)$", "", parts[-1], flags=re.IGNORECASE)
    return last.replace("_", " ").replace("-", " ")


def _url_name(match: re.Match[str]) -> str:
    host = urlparse(match.group(0)).hostname or ""
    return host.removeprefix("www.")


def name_paths_and_links(text: str) -> str:
    """Replace URLs, file paths and markdown links with the names they refer to."""
    cleaned = _MD_LINK.sub(r"\1", text or "")
    cleaned = _URL.sub(_url_name, cleaned)
    cleaned = _WIN_PATH.sub(_path_name, cleaned)
    return _POSIX_PATH.sub(_path_name, cleaned)


def speech_safe(text: str) -> str:
    cleaned = strip_reasoning_preamble(text or "")
    if not cleaned:
        return ""
    cleaned = _FENCED.sub(" ", cleaned)
    cleaned = _MD_LINK.sub(r"\1", cleaned)
    cleaned = _URL.sub(_url_name, cleaned)
    cleaned = _WIN_PATH.sub(_path_name, cleaned)
    cleaned = _POSIX_PATH.sub(_path_name, cleaned)
    cleaned = _INLINE_CODE.sub(lambda m: m.group(1) if len(m.group(1)) <= 40 else " ", cleaned)
    cleaned = _TABLE_RULE.sub(" ", cleaned)
    cleaned = _HEADING.sub("", cleaned)
    cleaned = _BULLET.sub("", cleaned)
    cleaned = _QUOTE.sub("", cleaned)
    for _ in range(2):
        cleaned = _EMPHASIS.sub(r"\2", cleaned)
    cleaned = _SYMBOLS.sub(" ", cleaned)
    cleaned = re.sub(r"\s*\n\s*", ". ", cleaned.strip())
    cleaned = re.sub(r"(?:\.\s*){2,}", ". ", cleaned)
    cleaned = re.sub(r"\s+([,.!?;:])", r"\1", cleaned)
    cleaned = _SPACES.sub(" ", cleaned).strip(" .;:,")
    letters = sum(ch.isalpha() for ch in cleaned)
    if letters < 2 or letters / max(1, len(cleaned)) < 0.4:
        return ""
    if cleaned and cleaned[-1] not in ".!?":
        cleaned += "."
    return cleaned
