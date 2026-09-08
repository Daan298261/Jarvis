from __future__ import annotations

import time
import uuid

from .base import RiskLevel, Tool, ToolResult


class MobileCallTool(Tool):
    name = "mobile_call"
    description = "List paired Jarvis phones or call an owner-enabled phone about an important event. Reuse the same incident_id for retries. Calls require that phone's explicit incoming-call preference."
    risk = RiskLevel.MEDIUM
    parameters = {"type": "object", "properties": {
        "action": {"type": "string", "enum": ["devices", "call"]},
        "device_id": {"type": "string"}, "incident_id": {"type": "string"},
        "task_id": {"type": "string"},
    }, "required": ["action"]}

    async def execute(self, action="devices", device_id="", incident_id="", task_id="", **kwargs):
        from ..mobile.store import database, get, rows
        from ..mobile.calls import create_call
        from ..mobile.runtime import push
        with database() as db:
            devices = rows(db, "device")
        if action == "devices":
            return ToolResult(True, "Paired Android devices", data={"devices": [{"id": d["id"], "name": d["name"], "calls_enabled": d.get("critical_calls", False)} for d in devices if d["status"] == "active"]})
        if action != "call" or not device_id or not incident_id:
            return ToolResult(False, "", error="Call requires device_id and a stable incident_id")
        try:
            uuid.UUID(device_id)
            incident = str(uuid.uuid5(uuid.NAMESPACE_URL, incident_id))
            call = create_call(device_id, "incoming", task_id=task_id or None, incident_id=incident)
            with database() as db:
                device = get(db, "device", device_id)
            delivered = await push(device, call["id"], "call")
            return ToolResult(delivered, "Incoming call sent" if delivered else "Call created, but push is unavailable. The app can see it while connected.", data={"call_id": call["id"], "push_delivered": delivered})
        except Exception as exc:
            return ToolResult(False, "", error=str(getattr(exc, "detail", type(exc).__name__)))
