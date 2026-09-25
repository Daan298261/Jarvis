from __future__ import annotations

import time
from typing import Any, Callable

from ..config import AppSettings, default_allowed_directories
from .base import Tool, ToolResult
from .browser import BrowserTool
from .browser_use import BrowserUseTool
from .capability import RequestCapabilityTool
from .code_worker import CodeWorkerTool
from .computer_use import CuaTool, ReflexComputerUseTool, UFOTool
from .desktop import DesktopTool
from .docker_tools import DockerTool
from .exposure import REQUEST_CAPABILITY, ToolExposure
from .filesystem import FilesystemTool
from .git_tools import GitTool
from .interpreter import OpenInterpreterTool
from .mcp_runtime import MCP, MCPProxyTool
from .office import OfficeTool
from .python_exec import PythonTool
from .request_tools import RequestToolsTool
from .screenshot import ScreenshotTool
from .terminal import TerminalTool
from .verify_code import VerifyCodeTool
from .external_ingest import ExternalIngestTool
from .internal_references import InternalReferencesTool
from .web_fetch import WebFetchTool
from .mobile_call import MobileCallTool
from .hexstrike_defensive import HexStrikeDefensiveTool
from .hexstrike_operator import HexStrikeOperatorTool
from .chat_projects import ChatProjectsTool
from .vault_memory import VaultMemoryTool
from .intelligence import IntelligenceTool
from .dcc_tools import BlenderTool, FreecadTool, OpenScadTool


class ToolRegistry:
    def __init__(self) -> None:
        self._context: dict[str, Any] = {}
        self.tools: dict[str, Tool] = {}
        self._init_tools()

    def _init_tools(self) -> None:
        getter: Callable[[], dict[str, Any]] = lambda: self._context
        items = [
            FilesystemTool(getter),
            TerminalTool(),
            PythonTool(),
            BrowserTool(getter),
            BrowserUseTool(),
            CodeWorkerTool(getter),
            OpenInterpreterTool(getter),
            DesktopTool(),
            OfficeTool(getter),
            GitTool(getter),
            DockerTool(),
            WebFetchTool(getter),
            ExternalIngestTool(getter),
            InternalReferencesTool(),
            ScreenshotTool(),
            VerifyCodeTool(getter),
            RequestToolsTool(),
            RequestCapabilityTool(),
            MCPProxyTool(),
            UFOTool(),
            CuaTool(),
            ReflexComputerUseTool(),
            MobileCallTool(),
            HexStrikeDefensiveTool(getter),
            HexStrikeOperatorTool(getter),
            ChatProjectsTool(),
            VaultMemoryTool(),
            IntelligenceTool(),
            BlenderTool(getter),
            OpenScadTool(getter),
            FreecadTool(getter),
        ]
        self.tools = {tool.name: tool for tool in items}

    def bind_exposure(self, exposure: ToolExposure | None) -> None:
        self._context["exposure"] = exposure

    def apply_settings(self, settings: AppSettings) -> None:
        allowed = settings.allowed_directories or default_allowed_directories()
        exposure = self._context.get("exposure")
        security_role = self._context.get("security_role")
        self._context = {
            "allowed_directories": allowed,
            "autonomy": settings.autonomy,
            "browser": settings.browser.model_dump(),
            "backup_enabled": settings.backup_enabled,
            "exposure": exposure,
            "security_role": security_role,
        }
        disabled = set(settings.disabled_tools or [])
        for name, tool in self.tools.items():
            tool.enabled = name not in disabled

    def openai_tools(self, names: set[str] | None = None) -> list[dict[str, Any]]:
        native = [
            tool.schema()
            for tool in self.tools.values()
            if tool.enabled and (names is None or tool.name in names)
        ]
        include_mcp = names is None or "mcp" in names or "mcp_call" in names
        return native + (MCP.openai_tools() if include_mcp else [])

    def list_tools(self) -> list[dict[str, Any]]:
        out = []
        for tool in self.tools.values():
            out.append(
                {
                    "name": tool.name,
                    "description": tool.description,
                    "enabled": tool.enabled,
                    "risk": tool.risk.value,
                    "effect_class": getattr(tool, "effect_class", "internal"),
                    "replay_policy": getattr(tool, "replay_policy", None),
                }
            )
        return out

    def enable(self, name: str, enabled: bool = True) -> None:
        if name in self.tools:
            self.tools[name].enabled = enabled

    async def execute(
        self,
        name: str,
        arguments: dict[str, Any],
        *,
        security_role: str | None = None,
    ) -> ToolResult:
        self._context["security_role"] = security_role or ""
        exposure = self._context.get("exposure")
        if isinstance(exposure, ToolExposure):
            if name in {REQUEST_CAPABILITY, "request_tools"}:
                arguments = dict(arguments or {})
                arguments.setdefault("task_class", exposure.task_class)
            elif name.startswith("mcp_"):
                exposure.grant("mcp")
            elif name in self.tools:
                exposure.ensure_named_tool(name)
        from ..observability.rolling_log import record_tool_call

        started = time.perf_counter()
        try:
            if name == "mcp_call":
                proxy = self.tools.get("mcp_call")
                if not proxy or not proxy.enabled:
                    result = ToolResult(False, "", error="Tool mcp_call is disabled")
                else:
                    result = await proxy.execute(**arguments)
            elif name.startswith("mcp_"):
                result = await MCP.call(name, arguments)
            else:
                tool = self.tools.get(name)
                if not tool:
                    result = ToolResult(False, "", error=f"Unknown tool {name}")
                elif not tool.enabled:
                    result = ToolResult(False, "", error=f"Tool {name} is disabled")
                else:
                    result = await tool.execute(**arguments)
        except Exception as exc:
            duration_ms = (time.perf_counter() - started) * 1000.0
            record_tool_call(
                name=name,
                arguments=arguments,
                success=False,
                error=str(exc),
                duration_ms=duration_ms,
            )
            raise
        duration_ms = (time.perf_counter() - started) * 1000.0
        record_tool_call(
            name=name,
            arguments=arguments,
            success=result.success,
            error=result.error,
            duration_ms=duration_ms,
        )
        return result


REGISTRY = ToolRegistry()
