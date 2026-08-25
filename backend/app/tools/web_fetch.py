from __future__ import annotations

from typing import Any

import httpx

from .base import RiskLevel, Tool, ToolResult


class WebFetchTool(Tool):
    name = "web_fetch"
    description = (
        "HTTP GET/POST for public web pages and APIs. Separate from the browser tool. "
        "Use this for research, downloading text, and checking endpoints. Do not send secrets."
    )
    risk = RiskLevel.MEDIUM
    parameters = {
        "type": "object",
        "properties": {
            "url": {"type": "string"},
            "method": {"type": "string", "enum": ["GET", "POST", "HEAD"], "default": "GET"},
            "max_chars": {"type": "integer", "default": 12000},
        },
        "required": ["url"],
    }

    async def execute(self, **kwargs: Any) -> ToolResult:
        url = kwargs.get("url")
        method = (kwargs.get("method") or "GET").upper()
        limit = int(kwargs.get("max_chars") or 12000)
        try:
            async with httpx.AsyncClient(follow_redirects=True, timeout=30, headers={"User-Agent": "JarvisLocal/1.0"}) as client:
                response = await client.request(method, url)
            text = response.text[:limit]
            title = ""
            lower_type = (response.headers.get("content-type") or "").lower()
            if "html" in lower_type or "<title" in text.lower():
                import re

                match = re.search(r"<title[^>]*>(.*?)</title>", text, re.I | re.S)
                if match:
                    title = re.sub(r"\s+", " ", match.group(1)).strip()
            header = f"status={response.status_code}\ncontent-type={response.headers.get('content-type')}"
            if title:
                header += f"\ntitle={title}"
            return ToolResult(
                response.is_success,
                f"{header}\n\n{text}",
                error="" if response.is_success else f"HTTP {response.status_code}",
                data={"title": title} if title else {},
            )
        except Exception as exc:
            return ToolResult(False, "", error=str(exc))
