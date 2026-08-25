from __future__ import annotations

import json
import os
import shutil
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Callable

from sqlalchemy import select

from ..db.models import AcpSession
from ..db.session import SessionLocal

CONSEQUENTIAL_MARKERS = (
    "production",
    "prod deploy",
    "merge to main",
    "merge into main",
    "delete the database",
    "drop table",
    "credentials",
    "secret",
    "api key",
    "billing",
    "purchase",
    "public internet",
    "security boundary",
    "overwrite the trusted",
    "destroy",
)


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def is_consequential(text: str) -> bool:
    lowered = (text or "").lower()
    return any(marker in lowered for marker in CONSEQUENTIAL_MARKERS)


def auto_answer_ask_question(
    question: str,
    options: list[str] | None = None,
    *,
    isolated: bool = True,
    autonomy: str = "autonomous",
) -> dict[str, Any]:
    """Answer routine Cursor ACP questions. Wake the user only for consequential decisions."""
    if autonomy not in {"trusted", "autonomous"}:
        return {"auto": False, "reason": "interactive mode requires a human answer"}
    if not isolated:
        return {"auto": False, "reason": "work is not isolated from the trusted checkout"}
    if is_consequential(question):
        return {"auto": False, "reason": "consequential product decision"}
    choices = [item for item in (options or []) if isinstance(item, str) and item.strip()]
    answer = choices[0] if choices else "Proceed with the safer, more reversible option that matches the acceptance criteria."
    return {"auto": True, "answer": answer, "reason": "routine planning question during isolated work"}


def auto_answer_create_plan(
    plan: str,
    *,
    isolated: bool = True,
    autonomy: str = "autonomous",
) -> dict[str, Any]:
    if autonomy not in {"trusted", "autonomous"}:
        return {"auto": False, "approved": False, "reason": "interactive mode requires a human plan approval"}
    if not isolated:
        return {"auto": False, "approved": False, "reason": "plan would touch the trusted checkout"}
    if is_consequential(plan):
        return {"auto": False, "approved": False, "reason": "plan includes a consequential production action"}
    return {
        "auto": True,
        "approved": True,
        "reason": "isolated work with clear acceptance criteria; routine plan approval",
    }


def handle_blocking_request(method: str, params: dict[str, Any] | None = None, **policy: Any) -> dict[str, Any]:
    payload = params or {}
    isolated = bool(policy.get("isolated", True))
    autonomy = str(policy.get("autonomy") or "autonomous")
    if method in {"cursor/ask_question", "session/request_permission"}:
        question = str(payload.get("question") or payload.get("message") or payload.get("prompt") or "")
        options = payload.get("options") or payload.get("choices") or []
        if isinstance(options, list) and options and isinstance(options[0], dict):
            options = [str(item.get("label") or item.get("name") or item.get("id") or "") for item in options]
        return {"method": method, **auto_answer_ask_question(question, options, isolated=isolated, autonomy=autonomy)}
    if method in {"cursor/create_plan", "session/update_plan"}:
        plan = str(payload.get("plan") or payload.get("content") or payload.get("title") or "")
        return {"method": method, **auto_answer_create_plan(plan, isolated=isolated, autonomy=autonomy)}
    return {"method": method, "auto": False, "reason": f"unhandled ACP request {method}"}


@dataclass
class JsonRpcMessage:
    payload: dict[str, Any]

    @property
    def method(self) -> str:
        return str(self.payload.get("method") or "")

    @property
    def id(self) -> Any:
        return self.payload.get("id")


