from __future__ import annotations

"""Read-oriented Jarvis MCP server for Cursor (plan §11).

Cursor attaches here as a client. Jarvis remains the single supervisor.
These tools must not start a Cursor ACP session or create a new Jarvis task.
"""

import json
from typing import Any, Callable, Awaitable

from sqlalchemy import select

from .config import load_settings, repo_root
from .db.models import Task, Trajectory, WorkerReport
from .db.session import SessionLocal
from .hardware import hardware_dict
from .inference.manager import MANAGER

PROTOCOL_VERSION = "2024-11-05"
MAX_TEXT = 12000

ToolHandler = Callable[[dict[str, Any]], Awaitable[str]]

READ_TOOLS = (
    "get_master_plan",
    "get_current_task",
    "get_acceptance_criteria",
    "get_known_architecture",
    "get_relevant_trajectory",
    "get_previous_failure",
    "get_environment_info",
    "query_jarvis_status",
)
ACTION_TOOLS = (
    "request_verification",
    "report_worker_result",
)
FORBIDDEN_TOOLS = (
    "start_cursor",
    "dispatch_worker",
    "create_task",
    "run_agent",
    "start_acp",
)

TOOL_SCHEMAS: list[dict[str, Any]] = [
    {
        "name": "get_master_plan",
        "description": "Read the Jarvis master plan (priorities and queue). Truncated.",
        "inputSchema": {"type": "object", "properties": {"section": {"type": "string"}}, "additionalProperties": False},
    },
    {
        "name": "get_current_task",
        "description": "Latest running, waiting, or queued Jarvis task.",
        "inputSchema": {"type": "object", "properties": {"task_id": {"type": "string"}}},
    },
    {
        "name": "get_acceptance_criteria",
        "description": "Acceptance criteria for the current or named task.",
        "inputSchema": {"type": "object", "properties": {"task_id": {"type": "string"}}},
    },
    {
        "name": "get_known_architecture",
        "description": "Short architecture notes from the contributor guide.",
        "inputSchema": {"type": "object", "properties": {}},
    },
    {
        "name": "get_relevant_trajectory",
        "description": "Recent trajectory lessons for a task class or goal keywords.",
        "inputSchema": {
            "type": "object",
            "properties": {"task_class": {"type": "string"}, "goal": {"type": "string"}},
        },
    },
    {
        "name": "get_previous_failure",
        "description": "Most recent failed Jarvis task and its error.",
        "inputSchema": {"type": "object", "properties": {}},
    },
    {
        "name": "get_environment_info",
        "description": "Local hardware, bind address, and model load state.",
        "inputSchema": {"type": "object", "properties": {}},
    },
    {
        "name": "query_jarvis_status",
        "description": "Compact supervisor status. Does not start work.",
        "inputSchema": {"type": "object", "properties": {}},
    },
    {
        "name": "request_verification",
        "description": "Record that Jarvis should independently verify a worker result. Does not dispatch Cursor.",
        "inputSchema": {
            "type": "object",
            "properties": {"task_id": {"type": "string"}, "note": {"type": "string"}},
            "required": ["task_id"],
        },
    },
    {
        "name": "report_worker_result",
        "description": "Record a worker-reported result. A worker claiming success is never completion.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "task_id": {"type": "string"},
                "worker": {"type": "string"},
                "success": {"type": "boolean"},
                "summary": {"type": "string"},
            },
            "required": ["task_id", "summary"],
        },
    },
]


def _clip(text: str, limit: int = MAX_TEXT) -> str:
    text = text or ""
    if len(text) <= limit:
        return text
    return text[: limit - 20] + "\n…[truncated]"


def _section_excerpt(text: str, heading: str, limit: int = 4000) -> str:
    marker = heading
    index = text.find(marker)
    if index < 0:
        return _clip(text, limit)
    nxt = text.find("\n# ", index + len(marker))
    chunk = text[index:nxt if nxt > index else index + limit]
    return _clip(chunk, limit)


async def _latest_task(task_id: str | None = None) -> Task | None:
    async with SessionLocal() as session:
        if task_id:
            return await session.get(Task, task_id)
        for status in ("running", "waiting", "queued"):
            row = (
                await session.execute(select(Task).where(Task.status == status).order_by(Task.updated_at.desc()).limit(1))
            ).scalar_one_or_none()
            if row:
                return row
        return (await session.execute(select(Task).order_by(Task.updated_at.desc()).limit(1))).scalar_one_or_none()


