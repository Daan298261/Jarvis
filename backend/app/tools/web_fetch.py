from __future__ import annotations

from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import httpx

from .base import RiskLevel, Tool, ToolResult
from .safety import resolve_allowed_path


_ALLOWED_SCHEMES = {"http", "https"}
_MAX_DOWNLOAD_BYTES = 20 * 1024 * 1024


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
            "body": {"type": "string", "description": "Request body for POST"},
            "json_body": {"description": "JSON object sent as the POST body"},
            "headers": {
                "type": "object",
                "additionalProperties": {"type": "string"},
                "description": "Optional HTTP headers",
            },
            "timeout_seconds": {"type": "integer", "default": 30},
            "path": {"type": "string", "description": "If set, save the response body to this allowed path"},
        },
        "required": ["url"],
    }

    def __init__(self, context_getter=None) -> None:
        self.context_getter = context_getter or (lambda: {})

    async def execute(self, **kwargs: Any) -> ToolResult:
        url = (kwargs.get("url") or "").strip()
        if not url:
            return ToolResult(False, "", error="url is required")
        parsed = urlparse(url)
        if parsed.scheme.lower() not in _ALLOWED_SCHEMES:
            return ToolResult(
                False,
                "",
                error=f"Blocked URL scheme {parsed.scheme!r}. Only http and https URLs are allowed (http/https).",
            )
        if not parsed.netloc:
            return ToolResult(False, "", error="url is missing a host")
        method = (kwargs.get("method") or "GET").upper()
        if method not in {"GET", "POST", "HEAD"}:
            return ToolResult(False, "", error=f"Unsupported method {method}")
        limit = int(kwargs.get("max_chars") or 12000)
        timeout = float(kwargs.get("timeout_seconds") or 30)
        headers = {"User-Agent": "JarvisLocal/1.0"}
        extra = kwargs.get("headers") or {}
        if isinstance(extra, dict):
            for key, value in extra.items():
                if value is None:
                    continue
                headers[str(key)] = str(value)
        body = kwargs.get("body")
        json_body = kwargs.get("json_body")
        if json_body is None:
            json_body = kwargs.get("json")
        save_to = kwargs.get("path")
        allowed = list((self.context_getter() or {}).get("allowed_directories") or [])
        dest: Path | None = None
        if save_to:
            try:
                dest = resolve_allowed_path(str(save_to), allowed)
            except PermissionError as exc:
                return ToolResult(False, "", error=str(exc))
        try:
            async with httpx.AsyncClient(follow_redirects=True, timeout=timeout, headers=headers) as client:
                request_kwargs: dict[str, Any] = {}
                if method == "POST":
                    if json_body is not None:
                        request_kwargs["json"] = json_body
                    elif body is not None:
                        request_kwargs["content"] = body if isinstance(body, (bytes, str)) else str(body)
                response = await client.request(method, url, **request_kwargs)
            content_type = response.headers.get("content-type", "")
            raw = getattr(response, "content", None)
            if raw is None:
                text_body = getattr(response, "text", "") or ""
                raw = text_body.encode("utf-8") if isinstance(text_body, str) else b""
            payload = raw[:_MAX_DOWNLOAD_BYTES]
            truncated_bytes = len(raw) > _MAX_DOWNLOAD_BYTES
            saved = ""
            if dest is not None and method != "HEAD":
                dest.parent.mkdir(parents=True, exist_ok=True)
                dest.write_bytes(payload)
                saved = str(dest)
            try:
                text = payload.decode(getattr(response, "encoding", None) or "utf-8")
            except (LookupError, UnicodeDecodeError):
                text = payload.decode("utf-8", errors="replace")
            preview = text[:limit]
            lines = [
                f"status={response.status_code}",
                f"content-type={content_type}",
                f"bytes={len(payload)}" + (" (truncated)" if truncated_bytes else ""),
            ]
            if saved:
                lines.append(f"saved={saved}")
            if method != "HEAD":
                lines.extend(["", preview])
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
