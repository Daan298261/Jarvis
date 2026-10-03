from __future__ import annotations

import inspect
import logging
import os
import re
from contextlib import AsyncExitStack
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from .base import RiskLevel, Tool, ToolResult

log = logging.getLogger(__name__)

_SAFE_NAME = re.compile(r"[^a-zA-Z0-9_-]+")


def _looks_like_fs_path(arg: str) -> bool:
    text = str(arg or "")
    if not text or text.startswith(("@", "-", "http:", "https:")):
        return False
    if text.startswith("/") or text.startswith("\\\\") or text.startswith("./") or text.startswith("../"):
        return True
    if len(text) >= 3 and text[1] == ":" and text[0].isalpha():
        return True
    return "\\" in text


def mcp_filesystem_directories(allowed: list[str] | None = None) -> list[str]:
    """Directories to pass to MCP ``server-filesystem``.

    The official server only sees argv roots. Documents-only meant a plugged-in
    USB or ``D:`` was invisible to MCP file tools. Extra volumes plus the
    owner's Documents folder; never the OS volume root or the LAN UNC sentinel.
    """
    from ..config import LOCAL_NETWORK_SCOPE, extra_volume_roots, live_allowed_directories
    from .filesystem import _root_key, _system_volume_keys
    from .owner_paths import default_workspace_dir
    from .safety import resolve_allowed_path

    roots = list(allowed if allowed is not None else live_allowed_directories())
    skip = _system_volume_keys()
    found: list[str] = []
    seen: set[str] = set()

    def _take(raw: str) -> None:
        text = str(raw or "").strip()
        if not text or text == LOCAL_NETWORK_SCOPE:
            return
        try:
            path = resolve_allowed_path(text, roots)
        except (PermissionError, OSError, ValueError):
            return
        try:
            if not path.is_dir():
                return
            resolved = path.resolve()
        except OSError:
            return
        key = _root_key(resolved)
        if key in seen or key in skip:
            return
        seen.add(key)
        found.append(str(resolved))

    for extra in extra_volume_roots():
        _take(str(extra))
    try:
        _take(str(default_workspace_dir(roots)))
    except (PermissionError, OSError, ValueError):
        pass
    return found[:16]


def mcp_prefix_dir() -> Path:
    from ..config import repo_root

    return repo_root() / "mcp"


def mcp_tool_key(server_name: str, tool_name: str) -> str:
    raw = f"mcp_{server_name}_{tool_name}"
    cleaned = _SAFE_NAME.sub("_", raw).strip("_") or "mcp_tool"
    return cleaned[:64]


def prepare_stdio_launch(server: dict[str, Any]) -> dict[str, Any]:
    """Make stdio MCP launches independent of process CWD."""
    from ..config import live_allowed_directories, repo_root
    from .safety import resolve_allowed_path

    root = repo_root()
    prefix = mcp_prefix_dir()
    command = str(server.get("command") or "npx")
    args = [str(item) for item in (server.get("args") or [])]
    for index, arg in enumerate(args):
        if arg in {"mcp", "./mcp"} and index > 0 and args[index - 1] == "--prefix":
            args[index] = str(prefix)
    allowed = live_allowed_directories()
    cwd = str(root)
    raw_cwd = str(server.get("cwd") or "").strip()
    if raw_cwd and allowed:
        try:
            resolved_cwd = resolve_allowed_path(raw_cwd, allowed)
            if resolved_cwd.is_dir():
                cwd = str(resolved_cwd)
        except (PermissionError, OSError):
            cwd = str(root)
    if _looks_like_fs_path(command) and allowed:
        try:
            command = str(resolve_allowed_path(command, allowed))
        except (PermissionError, OSError):
            pass
    if allowed:
        rewritten: list[str] = []
        for arg in args:
            if not _looks_like_fs_path(arg):
                rewritten.append(arg)
                continue
            try:
                rewritten.append(str(resolve_allowed_path(arg, allowed)))
            except (PermissionError, OSError):
                rewritten.append(arg)
        args = rewritten
        if any("server-filesystem" in arg for arg in args) and not any(_looks_like_fs_path(arg) for arg in args):
            args.extend(mcp_filesystem_directories(allowed))
    env_in = server.get("env") or {}
    env = {str(key): str(value) for key, value in os.environ.items() if value is not None}
    for key, value in env_in.items():
        if value is None:
            continue
        env[str(key)] = str(value)
    from ..security.hexstrike import hexstrike_child_env, is_hexstrike_mcp_server

    if is_hexstrike_mcp_server(server):
        env = hexstrike_child_env(env)
    return {
        "command": command,
        "args": args,
        "cwd": cwd,
        "env": env,
    }


