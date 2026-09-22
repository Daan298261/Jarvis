from __future__ import annotations

import logging
import os
import re
from contextlib import AsyncExitStack
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .base import RiskLevel, Tool, ToolResult

log = logging.getLogger(__name__)

_SAFE_NAME = re.compile(r"[^a-zA-Z0-9_-]+")


def mcp_prefix_dir() -> Path:
    from ..config import repo_root

    return repo_root() / "mcp"


def mcp_tool_key(server_name: str, tool_name: str) -> str:
    raw = f"mcp_{server_name}_{tool_name}"
    cleaned = _SAFE_NAME.sub("_", raw).strip("_") or "mcp_tool"
    return cleaned[:64]


def prepare_stdio_launch(server: dict[str, Any]) -> dict[str, Any]:
    """Make stdio MCP launches independent of process CWD."""
    from ..config import repo_root

    root = repo_root()
    prefix = mcp_prefix_dir()
    command = str(server.get("command") or "npx")
    args = [str(item) for item in (server.get("args") or [])]
    for index, arg in enumerate(args):
        if arg in {"mcp", "./mcp"} and index > 0 and args[index - 1] == "--prefix":
            args[index] = str(prefix)
    env_in = server.get("env") or {}
    env = {str(key): str(value) for key, value in os.environ.items() if value is not None}
    for key, value in env_in.items():
        if value is None:
            continue
        env[str(key)] = str(value)
    return {
        "command": command,
        "args": args,
        "cwd": str(root),
        "env": env,
    }


@dataclass
class _LiveClient:
    stack: AsyncExitStack
    session: Any
    fingerprint: str


