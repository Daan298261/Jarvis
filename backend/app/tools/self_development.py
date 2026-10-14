"""ANZU chat controls for the owner's local development scheduler."""
from __future__ import annotations

import json
import os
from typing import Any

from .base import RiskLevel, Tool, ToolResult


class SelfDevelopmentTool(Tool):
    name = "self_development"
    description = "Control ANZU's local Ollama self-development scheduler: scan accepted RFCs, queue an exact revision, run one queued RFC, stop, or configure the schedule. Use only when the owner requests self-development. Results stay in isolated worktrees for review."
    risk = RiskLevel.MEDIUM
    parameters = {"type": "object", "properties": {
        "action": {"type": "string", "enum": ["status", "scan", "queue", "unqueue", "run", "stop", "configure", "reorder", "undo"]},
        "ids": {"type": "array", "items": {"type": "string"}}, "order_revision": {"type": "integer"}, "reason": {"type": "string"},
        "item_id": {"type": "string"}, "revision": {"type": "string"},
        "config": {"type": "object", "properties": {"enabled": {"type": "boolean"}, "resource_hold": {"type": "string"}, "repo": {"type": "string"}, "interval_minutes": {"type": "integer"}, "coder_model": {"type": "string"}, "vision_model": {"type": "string"}}},
    }, "required": ["action"]}

    async def execute(self, action: str, item_id: str = "", revision: str = "", config: dict[str, Any] | None = None, **_: Any):
        from ..agent.development_scheduler import DEVELOPMENT, DevelopmentConfig
        # A worker cannot recursively schedule more workers from an RFC/tool result.
        if os.environ.get("ANZU_DEVELOPMENT_MISSION"):
            return ToolResult(False, "", error="Development missions cannot control the owner's scheduler")
        try:
            if action == "status": result = DEVELOPMENT.public()
            elif action == "scan": result = await DEVELOPMENT.scan()
            elif action in {"queue", "unqueue"}: result = await DEVELOPMENT.select(item_id, revision, action == "queue")
            elif action == "run":
                await DEVELOPMENT.scan()
                result = await DEVELOPMENT.launch()
            elif action == "stop": result = await DEVELOPMENT.stop()
            elif action in {"reorder", "undo"}:
                result = await DEVELOPMENT.reorder(_.get("ids", []), _.get("order_revision", -1), actor="assistant", reason=_.get("reason", "Automatic scheduling"), undo=action == "undo")
            elif action == "configure":
                if "away_mode" in (config or {}):
                    raise ValueError("Only the authenticated owner can grant Away Mode publication authority")
                result = await DEVELOPMENT.configure(DevelopmentConfig.model_validate({**DEVELOPMENT.state()["config"], **(config or {})}))
            else: raise ValueError("Unknown scheduler action")
            return ToolResult(True, json.dumps(result, ensure_ascii=False), data=result)
        except (ValueError, RuntimeError) as exc:
            return ToolResult(False, "", error=str(exc))
