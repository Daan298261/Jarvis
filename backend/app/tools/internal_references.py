from __future__ import annotations

from typing import Any

from .base import RiskLevel, Tool, ToolResult


class InternalReferencesTool(Tool):
    name = "search_internal_references"
    description = (
        "Search Jarvis product/internal reference docs (seeded pack + allowlisted in-repo docs). "
        "Use for questions about Jarvis capabilities, install, settings, ports, models, and errors. "
        "Restricted to local allowlisted roots; does not use external web search."
    )
    parameters = {
        "type": "object",
        "properties": {
            "query": {
                "type": "string",
                "description": "What to look up in internal Jarvis references.",
            },
            "max_results": {
                "type": "integer",
                "description": "Maximum snippets to return (default 5).",
                "minimum": 1,
                "maximum": 10,
            },
        },
        "required": ["query"],
    }
    risk = RiskLevel.LOW

    async def execute(self, **kwargs: Any) -> ToolResult:
        query = str(kwargs.get("query") or "").strip()
        if not query:
            return ToolResult(False, "", error="query is required")
        max_results = int(kwargs.get("max_results") or 5)
        max_results = max(1, min(10, max_results))
        from ..agent.docs_first_grounding import search_internal_references

        hits = search_internal_references(query, max_results=max_results)
        if not hits:
            return ToolResult(
                True,
                "No matching internal references found in allowlisted roots.",
                data={"results": []},
            )
        lines = []
        payload = []
        for hit in hits:
            lines.append(f"[{hit.citation_id}] {hit.source_path}\n{hit.text}")
            payload.append(
                {
                    "citation_id": hit.citation_id,
                    "source_path": hit.source_path,
                    "text": hit.text,
                }
            )
        return ToolResult(True, "\n\n".join(lines), data={"results": payload})
