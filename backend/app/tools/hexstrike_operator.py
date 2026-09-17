from __future__ import annotations

import json
from typing import Any, Callable

from ..policy.computer_permissions import evaluate_permission, operator_intent_grant
from ..security.hexstrike import HEXSTRIKE, audit_hexstrike
from ..security.hexstrike_operator import (
    catalog_snapshot,
    operate,
    sync_operator_surface,
)
from ..security.hexstrike_tools import start_dependency_install
from .base import RiskLevel, Tool, ToolResult


class HexStrikeOperatorTool(Tool):
    name = "hexstrike_operator"
    description = (
        "Drive the managed HexStrike loopback suite: start or sync the operator surface, install missing "
        "dependencies, and invoke discovered capabilities by id with JSON arguments. Requires cyber.hexstrike."
    )
    risk = RiskLevel.HIGH
    parameters = {
        "type": "object",
        "properties": {
            "operation": {
                "type": "string",
                "enum": ["status", "start", "sync", "install_dependency", "operate"],
            },
            "capability_id": {"type": "string", "minLength": 1, "maxLength": 160},
            "dependency_id": {"type": "string", "minLength": 1, "maxLength": 120},
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
            operator = {}
            if snapshot.running:
                operator = await sync_operator_surface(register_mcp=True)
            payload = {**snapshot.as_dict(), **catalog_snapshot(), "operator": operator}
            return ToolResult(True, json.dumps(payload, default=str), data=payload)
        if operation == "start":
            snapshot = await HEXSTRIKE.ensure_started()
            return ToolResult(True, json.dumps(snapshot.as_dict(), default=str), data=snapshot.as_dict())
        if operation in {"sync", "refresh_catalog"}:
            surface = await sync_operator_surface(register_mcp=True)
            if not surface.get("operator_ready"):
                return ToolResult(
                    False,
                    "",
                    error=str(surface.get("mcp", {}).get("error") or "operator surface not ready"),
                    data=surface,
                )
            payload = {"operator": surface, **catalog_snapshot()}
            return ToolResult(True, json.dumps(payload, default=str), data=payload)
        if operation == "install_dependency":
            dep_id = str(kwargs.get("dependency_id") or "").strip()
            if not dep_id:
                return ToolResult(False, "", error="dependency_id is required for install_dependency")
            status = await HEXSTRIKE.status(enrich=False)
            job = start_dependency_install(dep_id, install_path=status.install_path)
            return ToolResult(True, json.dumps(job, default=str), data=job)
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
