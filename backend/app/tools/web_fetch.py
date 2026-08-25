from __future__ import annotations

from typing import Any
from urllib.parse import urlparse

import httpx

from .base import RiskLevel, Tool, ToolResult

_ALLOWED_SCHEMES = {"http", "https"}


class WebFetchTool(Tool):
    name = "web_fetch"
    description = (
        "HTTP GET/POST for public web pages and APIs. Separate from the browser tool. "
        "Use this for research, downloading text, and checking endpoints. Only http/https URLs. "
        "Do not send secrets."
    )
    risk = RiskLevel.MEDIUM
    parameters = {
        "type": "object",
        "properties": {
            "url": {"type": "string"},
            "method": {"type": "string", "enum": ["GET", "POST", "HEAD"], "default": "GET"},
            "max_chars": {"type": "integer", "default": 12000},
            "headers": {"type": "object"},
            "json_body": {"type": "object"},
            "timeout_seconds": {"type": "number", "default": 30},
        },
        "required": ["url"],
    }

    async def execute(self, **kwargs: Any) -> ToolResult:
        url = (kwargs.get("url") or "").strip()
        if not url:
            return ToolResult(False, "", error="url is required")
        lowered = url.lower()
        if lowered.startswith("file:") or lowered.startswith("javascript:") or lowered.startswith("data:"):
            return ToolResult(False, "", error="Only http(s) URLs are allowed")
        method = (kwargs.get("method") or "GET").upper()
        limit = int(kwargs.get("max_chars") or 12000)
        scheme = urlparse(url or "").scheme.lower()
        if scheme not in _ALLOWED_SCHEMES:
            return ToolResult(False, "", error=f"Blocked URL scheme {scheme or 'missing'}")
        try:
            async with httpx.AsyncClient(follow_redirects=True, timeout=timeout, headers=headers) as client:
                response = await client.request(method, url, json=json_body)
            text = response.text[:limit]
            return ToolResult(
                response.is_success,
                f"status={response.status_code}\ncontent-type={response.headers.get('content-type')}\n\n{text}",
                error="" if response.is_success else f"HTTP {response.status_code}",
            )
        except Exception as exc:
            return ToolResult(False, "", error=str(exc))