class MCPRuntime:
    def __init__(self) -> None:
        import asyncio

        self._tools: dict[str, dict[str, Any]] = {}
        self._status: dict[str, dict[str, Any]] = {}
        self._sessions: dict[str, _LiveClient] = {}
        self._lock = asyncio.Lock()

    def has_tools(self) -> bool:
        return bool(self._tools)

    def snapshot(self) -> dict[str, dict[str, Any]]:
        return {name: dict(row) for name, row in self._status.items()}

    def connected_keys(self) -> list[str]:
        return list(self._tools)

    def reset_for_tests(self) -> None:
        self._tools = {}
        self._status = {}

    def _server_id(self, server: dict[str, Any]) -> str:
        return str(server.get("id") or server.get("name") or "unnamed")

    def _fingerprint(self, server: dict[str, Any]) -> str:
        transport = (server.get("transport") or "stdio").lower()
        if transport == "stdio":
            launch = prepare_stdio_launch(server)
            return f"stdio:{launch['command']}:{' '.join(launch['args'])}:{launch['cwd']}"
        return f"{transport}:{server.get('url') or ''}"

    async def _close_session(self, server_id: str) -> None:
        live = self._sessions.pop(server_id, None)
        if live is None:
            return
        try:
            await live.stack.aclose()
        except Exception:
            log.debug("MCP session close failed for %s", server_id, exc_info=True)

    async def close_all(self) -> None:
        for server_id in list(self._sessions):
            await self._close_session(server_id)

    async def refresh(self, servers: list[dict[str, Any]]) -> dict[str, str]:
        status: dict[str, str] = {}
        async with self._lock:
            await self.close_all()
            self._tools = {}
            self._status = {}
            for server in servers:
                name = str(server.get("name") or "unnamed")
                if not server.get("enabled", True):
                    status[name] = "disabled"
                    self._status[name] = {"status": "disabled", "tools": [], "error": ""}
                    continue
                try:
                    tools = await self._list_tools(server)
                    listed: list[str] = []
                    for tool in tools:
                        tool_name = str(tool.get("name") or "tool")
                        key = mcp_tool_key(name, tool_name)
                        self._tools[key] = {"server": server, "tool": tool, "remote_name": tool_name}
                        listed.append(tool_name)
                    label = f"{len(tools)} tools"
                    status[name] = label
                    self._status[name] = {"status": label, "tools": listed, "error": ""}
                except Exception as exc:
                    status[name] = f"error: {exc}"
                    self._status[name] = {"status": "error", "tools": [], "error": str(exc)[:800]}
                    await self._close_session(self._server_id(server))
        return status

    async def _connect(self, server: dict[str, Any]) -> Any:
        from mcp import ClientSession

        server_id = self._server_id(server)
        fingerprint = self._fingerprint(server)
        live = self._sessions.get(server_id)
        if live is not None and live.fingerprint == fingerprint:
            return live.session
        if live is not None:
            await self._close_session(server_id)

        stack = AsyncExitStack()
        transport = (server.get("transport") or "stdio").lower()
        try:
            if transport == "stdio":
                from mcp.client.stdio import StdioServerParameters, stdio_client

                launch = prepare_stdio_launch(server)
                params = StdioServerParameters(
                    command=launch["command"],
                    args=launch["args"],
                    env=launch["env"],
                    cwd=launch["cwd"],
                )
                read, write = await stack.enter_async_context(stdio_client(params))
            elif transport in {"http", "sse", "streamable-http"}:
                from mcp.client.streamable_http import streamablehttp_client

                url = server.get("url")
                read, write, _ = await stack.enter_async_context(streamablehttp_client(url))
            else:
                await stack.aclose()
                raise RuntimeError(f"Unsupported MCP transport {transport}")
            session = await stack.enter_async_context(ClientSession(read, write))
            await session.initialize()
        except Exception:
            await stack.aclose()
            raise
        self._sessions[server_id] = _LiveClient(stack=stack, session=session, fingerprint=fingerprint)
        return session

    async def _list_tools(self, server: dict[str, Any]) -> list[dict[str, Any]]:
        session = await self._connect(server)
        listing = await session.list_tools()
        return [t.model_dump() if hasattr(t, "model_dump") else dict(t) for t in listing.tools]

    def _lookup(self, tool_key: str) -> dict[str, Any] | None:
        spec = self._tools.get(tool_key)
        if spec:
            return spec
        cleaned = mcp_tool_key("x", tool_key).removeprefix("mcp_x_")
        for key, row in self._tools.items():
            if key == tool_key or key.endswith(f"_{cleaned}") or row.get("remote_name") == tool_key:
                return row
        return None

    async def call(self, tool_key: str, arguments: dict[str, Any]) -> ToolResult:
        spec = self._lookup(tool_key)
        if not spec:
            return ToolResult(False, "", error=f"Unknown MCP tool {tool_key}")
        server = spec["server"]
        name = spec.get("remote_name") or spec["tool"]["name"]
        server_id = self._server_id(server)
        last_error = ""
        for attempt in range(2):
            try:
                async with self._lock:
                    if attempt:
                        await self._close_session(server_id)
                    session = await self._connect(server)
                    result = await session.call_tool(name, arguments or {})
                is_error = bool(getattr(result, "is_error", False) or getattr(result, "isError", False))
                return ToolResult(not is_error, str(getattr(result, "content", result)))
            except Exception as exc:
                last_error = str(exc)
                log.debug("MCP call %s attempt %s failed: %s", tool_key, attempt + 1, exc)
                await self._close_session(server_id)
        return ToolResult(False, "", error=last_error or f"MCP call failed for {tool_key}")

    def openai_tools(self) -> list[dict[str, Any]]:
        tools = []
        for key, spec in self._tools.items():
            tool = spec["tool"]
            tools.append(
                {
                    "type": "function",
                    "function": {
                        "name": key,
                        "description": f"MCP:{spec['server'].get('name')} {tool.get('description') or tool.get('name')}",
                        "parameters": tool.get("inputSchema") or {"type": "object", "properties": {}},
                    },
                }
            )
        return tools


MCP = MCPRuntime()


class MCPProxyTool(Tool):
    name = "mcp_call"
    description = (
        "Call a configured MCP server tool by mcp_tool name (for example mcp_email_send) "
        "with JSON arguments. Prefer a dedicated mcp_* schema when it is listed."
    )
    risk = RiskLevel.MEDIUM
    parameters = {
        "type": "object",
        "properties": {
            "mcp_tool": {"type": "string"},
            "arguments": {"type": "object"},
        },
        "required": ["mcp_tool"],
    }

    async def execute(self, **kwargs: Any) -> ToolResult:
        key = str(kwargs.get("mcp_tool") or kwargs.get("name") or "")
        return await MCP.call(key, kwargs.get("arguments") or {})
