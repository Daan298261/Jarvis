"""Secondary public-web lookup for the help assistant (RFC-0078)."""

from __future__ import annotations

import re
from html import unescape
from urllib.parse import quote_plus, urljoin

import httpx

from ..policy.network_http import gated_get

_TAG_RE = re.compile(r"<[^>]+>")
_RESULT_RE = re.compile(
    r'<a[^>]+class="[^"]*result__a[^"]*"[^>]+href="([^"]+)"[^>]*>(.*?)</a>',
    re.IGNORECASE | re.DOTALL,
)
_HREF_UDDG = re.compile(r"[?&]uddg=([^&]+)")


def _strip_html(raw: str) -> str:
    text = _TAG_RE.sub(" ", raw or "")
    text = unescape(text)
    return re.sub(r"\s+", " ", text).strip()


def _decode_ddg_href(href: str) -> str:
    if "uddg=" in href:
        match = _HREF_UDDG.search(href)
        if match:
            from urllib.parse import unquote

            return unquote(match.group(1))
    if href.startswith("//"):
        return "https:" + href
    return href


async def search_public_web(query: str, *, max_results: int = 2, client: httpx.AsyncClient | None = None) -> list[dict[str, str]]:
    """DuckDuckGo HTML search. Query only — never send local docs or secrets."""
    cleaned = (query or "").strip()
    if not cleaned:
        return []
    url = "https://html.duckduckgo.com/html/?q=" + quote_plus(cleaned[:200])
    try:
        response = await gated_get(
            url,
            tool="web_fetch",
            timeout=12.0,
            headers={"User-Agent": "JarvisHelp/1.0"},
            client=client,
        )
        if response.status_code >= 400:
            return []
        hits: list[dict[str, str]] = []
        for match in _RESULT_RE.finditer(response.text or ""):
            href = _decode_ddg_href(match.group(1))
            title = _strip_html(match.group(2))
            if not href.startswith("http"):
                href = urljoin("https://duckduckgo.com", href)
            if href and title:
                hits.append({"title": title[:160], "url": href[:500]})
            if len(hits) >= max_results:
                break
        return hits
    except Exception:
        return []


async def fetch_public_page(url: str, *, max_chars: int = 2500, client: httpx.AsyncClient | None = None) -> str:
    if not (url or "").startswith(("http://", "https://")):
        return ""
    try:
        response = await gated_get(
            url,
            tool="web_fetch",
            timeout=12.0,
            headers={"User-Agent": "JarvisHelp/1.0"},
            client=client,
        )
        if response.status_code >= 400:
            return ""
        return _strip_html(response.text or "")[:max_chars]
    except Exception:
        return ""
