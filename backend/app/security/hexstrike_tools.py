"""Discover and install host / Python dependencies for HexStrike (RFC-0106)."""
from __future__ import annotations

import asyncio
import re
import shutil
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from ..config import repo_root
from .hexstrike import audit_hexstrike, resolve_install, resolve_python

# winget package ids for common tooling referenced by the pinned upstream tree
WINGET_PACKAGES: dict[str, str] = {
    "nmap": "Insecure.Nmap",
    "trivy": "AquaSecurity.Trivy",
    "checkov": "Bridgecrew.Checkov",
    "docker": "Docker.DockerDesktop",
    "exiftool": "OliverBetz.ExifTool",
    "git": "Git.Git",
    "curl": "cURL.cURL",
    "jq": "jqlang.jq",
    "openssl": "ShiningLight.OpenSSL.Light",
    "wireshark": "WiresharkFoundation.Wireshark",
    "python": "Python.Python.3.11",
}

TOOL_LABELS: dict[str, str] = {
    "nmap": "Nmap",
    "trivy": "Trivy",
    "checkov": "Checkov",
    "docker": "Docker Desktop",
    "exiftool": "ExifTool",
    "git": "Git",
    "curl": "curl",
    "jq": "jq",
    "openssl": "OpenSSL",
    "wireshark": "Wireshark",
    "python": "Python 3.11",
}

PIP_NAME_OVERRIDES: dict[str, str] = {
    "beautifulsoup4": "bs4",
    "pyyaml": "yaml",
}

_INSTALL_LOCK = asyncio.Lock()
_INSTALL_JOBS: dict[str, dict[str, Any]] = {}


@dataclass(frozen=True)
class ToolInstallResult:
    command: str
    ok: bool
    detail: str

    def as_dict(self) -> dict[str, Any]:
        return {"command": self.command, "ok": self.ok, "detail": self.detail}


def dependency_commands() -> dict[str, str]:
    return dict(WINGET_PACKAGES)


def missing_host_tools() -> list[str]:
    return [name for name in WINGET_PACKAGES if shutil.which(name) is None]


def _parse_requirements(path: Path) -> list[str]:
    if not path.is_file():
        return []
    names: list[str] = []
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        cleaned = line.split("#", 1)[0].strip()
        if not cleaned or cleaned.startswith("-"):
            continue
        token = re.split(r"[<>=!~\\[]", cleaned, maxsplit=1)[0].strip()
        if token:
            names.append(token.lower())
    return names


def _discover_pip_packages(install_path: str) -> list[str]:
    root = Path(install_path) if install_path else resolve_install() or repo_root() / "runtime" / "hexstrike-ai"
    candidates = [
        root / "requirements.txt",
        repo_root() / "config" / "hexstrike-defensive-requirements.txt",
    ]
    found: list[str] = []
    seen: set[str] = set()
    for path in candidates:
        for name in _parse_requirements(path):
            if name not in seen:
                seen.add(name)
                found.append(name)
    return found


def dependency_catalog_rows(install_path: str = "") -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for command, package in WINGET_PACKAGES.items():
        rows.append(
            {
                "id": command,
                "command": command,
                "label": TOOL_LABELS.get(command, command),
                "method": "winget",
                "package": package,
                "available": shutil.which(command) is not None,
                "guidance": "" if shutil.which(command) else f"Install {TOOL_LABELS.get(command, command)} and ensure `{command}` is on PATH.",
            }
        )
    for pip_name in _discover_pip_packages(install_path):
        import_name = PIP_NAME_OVERRIDES.get(pip_name, pip_name.replace("-", "_"))
        rows.append(
            {
                "id": f"pip:{pip_name}",
                "command": pip_name,
                "label": pip_name,
                "method": "pip",
                "package": pip_name,
                "available": _pip_available(install_path, import_name),
                "guidance": "" if _pip_available(install_path, import_name) else f"Install Python package `{pip_name}` into hexstrike-env.",
            }
        )
    return rows


def _hexstrike_python(install_path: str = "") -> str:
    install = resolve_install(install_path)
    if install is None:
        return sys.executable
    return resolve_python(install)


def _pip_available(install_path: str, import_name: str) -> bool:
    python = _hexstrike_python(install_path)
    try:
        proc = subprocess_run([python, "-c", f"import {import_name}"], timeout=15)
    except OSError:
        return False
    return proc == 0


