from __future__ import annotations

import asyncio
import re
from pathlib import Path
from typing import Any
from urllib.parse import unquote, urljoin, urlparse

import httpx

from .base import RiskLevel, Tool, ToolResult
from .owner_paths import resolve_owner_file_path

_ALLOWED_SCHEMES = {"http", "https"}
_MAX_DOWNLOAD_BYTES = 20 * 1024 * 1024
_FETCH_ATTEMPTS = 3
_RETRY_STATUS = {502, 503, 504}
_REDIRECT_STATUS = {301, 302, 303, 307, 308}
_MAX_REDIRECTS = 8
_TEXT_TYPES = (
    "text/",
    "application/json",
    "application/xml",
    "application/javascript",
    "application/xhtml",
    "application/ld+json",
)
_FILENAME_RE = re.compile(
    r"filename\*=UTF-8''([^;]+)|filename=\"([^\"]+)\"|filename=([^;]+)",
    re.I,
)


def suggested_fetch_name(url: str, headers: Any) -> str:
    disp = ""
    if headers is not None:
        disp = str(getattr(headers, "get", lambda *_: "")("content-disposition") or "")
        if not disp and isinstance(headers, dict):
            disp = str(headers.get("content-disposition") or headers.get("Content-Disposition") or "")
    match = _FILENAME_RE.search(disp)
    if match:
        name = unquote((match.group(1) or match.group(2) or match.group(3) or "").strip().strip('"'))
        name = Path(name).name
        if name:
            return name
    leaf = Path(urlparse(url).path).name
    if leaf and "." in leaf:
        return leaf
    return "download"


def looks_downloadable_body(content_type: str, headers: Any, raw: bytes) -> bool:
    disp = ""
    if headers is not None:
        disp = str(getattr(headers, "get", lambda *_: "")("content-disposition") or "").lower()
        if not disp and isinstance(headers, dict):
            disp = str(headers.get("content-disposition") or headers.get("Content-Disposition") or "").lower()
    if "attachment" in disp:
        return True
    ctype = (content_type or "").split(";")[0].strip().lower()
    if not ctype:
        return b"\x00" in raw[:4096]
    if any(ctype.startswith(prefix) or ctype == prefix.rstrip("/") for prefix in _TEXT_TYPES):
        return False
    return True