async def tool_get_master_plan(arguments: dict[str, Any]) -> str:
    path = repo_root() / "JARVIS_MASTER_PLAN.md"
    if not path.exists():
        return "Master plan file is missing."
    text = path.read_text(encoding="utf-8")
    section = str(arguments.get("section") or "").strip()
    if section.lower() in {"58", "queue", "development queue"}:
        return _section_excerpt(text, "## 58. DEVELOPMENT QUEUE", 6000)
    if section.lower() in {"57", "state", "current state"}:
        return _section_excerpt(text, "## 57. CURRENT STATE", 5000)
    if section:
        needle = section if section.startswith("#") else f"## {section}"
        return _section_excerpt(text, needle, 5000)
    return _clip(text, 8000)


async def tool_get_current_task(arguments: dict[str, Any]) -> str:
    task = await _latest_task(arguments.get("task_id"))
    if not task:
        return "No tasks recorded."
    return json.dumps(
        {
            "id": task.id,
            "title": task.title,
            "status": task.status,
            "stage": task.stage,
            "task_class": task.task_class,
            "prompt": (task.prompt or "")[:1500],
            "acceptance_criteria": task.acceptance_criteria,
            "current_action": task.current_action,
            "error": task.error,
            "verification": (task.verification or "")[:800],
        },
        indent=2,
    )


async def tool_get_acceptance_criteria(arguments: dict[str, Any]) -> str:
    task = await _latest_task(arguments.get("task_id"))
    if not task:
        return "No tasks recorded."
    return task.acceptance_criteria or "(not yet captured)"


async def tool_get_known_architecture(_arguments: dict[str, Any]) -> str:
    path = repo_root() / "docs" / "DEVELOPMENT.md"
    if not path.exists():
        return "docs/DEVELOPMENT.md is missing."
    text = path.read_text(encoding="utf-8")
    excerpt = _section_excerpt(text, "## 1. What you are working on", 3500)
    return (
        excerpt
        + "\n\nJarvis is the supervisor. Cursor ACP is a worker. This MCP server is read-oriented "
        "plus verification/result reporting. Do not create a Jarvis→Cursor→Jarvis loop."
    )


async def tool_get_relevant_trajectory(arguments: dict[str, Any]) -> str:
    from .agent.trajectory import relevant_trajectories, as_prompt_block

    task_class = str(arguments.get("task_class") or "")
    goal = str(arguments.get("goal") or "")
    if not task_class and not goal:
        async with SessionLocal() as session:
            rows = (await session.execute(select(Trajectory).order_by(Trajectory.created_at.desc()).limit(3))).scalars().all()
        if not rows:
            return "No trajectories recorded."
        return "\n".join(f"- {row.task_class or 'mixed'} {row.outcome}: {row.goal[:160]}" for row in rows)
    rows = await relevant_trajectories(task_class, goal)
    return as_prompt_block(rows) or "No matching trajectories."


async def tool_get_previous_failure(_arguments: dict[str, Any]) -> str:
    async with SessionLocal() as session:
        row = (
            await session.execute(select(Task).where(Task.status == "failed").order_by(Task.updated_at.desc()).limit(1))
        ).scalar_one_or_none()
    if not row:
        return "No failed tasks recorded."
    return json.dumps(
        {
            "id": row.id,
            "title": row.title,
            "task_class": row.task_class,
            "error": row.error,
            "result": (row.result or "")[:800],
        },
        indent=2,
    )


async def tool_get_environment_info(_arguments: dict[str, Any]) -> str:
    settings = load_settings()
    model = await MANAGER.snapshot(settings)
    payload = {
        "hardware": hardware_dict(),
        "bind_host": settings.bind_host,
        "bind_port": settings.bind_port,
        "execution_mode": settings.execution_mode,
        "autonomy": settings.autonomy,
        "model": {
            "loaded": model.get("loaded"),
            "profile": model.get("profile"),
            "quantization": model.get("quantization"),
        },
    }
    return json.dumps(payload, indent=2, default=str)[:MAX_TEXT]


async def tool_query_jarvis_status(_arguments: dict[str, Any]) -> str:
    settings = load_settings()
    async with SessionLocal() as session:
        running = (await session.execute(select(Task).where(Task.status == "running"))).scalars().all()
    model = await MANAGER.snapshot(settings)
    return json.dumps(
        {
            "ok": True,
            "supervisor": "jarvis",
            "running_tasks": [{"id": task.id, "title": task.title, "stage": task.stage} for task in running],
            "model_loaded": bool(model.get("loaded")),
            "recursive_dispatch": False,
        },
        indent=2,
    )


async def tool_request_verification(arguments: dict[str, Any]) -> str:
    task_id = str(arguments.get("task_id") or "")
    note = str(arguments.get("note") or "worker requested independent verification")
    if not task_id:
        return "task_id is required"
    async with SessionLocal() as session:
        task = await session.get(Task, task_id)
        if not task:
            return f"Unknown task {task_id}"
        session.add(
            WorkerReport(
                task_id=task_id,
                worker="mcp",
                kind="verification_request",
                reported_success=False,
                summary=note[:2000],
            )
        )
        await session.commit()
    return (
        f"Recorded verification request for {task_id}. "
        "Jarvis remains the supervisor and will verify independently. "
        "This MCP tool does not start Cursor or a new agent loop."
    )


