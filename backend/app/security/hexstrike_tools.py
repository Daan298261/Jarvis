"""Install optional host binaries for Daybreak Blue defensive actions (Windows)."""
from __future__ import annotations

import asyncio
import shutil
import sys
from dataclasses import dataclass
from typing import Any

from .hexstrike import audit_hexstrike

# winget package ids verified for common defensive tooling
WINGET_PACKAGES: dict[str, str] = {
    "nmap": "Insecure.Nmap",
    "trivy": "AquaSecurity.Trivy",
    "checkov": "Bridgecrew.Checkov",
    "docker": "Docker.DockerDesktop",
    "exiftool": "OliverBetz.ExifTool",
}

TOOL_LABELS: dict[str, str] = {
    "nmap": "Nmap",
    "trivy": "Trivy",
    "checkov": "Checkov",
    "docker": "Docker Desktop",
    "exiftool": "ExifTool",
}


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


async def install_host_tool(command: str) -> ToolInstallResult:
    key = (command or "").strip().lower()
    if key not in WINGET_PACKAGES:
        return ToolInstallResult(command=key, ok=False, detail=f"Unknown tool: {command}")
    if shutil.which(key):
        return ToolInstallResult(command=key, ok=True, detail=f"{TOOL_LABELS.get(key, key)} already on PATH.")
    if sys.platform != "win32":
        return ToolInstallResult(
            command=key,
            ok=False,
            detail="Automatic install is supported on Windows only (winget). Install manually and ensure PATH.",
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
    return ToolInstallResult(command=key, ok=ok, detail=detail)


async def install_all_missing() -> list[ToolInstallResult]:
    results: list[ToolInstallResult] = []
    for name in missing_host_tools():
        results.append(await install_host_tool(name))
    return results
