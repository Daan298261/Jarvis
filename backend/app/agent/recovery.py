from __future__ import annotations

import re
from dataclasses import dataclass

BLOCKED = "blocked"
PERMISSION = "permission"
NOT_FOUND = "not_found"
TIMEOUT = "timeout"
UNAVAILABLE = "unavailable"
USAGE = "usage"
NETWORK = "network"
UNKNOWN = "unknown"

_PATTERNS: list[tuple[str, tuple[str, ...]]] = [
    (BLOCKED, (r"blocked irreversible", r"blocked identical", r"ask the user explicitly")),
    (PERMISSION, (r"outside allowed directories", r"permission", r"access is denied", r"unauthorized", r"\b403\b")),
    (UNAVAILABLE, (
        r"is not available",
        r"not installed",
        r"is disabled",
        r"no module named",
        r"unknown tool",
        r"is not recognized as",
        r"command not found",
        r"no distro",
    )),
    (TIMEOUT, (r"timed out", r"\btimeout\b")),
    (NETWORK, (r"connection refused", r"connection error", r"failed to resolve", r"name or service not known", r"ssl", r"\bdns\b")),
    (NOT_FOUND, (r"not found", r"does not exist", r"no such file", r"cannot find", r"\b404\b")),
    (USAGE, (r"unknown action", r"is required", r"invalid", r"old_text not found", r"no packages or requirements")),
]


@dataclass(frozen=True)
class Alternative:
    tool: str
    why: str


# Ordered by the plan's tool-selection priority: deterministic APIs and
# libraries before DOM automation, accessibility, and finally vision.
_ALTERNATIVES: dict[str, tuple[Alternative, ...]] = {
    "browser": (
        Alternative("web_fetch", "read the page or its API directly when no JavaScript is needed"),
        Alternative("python", "call the site's API or parse the response with a library"),
        Alternative("screenshot", "look at the page only when the DOM cannot answer the question"),
    ),
    "browser_use": (
        Alternative("browser", "Playwright is the default deterministic backend; use it when selectors are known"),
        Alternative("web_fetch", "read the page or its API directly when no JavaScript is needed"),
        Alternative("python", "call the site's API or parse the response with a library"),
    ),
    "code_worker": (
        Alternative("python", "make the change with a script instead of delegating to OpenHands"),
        Alternative("filesystem", "inspect and edit the files directly"),
        Alternative("git", "inspect the working tree, then apply a smaller native change"),
        Alternative("terminal", "run tests or the project CLI yourself"),
    ),
    "web_fetch": (
        Alternative("browser", "the endpoint needs a real session, cookies, or JavaScript"),
    ),
    "office": (
        Alternative("python", "edit the document with openpyxl / python-docx / python-pptx instead of COM"),
        Alternative("filesystem", "inspect or copy the file directly"),
    ),
    "desktop": (
        Alternative("terminal", "drive the app through its CLI or PowerShell instead of the GUI"),
        Alternative("screenshot", "capture the screen and use vision when UI Automation cannot see the control"),
        Alternative("browser", "use the web interface if the app has one"),
        Alternative("ufo", "Windows HostAgent worker when native UI Automation is not enough"),
        Alternative("cua", "computer-use worker when accessibility lookup fails"),
    ),
    "ufo": (
        Alternative("desktop", "use native UI Automation / pywinauto instead of UFO"),
        Alternative("terminal", "drive the app through its CLI or PowerShell"),
        Alternative("screenshot", "inspect the screen when the worker cannot see the control"),
    ),
    "cua": (
        Alternative("desktop", "use native UI Automation / pywinauto instead of Cua"),
        Alternative("terminal", "drive the app through its CLI or PowerShell"),
        Alternative("screenshot", "inspect the screen when the worker cannot see the control"),
    ),
    "terminal": (
        Alternative("python", "do the work in a script instead of a shell one-liner"),
        Alternative("filesystem", "use direct file operations for file work"),
    ),
    "python": (
        Alternative("terminal", "run the interpreter or tool directly and read stderr"),
        Alternative("filesystem", "inspect the inputs before running code again"),
        Alternative("code_worker", "delegate a larger coding job to Open Interpreter when it is installed"),
    ),
    "code_worker": (
        Alternative("python", "write and run the script with the native python tool"),
        Alternative("terminal", "run the commands directly"),
        Alternative("filesystem", "inspect or edit the files yourself"),
    ),
    "docker": (
        Alternative("terminal", "run the process locally; Docker may not be installed"),
        Alternative("python", "reproduce the job in a virtualenv"),
    ),
    "filesystem": (
        Alternative("python", "glob, compare, or transform files in a script"),
        Alternative("terminal", "inspect the path with a shell command"),
    ),
    "git": (
        Alternative("terminal", "run the git command directly to see the full error"),
    ),
    "screenshot": (
        Alternative("desktop", "query the UI Automation tree instead of pixels"),
    ),
}

_NATIVE_FALLBACK = (
    Alternative("filesystem", "use the native tool instead of the MCP server"),
    Alternative("terminal", "use a local command instead of the MCP server"),
)

_KIND_GUIDANCE: dict[str, str] = {
    BLOCKED: "This action is deliberately blocked. Achieve the goal a safer way, or explain why it cannot be done without the user.",
    PERMISSION: "This is a permissions or sandbox boundary, not a transient error. Work inside the allowed directories, or use a path the task actually authorizes.",
    NOT_FOUND: "The target does not exist where you looked. Inspect the parent directory or search for it before acting again.",
    TIMEOUT: "The operation did not finish in time. Reduce the scope, raise the timeout deliberately, or run it as a background step.",
    UNAVAILABLE: "That capability is missing on this machine. Do not retry it. Switch to an available tool.",
    USAGE: "The call itself was malformed. Re-read the tool's parameters and send corrected arguments.",
    NETWORK: "The network call failed. Verify the host and try a different endpoint or transport.",
    UNKNOWN: "Read the error text and change one thing deliberately before retrying.",
}


def classify_failure(observation: str) -> str:
    text = (observation or "").lower()
    for kind, patterns in _PATTERNS:
        for pattern in patterns:
            if re.search(pattern, text):
                return kind
    return UNKNOWN


def alternatives_for(tool: str, kind: str) -> list[Alternative]:
    options = _NATIVE_FALLBACK if tool.startswith("mcp_") else _ALTERNATIVES.get(tool, ())
    if kind in {PERMISSION, BLOCKED}:
        # A different tool does not grant more rights, so do not suggest one.
        return []
    return list(options)


def recovery_hint(tool: str, observation: str, attempt: int = 1) -> str:
    kind = classify_failure(observation)
    lines = [f"{tool} failed ({kind.replace('_', ' ')}). {_KIND_GUIDANCE[kind]}"]
    options = alternatives_for(tool, kind)
    if options:
        limit = 1 if attempt <= 1 else len(options)
        lines.append("Alternative tools, most deterministic first:")
        lines.extend(f"- {item.tool}: {item.why}" for item in options[:limit])
    if kind == UNAVAILABLE:
        lines.append("If that tool is not in the current exposed set, call request_capability with its name.")
    if attempt >= 3:
        lines.append(
            "Several strategies have now failed. Re-check your assumptions about the environment, "
            "inspect the actual state before acting, and change approach rather than parameters."
        )
    lines.append("Do not repeat the call that just failed.")
    return "\n".join(lines)
