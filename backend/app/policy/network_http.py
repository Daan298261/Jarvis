"""HTTP GET that re-checks computer-permissions on each redirect hop."""
from __future__ import annotations

from typing import Any
from urllib.parse import urljoin, urlparse

import httpx

from .computer_permissions import evaluate_tool_permissions

_REDIRECT = {301, 302, 303, 307, 308}


def require_http_url_allowed(url: str, *, tool: str) -> None:
    scheme = (urlparse(url).scheme or "").lower()
    if scheme not in {"http", "https"}:
        raise PermissionError("Blocked URL scheme. Only http and https URLs are allowed")
    gate = evaluate_tool_permissions(tool, {"url": url, "method": "GET"})
    if gate.status != "allow":
        raise PermissionError(gate.reason or "Permission required before using the network.")


async def gated_get(
    url: str,
    *,
    tool: str,
    timeout: float = 12.0,
    headers: dict[str, str] | None = None,
    params: dict[str, Any] | None = None,
    max_hops: int = 8,
    client: httpx.AsyncClient | None = None,
) -> httpx.Response:
    current = url
    query = params
    own = client is None
    http = client or httpx.AsyncClient(follow_redirects=False, timeout=timeout, headers=headers or {})
    try:
        for _ in range(max(1, int(max_hops))):
            require_http_url_allowed(current, tool=tool)
            request_headers = headers if (headers and not own) else None
            response = await http.get(
                current,
                params=query,
                headers=request_headers,
                follow_redirects=False,
            )
            query = None
            location = (response.headers.get("location") or "").strip()
            if response.status_code not in _REDIRECT or not location:
                return response
            current = urljoin(str(response.url), location)
        raise PermissionError("Too many redirects")
    finally:
        if own:
            await http.aclose()
