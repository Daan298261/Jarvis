from __future__ import annotations

import asyncio
from typing import Any
from urllib.parse import urlparse

from .base import RiskLevel, Tool, ToolResult


class MCPRuntime:
    def __init__(self) -> None:
        self._tools: dict[str, dict[str, Any]] = {}
        self._lock = asyncio.Lock()

    async def refresh(self, servers: list[dict[str, Any]]) -> dict[str, str]:
        status: dict[str, str] = {}
        async with self._lock:
            self._tools = {}
            for server in servers:
                if not server.get("enabled", True):
                    status[server.get("name", "unnamed")] = "disabled"
                    continue
                try:
                    tools = await self._list_tools(server)
                    for tool in tools:
                        key = f"mcp_{server.get('name')}_{tool['name']}"
                        self._tools[key] = {"server": server, "tool": tool}
                    status[server.get("name", "unnamed")] = f"{len(tools)} tools"
                except Exception as exc:
                    status[server.get("name", "unnamed")] = f"error: {exc}"
        return status

    async def _list_tools(self, server: dict[str, Any]) -> list[dict[str, Any]]:
        from mcp import ClientSession
        from mcp.client.stdio import StdioServerParameters, stdio_client

        transport = (server.get("transport") or "stdio").lower()
        if transport == "stdio":
            params = StdioServerParameters(
                command=server.get("command") or "npx",
                args=server.get("args") or [],
                env=server.get("env") or None,
            )
            async with stdio_client(params) as (read, write):
                async with ClientSession(read, write) as session:
                    await session.initialize()
                    listing = await session.list_tools()
                    return [t.model_dump() if hasattr(t, "model_dump") else dict(t) for t in listing.tools]
        if transport in {"http", "sse", "streamable-http"}:
            from mcp.client.streamable_http import streamablehttp_client

            url = server.get("url")
            async with streamablehttp_client(url) as (read, write, _):
                async with ClientSession(read, write) as session:
                    await session.initialize()
                    listing = await session.list_tools()
                    return [t.model_dump() if hasattr(t, "model_dump") else dict(t) for t in listing.tools]
        raise RuntimeError(f"Unsupported MCP transport {transport}")

    async def call(self, tool_key: str, arguments: dict[str, Any]) -> ToolResult:
        spec = self._tools.get(tool_key)
        if not spec:
            return ToolResult(False, "", error=f"Unknown MCP tool {tool_key}")
        server = spec["server"]
        name = spec["tool"]["name"]
        try:
            from mcp import ClientSession
            from mcp.client.stdio import StdioServerParameters, stdio_client

            transport = (server.get("transport") or "stdio").lower()
            if transport == "stdio":
                params = StdioServerParameters(
                    command=server.get("command") or "npx",
                    args=server.get("args") or [],
                    env=server.get("env") or None,
                )
                async with stdio_client(params) as (read, write):
                    async with ClientSession(read, write) as session:
                        await session.initialize()
                        result = await session.call_tool(name, arguments)
                        return ToolResult(not result.isError, str(result.content))
            if transport in {"http", "sse", "streamable-http"}:
                from mcp.client.streamable_http import streamablehttp_client

                async with streamablehttp_client(server.get("url")) as (read, write, _):
                    async with ClientSession(read, write) as session:
                        await session.initialize()
                        result = await session.call_tool(name, arguments)
                        return ToolResult(not result.isError, str(result.content))
            return ToolResult(False, "", error="Unsupported transport")
        except Exception as exc:
            return ToolResult(False, "", error=str(exc))

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
    description = "Call a configured MCP server tool by mcp_tool name with JSON arguments."
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
        return await MCP.call(kwargs.get("mcp_tool") or "", kwargs.get("arguments") or {})
