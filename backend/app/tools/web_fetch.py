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
            "headers": {"type": "object"},
            "body": {"type": "string"},
            "json_body": {"type": "object"},
            "path": {"type": "string", "description": "Optional path in an allowed directory to save the body"},
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
        limit = int(kwargs.get("max_chars") or 12000)
        timeout = float(kwargs.get("timeout_seconds") or 30)
        headers = {"User-Agent": "JarvisLocal/1.0"}
        extra = kwargs.get("headers")
        if isinstance(extra, dict):
            headers.update({str(key): str(value) for key, value in extra.items()})
        json_body = kwargs.get("json_body") if isinstance(kwargs.get("json_body"), dict) else None
        body = kwargs.get("body")
        save_path = kwargs.get("path")
        resolved_path: Path | None = None
        if save_path:
            ctx = self.context_getter() or {}
            allowed = ctx.get("allowed_directories") or []
            try:
                resolved_path = resolve_allowed_path(str(save_path), allowed)
            except PermissionError as exc:
                return ToolResult(False, "", error=str(exc))

        try:
            async with httpx.AsyncClient(follow_redirects=True, timeout=timeout, headers=headers) as client:
                request_kwargs: dict[str, Any] = {}
                if json_body is not None:
                    request_kwargs["json"] = json_body
                elif body is not None:
                    request_kwargs["content"] = body
                response = await client.request(method, url, **request_kwargs)
            content_type = response.headers.get("content-type") or ""
            raw = getattr(response, "content", None)
            if raw is None:
                text_body = getattr(response, "text", "") or ""
                raw = text_body.encode("utf-8") if isinstance(text_body, str) else b""
            truncated_bytes = len(raw) > _MAX_DOWNLOAD_BYTES
            if truncated_bytes:
                raw = raw[:_MAX_DOWNLOAD_BYTES]
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
