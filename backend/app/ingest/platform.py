from __future__ import annotations

import re
from urllib.parse import urlparse

_PLATFORM_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    ("instagram", re.compile(r"(?:^|\.)instagram\.com$", re.I)),
    ("tiktok", re.compile(r"(?:^|\.)tiktok\.com$", re.I)),
    ("x", re.compile(r"(?:^|\.)((?:twitter|x)\.com)$", re.I)),
    ("youtube", re.compile(r"(?:^|\.)((?:youtube\.com|youtu\.be))$", re.I)),
    ("github", re.compile(r"(?:^|\.)github\.com$", re.I)),
]


def detect_platform(url: str) -> str:
    host = (urlparse(url).hostname or "").lower()
    if not host:
        return "web"
    for name, pattern in _PLATFORM_PATTERNS:
        if pattern.search(host):
            return name
    return "web"