class InMemoryAcpTransport:
    """Test double for newline-delimited JSON-RPC over stdio."""

    def __init__(self) -> None:
        self.sent: list[dict[str, Any]] = []
        self._handlers: dict[str, Callable[[dict[str, Any]], dict[str, Any]]] = {}
        self.closed = False

    def on(self, method: str, handler: Callable[[dict[str, Any]], dict[str, Any]]) -> None:
        self._handlers[method] = handler

    async def request(self, method: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        message = {"jsonrpc": "2.0", "id": str(uuid.uuid4()), "method": method, "params": params or {}}
        self.sent.append(message)
        handler = self._handlers.get(method)
        if handler:
            return handler(params or {})
        return {"ok": True, "method": method}

    async def notify(self, method: str, params: dict[str, Any] | None = None) -> None:
        self.sent.append({"jsonrpc": "2.0", "method": method, "params": params or {}})

    async def close(self) -> None:
        self.closed = True


@dataclass
class CursorACPWorker:
    """ACP client for Cursor Agent. Live `agent acp` is optional; sessions persist either way."""

    transport: InMemoryAcpTransport | None = None
    session_id: str | None = None
    model: str = ""
    cwd: str = ""
    connected: bool = False
    last_error: str = ""
    events: list[dict[str, Any]] = field(default_factory=list)

    def verify_connection(self) -> dict[str, Any]:
        agent = shutil.which("agent") or shutil.which("cursor-agent")
        cursor = shutil.which("cursor")
        available = bool(agent or cursor)
        status = "ready" if available else "not_connected"
        detail = (
            f"ACP CLI found at {agent or cursor}"
            if available
            else "Cursor ACP CLI (`agent acp`) is not on PATH. Catalogued, not started."
        )
        return {
            "id": "cursor-acp",
            "name": "Cursor ACP",
            "available": available,
            "status": status,
            "command": "agent acp",
            "detail": detail,
            "connected": self.connected,
            "session_id": self.session_id,
            "model": self.model,
        }

    async def initialize(self, cwd: str | None = None, model: str = "composer-2.5") -> dict[str, Any]:
        info = self.verify_connection()
        self.cwd = cwd or os.getcwd()
        self.model = model
        transport = self.transport or InMemoryAcpTransport()
        self.transport = transport
        if not info["available"] and not isinstance(self.transport, InMemoryAcpTransport):
            self.last_error = info["detail"]
            return {**info, "ok": False, "error": self.last_error}
        result = await transport.request(
            "initialize",
            {
                "protocolVersion": "0.1.0",
                "clientInfo": {"name": "jarvis", "version": "1.0.0"},
                "cwd": self.cwd,
            },
        )
        self.connected = True
        self.events.append({"kind": "initialized", "result": result})
        return {**info, "ok": True, "initialize": result}

    async def create_or_load_session(self, session_id: str | None = None, model: str | None = None) -> dict[str, Any]:
        if not self.transport:
            await self.initialize(model=model or self.model or "composer-2.5")
        assert self.transport is not None
        if model:
            self.model = model
        if session_id:
            result = await self.transport.request("session/load", {"sessionId": session_id})
            self.session_id = session_id
            kind = "loaded"
        else:
            result = await self.transport.request(
                "session/new",
                {"cwd": self.cwd, "model": self.model},
            )
            self.session_id = str(result.get("sessionId") or result.get("session_id") or uuid.uuid4())
            kind = "created"
        record = await _persist_session(self)
        self.events.append({"kind": kind, "session_id": self.session_id, "result": result})
        return {"ok": True, "session_id": self.session_id, "model": self.model, "record": record, "result": result}

    async def send_task(self, prompt: str, *, isolated: bool = True, autonomy: str = "autonomous") -> dict[str, Any]:
        if not self.session_id:
            await self.create_or_load_session()
        assert self.transport is not None
        result = await self.transport.request(
            "session/prompt",
            {"sessionId": self.session_id, "prompt": prompt},
        )
        self.events.append({"kind": "prompt", "session_id": self.session_id})
        await _persist_session(self, last_event="prompt")
        return {"ok": True, "session_id": self.session_id, "result": result, "isolated": isolated, "autonomy": autonomy}

    async def handle_cursor_request(self, method: str, params: dict[str, Any] | None = None, **policy: Any) -> dict[str, Any]:
        answer = handle_blocking_request(method, params, **policy)
        self.events.append({"kind": "blocking_request", "method": method, "answer": answer})
        await _persist_session(self, last_event=method)
        return answer

    async def cancel(self) -> dict[str, Any]:
        if self.transport and self.session_id:
            await self.transport.notify("session/cancel", {"sessionId": self.session_id})
        self.connected = False
        await _persist_session(self, status="cancelled", last_event="cancel")
        if self.transport:
            await self.transport.close()
        return {"ok": True, "session_id": self.session_id, "status": "cancelled"}


ACP_WORKER = CursorACPWorker()


async def _persist_session(worker: CursorACPWorker, status: str | None = None, last_event: str = "") -> dict[str, Any]:
    session_id = worker.session_id or str(uuid.uuid4())
    worker.session_id = session_id
    payload = {
        "id": session_id,
        "cursor_session_id": session_id,
        "model": worker.model,
        "cwd": worker.cwd,
        "status": status or ("connected" if worker.connected else "disconnected"),
        "last_event": last_event or (worker.events[-1]["kind"] if worker.events else ""),
        "updated_at": _utcnow().isoformat(),
    }
    async with SessionLocal() as session:
        row = await session.get(AcpSession, session_id)
        if row is None:
            session.add(
                AcpSession(
                    id=session_id,
                    cursor_session_id=session_id,
                    model=worker.model,
                    cwd=worker.cwd,
                    status=payload["status"],
                    last_event=payload["last_event"],
                )
            )
        else:
            row.model = worker.model
            row.cwd = worker.cwd
            row.status = payload["status"]
            row.last_event = payload["last_event"]
            row.updated_at = _utcnow()
        await session.commit()
    return payload


async def list_acp_sessions(limit: int = 20) -> list[dict[str, Any]]:
    async with SessionLocal() as session:
        rows = (await session.execute(select(AcpSession).order_by(AcpSession.updated_at.desc()).limit(limit))).scalars().all()
    return [
        {
            "id": row.id,
            "cursor_session_id": row.cursor_session_id,
            "model": row.model,
            "cwd": row.cwd,
            "status": row.status,
            "last_event": row.last_event,
            "created_at": row.created_at.isoformat() if row.created_at else "",
            "updated_at": row.updated_at.isoformat() if row.updated_at else "",
        }
        for row in rows
    ]


def acp_status() -> dict[str, Any]:
    info = ACP_WORKER.verify_connection()
    info["events"] = list(ACP_WORKER.events[-8:])
    return info