def mcp_url_bypasses_env_proxy(url: str) -> bool:
    """Loopback / RFC1918 MCP HTTP must not follow HTTP_PROXY (VPN steal-default)."""
    from .safety import is_owner_local_host

    host = (urlparse(str(url or "")).hostname or "").strip()
    return bool(host) and is_owner_local_host(host)


def _mcp_direct_http_client(**kwargs: Any):
    """httpx/httpx2 client that ignores process proxy env (HexStrike loopback)."""
    options = dict(kwargs)
    options["trust_env"] = False
    try:
        from mcp.shared._httpx_utils import MCP_DEFAULT_SSE_READ_TIMEOUT, MCP_DEFAULT_TIMEOUT

        import httpx2

        options.setdefault("timeout", httpx2.Timeout(MCP_DEFAULT_TIMEOUT, read=MCP_DEFAULT_SSE_READ_TIMEOUT))
        return httpx2.AsyncClient(**options)
    except Exception:
        import httpx

        options.setdefault("timeout", 30.0)
        return httpx.AsyncClient(**options)


def _streamable_http_opener():
    from mcp.client import streamable_http as module

    return getattr(module, "streamablehttp_client", None) or getattr(module, "streamable_http_client")


def streamable_http_proxy_bypass_param(server: dict[str, Any], opener: Any | None = None) -> str | None:
    """Which opener kwarg binds a trust_env=False client for owner-local MCP HTTP."""
    from ..security.hexstrike import is_hexstrike_mcp_server

    url = str(server.get("url") or "")
    if not mcp_url_bypasses_env_proxy(url) and not is_hexstrike_mcp_server(server):
        return None
    target = opener
    if target is None:
        try:
            target = _streamable_http_opener()
        except Exception:
            return None
    try:
        names = set(inspect.signature(target).parameters)
    except (TypeError, ValueError):
        return None
    if "http_client" in names:
        return "http_client"
    if "httpx_client_factory" in names:
        return "httpx_client_factory"
    return None


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
                opener = _streamable_http_opener()
                url = str(server.get("url") or "")
                kwargs: dict[str, Any] = {}
                param = streamable_http_proxy_bypass_param(server, opener)
                if param == "http_client":
                    client = _mcp_direct_http_client()
                    await stack.enter_async_context(client)
                    kwargs["http_client"] = client
                elif param == "httpx_client_factory":
                    kwargs["httpx_client_factory"] = lambda **factory_kw: _mcp_direct_http_client(**factory_kw)
                streams = await stack.enter_async_context(opener(url, **kwargs))
                read, write = streams[0], streams[1]
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
        args = dict(arguments or {})
        from ..security.hexstrike_defensive import (
            bind_hexstrike_lan_payload,
            looks_like_nmap_tool,
            looks_like_snmp_tool,
            looks_like_iface_host_tool,
            lan_inventory_uses_host_nmap,
            lan_uses_host_iface_argv,
            nmap_target_from_payload,
            lan_bind_target,
            lan_bind_nic,
            _host_nmap_lan_scan,
            _host_snmp_lan,
            _host_iface_lan,
            _iface_lan_target,
        )

        args = bind_hexstrike_lan_payload(str(tool_key or name), args)
        if looks_like_nmap_tool(tool_key) or looks_like_nmap_tool(str(name)):
            target = nmap_target_from_payload(args)
            if lan_inventory_uses_host_nmap(target):
                data = await _host_nmap_lan_scan({**args, "target": target})
                return ToolResult(True, str(data.get("stdout") or data), data=data)
        if looks_like_snmp_tool(tool_key) or looks_like_snmp_tool(str(name)):
            target = lan_bind_target(args) or nmap_target_from_payload(args)
            if lan_bind_nic(target)[1]:
                data = await _host_snmp_lan(str(tool_key or name), args)
                return ToolResult(True, str(data.get("stdout") or data), data=data)
        if looks_like_iface_host_tool(tool_key) or looks_like_iface_host_tool(str(name)):
            target = _iface_lan_target(args)
            if lan_uses_host_iface_argv(target):
                data = await _host_iface_lan(str(tool_key or name), args)
                return ToolResult(True, str(data.get("stdout") or data), data=data)
        server_id = self._server_id(server)
        last_error = ""
        for attempt in range(2):
            try:
                async with self._lock:
                    if attempt:
                        await self._close_session(server_id)
                    session = await self._connect(server)
                    result = await session.call_tool(name, args)
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
