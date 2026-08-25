from __future__ import annotations

from typing import Iterable

REQUEST_CAPABILITY = "request_capability"

# Always available so the model can ask for a missing capability.
CORE_TOOLS = frozenset({"filesystem", REQUEST_CAPABILITY})

# Task class → native tools Jarvis should send on each inference call.
# Keep these small: the point is fewer definitions, less confusion, lower latency.
TASK_TOOL_SETS: dict[str, frozenset[str]] = {
    "filesystem": frozenset({"filesystem", "python"}),
    "shell": frozenset({"filesystem", "terminal", "python"}),
    "system administration": frozenset({"filesystem", "terminal", "python"}),
    "software engineering": frozenset({"filesystem", "terminal", "python", "git"}),
    "research": frozenset({"filesystem", "web_fetch", "browser", "python"}),
    "browser automation": frozenset({"filesystem", "browser", "web_fetch"}),
    "windows gui": frozenset({"filesystem", "desktop", "screenshot", "terminal"}),
    "office": frozenset({"filesystem", "office", "python"}),
    "document processing": frozenset({"filesystem", "office", "python"}),
    "data processing": frozenset({"filesystem", "python", "terminal"}),
    "multimodal": frozenset({"filesystem", "screenshot", "desktop", "browser"}),
    "mixed": frozenset({"filesystem", "terminal", "python", "git", "web_fetch"}),
    "long-horizon autonomous": frozenset(
        {"filesystem", "terminal", "python", "git", "web_fetch", "browser"}
    ),
}

CAPABILITY_ALIASES: dict[str, str] = {
    "file": "filesystem",
    "files": "filesystem",
    "fs": "filesystem",
    "shell": "terminal",
    "powershell": "terminal",
    "cmd": "terminal",
    "bash": "terminal",
    "py": "python",
    "playwright": "browser",
    "web": "web_fetch",
    "http": "web_fetch",
    "http_get": "web_fetch",
    "uia": "desktop",
    "windows_ui": "desktop",
    "ui": "desktop",
    "vision": "screenshot",
    "image": "screenshot",
    "word": "office",
    "excel": "office",
    "powerpoint": "office",
    "com": "office",
    "repo": "git",
    "containers": "docker",
    "mcp_server": "mcp",
}

NATIVE_TOOLS = (
    "filesystem",
    "terminal",
    "python",
    "browser",
    "desktop",
    "office",
    "git",
    "docker",
    "web_fetch",
    "screenshot",
    "mcp",
    REQUEST_CAPABILITY,
)


def normalize_capability(name: str | None) -> str:
    key = (name or "").strip().lower().replace("-", "_").replace(" ", "_")
    if key.startswith("mcp_"):
        return "mcp"
    return CAPABILITY_ALIASES.get(key, key)


def tools_for_task(task_class: str | None) -> set[str]:
    key = (task_class or "mixed").strip().lower()
    selected = TASK_TOOL_SETS.get(key, TASK_TOOL_SETS["mixed"])
    return set(CORE_TOOLS | selected)


def exposure_catalog() -> dict[str, list[str]]:
    return {name: sorted(tools_for_task(name)) for name in sorted(TASK_TOOL_SETS)}


class ToolExposure:
    """Per-task set of tool definitions sent to the model."""

    def __init__(self, task_class: str | None = None) -> None:
        self.task_class = (task_class or "mixed").strip() or "mixed"
        self.granted: set[str] = set()

    def names(self) -> set[str]:
        return tools_for_task(self.task_class) | self.granted

    def grant(self, requested: str | None) -> tuple[bool, str, list[str]]:
        name = normalize_capability(requested)
        if not name:
            return False, "name is required to request a capability", []
        if name not in NATIVE_TOOLS:
            known = ", ".join(NATIVE_TOOLS)
            return False, f"Unknown capability {requested!r}. Known: {known}", []
        if name in self.names() and name != REQUEST_CAPABILITY:
            return True, f"{name} is already available for this task.", []
        self.granted.add(name)
        extra: list[str] = []
        if name == "browser":
            extra.append("web_fetch")
        elif name == "desktop":
            extra.append("screenshot")
        elif name == "office":
            extra.append("python")
        for item in extra:
            self.granted.add(item)
        added = [name, *[item for item in extra if item != name]]
        return True, f"Granted {', '.join(added)}. Use those tools on the next turn.", added

    def ensure_named_tool(self, tool_name: str) -> bool:
        """Escape hatch: if the model named a real hidden tool, expose it and allow the call."""
        name = normalize_capability(tool_name)
        if name == REQUEST_CAPABILITY:
            return True
        if name not in NATIVE_TOOLS and not str(tool_name).startswith("mcp_"):
            return False
        if name not in self.names():
            self.grant(name)
            return True
        return True


def schema_names(schemas: Iterable[dict]) -> list[str]:
    names: list[str] = []
    for item in schemas:
        function = item.get("function") if isinstance(item, dict) else None
        if isinstance(function, dict) and function.get("name"):
            names.append(str(function["name"]))
    return names
