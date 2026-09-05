from __future__ import annotations

import re

_URL_RE = re.compile(r"https?://[^\s\"'<>]+", re.I)
_GITHUB_RE = re.compile(r"https?://github\.com/[^\s\"'<>]+", re.I)


def extract_urls(*texts: str) -> list[str]:
    seen: set[str] = set()
    ordered: list[str] = []
    for text in texts:
        for match in _URL_RE.findall(text or ""):
            url = match.rstrip(".,)")
            if url not in seen:
                seen.add(url)
                ordered.append(url)
    return ordered


def extract_repo_urls(*texts: str) -> list[str]:
    seen: set[str] = set()
    ordered: list[str] = []
    for text in texts:
        for match in _GITHUB_RE.findall(text or ""):
            url = match.rstrip(".,)")
            if url not in seen:
                seen.add(url)
                ordered.append(url)
    return ordered
