from __future__ import annotations

import importlib.util
import platform
import shutil
from typing import Any

from ..workers.browser import BrowserUseBackend
from ..workers.code import OpenHandsBackend
from ..workers.voice import voice_status


def _module_available(name: str) -> bool:
    return importlib.util.find_spec(name) is not None


def native_capabilities() -> list[dict[str, Any]]:
    windows = platform.system() == "Windows"
    office = False
    if windows:
        try:
            from ..hardware import detect_hardware

            office = detect_hardware().office_installed
        except Exception:
            office = False
    return [
        {
            "id": "filesystem",
            "name": "Filesystem",
            "kind": "native",
            "available": True,
            "status": "ready",
            "detail": "Deterministic file operations.",
        },
        {
            "id": "terminal",
            "name": "Shell",
            "kind": "native",
            "available": True,
            "status": "ready",
            "detail": "PowerShell on Windows; bash available when present.",
        },
        {
            "id": "python",
            "name": "Python",
            "kind": "native",
            "available": True,
            "status": "ready",
            "detail": "Scripts, venvs, and project installs.",
        },
        {
            "id": "playwright",
            "name": "Playwright",
            "kind": "native",
            "available": _module_available("playwright"),
            "status": "ready" if _module_available("playwright") else "missing",
            "detail": "Deterministic browser backend (default). Browser Use is optional for unfamiliar sites.",
        },
        {
            "id": "windows_ui",
            "name": "Windows UI Automation",
            "kind": "native",
            "available": windows and _module_available("pywinauto"),
            "status": "ready" if windows and _module_available("pywinauto") else "unavailable",
            "detail": "pywinauto / UI Automation. Coordinate clicking is last resort.",
        },
        {
            "id": "office",
            "name": "Microsoft Office COM",
            "kind": "native",
            "available": office,
            "status": "ready" if office else "unavailable",
            "detail": "Word/Excel/PowerPoint when Office is installed.",
        },
        {
            "id": "mcp",
            "name": "MCP",
            "kind": "native",
            "available": _module_available("mcp"),
            "status": "ready" if _module_available("mcp") else "missing",
            "detail": "User-configured stdio or HTTP MCP servers.",
        },
        {
            "id": "git",
            "name": "Git",
            "kind": "native",
            "available": shutil.which("git") is not None,
            "status": "ready" if shutil.which("git") else "missing",
            "detail": "Status, diff, and checkpoints before risky edits.",
        },
        {
            "id": "docker",
            "name": "Docker",
            "kind": "native",
            "available": shutil.which("docker") is not None,
            "status": "ready" if shutil.which("docker") else "unavailable",
            "detail": "Optional. Jarvis continues without it.",
        },
        voice_status(),
    ]


def optional_workers() -> list[dict[str, Any]]:
    return [
        BrowserUseBackend().probe(),
        {
            "id": "ufo",
            "name": "Microsoft UFO",
            "kind": "optional",
            "available": False,
            "status": "not_integrated",
            "detail": "Windows HostAgent/AppAgent worker. Native UI Automation is the current fallback.",
        },
        {
            "id": "cua",
            "name": "Cua",
            "kind": "optional",
            "available": False,
            "status": "not_integrated",
            "detail": "Computer-use worker. Not required for Jarvis to run.",
        },
        {
            "id": "open-interpreter",
            "name": "Open Interpreter",
            "kind": "optional",
            "available": False,
            "status": "not_integrated",
            "detail": "Optional code/shell worker behind an adapter.",
        },
        OpenHandsBackend().probe(),
    ]


def capability_snapshot() -> dict[str, Any]:
    native = native_capabilities()
    optional = optional_workers()
    return {
        "native": native,
        "optional_workers": optional,
        "all": native + optional,
    }
