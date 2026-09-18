from __future__ import annotations

import json
from typing import Any, Callable

from ..inference.security_gates import gate_is_enabled
from ..policy.computer_permissions import evaluate_permission
from ..security.hexstrike import audit_hexstrike
from ..security.hexstrike_defensive import CAPABILITY_BY_ID, execute_defensive
from .base import RiskLevel, Tool, ToolResult


class HexStrikeDefensiveTool(Tool):
    name = "hexstrike_defensive"
    description = (
        "Run one owner-scoped defensive HexStrike action. Available only to blue-team tasks; "
        "never accepts raw commands, arbitrary flags, payloads, exploits, or public targets."
    )
    risk = RiskLevel.HIGH
    parameters = {
        "type": "object",
        "properties": {
            "action": {"type": "string", "enum": sorted(CAPABILITY_BY_ID)},
            "scope_id": {"type": "string", "minLength": 1, "maxLength": 80},
            "options": {
                "type": "object",
                "properties": {"cve": {"type": "string", "pattern": "^CVE-[0-9]{4}-[0-9]{4,}$"}},
                "additionalProperties": False,
            },
        },
        "required": ["action", "scope_id"],
        "additionalProperties": False,
    }

    def __init__(self, context: Callable[[], dict[str, Any]]) -> None:
        self._context = context

    async def execute(self, **kwargs: Any) -> ToolResult:
        role = str(self._context().get("security_role") or "")
        action = str(kwargs.get("action") or "")
        if role != "blue-team" or not gate_is_enabled("blue-team"):
            audit_hexstrike("defensive_tool_denied", role=role, capability=action)
            return ToolResult(False, "", error="HexStrike defensive actions require a blue-team task and Blue team on the license package.")
        capability = CAPABILITY_BY_ID.get(action)
        if capability is None:
            audit_hexstrike("defensive_tool_denied", role=role, capability=action, reason="unknown_action")
            return ToolResult(False, "", error="Unknown defensive action.")
        required = (
            "cyber.hexstrike",
            capability.permission,
            *(("network.internet",) if action == "threat_intel_lookup" else ()),
        )
        denied = [permission for permission in required if evaluate_permission(permission).status != "allow"]
        if denied:
            audit_hexstrike("defensive_tool_denied", role=role, capability=action, permissions=denied)
            return ToolResult(False, "", error=f"Permissions required: {', '.join(denied)}")
        try:
            job = await execute_defensive(action, str(kwargs.get("scope_id") or ""), kwargs.get("options") or {})
        except (KeyError, ValueError, PermissionError, RuntimeError) as exc:
            return ToolResult(False, "", error=str(exc))
        return ToolResult(True, json.dumps(job, default=str), data=job)
