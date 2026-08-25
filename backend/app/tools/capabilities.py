from __future__ import annotations

import importlib.util
import platform
import shutil
from typing import Any

from ..agent.acp import acp_status
from ..agent.coding_workers import coding_worker_catalog
from ..workers.browser import BrowserUseBackend
from ..workers.code import OpenHandsBackend
from ..workers.computer import CuaBackend, UFOBackend
from ..workers.interpreter import OpenInterpreterBackend
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
    office_lib = any(_module_available(name) for name in ("docx", "openpyxl", "pptx"))
    if office and office_lib:
        office_detail = "Word/Excel/PowerPoint via COM, with python-docx/openpyxl/python-pptx as fallback."
    elif office:
        office_detail = "Word/Excel/PowerPoint via Windows COM."
    elif office_lib:
        office_detail = "Word/Excel/PowerPoint via python-docx/openpyxl/python-pptx. COM is used when Office is installed."
    else:
        office_detail = "Install Microsoft Office (Windows) or python-docx/openpyxl/python-pptx."
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
            "detail": "PowerShell on Windows; bash on Linux when present.",
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
            "detail": "Named-control UI Automation first (inspect / name / automation_id). Coordinate click is last resort.",
        },
        {
            "id": "office",
            "name": "Microsoft Office",
            "kind": "native",
            "available": office or office_lib,
            "status": "ready" if (office or office_lib) else "unavailable",
            "detail": office_detail,
        },
        {
            "id": "mcp",
            "name": "MCP",
            "kind": "native",
            "available": _module_available("mcp"),
            "status": "ready" if _module_available("mcp") else "missing",
            "detail": "User-configured stdio or HTTP MCP servers, plus the built-in Jarvis MCP server for Cursor.",
        },
        {
            "id": "jarvis-mcp-server",
            "name": "Jarvis MCP for Cursor",
            "kind": "native",
            "available": True,
            "status": "ready",
            "detail": "Read-oriented MCP server Cursor can attach to. Jarvis remains the supervisor.",
        },
        {
            "id": "git",
            "name": "Git",
            "kind": "native",
            "available": shutil.which("git") is not None,
            "status": "ready" if shutil.which("git") else "missing",
            "detail": "Status, diff, and non-destructive jarvis-checkpoint-* backup branches.",
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
    acp = acp_status()
    return [
        BrowserUseBackend().probe(),
        UFOBackend().probe(),
        CuaBackend().probe(),
        OpenInterpreterBackend().probe(),
        OpenHandsBackend().probe(),
        {
            "id": "cursor-acp",
            "name": "Cursor ACP",
            "kind": "optional",
            "available": bool(acp.get("available")),
            "status": acp.get("status") or "not_connected",
            "detail": acp.get("detail") or "Cursor ACP CLI is not on PATH.",
        },
    ]


def professional_analysis_policy() -> dict[str, Any]:
    return {
        "id": "professional-analysis",
        "analyze_sensitive_material": True,
        "operational_authorization_separate": True,
        "detail": (
            "Legitimate security, forensic, and investigative analysis is permitted. "
            "Analysis is not authorization to attack, deploy exploits, or disable defenses."
        ),
    }


def capability_snapshot() -> dict[str, Any]:
    native = native_capabilities()
    optional = optional_workers()
    coding = coding_worker_catalog()
    return {
        "native": native,
        "optional_workers": optional,
        "coding_workers": coding,
        "all": native + optional,
        "professional_analysis": professional_analysis_policy(),
    }
