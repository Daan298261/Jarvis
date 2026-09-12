"""Leader-side Remote Desktop client launch (RFC-0079).

Opens the local RDP client to a worker-node address. This is not a remote
UI-Automation protocol and does not send credentials.
"""
from __future__ import annotations

import platform
import re
import shutil
import subprocess
from typing import Any

_HOST_OK = re.compile(r"^[A-Za-z0-9._:-]+$")


def validate_rdp_host(host: str) -> str:
    value = (host or "").strip()
    if not value:
        raise ValueError("RDP host is required")
    if len(value) > 253 or not _HOST_OK.fullmatch(value):
        raise ValueError("RDP host looks invalid")
    return value


def rdp_command(host: str) -> list[str]:
    target = validate_rdp_host(host)
    if platform.system() == "Windows":
        return ["mstsc", f"/v:{target}"]
    return ["xfreerdp", f"/v:{target}", "/cert:ignore"]


def launch_rdp(host: str) -> dict[str, Any]:
    command = rdp_command(host)
    if platform.system() != "Windows":
        return {
            "started": False,
            "host": validate_rdp_host(host),
            "command": command,
            "reason": "RDP client launch from the leader is Windows-only (mstsc).",
        }
    executable = shutil.which(command[0]) or command[0]
    try:
        subprocess.Popen(  # noqa: S603 — argv list, host already validated
            [executable, *command[1:]],
            close_fds=True,
        )
    except OSError as exc:
        return {
            "started": False,
            "host": validate_rdp_host(host),
            "command": command,
            "reason": str(exc)[:400],
        }
    return {
        "started": True,
        "host": validate_rdp_host(host),
        "command": command,
        "reason": "Opened the local Remote Desktop client.",
    }
