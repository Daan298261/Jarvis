from __future__ import annotations

from typing import Any, Callable

from ..config import AppSettings, default_allowed_directories
from .base import Tool, ToolResult
from .browser import BrowserTool
from .browser_use import BrowserUseTool
from .capability import RequestCapabilityTool
from .code_worker import CodeWorkerTool
from .computer_use import CuaTool, UFOTool
from .desktop import DesktopTool
from .docker_tools import DockerTool
from .exposure import REQUEST_CAPABILITY, ToolExposure
from .filesystem import FilesystemTool
from .git_tools import GitTool
from .mcp_runtime import MCP, MCPProxyTool
from .office import OfficeTool
from .python_exec import PythonTool
from .request_tools import RequestToolsTool
from .screenshot import ScreenshotTool
from .terminal import TerminalTool
from .web_fetch import WebFetchTool


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
            DesktopTool(),
            OfficeTool(getter),
            GitTool(getter),
            DockerTool(),
            WebFetchTool(getter),
            ScreenshotTool(),
            RequestToolsTool(),
            MCPProxyTool(),
            UFOTool(),
            CuaTool(),
        ]
        self.tools = {tool.name: tool for tool in items}

    def bind_exposure(self, exposure: ToolExposure | None) -> None:
        self._context["exposure"] = exposure

    def apply_settings(self, settings: AppSettings) -> None:
        allowed = settings.allowed_directories or default_allowed_directories()
        exposure = self._context.get("exposure")
        self._context = {
            "allowed_directories": allowed,
            "autonomy": settings.autonomy,
            "browser": settings.browser.model_dump(),
            "backup_enabled": settings.backup_enabled,
            "exposure": exposure,
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
        include_mcp = names is None or "mcp" in names
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
                }
            )
        return out

    def enable(self, name: str, enabled: bool = True) -> None:
        if name in self.tools:
            self.tools[name].enabled = enabled

    async def execute(self, name: str, arguments: dict[str, Any]) -> ToolResult:
        exposure = self._context.get("exposure")
        if isinstance(exposure, ToolExposure):
            if name == REQUEST_CAPABILITY:
                arguments = dict(arguments or {})
                arguments.setdefault("task_class", exposure.task_class)
            elif name.startswith("mcp_"):
                exposure.grant("mcp")
            elif name in self.tools:
                exposure.ensure_named_tool(name)
        if name.startswith("mcp_"):
            return await MCP.call(name, arguments)
        tool = self.tools.get(name)
        if not tool:
            return ToolResult(False, "", error=f"Unknown tool {name}")
        if not tool.enabled:
            return ToolResult(False, "", error=f"Tool {name} is disabled")
        return await tool.execute(**arguments)


REGISTRY = ToolRegistry()