async def tool_report_worker_result(arguments: dict[str, Any]) -> str:
    task_id = str(arguments.get("task_id") or "")
    summary = str(arguments.get("summary") or "")
    worker = str(arguments.get("worker") or "cursor")
    success = bool(arguments.get("success"))
    if not task_id or not summary:
        return "task_id and summary are required"
    async with SessionLocal() as session:
        task = await session.get(Task, task_id)
        if not task:
            return f"Unknown task {task_id}"
        session.add(
            WorkerReport(
                task_id=task_id,
                worker=worker,
                kind="worker_result",
                reported_success=success,
                summary=summary[:4000],
            )
        )
        await session.commit()
    verdict = "reported success" if success else "reported failure"
    return (
        f"Recorded {worker} {verdict} for {task_id}. "
        "A worker claiming success is NOT completion. Jarvis still verifies."
    )


HANDLERS: dict[str, ToolHandler] = {
    "get_master_plan": tool_get_master_plan,
    "get_current_task": tool_get_current_task,
    "get_acceptance_criteria": tool_get_acceptance_criteria,
    "get_known_architecture": tool_get_known_architecture,
    "get_relevant_trajectory": tool_get_relevant_trajectory,
    "get_previous_failure": tool_get_previous_failure,
    "get_environment_info": tool_get_environment_info,
    "query_jarvis_status": tool_query_jarvis_status,
    "request_verification": tool_request_verification,
    "report_worker_result": tool_report_worker_result,
}


def connect_command() -> str:
    root = repo_root()
    return f"PYTHONPATH={root / 'backend'} python3 -m app.mcp_stdio"


def jarvis_mcp_manifest() -> dict[str, Any]:
    return {
        "name": "jarvis",
        "status": "ready",
        "transport": "stdio",
        "command": connect_command(),
        "protocol": PROTOCOL_VERSION,
        "supervisor": "jarvis",
        "recursive_dispatch": False,
        "read_tools": list(READ_TOOLS),
        "action_tools": list(ACTION_TOOLS),
        "forbidden": list(FORBIDDEN_TOOLS),
        "tools": TOOL_SCHEMAS,
        "detail": "Cursor can attach as an MCP client. Jarvis stays the supervisor; these tools cannot start ACP or create tasks.",
    }


class JarvisMcpServer:
    def list_tools(self) -> list[dict[str, Any]]:
        return list(TOOL_SCHEMAS)

    async def call_tool(self, name: str, arguments: dict[str, Any] | None = None) -> dict[str, Any]:
        if name in FORBIDDEN_TOOLS:
            return {"isError": True, "content": [{"type": "text", "text": f"Refused {name}: recursive self-control is disabled."}]}
        handler = HANDLERS.get(name)
        if not handler:
            return {"isError": True, "content": [{"type": "text", "text": f"Unknown tool {name}"}]}
        try:
            text = await handler(arguments or {})
        except Exception as exc:
            return {"isError": True, "content": [{"type": "text", "text": str(exc)}]}
        return {"isError": False, "content": [{"type": "text", "text": text}]}

    async def handle(self, message: dict[str, Any]) -> dict[str, Any] | None:
        if not isinstance(message, dict):
            return {"jsonrpc": "2.0", "id": None, "error": {"code": -32600, "message": "Invalid request"}}
        method = message.get("method")
        msg_id = message.get("id")
        if method is None:
            return None
        if str(method).startswith("notifications/"):
            return None
        if method == "initialize":
            return {
                "jsonrpc": "2.0",
                "id": msg_id,
                "result": {
                    "protocolVersion": PROTOCOL_VERSION,
                    "capabilities": {"tools": {"listChanged": False}},
                    "serverInfo": {"name": "jarvis", "version": "1.0.0"},
                    "instructions": (
                        "Read-only Jarvis context plus verification/result reporting. "
                        "Do not use this server to start Cursor or a new Jarvis task."
                    ),
                },
            }
        if method == "tools/list":
            return {"jsonrpc": "2.0", "id": msg_id, "result": {"tools": self.list_tools()}}
        if method == "tools/call":
            params = message.get("params") or {}
            name = str(params.get("name") or "")
            arguments = params.get("arguments") or {}
            result = await self.call_tool(name, arguments if isinstance(arguments, dict) else {})
            return {"jsonrpc": "2.0", "id": msg_id, "result": result}
        if method == "ping":
            return {"jsonrpc": "2.0", "id": msg_id, "result": {}}
        return {"jsonrpc": "2.0", "id": msg_id, "error": {"code": -32601, "message": f"Method not found: {method}"}}


SERVER = JarvisMcpServer()
