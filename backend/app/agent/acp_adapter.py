"""Optional local ACP server.  The client is a UI; Jarvis keeps all authority."""
from __future__ import annotations

import json
import os
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from sqlalchemy import select

from ..agent.loop import AGENT
from ..config import AcpAdapterSettings
from ..db.models import AcpAdapterSession, Task
from ..db.session import SessionLocal
from ..tools.mcp_runtime import MCPRuntime

PROTOCOL_VERSION = "0.1.0"


class AcpProtocolError(ValueError):
    pass


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _json(value: str, default: Any) -> Any:
    try:
        return json.loads(value or "")
    except (TypeError, json.JSONDecodeError):
        return default


def _clean_workspace(value: Any) -> str:
    path = Path(str(value or "")).expanduser()
    if not path.is_absolute():
        raise AcpProtocolError("workspace must be an absolute local path")
    return str(path.resolve())


class ACPAgentAdapter:
    """A small JSON-RPC ACP boundary with durable idempotent Jarvis bindings."""

    def __init__(self, settings: AcpAdapterSettings, *, task_runner=None) -> None:
        self.settings = settings
        self.task_runner = task_runner or self._run_task
        self._mcp: dict[str, MCPRuntime] = {}

    def _enabled(self) -> bool:
        # An environment switch is useful for one-shot local clients, but cannot
        # turn an explicitly disabled persisted setting on by accident.
        return self.settings.enabled and os.environ.get("JARVIS_DISABLE_ACP_ADAPTER") != "1"

    async def handle(self, message: dict[str, Any]) -> dict[str, Any]:
        if message.get("jsonrpc") != "2.0" or not isinstance(message.get("method"), str):
            raise AcpProtocolError("invalid JSON-RPC request")
        if not self._enabled():
            raise AcpProtocolError("ACP adapter is disabled")
        method = message["method"]
        params = message.get("params") or {}
        if not isinstance(params, dict):
            raise AcpProtocolError("params must be an object")
        handlers = {
            "initialize": self.initialize,
            "session/new": self.new_session,
            "session/load": self.load_session,
            "session/list": self.list_sessions,
            "session/prompt": self.prompt,
            "session/cancel": self.cancel,
            "session/close": self.close,
            "session/request_permission": self.request_permission,
            "session/register_mcp": self.register_mcp,
        }
        handler = handlers.get(method)
        if handler is None:
            raise AcpProtocolError(f"unsupported ACP method {method}")
        return await handler(params)

    async def initialize(self, params: dict[str, Any]) -> dict[str, Any]:
        info = params.get("clientInfo") if isinstance(params.get("clientInfo"), dict) else {}
        return {"protocolVersion": PROTOCOL_VERSION, "serverInfo": {"name": "jarvis-acp", "version": "1.3.2"}, "capabilities": {"session": True, "streaming": "normalized-events", "mcp": True, "filesystem": "delegated-only"}, "client": {"name": str(info.get("name") or ""), "version": str(info.get("version") or "")}}

    async def new_session(self, params: dict[str, Any]) -> dict[str, Any]:
        profile = str(params.get("agentProfileId") or "balanced")
        if profile not in self.settings.allowed_profiles:
            raise AcpProtocolError("agent profile is not permitted for ACP")
        session_id = str(params.get("sessionId") or uuid.uuid4())
        workspace = _clean_workspace(params.get("workspace") or params.get("cwd"))
        client = params.get("clientInfo") if isinstance(params.get("clientInfo"), dict) else {}
        capabilities = params.get("capabilities") if isinstance(params.get("capabilities"), dict) else {}
        async with SessionLocal() as db:
            existing = await db.get(AcpAdapterSession, session_id)
            if existing:
                return self._session_payload(existing, replay=True)
            row = AcpAdapterSession(id=session_id, agent_profile_id=profile, workspace=workspace,
                client_name=str(client.get("name") or ""), client_version=str(client.get("version") or ""),
                capabilities_json=json.dumps(self._effective_capabilities(capabilities)), events_json="[]")
            db.add(row); await db.commit()
        return {"sessionId": session_id, "agentProfileId": profile, "workspace": workspace, "events": []}

    async def load_session(self, params: dict[str, Any]) -> dict[str, Any]:
        session_id = str(params.get("sessionId") or "")
        async with SessionLocal() as db:
            row = await db.get(AcpAdapterSession, session_id)
            if row is None:
                raise AcpProtocolError("unknown ACP session")
            row.status = "open"; row.updated_at = _now(); await db.commit()
            return self._session_payload(row, replay=True)

    async def list_sessions(self, _params: dict[str, Any]) -> dict[str, Any]:
        async with SessionLocal() as db:
            rows = (await db.execute(select(AcpAdapterSession).order_by(AcpAdapterSession.updated_at.desc()))).scalars().all()
        return {"sessions": [self._session_payload(row, replay=False) for row in rows]}

    async def prompt(self, params: dict[str, Any]) -> dict[str, Any]:
        session_id = str(params.get("sessionId") or "")
        text = str(params.get("prompt") or "").strip()
        request_id = str(params.get("requestId") or "")
        if not text: raise AcpProtocolError("prompt is required")
        async with SessionLocal() as db:
            row = await db.get(AcpAdapterSession, session_id)
            if row is None or row.status != "open": raise AcpProtocolError("ACP session is not open")
            cache = _json(row.request_cache_json, {})
            if request_id and request_id in cache: return cache[request_id]
            task = await self.task_runner(text, row.agent_profile_id, row.workspace)
            row.task_id = str(task.get("id") or task.get("task_id") or "")
            result = {"sessionId": row.id, "taskId": row.task_id, "updates": self._append_event(row, "task_started", {"task_id": row.task_id, "phase": "queued"})}
            if request_id:
                cache[request_id] = result; row.request_cache_json = json.dumps(dict(list(cache.items())[-50:]))
            row.updated_at = _now(); await db.commit()
            return result

    async def cancel(self, params: dict[str, Any]) -> dict[str, Any]:
        return await self._transition(params, "cancelled")

    async def close(self, params: dict[str, Any]) -> dict[str, Any]:
        return await self._transition(params, "closed")

    async def _transition(self, params: dict[str, Any], state: str) -> dict[str, Any]:
        async with SessionLocal() as db:
            row = await db.get(AcpAdapterSession, str(params.get("sessionId") or ""))
            if row is None: raise AcpProtocolError("unknown ACP session")
            row.status = state; row.updated_at = _now()
            updates = self._append_event(row, state, {"task_id": row.task_id})
            await db.commit(); return {"sessionId": row.id, "status": state, "updates": updates}

    async def request_permission(self, params: dict[str, Any]) -> dict[str, Any]:
        """Client policy can only narrow Jarvis policy; escalation is always denied."""
        session_id = str(params.get("sessionId") or "")
        requested = str(params.get("mode") or "prompt")
        action_id = str(params.get("actionId") or uuid.uuid4())
        async with SessionLocal() as db:
            row = await db.get(AcpAdapterSession, session_id)
            if row is None: raise AcpProtocolError("unknown ACP session")
            allowed = requested in {"prompt", "read-only"}
            event = {"action_id": action_id, "requested_mode": requested, "approved": allowed, "reason": "client policy cannot broaden Jarvis authority" if not allowed else "requires normal Jarvis approval"}
            updates = self._append_event(row, "permission_request", event); row.updated_at = _now(); await db.commit()
            return {"sessionId": session_id, **event, "updates": updates}

    async def register_mcp(self, params: dict[str, Any]) -> dict[str, Any]:
        session_id = str(params.get("sessionId") or "")
        servers = params.get("servers")
        if not isinstance(servers, list) or not all(isinstance(item, dict) for item in servers): raise AcpProtocolError("servers must be a list")
        async with SessionLocal() as db:
            row = await db.get(AcpAdapterSession, session_id)
            if row is None or row.status != "open": raise AcpProtocolError("ACP session is not open")
            runtime = self._mcp.setdefault(session_id, MCPRuntime())
            status = await runtime.refresh(servers)  # Existing MCP abstraction, session-scoped.
            caps = _json(row.capabilities_json, {}); caps["mcp_servers"] = sorted(status); row.capabilities_json = json.dumps(caps)
            updates = self._append_event(row, "mcp_handoff", {"servers": status}); row.updated_at = _now(); await db.commit()
            return {"sessionId": session_id, "status": status, "updates": updates}

    async def _run_task(self, prompt: str, profile: str, _workspace: str) -> dict[str, Any]:
        task = await AGENT.create_task(prompt, profile=profile)
        return {"id": task.id}

    def _effective_capabilities(self, offered: dict[str, Any]) -> dict[str, Any]:
        return {"filesystem": bool(offered.get("filesystem")) and "delegated-only", "mcp": bool(offered.get("mcp")), "permission_mode": "prompt"}

    def _append_event(self, row: AcpAdapterSession, kind: str, payload: dict[str, Any]) -> list[dict[str, Any]]:
        events = _json(row.events_json, [])
        event = {"kind": kind, "at": _now().isoformat(), **payload}; events.append(event)
        row.events_json = json.dumps(events[-self.settings.max_replay_events:])
        return [event]

    def _session_payload(self, row: AcpAdapterSession, *, replay: bool) -> dict[str, Any]:
        return {"sessionId": row.id, "agentProfileId": row.agent_profile_id, "workspace": row.workspace, "taskId": row.task_id, "status": row.status, "capabilities": _json(row.capabilities_json, {}), "events": _json(row.events_json, [])[-self.settings.max_replay_events:] if replay else []}
