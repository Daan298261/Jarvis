"""RFC-0200 thin tool: resolve owner REA investigation paths and enable MCP."""

from __future__ import annotations

import json
from typing import Any, Callable

from ..security.rea_mcp import (
    REA_AGENTS_PIN,
    REA_MCP_CATALOG_KEY,
    enable_rea_mcp,
    grant_investigation_root,
    mcp_registration_error,
    mcp_registration_status,
)
from ..security.rea_paths import PathNotAllowed, configured_investigation_roots, resolve_rea_investigation_path
from .base import RiskLevel, Tool, ToolResult


class ReaInvestigateTool(Tool):
    name = "rea_investigate"
    description = (
        "Reverse-engineer owner-named local artifacts via REA MCP (io.github.morluto/rea). "
        "Pass an absolute path under REA_INVESTIGATION_INPUT_ROOTS_JSON ∩ allowed_directories, "
        "or an LTA job id whose RFC-0198 extract already succeeded. Does not unlock LTA archives. "
        "Does not paste keys or certs."
    )
    risk = RiskLevel.HIGH
    effect_class = "external"
    replay_policy = "MANUAL_RECOVERY"
    parameters = {
        "type": "object",
        "properties": {
            "operation": {
                "type": "string",
                "enum": ["resolve", "status", "enable", "grant_root"],
            },
            "path": {"type": "string", "maxLength": 4000},
            "lta_job_id": {"type": "string", "minLength": 8, "maxLength": 32},
            "root": {"type": "string", "maxLength": 4000},
        },
        "required": ["operation"],
        "additionalProperties": False,
    }

    def __init__(self, context: Callable[[], dict[str, Any]] | None = None) -> None:
        self._context = context or (lambda: {})

    async def execute(self, **kwargs: Any) -> ToolResult:
        operation = str(kwargs.get("operation") or "").strip().lower()
        if operation == "status":
            from ..config import load_settings

            settings = load_settings()
            payload = {
                "enabled": bool(settings.rea.enabled),
                "catalog_key": REA_MCP_CATALOG_KEY,
                "package_version": settings.rea.package_version or REA_AGENTS_PIN,
                "investigation_roots": configured_investigation_roots(),
                "mcp_status": mcp_registration_status(),
                "mcp_error": mcp_registration_error(),
                "process_capture_enabled": bool(settings.rea.process_capture_enabled),
                "browser_scenario_enabled": bool(settings.rea.browser_scenario_enabled),
            }
            return ToolResult(True, json.dumps(payload), data=payload)
        if operation == "enable":
            try:
                result = await enable_rea_mcp(context={"source": "tool"})
            except PermissionError as exc:
                return ToolResult(False, "", error=str(exc))
            pending = result.get("status") == "pending_approval"
            return ToolResult(
                not pending,
                json.dumps(result, default=str),
                data=result,
                error="" if not pending else "pending_approval",
            )
        if operation == "grant_root":
            root = str(kwargs.get("root") or "").strip()
            if not root:
                return ToolResult(False, "", error="root is required")
            try:
                result = grant_investigation_root(root, context={"source": "tool"})
            except PermissionError as exc:
                return ToolResult(False, "", error=str(exc))
            pending = result.get("status") == "pending_approval"
            return ToolResult(
                not pending,
                json.dumps(result, default=str),
                data=result,
                error="" if not pending else "pending_approval",
            )
        if operation != "resolve":
            return ToolResult(False, "", error=f"Unknown operation: {operation}")

        path = str(kwargs.get("path") or "").strip() or None
        job_id = str(kwargs.get("lta_job_id") or "").strip() or None
        try:
            resolved = resolve_rea_investigation_path(path, lta_job_id=job_id)
        except PathNotAllowed as exc:
            return ToolResult(False, "", error=exc.code, data=exc.as_dict())
        payload = {
            "path": str(resolved),
            "lta_job_id": job_id or "",
            "catalog_key": REA_MCP_CATALOG_KEY,
            "note": "Call REA MCP tools (mcp_call) with this allowlisted path. No second LTA unlock.",
        }
        return ToolResult(True, json.dumps(payload), data=payload)