class WebFetchTool(Tool):
    name = "web_fetch"
    description = (
        "HTTP GET/POST/HEAD for public web pages and APIs. Separate from the browser tool. "
        "Use this for research, downloading text, posting JSON, and checking endpoints. "
        "Optional path saves the body into an allowed folder (including extra drives). "
        "PDFs, zips, images, and Content-Disposition attachments without a path go to the "
        "owner's Downloads folder. Do not send secrets. Only http and https URLs are allowed."
    )
    risk = RiskLevel.MEDIUM
    effect_class = "external"
    replay_policy = "KEYED"
    parameters = {
        "type": "object",
        "properties": {
            "url": {"type": "string"},
            "method": {"type": "string", "enum": ["GET", "POST", "HEAD"], "default": "GET"},
            "max_chars": {"type": "integer", "default": 12000},
            "headers": {"type": "object"},
            "body": {"type": "string"},
            "json_body": {"type": "object"},
            "path": {
                "type": "string",
                "description": "Optional save path or folder. Omit for HTML/JSON; binaries go to Downloads.",
            },
            "timeout_seconds": {"type": "number", "default": 30},
        },
        "required": ["url"],
    }

    def __init__(self, context_getter=None) -> None:
        self.context_getter = context_getter or (lambda: {})

    async def execute(self, **kwargs: Any) -> ToolResult:
        url = (kwargs.get("url") or "").strip()
        if not url:
            return ToolResult(False, "", error="url is required")
        lowered = url.lower()
        if lowered.startswith("file:") or lowered.startswith("javascript:") or lowered.startswith("data:"):
            return ToolResult(False, "", error="Blocked URL scheme. Only http and https URLs are allowed (http/https only)")
        scheme = (urlparse(url).scheme or "").lower()
        if scheme not in _ALLOWED_SCHEMES:
            return ToolResult(False, "", error="Blocked URL scheme. Only http and https URLs are allowed (http/https only)")
        method = (kwargs.get("method") or "GET").upper()
        if method not in {"GET", "POST", "HEAD"}:
            return ToolResult(False, "", error=f"Unsupported method {method}")
        from ..policy.computer_permissions import evaluate_tool_permissions

        gate = evaluate_tool_permissions("web_fetch", {"url": url, "method": method})
        if gate.status == "deny":
            return ToolResult(False, "", error=gate.reason)
        if gate.status == "ask":
            return ToolResult(False, "", error=gate.reason or "Permission required before fetching from the network.")
        limit = int(kwargs.get("max_chars") or 12000)
        timeout = float(kwargs.get("timeout_seconds") or 30)
        headers = {"User-Agent": "JarvisLocal/1.0"}
        extra = kwargs.get("headers")
        if isinstance(extra, dict):
            headers.update({str(key): str(value) for key, value in extra.items()})
        json_body = kwargs.get("json_body") if isinstance(kwargs.get("json_body"), dict) else None
        body = kwargs.get("body")
        save_path = str(kwargs.get("path") or "").strip()
        ctx = self.context_getter() or {}
        allowed = list((ctx or {}).get("allowed_directories") or []) if isinstance(ctx, dict) else []

        try:
            async with httpx.AsyncClient(follow_redirects=False, timeout=timeout, headers=headers) as client:
                request_kwargs: dict[str, Any] = {}
                if json_body is not None:
                    request_kwargs["json"] = json_body
                elif body is not None:
                    request_kwargs["content"] = body
                current_url = url
                current_method = method
                current_kwargs = dict(request_kwargs)
                hops = 0
                last_error: Exception | None = None
                response = None
                while True:
                    response = None
                    for attempt in range(_FETCH_ATTEMPTS):
                        try:
                            response = await client.request(current_method, current_url, **current_kwargs)
                        except (httpx.ConnectError, httpx.ConnectTimeout, httpx.ReadTimeout, httpx.RemoteProtocolError) as exc:
                            last_error = exc
                            await asyncio.sleep(0.15 * (attempt + 1))
                            continue
                        if (
                            current_method in {"GET", "HEAD"}
                            and response.status_code in _RETRY_STATUS
                            and attempt + 1 < _FETCH_ATTEMPTS
                        ):
                            await asyncio.sleep(0.15 * (attempt + 1))
                            continue
                        break
                    if response is None:
                        raise last_error or RuntimeError("web_fetch failed")
                    location = (response.headers.get("location") or "").strip()
                    if response.status_code not in _REDIRECT_STATUS or not location or hops >= _MAX_REDIRECTS:
                        break
                    nxt = urljoin(str(response.url), location)
                    hop_scheme = (urlparse(nxt).scheme or "").lower()
                    if hop_scheme not in _ALLOWED_SCHEMES:
                        return ToolResult(False, "", error="Blocked URL scheme. Only http and https URLs are allowed (http/https only)")
                    hop_gate = evaluate_tool_permissions("web_fetch", {"url": nxt, "method": current_method})
                    if hop_gate.status != "allow":
                        return ToolResult(False, "", error=hop_gate.reason or "Permission required before fetching from the network.")
                    hops += 1
                    current_url = nxt
                    if response.status_code in {301, 302, 303} and current_method == "POST":
                        current_method = "GET"
                        current_kwargs = {}
            content_type = response.headers.get("content-type") or ""
            raw = getattr(response, "content", None)
            if raw is None:
                text_body = getattr(response, "text", "") or ""
                raw = text_body.encode("utf-8") if isinstance(text_body, str) else b""
            truncated_bytes = len(raw) > _MAX_DOWNLOAD_BYTES
            if truncated_bytes:
                raw = raw[:_MAX_DOWNLOAD_BYTES]
            filename = suggested_fetch_name(str(getattr(response, "url", "") or current_url), response.headers)
            resolved_path = None
            if save_path:
                resolved_path = resolve_owner_file_path(
                    save_path,
                    suggested_name=filename,
                    allowed=allowed,
                    fallback_dirs=("Downloads",),
                )
            elif method != "HEAD" and looks_downloadable_body(content_type, response.headers, raw):
                resolved_path = resolve_owner_file_path(
                    None,
                    suggested_name=filename,
                    allowed=allowed,
                    fallback_dirs=("Downloads",),
                )
            binary = looks_downloadable_body(content_type, response.headers, raw)
            text = ""
            if not binary:
                text = (getattr(response, "text", None) or raw.decode("utf-8", errors="replace"))[:limit]
            saved = ""
            if resolved_path is not None:
                resolved_path.parent.mkdir(parents=True, exist_ok=True)
                resolved_path.write_bytes(raw)
                saved = str(resolved_path)
            lines = [
                f"status={response.status_code}",
                f"content-type={content_type}",
            ]
            if saved:
                lines.append(f"path={saved}")
            if text:
                lines.append("")
                lines.append(text)
            return ToolResult(
                response.is_success,
                "\n".join(lines),
                data={
                    "status_code": response.status_code,
                    "content_type": content_type,
                    "path": saved,
                    "truncated": truncated_bytes or len(text) > limit,
                },
                error="" if response.is_success else f"HTTP {response.status_code}",
            )
        except Exception as exc:
            return ToolResult(False, "", error=str(exc))
