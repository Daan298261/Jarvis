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
# Directory segments may contain spaces ("Program Files (x86)"); the last segment may
# not, because the sentence continues after it.
_WIN_PATH = re.compile(
    r"(?:[A-Za-z]:[\\/]|\\\\)"
    r"(?:[^\\/\s\"'<>|]+(?: [^\\/\s\"'<>|]+)*[\\/])*"
    r"[^\\/\s\"'<>|,;]*"
)
_POSIX_PATH = re.compile(r"(?<![\w.])(?:~|\.{1,2})?/(?:[\w.-]+/)+[\w.-]*")
_MD_LINK = re.compile(r"\[([^\]]+)\]\([^)]*\)")
_HEADING = re.compile(r"(?m)^\s{0,3}#{1,6}\s*")
_BULLET = re.compile(r"(?m)^\s*(?:[-*+•]|\d+[.)])\s+")
_QUOTE = re.compile(r"(?m)^\s*>\s?")
_TABLE_RULE = re.compile(r"(?m)^\s*\|?[\s:|-]{3,}\|?\s*$")
_EMPHASIS = re.compile(r"(\*{1,3}|_{2,3}|~~)(\S(?:.*?\S)?)\1")
_SYMBOLS = re.compile(r"[\\*_#~^|<>{}\[\]=`]+")
_FILE_EXT = re.compile(r"\.(?:exe|lnk|url|py|ts|tsx|js|json|ps1|bat|cmd|md|txt|log|dll|msi)$", re.IGNORECASE)
_TECHNICAL_DUMP = re.compile(
    r"(?is)("
    r"error rendering prompt"
    r"|jinja template"
    r"|no user query found"
    r"|traceback \(most recent call last\)"
    r")"
)


def _path_name(match: re.Match[str]) -> str:
    """Say a path as its last component: C:\\...\\Steam\\steam.exe -> "steam"."""
    raw = match.group(0).rstrip("\\/.,;:)")
    parts = [part for part in re.split(r"[\\/]+", raw) if part and not part.endswith(":")]
    if not parts:
        return ""
    name = _FILE_EXT.sub("", parts[-1])
    return re.sub(r"[_\-.]+", " ", name).strip()


def _url_name(match: re.Match[str]) -> str:
    host = urlparse(match.group(0)).netloc.lower()
    return host.removeprefix("www.") or ""


def name_paths_and_links(text: str) -> str:
    """Replace URLs and filesystem paths with pronounceable names, keep the sentence."""
    cleaned = _MD_LINK.sub(r"\1", text or "")
    cleaned = _URL.sub(_url_name, cleaned)
    cleaned = _WIN_PATH.sub(_path_name, cleaned)
    cleaned = _POSIX_PATH.sub(_path_name, cleaned)
    return cleaned


def speech_safe(text: str) -> str:
    """Return text a person would say aloud; empty if nothing speakable remains."""
    cleaned = strip_reasoning_preamble(text or "")
    if not cleaned or _TECHNICAL_DUMP.search(cleaned):
        return ""
    cleaned = _FENCED.sub(" ", cleaned)
    cleaned = _INLINE_CODE.sub(lambda m: m.group(1) if len(m.group(1)) <= 40 and " " not in m.group(1).strip() else " ", cleaned)
    cleaned = name_paths_and_links(cleaned)
    cleaned = _TABLE_RULE.sub(" ", cleaned)
    cleaned = _HEADING.sub("", cleaned)
    cleaned = _QUOTE.sub("", cleaned)
    cleaned = _BULLET.sub("", cleaned)
    for _ in range(2):
        cleaned = _EMPHASIS.sub(r"\2", cleaned)
    cleaned = cleaned.replace("&", " and ")
    cleaned = _SYMBOLS.sub(" ", cleaned)
    cleaned = re.sub(r"\s*\n\s*", ". ", cleaned)
    cleaned = re.sub(r"\s{2,}", " ", cleaned)
    cleaned = re.sub(r"\s+([,.!?;:])", r"\1", cleaned)
    cleaned = re.sub(r"([.!?])(?:\s*[.!?])+", r"\1", cleaned)
    cleaned = re.sub(r"^[\s.,;:!?-]+", "", cleaned).strip()
    letters = sum(1 for char in cleaned if char.isalpha())
    if letters < 2 or letters / max(1, len(cleaned)) < 0.4:
        return ""
    return cleaned
