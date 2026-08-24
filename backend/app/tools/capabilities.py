from __future__ import annotations

import importlib.util
import platform
import shutil
from typing import Any

from ..config import load_settings
from .browser_backends import browser_use_available


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
            "detail": "Deterministic browser backend.",
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
    ]


def optional_workers() -> list[dict[str, Any]]:
    browser_use_installed = browser_use_available()
    return [
        {
            "id": "browser-use",
            "name": "Browser Use",
            "kind": "optional",
            "available": browser_use_installed,
            "status": "ready" if browser_use_installed else "missing",
            "detail": (
                "Intelligent browser discovery worker behind BrowserBackend. "
                "Playwright remains the deterministic default."
            ),
        },
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
        {
            "id": "openhands",
            "name": "OpenHands",
            "kind": "optional",
            "available": False,
            "status": "not_integrated",
            "detail": "Optional software-engineering worker. Jarvis still verifies results.",
        },
    ]


def capability_snapshot() -> dict[str, Any]:
    native = native_capabilities()
    optional = optional_workers()
    settings = load_settings()
    return {
        "native": native,
        "optional_workers": optional,
        "browser_backends": [
            {
                "backend": "playwright",
                "available": _module_available("playwright"),
                "default": (settings.browser.backend or "playwright").lower() in {"playwright", "default", "deterministic"},
            },
            {
                "backend": "browser-use",
                "available": browser_use_available(),
                "default": (settings.browser.backend or "playwright").lower() in {"browser-use", "browser_use", "browseruse", "intelligent"},
            },
        ],
        "all": native + optional,
    }
