from __future__ import annotations

from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import httpx

from .base import RiskLevel, Tool, ToolResult
from .safety import resolve_allowed_path


_ALLOWED_SCHEMES = {"http", "https"}
_MAX_DOWNLOAD_BYTES = 20 * 1024 * 1024

_ALLOWED_SCHEMES = {"http", "https"}


class WebFetchTool(Tool):
    name = "web_fetch"
    description = (
        "HTTP GET/POST/HEAD for public web pages and APIs. Separate from the browser tool. "
        "Use this for research, downloading text, posting JSON, and checking endpoints. "
        "Optional path saves the response body into an allowed directory. Do not send secrets. "
        "Only http and https URLs are allowed."
    )
    risk = RiskLevel.MEDIUM
    parameters = {
        "type": "object",
        "properties": {
            "url": {"type": "string"},
            "method": {"type": "string", "enum": ["GET", "POST", "HEAD"], "default": "GET"},
            "max_chars": {"type": "integer", "default": 12000},
            "headers": {"type": "object"},
            "body": {"type": "string"},
            "json_body": {"type": "object"},
            "path": {"type": "string", "description": "Optional file path under an allowed directory to save the body"},
        },
        "required": ["url"],
    }

    def __init__(self, context_getter=None) -> None:
        self.context_getter = context_getter or (lambda: {})

    async def execute(self, **kwargs: Any) -> ToolResult:
        url = kwargs.get("url")
        if not url:
            return ToolResult(False, "", error="url is required")
        scheme = (urlparse(str(url)).scheme or "").lower()
        if scheme not in _ALLOWED_SCHEMES:
            return ToolResult(
                False,
                "",
                error=f"Blocked URL scheme {scheme or '(none)'}. Only http and https URLs are allowed (http/https).",
            )
        method = (kwargs.get("method") or "GET").upper()
        if method not in {"GET", "POST", "HEAD"}:
            return ToolResult(False, "", error=f"Unsupported method {method}")
        limit = int(kwargs.get("max_chars") or 12000)
        headers = {"User-Agent": "JarvisLocal/1.0"}
        extra = kwargs.get("headers")
        if isinstance(extra, dict):
            headers.update({str(key): str(value) for key, value in extra.items()})
        json_body = kwargs.get("json_body") if isinstance(kwargs.get("json_body"), dict) else None
        body = kwargs.get("body")
        dest = kwargs.get("path")
        saved = ""
        if dest:
            allowed = list((self.context_getter() or {}).get("allowed_directories") or [])
            try:
                dest_path = resolve_allowed_path(str(dest), allowed)
            except Exception as exc:
                return ToolResult(False, "", error=str(exc))
        else:
            dest_path = None
        try:
            async with httpx.AsyncClient(follow_redirects=True, timeout=30, headers=headers) as client:
                request_kwargs: dict[str, Any] = {}
                if json_body is not None:
                    request_kwargs["json"] = json_body
                elif body is not None:
                    request_kwargs["content"] = body
                response = await client.request(method, url, **request_kwargs)
            raw = getattr(response, "content", None)
            if raw is None:
                raw = (getattr(response, "text", "") or "").encode("utf-8")
            truncated_bytes = max(0, len(raw) - _MAX_DOWNLOAD_BYTES)
            payload = raw[:_MAX_DOWNLOAD_BYTES]
            headers_obj = getattr(response, "headers", {}) or {}
            content_type = headers_obj.get("content-type", "") if hasattr(headers_obj, "get") else ""
            encoding = getattr(response, "encoding", None) or "utf-8"
            try:
                text = payload.decode(encoding, errors="replace")
            except Exception:
                text = payload.decode("utf-8", errors="replace")
            preview = text[:limit]
            if dest_path is not None:
                dest_path.parent.mkdir(parents=True, exist_ok=True)
                dest_path.write_bytes(payload)
                saved = str(dest_path)
            lines = [
                f"status={response.status_code}",
                f"content_type={content_type}",
                preview,
            ]
            return ToolResult(
                response.is_success,
                "\n".join(lines),
                data={
                    "status_code": response.status_code,
                    "content_type": content_type,
                    "path": saved,
                    "truncated": bool(truncated_bytes) or len(text) > limit,
                },
                error="" if response.is_success else f"HTTP {response.status_code}",
            )
        except Exception as exc:
            return ToolResult(False, "", error=str(exc))
