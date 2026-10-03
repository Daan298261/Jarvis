"""Bind net-snmp of on-link RFC1918 hosts to this PC's home NIC.

``snmpwalk 192.168.1.1`` follows the OS default route. A VPN default route
would steal UDP/161 to the printer or gateway. net-snmp has no ``-b`` flag;
``snmp.conf`` ``clientaddr`` pins the source IP.
"""
from __future__ import annotations

import os
import re
import tempfile
from pathlib import Path

SNMP_TOOL_STEMS = frozenset(
    {
        "snmpwalk",
        "snmpget",
        "snmpbulkwalk",
        "snmpgetnext",
        "snmpstatus",
        "snmptable",
        "snmpdf",
    }
)
_SNMP_NAMES = SNMP_TOOL_STEMS
_IPV4_OR_CIDR = re.compile(r"\d{1,3}(?:\.\d{1,3}){3}(?:/\d{1,2})?(?::\d+)?$")


def snmp_tool_name(argv0: str) -> str:
    text = Path(argv0 or "").name.lower()
    if text.endswith(".exe"):
        text = text[:-4]
    return text


def is_snmp_tool(argv0: str) -> bool:
    return snmp_tool_name(argv0) in _SNMP_NAMES


def snmp_target_from_argv(parts: list[str]) -> str:
    for item in parts[1:]:
        text = str(item or "").strip().strip("'\"")
        if not text or text.startswith("-"):
            continue
        host = text.split("%", 1)[0]
        if _IPV4_OR_CIDR.fullmatch(host):
            return host.split(":", 1)[0]
        lowered = host.lower().rstrip(".")
        if lowered.endswith((".local", ".lan", ".home.arpa")):
            return host.split(":", 1)[0] if host.count(":") == 1 and host.rsplit(":", 1)[-1].isdigit() else host
    return ""


def snmp_lan_child_env(args: list[str], base: dict[str, str] | None = None) -> dict[str, str]:
    """``SNMPCONFPATH`` with ``clientaddr`` when the peer is on-link RFC1918."""
    from ..security.hexstrike_defensive import lan_bind_nic
    from .lan_ssh import lan_ssh_bind_ip
    from .owner_paths import direct_child_env

    env = direct_child_env(base)
    host = snmp_target_from_argv(list(args or []))
    bind = lan_ssh_bind_ip(host)
    if not bind:
        _iface, bind = lan_bind_nic(host)
    if not bind:
        return env
    root = tempfile.mkdtemp(prefix="jarvis-snmp-")
    Path(root, "snmp.conf").write_text(f"clientaddr {bind}\n", encoding="utf-8")
    existing = str(env.get("SNMPCONFPATH") or "").strip()
    env["SNMPCONFPATH"] = root if not existing else os.pathsep.join([root, existing])
    return env
