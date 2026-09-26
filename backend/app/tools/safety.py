from __future__ import annotations

import ipaddress
import ntpath
import os
import re
from pathlib import Path, PureWindowsPath

from ..config import LOCAL_NETWORK_SCOPE
from .base import RiskLevel

IRREVERSIBLE_PATTERNS = [
    r"\bformat\s+[a-z]:",
    r"\bdiskpart\b",
    r"\bcipher\s+/w",
    r"remove-item\s+.*-recurse.*(c:\\|windows|system32)",
    r"rmdir\s+/s\s+/q\s+[c-z]:\\",
    r"bcdedit",
    r"disable.*(defender|firewall|bitlocker)",
    r"net\s+user\s+\S+\s+\S+",
    r"shutdown\s+/s",
    r"Remove-WindowsFeature",
    r"\bremove-item\b",
    r"(^|[;&|]\s*)rm\s+",
    r"(^|[;&|]\s*)(del|erase|rmdir|rd)\s+",
    r"\b(unlink|shred)\s+",
    r"\b(drop|truncate)\s+(database|schema|table)\b",
    r"\bdelete\s+from\b",
    r"git\s+(reset\s+--hard|clean\s+-[^\r\n]*f)",
]

HIGH_IMPACT_PATTERNS = [
    r"remove-item\s+.*-recurse",
    r"rm\s+-rf\s+",
    r"git\s+push\s+.*--force",
    r"git\s+reset\s+--hard",
    r"drop\s+database",
    r"invoke-webrequest.*\|.*iex",
    r"iwr\s+.*\|\s*iex",
]

EXTERNAL_COMMS = [
    r"send-mail",
    r"curl\s+.*-d\s+",
    r"invoke-restmethod\s+.*-method\s+post",
]


def classify_command(command: str) -> RiskLevel:
    text = command.lower()
    for pattern in IRREVERSIBLE_PATTERNS:
        if re.search(pattern, text, re.I):
            return RiskLevel.IRREVERSIBLE
    for pattern in HIGH_IMPACT_PATTERNS:
        if re.search(pattern, text, re.I):
            return RiskLevel.HIGH
    for pattern in EXTERNAL_COMMS:
        if re.search(pattern, text, re.I):
            return RiskLevel.HIGH
    return RiskLevel.MEDIUM


def is_destructive_operation(
    tool_name: str | None = None,
    arguments: dict | None = None,
    command: str | None = None,
) -> bool:
    """Return true only for actions that erase data or discard recoverable state."""
    args = arguments or {}
    action = str(args.get("action") or "").strip().lower()
    name = str(tool_name or "").strip().lower()
    if action in {"delete", "remove", "destroy", "purge", "truncate", "drop", "uninstall"}:
        return True
    if name == "git" and action in {"worktree_remove", "clean", "reset_hard"}:
        return True
    raw = command or (str(args.get("command") or "") if args else "")
    return bool(raw and classify_command(raw) == RiskLevel.IRREVERSIBLE)


def needs_confirmation(
    autonomy: str,
    risk: RiskLevel,
    command: str | None = None,
    *,
    tool_name: str | None = None,
    arguments: dict | None = None,
) -> bool:
    """Routine task operations are automatic; destructive deletion always pauses."""
    del autonomy
    return risk == RiskLevel.IRREVERSIBLE or is_destructive_operation(tool_name, arguments, command)


def _private_lan_unc(path: str) -> bool:
    """Only named LAN shares; never silently send Windows credentials to WAN UNC hosts."""
    drive = PureWindowsPath(path).drive
    if not drive.startswith("\\\\"):
        return False
    host = drive.lstrip("\\").split("\\", 1)[0].lower()
    if not host or host in {".", "?"}:
        return False
    try:
        ip = ipaddress.ip_address(host)
    except ValueError:
        return host == "localhost" or host.endswith((".local", ".home.arpa")) or "." not in host
    return ip.is_loopback or ip.is_link_local or ip in ipaddress.ip_network("10.0.0.0/8") or ip in ipaddress.ip_network("172.16.0.0/12") or ip in ipaddress.ip_network("192.168.0.0/16") or ip in ipaddress.ip_network("fc00::/7")


def resolve_allowed_path(path: str, allowed: list[str]) -> Path:
    if os.name == "nt" and PureWindowsPath(path).drive.startswith("\\\\"):
        if LOCAL_NETWORK_SCOPE in allowed and _private_lan_unc(path):
            # Normalize .. lexically within the share; Path.resolve would contact
            # the remote host before authorization and can stall an offline share.
            return Path(ntpath.normpath(path))
        explicit = any(
            PureWindowsPath(root).drive.startswith("\\\\")
            and PureWindowsPath(path).is_relative_to(PureWindowsPath(root))
            for root in allowed
        )
        if not explicit:
            raise PermissionError(f"Path {path} is outside allowed directories")
    target = Path(path).expanduser().resolve()
    if not allowed:
        raise PermissionError("No workspace directories are configured")
    for root in allowed:
        if root == LOCAL_NETWORK_SCOPE:
            continue
        base = Path(root).expanduser().resolve()
        try:
            target.relative_to(base)
            return target
        except ValueError:
            continue
    raise PermissionError(f"Path {target} is outside allowed directories")
