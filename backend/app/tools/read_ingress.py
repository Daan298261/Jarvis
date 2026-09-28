"""Read bounded slices of the current task's stored owner input."""

from __future__ import annotations

from typing import Any

from .base import RiskLevel, Tool, ToolResult


class ReadIngressTool(Tool):
    name = "read_ingress"
    description = (
        "Read an exact slice of this task's long owner message by blob id and character offset. "
        "Use when the condensed task brief lacks a precise detail."
    )
    parameters = {
        "type": "object",
        "properties": {
            "blob_id": {"type": "string", "description": "Stored input id shown in the task brief."},
            "offset": {"type": "integer", "minimum": 0, "description": "Zero-based character offset."},
            "limit": {"type": "integer", "minimum": 1, "maximum": 4000, "description": "Characters to read (max 4000)."},
        },
        "required": ["blob_id", "offset"],
    }
    risk = RiskLevel.LOW

    async def execute(self, **kwargs: Any) -> ToolResult:
        from ..memory.ingress_spill import get_ingress_blob, list_ingress_chunks, read_ingress

        task_id = str(kwargs.get("_task_id") or "").strip()
        blob_id = str(kwargs.get("blob_id") or "").strip()
        if not task_id or not blob_id:
            return ToolResult(False, "", error="A current task and blob id are required")
        blob = await get_ingress_blob(blob_id)
        if blob is None or blob.task_id != task_id or blob.root_id != blob_id:
            return ToolResult(False, "", error="Stored input is unavailable for this task")
        try:
            offset = max(0, int(kwargs.get("offset") or 0))
            limit = max(1, min(4000, int(kwargs.get("limit") or 3000)))
        except (TypeError, ValueError):
            return ToolResult(False, "", error="offset and limit must be integers")
        body = await read_ingress(blob_id, offset, limit)
        next_offset = offset + len(body)
        total_chars = sum(len(row.body or "") for row in await list_ingress_chunks(blob_id))
        has_more = next_offset < total_chars
        return ToolResult(
            True,
            f"Stored input chars {offset}-{next_offset}; next_offset={next_offset}; "
            f"has_more={has_more}\n{body or 'End of stored input.'}",
            data={"blob_id": blob_id, "offset": offset, "next_offset": next_offset, "has_more": has_more},
        )
