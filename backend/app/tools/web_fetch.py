from __future__ import annotations

from typing import Any
from urllib.parse import urlparse

import httpx

from .base import RiskLevel, Tool, ToolResult


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
        url = kwargs.get("url") or ""
        parsed = urlparse(url)
        if parsed.scheme not in {"http", "https"}:
            return ToolResult(False, "", error="Only http/https URLs are allowed")
        method = (kwargs.get("method") or "GET").upper()
        limit = int(kwargs.get("max_chars") or 12000)
        timeout = float(kwargs.get("timeout_seconds") or 30)
        headers = {"User-Agent": "JarvisLocal/1.0"}
        extra = kwargs.get("headers")
        if isinstance(extra, dict):
            for key, value in extra.items():
                if str(key).lower() in {"authorization", "cookie", "x-api-key"}:
                    continue
                headers[str(key)] = str(value)
        json_body = kwargs.get("json_body") if method == "POST" else None
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
