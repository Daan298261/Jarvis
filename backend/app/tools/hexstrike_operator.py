from __future__ import annotations

import json
from typing import Any, Callable

from ..policy.computer_permissions import evaluate_permission, operator_intent_grant
from ..security.hexstrike import HEXSTRIKE, audit_hexstrike
from ..security.hexstrike_mcp import register_hexstrike_mcp
from ..security.hexstrike_operator import catalog_snapshot, operate, refresh_discovered_catalog
from .base import RiskLevel, Tool, ToolResult


class HexStrikeOperatorTool(Tool):
    name = "hexstrike_operator"
    description = (
        "Drive the managed HexStrike loopback suite: refresh catalog, install missing host deps, "
        "and invoke discovered capabilities by id with JSON arguments. Requires owner cyber.hexstrike permission."
    )
    risk = RiskLevel.HIGH
    parameters = {
        "type": "object",
        "properties": {
            "operation": {
                "type": "string",
                "enum": ["status", "start", "refresh_catalog", "operate"],
            },
            "capability_id": {"type": "string", "minLength": 1, "maxLength": 160},
            "arguments": {"type": "object"},
        },
        "required": ["operation"],
        "additionalProperties": False,
    }

    def __init__(self, context: Callable[[], dict[str, Any]]) -> None:
        self._context = context

    def _ensure_permission(self) -> str | None:
        decision = evaluate_permission("cyber.hexstrike")
        if decision.status == "allow":
            return None
        if decision.status == "ask":
            try:
                operator_intent_grant("cyber.hexstrike", "allow_session")
                return None
            except PermissionError as exc:
                return str(exc)
        return decision.reason

    async def execute(self, **kwargs: Any) -> ToolResult:
        denied = self._ensure_permission()
        if denied:
            audit_hexstrike("operator_tool_denied", reason=denied)
            return ToolResult(False, "", error=denied)
        operation = str(kwargs.get("operation") or "").strip().lower()
        if operation == "status":
            snapshot = await HEXSTRIKE.status(enrich=True)
            payload = {**snapshot.as_dict(), **catalog_snapshot()}
            return ToolResult(True, json.dumps(payload, default=str), data=payload)
        if operation == "start":
            snapshot = await HEXSTRIKE.ensure_started()
            return ToolResult(True, json.dumps(snapshot.as_dict(), default=str), data=snapshot.as_dict())
        if operation == "refresh_catalog":
            status = await HEXSTRIKE.status(enrich=True)
            if status.running:
                from pathlib import Path

                await register_hexstrike_mcp(
                    install_path=Path(status.install_path),
                    python_executable=status.python_executable,
                    host=status.host,
                    port=status.port,
                )
            catalog = await refresh_discovered_catalog(force=True)
            payload = {"catalog": catalog, "count": len(catalog)}
            return ToolResult(True, json.dumps(payload, default=str), data=payload)
        if operation == "operate":
            capability_id = str(kwargs.get("capability_id") or "").strip()
            if not capability_id:
                return ToolResult(False, "", error="capability_id is required for operate")
            try:
                job = await operate(capability_id, kwargs.get("arguments") or {})
            except (ValueError, PermissionError, RuntimeError) as exc:
                return ToolResult(False, "", error=str(exc))
            return ToolResult(True, json.dumps(job, default=str), data=job)
        return ToolResult(False, "", error=f"Unknown operation: {operation}")
