"""HTTP GET that re-checks computer-permissions on each redirect hop."""
from __future__ import annotations

from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any
from urllib.parse import urljoin, urlparse

import httpx

from .computer_permissions import evaluate_tool_permissions

_REDIRECT = {301, 302, 303, 307, 308}


def lan_http_bind_for_url(url: str) -> str:
    from ..mobile.wan_forward import lan_http_bind_for_url as bind_for_url

    return bind_for_url(url)


def _with_lan_bind(kwargs: dict[str, Any], url: str, *, async_client: bool) -> dict[str, Any]:
    bind = lan_http_bind_for_url(url)
    if not bind or kwargs.get("transport") is not None:
        return kwargs
    transport_cls = httpx.AsyncHTTPTransport if async_client else httpx.HTTPTransport
    kwargs["transport"] = transport_cls(local_address=bind)
    return kwargs


def _redirect_target(response: httpx.Response) -> str | None:
    location = (response.headers.get("location") or "").strip()
    if response.status_code not in _REDIRECT or not location:
        return None
    return urljoin(str(response.url), location)


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
    http = client or httpx.AsyncClient(
        **_with_lan_bind(
            {
                "follow_redirects": False,
                "timeout": timeout,
                "headers": headers or {},
            },
            current,
            async_client=True,
        )
    )
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
            nxt = _redirect_target(response)
            if nxt is None:
                return response
            current = nxt
        raise PermissionError("Too many redirects")
    finally:
        if own:
            await http.aclose()


def gated_get_sync(
    url: str,
    *,
    tool: str,
    timeout: float = 12.0,
    headers: dict[str, str] | None = None,
    params: dict[str, Any] | None = None,
    max_hops: int = 8,
    trust_env: bool = False,
    client: httpx.Client | None = None,
) -> httpx.Response:
    current = url
    query = params
    own = client is None
    http = client or httpx.Client(
        **_with_lan_bind(
            {
                "follow_redirects": False,
                "timeout": timeout,
                "headers": headers or {},
                "trust_env": trust_env,
            },
            current,
            async_client=False,
        )
    )
    try:
        for _ in range(max(1, int(max_hops))):
            require_http_url_allowed(current, tool=tool)
            request_headers = headers if (headers and not own) else None
            response = http.get(
                current,
                params=query,
                headers=request_headers,
                follow_redirects=False,
            )
            query = None
            nxt = _redirect_target(response)
            if nxt is None:
                return response
            current = nxt
        raise PermissionError("Too many redirects")
    finally:
        if own:
            http.close()


@asynccontextmanager
async def gated_stream(
    url: str,
    *,
    tool: str,
    timeout: float | httpx.Timeout = 30.0,
    headers: dict[str, str] | None = None,
    max_hops: int = 8,
) -> AsyncIterator[httpx.Response]:
    current = url
    response: httpx.Response | None = None
    async with httpx.AsyncClient(
        **_with_lan_bind(
            {
                "follow_redirects": False,
                "timeout": timeout,
                "headers": headers or {},
            },
            current,
            async_client=True,
        )
    ) as http:
        try:
            for _ in range(max(1, int(max_hops))):
                require_http_url_allowed(current, tool=tool)
                request = http.build_request("GET", current)
                response = await http.send(request, stream=True)
                nxt = _redirect_target(response)
                if nxt is None:
                    yield response
                    return
                await response.aclose()
                response = None
                current = nxt
            raise PermissionError("Too many redirects")
        finally:
            if response is not None:
                await response.aclose()


def gated_download_to(
    url: str,
    dest: Path,
    *,
    tool: str,
    timeout: float = 120.0,
    max_hops: int = 8,
    trust_env: bool = False,
    on_progress: Callable[[int, int], None] | None = None,
) -> None:
    current = url
    tmp = dest.with_name(dest.name + ".partial")
    with httpx.Client(
        **_with_lan_bind(
            {
                "follow_redirects": False,
                "timeout": timeout,
                "trust_env": trust_env,
            },
            current,
            async_client=False,
        )
    ) as http:
        for _ in range(max(1, int(max_hops))):
            require_http_url_allowed(current, tool=tool)
            with http.stream("GET", current) as response:
                nxt = _redirect_target(response)
                if nxt is not None:
                    current = nxt
                    continue
                if response.status_code >= 400:
                    raise RuntimeError(f"Download failed with HTTP {response.status_code}")
                total = int(response.headers.get("content-length") or 0)
                dest.parent.mkdir(parents=True, exist_ok=True)
                done = 0
                with open(tmp, "wb") as out:
                    for chunk in response.iter_bytes(256 * 1024):
                        out.write(chunk)
                        done += len(chunk)
                        if on_progress:
                            on_progress(done, total or done)
                tmp.replace(dest)
                return
    raise PermissionError("Too many redirects")