def subprocess_run(cmd: list[str], *, timeout: float) -> int:
    completed = __import__("subprocess").run(cmd, capture_output=True, timeout=timeout, check=False)
    return completed.returncode


async def install_host_tool(command: str) -> ToolInstallResult:
    key = (command or "").strip().lower()
    if key.startswith("pip:"):
        return await install_pip_package(key.split(":", 1)[1])
    if key not in WINGET_PACKAGES:
        return ToolInstallResult(command=key, ok=False, detail=f"Unknown tool id: {command}")
    if shutil.which(key):
        return ToolInstallResult(command=key, ok=True, detail=f"{TOOL_LABELS.get(key, key)} already on PATH.")
    if sys.platform != "win32":
        return ToolInstallResult(
            command=key,
            ok=False,
            detail="Automatic winget install is supported on Windows only. Install manually and ensure PATH.",
        )
    winget = shutil.which("winget")
    if not winget:
        return ToolInstallResult(
            command=key,
            ok=False,
            detail="winget not found. Install App Installer from the Microsoft Store, then retry.",
        )
    package = WINGET_PACKAGES[key]
    audit_hexstrike("dependency_install_start", command=key, package=package)
    async with _INSTALL_LOCK:
        _INSTALL_JOBS[key] = {"status": "installing", "command": key}
        proc = await asyncio.create_subprocess_exec(
            winget,
            "install",
            "--id",
            package,
            "-e",
            "--accept-package-agreements",
            "--accept-source-agreements",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await proc.communicate()
    combined = (stdout.decode("utf-8", errors="replace") + stderr.decode("utf-8", errors="replace")).strip()
    ok = proc.returncode == 0 or shutil.which(key) is not None
    detail = combined[-1200:] if combined else ("Installed." if ok else "Install failed.")
    audit_hexstrike("dependency_install_finish", command=key, ok=ok, detail=detail[:500])
    _INSTALL_JOBS[key] = {"status": "ready" if ok else "error", "command": key, "detail": detail[:500]}
    return ToolInstallResult(command=key, ok=ok, detail=detail)


async def install_pip_package(package: str, *, install_path: str = "") -> ToolInstallResult:
    pip_name = (package or "").strip().lower()
    if not pip_name or not re.fullmatch(r"[a-z0-9][a-z0-9._-]*", pip_name):
        return ToolInstallResult(command=pip_name, ok=False, detail="Invalid pip package name.")
    python = _hexstrike_python(install_path)
    audit_hexstrike("pip_install_start", package=pip_name)
    async with _INSTALL_LOCK:
        _INSTALL_JOBS[f"pip:{pip_name}"] = {"status": "installing", "package": pip_name}
        proc = await asyncio.create_subprocess_exec(
            python,
            "-m",
            "pip",
            "install",
            pip_name,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await proc.communicate()
    combined = (stdout.decode("utf-8", errors="replace") + stderr.decode("utf-8", errors="replace")).strip()
    import_name = PIP_NAME_OVERRIDES.get(pip_name, pip_name.replace("-", "_"))
    ok = proc.returncode == 0 or _pip_available(install_path, import_name)
    detail = combined[-1200:] if combined else ("Installed." if ok else "pip install failed.")
    audit_hexstrike("pip_install_finish", package=pip_name, ok=ok, detail=detail[:500])
    _INSTALL_JOBS[f"pip:{pip_name}"] = {"status": "ready" if ok else "error", "package": pip_name, "detail": detail[:500]}
    return ToolInstallResult(command=pip_name, ok=ok, detail=detail)


async def install_dependency_by_id(dep_id: str, *, install_path: str = "") -> ToolInstallResult:
    ident = (dep_id or "").strip().lower()
    if ident.startswith("pip:"):
        return await install_pip_package(ident.split(":", 1)[1], install_path=install_path)
    return await install_host_tool(ident)


async def install_all_missing() -> list[ToolInstallResult]:
    results: list[ToolInstallResult] = []
    for name in missing_host_tools():
        results.append(await install_host_tool(name))
    return results


def install_job_overlay() -> dict[str, Any]:
    return dict(_INSTALL_JOBS)
