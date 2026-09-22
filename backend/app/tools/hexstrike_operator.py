from __future__ import annotations

import json
from typing import Any, Callable

from ..policy.approval_pending import park_action
from ..policy.computer_permissions import evaluate_permission
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

    def _permission_block(
        self,
        *,
        action_kind: str,
        context: dict[str, Any],
        permission_id: str = "cyber.hexstrike",
    ) -> ToolResult | None:
        asking: list[str] = []
        for required in dict.fromkeys((permission_id, "cyber.hexstrike")):
            decision = evaluate_permission(required)
            if decision.status == "deny":
                return ToolResult(False, "", error=decision.reason)
            if decision.status == "ask":
                asking.append(required)
        if not asking:
            return None
        payload = dict(context)
        payload["_permission_ids"] = asking
        parked = park_action(action_kind=action_kind, permission_ids=asking, context=payload)
        audit_hexstrike("operator_tool_pending", action_kind=action_kind, permissions=asking)
        return ToolResult(
            False,
            json.dumps(parked, default=str),
            error="pending_approval",
            data=parked,
        )

    async def execute(self, **kwargs: Any) -> ToolResult:
        from ..licensing.entitlements import (
            HEXSTRIKE_ACCESS_FULL,
            HEXSTRIKE_ACCESS_LOCKED,
            HEXSTRIKE_OPERATOR_LICENSE_MESSAGE,
            HEXSTRIKE_PRO_MESSAGE,
            hexstrike_access_mode,
        )

        mode = hexstrike_access_mode()
        if mode == HEXSTRIKE_ACCESS_LOCKED:
            return ToolResult(False, "", error=HEXSTRIKE_PRO_MESSAGE)
        if mode != HEXSTRIKE_ACCESS_FULL:
            return ToolResult(False, "", error=HEXSTRIKE_OPERATOR_LICENSE_MESSAGE)
        operation = str(kwargs.get("operation") or "").strip().lower()
        if operation == "status":
            snapshot = await HEXSTRIKE.status(enrich=True)
            operator = {}
            if snapshot.running:
                operator = await sync_operator_surface(register_mcp=False)
            payload = {**snapshot.as_dict(), **catalog_snapshot(), "operator": operator}
            return ToolResult(True, json.dumps(payload, default=str), data=payload)
        if operation == "start":
            blocked = self._permission_block(action_kind="hexstrike.start", context={})
            if blocked:
                return blocked
            snapshot = await HEXSTRIKE.ensure_started()
            return ToolResult(True, json.dumps(snapshot.as_dict(), default=str), data=snapshot.as_dict())
        if operation in {"sync", "refresh_catalog"}:
            blocked = self._permission_block(action_kind="hexstrike.tools.refresh", context={})
            if blocked:
                return blocked
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
            blocked = self._permission_block(
                permission_id="blue.static_rules",
                action_kind="hexstrike.tool.install",
                context={"tool_id": dep_id, "install_path": status.install_path},
            )
            if blocked:
                return blocked
            try:
                job = start_dependency_install(dep_id, install_path=status.install_path)
            except ValueError as exc:
                return ToolResult(False, "", error=str(exc))
            return ToolResult(True, json.dumps(job, default=str), data=job)
        if operation == "operate":
            capability_id = str(kwargs.get("capability_id") or "").strip()
            if not capability_id:
                return ToolResult(False, "", error="capability_id is required for operate")
            blocked = self._permission_block(
                action_kind="hexstrike.operate",
                context={"capability_id": capability_id, "arguments": kwargs.get("arguments") or {}},
            )
            if blocked:
                return blocked
            try:
                job = await operate(capability_id, kwargs.get("arguments") or {})
            except (ValueError, PermissionError, RuntimeError) as exc:
                return ToolResult(False, "", error=str(exc))
            return ToolResult(True, json.dumps(job, default=str), data=job)
        return ToolResult(False, "", error=f"Unknown operation: {operation}")
