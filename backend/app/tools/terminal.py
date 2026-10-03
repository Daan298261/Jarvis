from __future__ import annotations

import asyncio
import json
import os
import platform
import re
import shlex
import shutil
import sys
import tempfile
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from urllib.parse import unquote, urlparse

import psutil

from ..config import live_workspace_roots_from_context
from .base import RiskLevel, Tool, ToolResult
from .owner_paths import direct_child_env, git_child_env, lan_http_child_env, python_child_env, workspace_cwd
from .safety import classify_command, is_protected_process


@dataclass
class BackgroundJob:
    pid: int
    command: str
    proc: asyncio.subprocess.Process
    stdout: bytearray = field(default_factory=bytearray)
    stderr: bytearray = field(default_factory=bytearray)
    started: float = field(default_factory=time.time)
    pump: asyncio.Task | None = None


def default_shell() -> str:
    return "powershell" if platform.system() == "Windows" else "bash"


def _default_shell() -> str:
    return default_shell()


_JOBS: dict[int, BackgroundJob] = {}

_SEARCH_COMMAND = re.compile(
    r"(?i)\b(?:findstr\b|find\.exe\b|find\s+/[aicnv]|grep\b|\brg\b|select-string\b|where\.exe\b)\b"
)
_POWERSHELL_MARKERS = re.compile(
    r"(?i)(?:Get-|Set-|Select-|Where-Object|ForEach-Object|Out-File|\$\w+|`-| -[ie][a-z]+ )"
)
_CMD_IDIOMS = re.compile(
    r"(?i)\b(?:findstr\b|find\s+/[a-z]|dir\s+/[a-z]|tasklist\b|where\.exe\b|"
    r"wmic\b|netstat\b|type\s+[A-Za-z]:|copy\s+\S+\s+\S+|del\s+/|rmdir\s+/)"
)
_UNSAFE_SHELL = re.compile(r"[;&|`$<>\n]")
_PROXY_FLAGS = frozenset({"-x", "--proxy", "--interface", "--local-addr", "--bind-address"})
_HTTP_BIND_NAMES = frozenset({"curl", "wget", "wget2", "aria2c", "aria2"})
_HTTP_SKIP_FLAGS = {
    "curl": frozenset({"-x", "--proxy", "--interface", "--local-addr"}),
    "wget": frozenset({"--bind-address", "--interface"}),
    "wget2": frozenset({"--bind-address", "--interface"}),
    "aria2c": frozenset({"--interface", "--all-proxy", "--http-proxy", "--ftp-proxy", "--no-proxy"}),
    "aria2": frozenset({"--interface", "--all-proxy", "--http-proxy", "--ftp-proxy", "--no-proxy"}),
}
_IWR_NAMES = frozenset({"invoke-webrequest", "iwr", "invoke-restmethod", "irm"})
_IWR_URI_FLAGS = frozenset({"-uri", "-url"})
_IWR_OUT_FLAGS = frozenset({"-outfile"})
_IWR_IGNORE_FLAGS = frozenset({"-usebasicparsing"})


def search_miss_ok(command: str, code: int) -> bool:
    """Exit 1 from findstr/grep means 'not found', not a broken command."""
    return int(code or 0) == 1 and bool(_SEARCH_COMMAND.search(command or ""))


def _http_target_from_argv(parts: list[str]) -> str:
    for item in parts[1:]:
        text = str(item or "").strip().strip("'\"")
        if not text or text.startswith("-"):
            continue
        if text.lower().startswith(("http://", "https://", "ftp://", "ftps://")):
            return text
        host = text.split("/", 1)[0]
        if re.fullmatch(r"\d{1,3}(?:\.\d{1,3}){3}(?::\d+)?", host):
            return text
        lowered = host.lower().rstrip(".")
        if lowered.endswith((".local", ".lan", ".home.arpa")):
            return text
    return ""


def _lan_bind_for_http_target(target: str) -> str:
    from ..mobile.wan_forward import lan_http_bind_for_url, lan_source_ipv4_for_peer

    text = str(target or "").strip()
    if not text:
        return ""
    if "://" in text:
        return lan_http_bind_for_url(text)
    bind = lan_source_ipv4_for_peer(text.split(":", 1)[0])
    if bind:
        return bind
    return lan_http_bind_for_url(f"http://{text}")


def _curl_lan_argv(url: str, *, outfile: str = "") -> list[str] | None:
    bind = _lan_bind_for_http_target(url)
    if not bind:
        return None
    exe = shutil.which("curl") or shutil.which("curl.exe")
    if not exe:
        return None
    argv = [exe, "--interface", bind, "-sL"]
    if outfile:
        argv.extend(["-o", outfile])
    argv.append(url)
    return argv


def _iwr_lan_argv(command: str) -> list[str] | None:
    """PowerShell IWR/iwr/irm of an on-link RFC1918 URL → curl --interface.

    Invoke-WebRequest cannot bind a source IP. On Windows, ``wget`` without
    wget.exe is the same alias.
    """
    text = str(command or "").strip()
    if not text or _UNSAFE_SHELL.search(text):
        return None
    try:
        parts = shlex.split(text, posix=os.name != "nt")
    except ValueError:
        return None
    if not parts:
        return None
    name = Path(parts[0]).name.lower()
    if name.endswith(".exe"):
        name = name[:-4]
    if name not in _IWR_NAMES:
        return None
    url = ""
    outfile = ""
    index = 1
    while index < len(parts):
        token = str(parts[index]).strip().strip("'\"")
        key = token.lower()
        if key in _IWR_URI_FLAGS:
            if index + 1 >= len(parts):
                return None
            url = str(parts[index + 1]).strip().strip("'\"")
            index += 2
            continue
        if key in _IWR_OUT_FLAGS:
            if index + 1 >= len(parts):
                return None
            outfile = str(parts[index + 1]).strip().strip("'\"")
            index += 2
            continue
        if key in _IWR_IGNORE_FLAGS:
            index += 1
            continue
        if token.startswith("-"):
            return None
        if not url:
            url = token
            index += 1
            continue
        return None
    return _curl_lan_argv(url, outfile=outfile)


def lan_bound_http_argv(command: str) -> list[str] | None:
    """Real curl/wget/wget2/aria2c/IWR of an on-link RFC1918 URL, sourced from that NIC.

    PowerShell aliases ``curl``/``wget`` to Invoke-WebRequest, which cannot bind
    a source IP. A VPN default route would steal the hop to the home gateway.
    Skip pipes and explicit proxies. ``aria2c -x`` is max-connections, not proxy.
    """
    iwr = _iwr_lan_argv(command)
    if iwr:
        return iwr
    text = str(command or "").strip()
    if not text or _UNSAFE_SHELL.search(text):
        return None
    try:
        parts = shlex.split(text, posix=os.name != "nt")
    except ValueError:
        return None
    if not parts:
        return None
    name = Path(parts[0]).name.lower()
    if name.endswith(".exe"):
        name = name[:-4]
    if name not in _HTTP_BIND_NAMES:
        return None
    flags = {part.split("=", 1)[0] for part in parts[1:] if str(part).startswith("-")}
    if flags & _HTTP_SKIP_FLAGS.get(name, _PROXY_FLAGS):
        return None
    url = _http_target_from_argv(parts)
    bind = _lan_bind_for_http_target(url)
    if not bind:
        return None
    exe = shutil.which(name) or shutil.which(f"{name}.exe")
    rest = parts[1:]
    if name in {"wget", "wget2"}:
        if exe:
            return [exe, f"--bind-address={bind}", *rest]
        return _curl_lan_argv(url)
    if name in {"aria2c", "aria2"}:
        if exe:
            return [exe, f"--interface={bind}", *rest]
        return _curl_lan_argv(url)
    if not exe:
        return None
    return [exe, "--interface", bind, *rest]


def lan_bound_ssh_argv(command: str) -> list[str] | None:
    """OpenSSH of an on-link RFC1918 host, sourced from that NIC.

    ``ssh -b`` is bind-address; scp/sftp ``-b`` is not. Use ``BindAddress`` for
    ssh/scp/sftp. Skip pipes, ProxyJump, and explicit binds.
    """
    text = str(command or "").strip()
    if not text or _UNSAFE_SHELL.search(text):
        return None
    try:
        parts = shlex.split(text, posix=os.name != "nt")
    except ValueError:
        return None
    if not parts:
        return None
    name = Path(parts[0]).name.lower()
    if name.endswith(".exe"):
        name = name[:-4]
    if name not in {"ssh", "scp", "sftp"}:
        return None
    exe = shutil.which(name) or shutil.which(f"{name}.exe")
    if not exe:
        return None
    from .lan_ssh import with_lan_ssh_bind

    bound = with_lan_ssh_bind([exe, *parts[1:]])
    if bound[1:2] != ["-o"] or not str(bound[2] if len(bound) > 2 else "").startswith("BindAddress="):
        return None
    return bound


_SCAN_NAMES = frozenset(
    {
        "nmap",
        "nping",
        "ping",
        "traceroute",
        "masscan",
        "arp-scan",
        "arping",
        "fping",
        "iperf",
        "iperf3",
        "mtr",
        "nmblookup",
        "tcpdump",
        "tshark",
        "dumpcap",
        "hping",
        "hping3",
    }
)
_IPV4_OR_CIDR = re.compile(r"\d{1,3}(?:\.\d{1,3}){3}(?:/\d{1,2})?(?::\d+)?$")


def _scan_target_from_argv(parts: list[str]) -> str:
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


def _scan_already_bound(name: str, parts: list[str]) -> bool:
    flags = {str(part).split("=", 1)[0] for part in parts[1:] if str(part).startswith("-")}
    if name in {"nmap", "nping"}:
        return bool(flags & {"-S", "-e"})
    if name == "ping":
        if platform.system() == "Windows":
            return any(flag.lower() == "-s" for flag in flags)
        return "-I" in flags
    if name == "traceroute":
        return "-s" in flags
    if name == "masscan":
        return bool(flags & {"--source-ip", "-e", "-S"})
    if name == "arp-scan":
        return bool(flags & {"-I", "--interface", "--arpspa", "--localip"})
    if name == "arping":
        return bool(flags & {"-I", "-i", "-s"})
    if name == "fping":
        return bool(flags & {"-I", "-S"})
    if name in {"iperf", "iperf3"}:
        return bool(flags & {"-B", "--bind"})
    if name == "mtr":
        return bool(flags & {"-a", "--address"})
    if name == "nmblookup":
        return bool(flags & {"-i", "-B", "--broadcast"})
    if name in {"tcpdump", "tshark", "dumpcap"}:
        return bool(flags & {"-i", "--interface"})
    if name in {"hping", "hping3"}:
        return bool(flags & {"-I", "--interface"})
    return True


def _scan_bind_flags(name: str, target: str) -> list[str] | None:
    from ..security.hexstrike_defensive import lan_bind_nic

    iface, source = lan_bind_nic(target)
    if not source:
        return None
    if name in {"nmap", "nping"}:
        flags = ["-S", source]
        if iface:
            flags.extend(["-e", iface])
        return flags
    if name == "ping":
        if platform.system() == "Windows":
            return ["-S", source]
        return ["-I", source]
    if name == "traceroute":
        return ["-s", source]
    if name == "masscan":
        flags = ["--source-ip", source]
        if iface:
            flags.extend(["-e", iface])
        return flags
    if name == "arp-scan":
        flags = ["--arpspa", source]
        if iface:
            flags.extend(["-I", iface])
        return flags
    if name == "arping":
        flags = ["-s", source]
        if iface:
            flags.extend(["-I", iface])
        return flags
    if name == "fping":
        flags = ["-S", source]
        if iface:
            flags.extend(["-I", iface])
        return flags
    if name in {"iperf", "iperf3"}:
        return ["-B", source]
    if name == "mtr":
        return ["-a", source]
    if name == "nmblookup":
        from ..security.hexstrike_defensive import lan_nic_detail

        iface, source, broadcast = lan_nic_detail(target)
        if not source:
            return None
        flags: list[str] = []
        if broadcast:
            flags.extend(["-B", broadcast])
        if iface:
            flags.extend(["-i", iface])
        return flags or None
    if name in {"tcpdump", "tshark", "dumpcap"}:
        from ..security.hexstrike_defensive import lan_nic_detail

        iface, _source, _broadcast = lan_nic_detail(target)
        if not iface:
            return None
        return ["-i", iface]
    if name in {"hping", "hping3"}:
        from ..security.hexstrike_defensive import lan_nic_detail

        iface, _source, _broadcast = lan_nic_detail(target)
        if not iface:
            return None
        return ["-I", iface]
    return None


def lan_bound_scan_argv(command: str) -> list[str] | None:
    """nmap/ping/mtr/nmblookup of on-link RFC1918, sourced from that NIC.

    HexStrike nmap already pins ``-S``/``-e``. Terminal nmap/ping plus ARP/fping
    still follow the OS default route, so a VPN steals (or black-holes) the hop
    to the LAN. mtr uses ``-a``; nmblookup uses ``-B``/``-i`` so NetBIOS to a NAS
    is not sent on the VPN. tcpdump/tshark/dumpcap use ``-i`` when the filter
    names an on-link RFC1918 host. hping3 uses ``-I``. Skip pipes and explicit
    source-bind flags. Public targets are unchanged.
    """
    text = str(command or "").strip()
    if not text or _UNSAFE_SHELL.search(text):
        return None
    try:
        parts = shlex.split(text, posix=os.name != "nt")
    except ValueError:
        return None
    if not parts:
        return None
    name = Path(parts[0]).name.lower()
    if name.endswith(".exe"):
        name = name[:-4]
    if name not in _SCAN_NAMES:
        return None
    if _scan_already_bound(name, parts):
        return None
    target = _scan_target_from_argv(parts)
    if name == "nmblookup" and not target:
        from ..security.hexstrike_defensive import preferred_lan_bind_target

        target = preferred_lan_bind_target()
    if name in {"tcpdump", "tshark", "dumpcap"} and not target:
        from ..security.hexstrike_defensive import ipv4_or_lan_host_from_tokens

        target = ipv4_or_lan_host_from_tokens(parts[1:])
    flags = _scan_bind_flags(name, target)
    if not flags:
        return None
    exe = shutil.which(name) or shutil.which(f"{name}.exe")
    if not exe:
        return None
    return [exe, *flags, *parts[1:]]


_NETCAT_NAMES = frozenset({"nc", "ncat", "netcat"})
_RSYNC_BIND_FLAGS = frozenset({"-e", "--rsh", "--address"})


def _tool_basename(argv0: str) -> str:
    name = Path(argv0 or "").name.lower()
    if name.endswith(".exe"):
        name = name[:-4]
    return name


def rsync_host_from_token(token: str) -> str:
    """Remote host in an rsync source/dest token (SSH, ``host::mod``, ``rsync://``)."""
    text = str(token or "").strip().strip("'\"")
    if not text or text.startswith("-"):
        return ""
    if "://" in text:
        from urllib.parse import urlparse

        return (urlparse(text).hostname or "").strip()
    if len(text) >= 2 and text[1] == ":" and text[0].isalpha() and (len(text) == 2 or text[2] in "\\/"):
        return ""
    if "@" in text or ":" in text or "::" in text:
        from .lan_ssh import ssh_host_from_token

        return ssh_host_from_token(text)
    return ""


def _rsync_host_from_argv(parts: list[str]) -> str:
    for item in parts[1:]:
        host = rsync_host_from_token(item)
        if host:
            return host
    return ""


def _rsync_is_daemon(parts: list[str]) -> bool:
    for item in parts[1:]:
        text = str(item or "")
        if text.startswith("-"):
            continue
        if "://" in text or "::" in text:
            return True
    return False


def _lan_bind_ip_for_host(host: str) -> str:
    from ..security.hexstrike_defensive import lan_bind_nic
    from .lan_ssh import lan_ssh_bind_ip

    bind = lan_ssh_bind_ip(host)
    if bind:
        return bind
    _iface, source = lan_bind_nic(host)
    return source


def lan_bound_rsync_argv(command: str) -> list[str] | None:
    """rsync of an on-link RFC1918 NAS, sourced from that NIC.

    SSH transport uses ``RSYNC_RSH`` (``lan_ssh.py`` BindAddress). The daemon
    protocol (``rsync://`` / ``host::module``) has no rsh, so pin ``--address``.
    Skip pipes, ``-e`` / ``--rsh`` / ``--address``, and public hosts.
    """
    text = str(command or "").strip()
    if not text or _UNSAFE_SHELL.search(text):
        return None
    try:
        parts = shlex.split(text, posix=os.name != "nt")
    except ValueError:
        return None
    if not parts or _tool_basename(parts[0]) != "rsync":
        return None
    flags = {str(part).split("=", 1)[0] for part in parts[1:] if str(part).startswith("-")}
    if flags & _RSYNC_BIND_FLAGS or "--daemon" in flags:
        return None
    host = _rsync_host_from_argv(parts)
    bind = _lan_bind_ip_for_host(host)
    if not bind:
        return None
    exe = shutil.which("rsync") or shutil.which("rsync.exe")
    if not exe:
        return None
    if _rsync_is_daemon(parts):
        return [exe, f"--address={bind}", *parts[1:]]
    from .lan_ssh import git_ssh_command

    return [exe, "-e", git_ssh_command(), *parts[1:]]


_RCLONE_HOST_FLAGS = frozenset(
    {
        "--sftp-host",
        "--smb-host",
        "--ftp-host",
        "--nfs-host",
        "--ssh-host",
        "--webdav-url",
        "--http-url",
    }
)
_RCLONE_HOST_PARAM = re.compile(r"(?:^|,)host=([^,:]+)")


def rclone_host_from_token(token: str) -> str:
    """Host in an rclone URL or ``:sftp,host=192.168.1.50:path`` connection string."""
    from urllib.parse import urlparse

    text = str(token or "").strip().strip("'\"")
    if not text or text.startswith("-"):
        return ""
    if "://" in text:
        return (urlparse(text).hostname or "").strip()
    if text.startswith(":"):
        match = _RCLONE_HOST_PARAM.search(text[1:])
        if match:
            return match.group(1).strip()
    return ""


def _rclone_host_from_argv(parts: list[str]) -> str:
    from urllib.parse import urlparse

    for index, item in enumerate(parts[1:], start=1):
        text = str(item or "").strip().strip("'\"")
        key = text.split("=", 1)[0]
        if key in _RCLONE_HOST_FLAGS:
            if "=" in text:
                raw = text.split("=", 1)[1]
            elif index + 1 < len(parts):
                raw = str(parts[index + 1] or "").strip().strip("'\"")
            else:
                raw = ""
            if "://" in raw:
                return (urlparse(raw).hostname or "").strip()
            return raw.split("/")[0]
        host = rclone_host_from_token(text)
        if host:
            return host
        if not text or text.startswith("-"):
            continue
        host = text.split("%", 1)[0]
        if _IPV4_OR_CIDR.fullmatch(host):
            return host.split(":", 1)[0]
        lowered = host.lower().rstrip(".")
        if lowered.endswith((".local", ".lan", ".home.arpa")):
            return host.split(":", 1)[0] if host.count(":") == 1 and host.rsplit(":", 1)[-1].isdigit() else host
    return ""


def lan_bound_rclone_argv(command: str) -> list[str] | None:
    """rclone of an on-link RFC1918 NAS, sourced from that NIC.

    ``--bind`` is a source IPv4, so a spaced Windows NIC name is not required.
    Skip pipes, existing ``--bind``, and public hosts.
    """
    text = str(command or "").strip()
    if not text or _UNSAFE_SHELL.search(text):
        return None
    try:
        parts = shlex.split(text, posix=os.name != "nt")
    except ValueError:
        return None
    if not parts or _tool_basename(parts[0]) != "rclone":
        return None
    flags = {str(part).split("=", 1)[0] for part in parts[1:] if str(part).startswith("-")}
    if "--bind" in flags:
        return None
    host = _rclone_host_from_argv(parts)
    bind = _lan_bind_ip_for_host(host)
    if not bind:
        return None
    exe = shutil.which("rclone") or shutil.which("rclone.exe")
    if not exe:
        return None
    return [exe, "--bind", bind, *parts[1:]]


def lan_bound_netcat_argv(command: str) -> list[str] | None:
    """nc/ncat/netcat of an on-link RFC1918 host, sourced from that NIC.

    ``-s`` is source address on OpenBSD nc, GNU netcat, and nmap ncat. Skip
    pipes, explicit ``-s`` / ``--source``, and public targets.
    """
    text = str(command or "").strip()
    if not text or _UNSAFE_SHELL.search(text):
        return None
    try:
        parts = shlex.split(text, posix=os.name != "nt")
    except ValueError:
        return None
    if not parts:
        return None
    name = _tool_basename(parts[0])
    if name not in _NETCAT_NAMES:
        return None
    flags = {str(part).split("=", 1)[0] for part in parts[1:] if str(part).startswith("-")}
    if flags & {"-s", "--source"}:
        return None
    target = _scan_target_from_argv(parts)
    bind = _lan_bind_ip_for_host(target)
    if not bind:
        return None
    exe = shutil.which(name) or shutil.which(f"{name}.exe")
    if not exe:
        return None
    return [exe, "-s", bind, *parts[1:]]


_DNS_NAMES = frozenset({"dig", "drill"})


def _dns_nameserver_from_argv(parts: list[str]) -> str:
    for item in parts[1:]:
        text = str(item or "").strip().strip("'\"")
        if text.startswith("@") and len(text) > 1:
            return text[1:].split("#", 1)[0]
    return ""


def lan_bound_dns_argv(command: str) -> list[str] | None:
    """dig/drill of an on-link RFC1918 nameserver, sourced from that NIC.

    ``dig @192.168.1.1`` follows the OS default route. ``-b`` pins the source
    so a VPN cannot steal DNS to the home resolver. Skip pipes, ``-b``, and
    public nameservers. Bare ``dig example.com`` (system resolver) is unchanged.
    """
    text = str(command or "").strip()
    if not text or _UNSAFE_SHELL.search(text):
        return None
    try:
        parts = shlex.split(text, posix=os.name != "nt")
    except ValueError:
        return None
    if not parts:
        return None
    name = _tool_basename(parts[0])
    if name not in _DNS_NAMES:
        return None
    flags = {str(part).split("=", 1)[0] for part in parts[1:] if str(part).startswith("-")}
    if "-b" in flags:
        return None
    host = _dns_nameserver_from_argv(parts)
    bind = _lan_bind_ip_for_host(host)
    if not bind:
        return None
    exe = shutil.which(name) or shutil.which(f"{name}.exe")
    if not exe:
        return None
    return [exe, "-b", bind, *parts[1:]]


def lan_bound_snmp_argv(command: str) -> list[str] | None:
    """snmpwalk of on-link RFC1918 as argv so SNMPCONFPATH can pin clientaddr.

    net-snmp has no source-bind flag. The child env writes ``snmp.conf``
    ``clientaddr``. Skip pipes and public targets.
    """
    from .lan_snmp import is_snmp_tool, snmp_target_from_argv

    text = str(command or "").strip()
    if not text or _UNSAFE_SHELL.search(text):
        return None
    try:
        parts = shlex.split(text, posix=os.name != "nt")
    except ValueError:
        return None
    if not parts or not is_snmp_tool(parts[0]):
        return None
    name = _tool_basename(parts[0])
    host = snmp_target_from_argv(parts)
    if not _lan_bind_ip_for_host(host):
        return None
    exe = shutil.which(name) or shutil.which(f"{name}.exe")
    if not exe:
        return None
    return [exe, *parts[1:]]


_CIFS_FS_TYPES = frozenset({"cifs", "smbfs"})
_CIFS_SRC_KEYS = ("srcaddr=", "interface=")


def cifs_host_from_token(token: str) -> str:
    """Host in a CIFS UNC (``//nas.local/share`` or ``\\\\192.168.1.50\\media``)."""
    text = str(token or "").strip().strip("'\"")
    if text.startswith("//"):
        rest = text[2:]
        return rest.split("/", 1)[0].split("\\", 1)[0]
    if text.startswith("\\\\"):
        rest = text[2:]
        return rest.split("\\", 1)[0].split("/", 1)[0]
    return ""


def _cifs_host_from_argv(parts: list[str]) -> str:
    for item in parts[1:]:
        host = cifs_host_from_token(item)
        if host:
            return host
    return ""


def _is_cifs_mount(parts: list[str]) -> bool:
    name = _tool_basename(parts[0])
    if name in {"mount.cifs", "mount.smbfs"}:
        return True
    if name != "mount":
        return False
    index = 1
    while index < len(parts):
        token = str(parts[index])
        if token in {"-t", "--types"} and index + 1 < len(parts):
            return str(parts[index + 1]).lower() in _CIFS_FS_TYPES
        if token.startswith("-t") and len(token) > 2 and not token.startswith("--"):
            return token[2:].lower() in _CIFS_FS_TYPES
        if token.startswith("--types="):
            return token.split("=", 1)[1].lower() in _CIFS_FS_TYPES
        index += 1
    return False


def _cifs_options_text(parts: list[str]) -> str:
    bits: list[str] = []
    index = 1
    while index < len(parts):
        token = str(parts[index])
        if token in {"-o", "--options"} and index + 1 < len(parts):
            bits.append(str(parts[index + 1]))
            index += 2
            continue
        if token.startswith("-o") and len(token) > 2 and not token.startswith("--"):
            bits.append(token[2:])
        elif token.startswith("--options="):
            bits.append(token.split("=", 1)[1])
        index += 1
    return ",".join(bits).lower()


def _mount_append_option(parts: list[str], extra: str) -> list[str]:
    out = list(parts)
    index = 1
    while index < len(out):
        token = str(out[index])
        if token in {"-o", "--options"} and index + 1 < len(out):
            out[index + 1] = f"{out[index + 1]},{extra}" if out[index + 1] else extra
            return out
        if token.startswith("-o") and len(token) > 2 and not token.startswith("--"):
            out[index] = f"{token},{extra}"
            return out
        if token.startswith("--options="):
            out[index] = f"{token},{extra}"
            return out
        index += 1
    return [out[0], "-o", extra, *out[1:]]


def _cifs_with_srcaddr(parts: list[str], bind: str) -> list[str]:
    return _mount_append_option(parts, f"srcaddr={bind}")


def lan_bound_cifs_argv(command: str) -> list[str] | None:
    """mount.cifs of an on-link RFC1918 NAS, sourced from that NIC.

    Windows ``Path(\\\\nas\\share)`` uses the SMB redirector and cannot
    source-bind. ``mount -t cifs`` ``srcaddr=`` pins the home NIC so a VPN
    default route cannot steal the NAS. Skip pipes, existing ``srcaddr`` /
    ``interface``, and public hosts.
    """
    text = str(command or "").strip()
    if not text or _UNSAFE_SHELL.search(text):
        return None
    try:
        parts = shlex.split(text, posix=os.name != "nt")
    except ValueError:
        return None
    if not parts or not _is_cifs_mount(parts):
        return None
    options = _cifs_options_text(parts)
    if any(key in options for key in _CIFS_SRC_KEYS):
        return None
    host = _cifs_host_from_argv(parts)
    bind = _lan_bind_ip_for_host(host)
    if not bind:
        return None
    name = _tool_basename(parts[0])
    exe = shutil.which(name) or shutil.which(f"{name}.exe")
    if not exe:
        return None
    return _cifs_with_srcaddr([exe, *parts[1:]], bind)


_NFS_FS_TYPES = frozenset({"nfs", "nfs4"})
_NFS_SRC_KEYS = ("clientaddr=",)


def nfs_host_from_token(token: str) -> str:
    """Host in an NFS source (``192.168.1.50:/export`` or ``nas.local:/share``)."""
    text = str(token or "").strip().strip("'\"")
    if not text or text.startswith("-"):
        return ""
    if text.startswith("[") and "]:" in text:
        return text[1 : text.index("]")]
    if "://" in text:
        from urllib.parse import urlparse

        return (urlparse(text).hostname or "").strip()
    if ":" not in text:
        return ""
    host, _rest = text.split(":", 1)
    if len(host) == 1 and host.isalpha():
        return ""
    return host


def _nfs_host_from_argv(parts: list[str]) -> str:
    for item in parts[1:]:
        host = nfs_host_from_token(str(item))
        if host:
            return host
    return ""


def _is_nfs_mount(parts: list[str]) -> bool:
    name = _tool_basename(parts[0])
    if name in {"mount.nfs", "mount.nfs4"}:
        return True
    if name != "mount":
        return False
    index = 1
    while index < len(parts):
        token = str(parts[index])
        if token in {"-t", "--types"} and index + 1 < len(parts):
            return str(parts[index + 1]).lower() in _NFS_FS_TYPES
        if token.startswith("-t") and len(token) > 2 and not token.startswith("--"):
            return token[2:].lower() in _NFS_FS_TYPES
        if token.startswith("--types="):
            return token.split("=", 1)[1].lower() in _NFS_FS_TYPES
        index += 1
    return False


def lan_bound_nfs_argv(command: str) -> list[str] | None:
    """mount.nfs of an on-link RFC1918 NAS, sourced from that NIC.

    ``clientaddr=`` is the NFSv4 client address so a VPN default route cannot
    steal the NAS. Skip pipes, existing ``clientaddr``, and public hosts.
    """
    text = str(command or "").strip()
    if not text or _UNSAFE_SHELL.search(text):
        return None
    try:
        parts = shlex.split(text, posix=os.name != "nt")
    except ValueError:
        return None
    if not parts or not _is_nfs_mount(parts):
        return None
    options = _cifs_options_text(parts)
    if any(key in options for key in _NFS_SRC_KEYS):
        return None
    host = _nfs_host_from_argv(parts)
    bind = _lan_bind_ip_for_host(host)
    if not bind:
        return None
    name = _tool_basename(parts[0])
    exe = shutil.which(name) or shutil.which(f"{name}.exe")
    if not exe:
        return None
    return _mount_append_option([exe, *parts[1:]], f"clientaddr={bind}")


_SMB_NAMES = frozenset({"smbclient", "smbget", "rpcclient", "smbtree"})


def _smb_already_bound(parts: list[str]) -> bool:
    for item in parts[1:]:
        text = str(item or "")
        lowered = text.lower()
        if "client addr" in lowered or lowered.startswith("clientaddr"):
            return True
        key = text.split("=", 1)[0]
        if key in {"-s", "--configfile"}:
            return True
    return False


def _smb_host_from_argv(parts: list[str]) -> str:
    from urllib.parse import urlparse

    for index, item in enumerate(parts[1:], start=1):
        host = cifs_host_from_token(str(item))
        if host:
            return host
        text = str(item or "").strip().strip("'\"")
        if not text:
            continue
        if text.lower().startswith("smb://"):
            return (urlparse(text).hostname or "").strip()
        if text in {"-L", "--list"} and index + 1 < len(parts):
            nxt = str(parts[index + 1] or "").strip().strip("'\"")
            return cifs_host_from_token(nxt) or nxt.split("/", 1)[0].lstrip("\\")
        if text.startswith("-"):
            continue
        if _IPV4_OR_CIDR.fullmatch(text.split("%", 1)[0]):
            return text.split("%", 1)[0].split(":", 1)[0]
        lowered = text.lower().rstrip(".")
        if lowered.endswith((".local", ".lan", ".home.arpa")):
            return text.split(":", 1)[0] if text.count(":") == 1 and text.rsplit(":", 1)[-1].isdigit() else text
    return ""


def lan_bound_smb_argv(command: str) -> list[str] | None:
    """smbclient of an on-link RFC1918 NAS, sourced from that NIC.

    Windows native UNC cannot source-bind. Samba ``--option=client addr=`` pins
    the home NIC so a VPN default route cannot steal SMB. Skip pipes, existing
    ``client addr`` / ``-s``, and public hosts. ``smbtree`` with no host uses
    the preferred home LAN.
    """
    text = str(command or "").strip()
    if not text or _UNSAFE_SHELL.search(text):
        return None
    collapsed = text.lower().replace(" ", "")
    if "client addr" in text.lower() or "clientaddr=" in collapsed:
        return None
    try:
        parts = shlex.split(text, posix=os.name != "nt")
    except ValueError:
        return None
    if not parts:
        return None
    name = _tool_basename(parts[0])
    if name not in _SMB_NAMES:
        return None
    if _smb_already_bound(parts):
        return None
    host = _smb_host_from_argv(parts)
    if name == "smbtree" and not host:
        from ..security.hexstrike_defensive import preferred_lan_bind_target

        host = preferred_lan_bind_target()
    bind = _lan_bind_ip_for_host(host)
    if not bind:
        return None
    exe = shutil.which(name) or shutil.which(f"{name}.exe")
    if not exe:
        return None
    return [exe, f"--option=client addr={bind}", *parts[1:]]


_LAN_HTTP_TOOL_STEMS = frozenset(
    {
        "skopeo",
        "podman",
        "buildah",
        "trivy",
        "grype",
        "crane",
        "oras",
        "pip",
        "pip3",
        "pipx",
        "uv",
        "poetry",
        "pdm",
        "pipenv",
        "twine",
        "npm",
        "npx",
        "pnpm",
        "yarn",
        "yarnpkg",
        "bun",
        "cargo",
        "gem",
        "bundle",
        "composer",
        "helm",
        "go",
        "gh",
        "apt",
        "apt-get",
        "aria2c",
        "aria2",
        "wget2",
        "httpie",
        "axel",
        "aws",
        "s3cmd",
        "mc",
        "mcli",
    }
)
_DOCKER_PULL_QUIET = frozenset({"-q", "--quiet"})


def resolve_skopeo() -> str | None:
    """skopeo on PATH, or ``runtime/skopeo`` next to the install / extra drives."""
    found = shutil.which("skopeo") or shutil.which("skopeo.exe")
    if found:
        return found
    roots: list[Path] = []
    try:
        from ..config import extra_volume_named_runtime_dirs, extra_volume_roots, repo_root

        roots.append(repo_root() / "runtime")
        roots.extend(extra_volume_named_runtime_dirs("skopeo"))
        for volume in extra_volume_roots():
            roots.append(volume / "Jarvis" / "runtime")
            roots.append(volume / "runtime")
    except Exception:
        pass
    seen: set[str] = set()
    for root in roots:
        for candidate in (root, root / "skopeo.exe", root / "skopeo"):
            try:
                if not candidate.is_file():
                    continue
            except OSError:
                continue
            key = str(candidate).replace("\\", "/").lower()
            if key in seen:
                continue
            seen.add(key)
            name = candidate.name.lower()
            if name in {"skopeo", "skopeo.exe"}:
                return str(candidate)
    return None


def docker_registry_host_from_image(ref: str) -> str:
    """Registry host in a docker image ref (``192.168.1.50:5000/app:tag``).

    Official Hub names (``nginx``, ``library/nginx``) have no registry host.
    """
    from ..security.hexstrike_defensive import container_registry_host

    return container_registry_host(ref)


def _docker_image_with_tag(ref: str) -> str:
    text = str(ref or "").strip().strip("'\"")
    lowered = text.lower()
    if lowered.startswith("docker://"):
        text = text[9:]
    if "@" in text.split("/", 1)[-1]:
        return text
    name = text.rsplit("/", 1)[-1]
    if ":" in name:
        return text
    return f"{text}:latest"


def _docker_repo_name(ref: str) -> str:
    text = str(ref or "").strip().strip("'\"")
    lowered = text.lower()
    if lowered.startswith("docker://"):
        text = text[9:]
    leaf = text.rsplit("/", 1)[-1]
    if "@" in leaf:
        text = text.split("@", 1)[0]
        leaf = text.rsplit("/", 1)[-1]
    if ":" in leaf:
        return text.rsplit(":", 1)[0]
    return text


def _docker_pull_image(parts: list[str]) -> str:
    image, _platform, _all_tags = _docker_pull_spec(parts)
    return image


def _docker_pull_spec(parts: list[str]) -> tuple[str, str, bool]:
    return _docker_image_xfer_spec(parts, "pull")


def _docker_push_spec(parts: list[str]) -> tuple[str, str, bool]:
    return _docker_image_xfer_spec(parts, "push")


def _docker_image_xfer_spec(parts: list[str], verb: str) -> tuple[str, str, bool]:
    if not parts or _tool_basename(parts[0]) != "docker":
        return "", "", False
    rest = parts[1:]
    if rest and _tool_basename(rest[0]) == "image":
        rest = rest[1:]
    if not rest or _tool_basename(rest[0]) != verb:
        return "", "", False
    image = ""
    platform = ""
    all_tags = False
    index = 1
    while index < len(rest):
        text = str(rest[index] or "").strip().strip("'\"")
        index += 1
        if not text or text in _DOCKER_PULL_QUIET or text == "--disable-content-trust":
            continue
        if text in {"-a", "--all-tags"}:
            all_tags = True
            continue
        if text.startswith("--platform="):
            if platform:
                return "", "", False
            platform = text.split("=", 1)[1].strip()
            continue
        if text == "--platform":
            if platform or index >= len(rest):
                return "", "", False
            platform = str(rest[index] or "").strip().strip("'\"")
            index += 1
            if not platform or platform.startswith("-"):
                return "", "", False
            continue
        if text.startswith("-"):
            return "", "", False
        if image:
            return "", "", False
        image = text
    return image, platform, all_tags


def _skopeo_platform_flags(platform: str) -> list[str] | None:
    text = str(platform or "").strip()
    if not text:
        return []
    bits = [part for part in text.split("/") if part]
    if len(bits) < 2 or len(bits) > 3:
        return None
    os_name, arch = bits[0], bits[1]
    if not re.fullmatch(r"[A-Za-z0-9._-]+", os_name) or not re.fullmatch(r"[A-Za-z0-9._-]+", arch):
        return None
    flags = ["--override-os", os_name, "--override-arch", arch]
    if len(bits) == 3:
        variant = bits[2]
        if not re.fullmatch(r"[A-Za-z0-9._-]+", variant):
            return None
        flags.extend(["--override-variant", variant])
    return flags


def lan_bound_docker_pull_argv(command: str) -> list[str] | None:
    """``docker pull`` of an on-link RFC1918 registry via skopeo + LAN HTTP proxy.

    Dockerd fetches the registry itself and cannot source-bind the home NIC.
    ``skopeo copy`` honors HTTP_PROXY, so the loopback LAN proxy sources the
    registry from that NIC and loads the image into the local docker daemon.
    Skip pipes, public Hub names, and missing docker. ``-a`` / ``--all-tags``
    lists tags through skopeo (or the registry API) and copies each. Optional
    ``-q`` / ``--quiet`` and ``--platform os/arch[/variant]``. When skopeo is
    missing, the helper uses the OCI API plus ``docker load`` on the LAN proxy.
    """
    text = str(command or "").strip()
    if not text or _UNSAFE_SHELL.search(text):
        return None
    try:
        parts = shlex.split(text, posix=os.name != "nt")
    except ValueError:
        return None
    image, platform, all_tags = _docker_pull_spec(parts)
    if not image:
        return None
    host = docker_registry_host_from_image(image)
    if not _lan_bind_ip_for_host(host):
        return None
    quiet = any(str(item) in _DOCKER_PULL_QUIET for item in parts[1:])
    overrides = _skopeo_platform_flags(platform)
    if overrides is None:
        return None
    exe = resolve_skopeo()
    if all_tags:
        return skopeo_copy_lan_images_argv(
            [_docker_repo_name(image)], quiet=quiet, all_tags=True, platform_flags=overrides
        )
    if exe:
        tagged = _docker_image_with_tag(image)
        argv = [exe, "copy", *overrides]
        if quiet:
            argv.append("--quiet")
        argv.extend(["--src-tls-verify=false", f"docker://{tagged}", f"docker-daemon:{tagged}"])
        return argv
    return skopeo_copy_lan_images_argv(
        [image], quiet=quiet, platform_flags=overrides
    )


def lan_bound_docker_push_argv(command: str) -> list[str] | None:
    """``docker push`` of an on-link RFC1918 registry via skopeo + LAN HTTP proxy.

    Dockerd uploads the registry itself and cannot source-bind the home NIC.
    ``skopeo copy`` honors HTTP_PROXY, so the loopback LAN proxy sources the
    daemon image from this PC and pushes to the NAS. Skip pipes, public Hub
    names, and missing docker. ``-a`` / ``--all-tags`` lists local daemon tags
    and uploads each. When skopeo is missing, the helper uses ``docker save``
    plus the OCI API on the LAN proxy.
    """
    text = str(command or "").strip()
    if not text or _UNSAFE_SHELL.search(text):
        return None
    try:
        parts = shlex.split(text, posix=os.name != "nt")
    except ValueError:
        return None
    image, platform, all_tags = _docker_push_spec(parts)
    if not image:
        return None
    host = docker_registry_host_from_image(image)
    if not _lan_bind_ip_for_host(host):
        return None
    quiet = any(str(item) in _DOCKER_PULL_QUIET for item in parts[1:])
    overrides = _skopeo_platform_flags(platform)
    if overrides is None:
        return None
    if all_tags:
        return skopeo_copy_lan_images_argv(
            [_docker_repo_name(image)], quiet=quiet, push=True, all_tags=True, platform_flags=overrides
        )
    exe = resolve_skopeo()
    if exe:
        tagged = _docker_image_with_tag(image)
        argv = [exe, "copy", *overrides]
        if quiet:
            argv.append("--quiet")
        argv.extend(["--dest-tls-verify=false", f"docker-daemon:{tagged}", f"docker://{tagged}"])
        return argv
    return skopeo_copy_lan_images_argv(
        [image], quiet=quiet, push=True, platform_flags=overrides
    )


_DOCKER_LOGIN_VALUE_FLAGS = frozenset({"-u", "--username", "-p", "--password"})
_DOCKER_LOGIN_BOOL_FLAGS = frozenset({"--password-stdin"})


def _docker_config_authfile() -> str:
    return str(Path.home() / ".docker" / "config.json")


def _skopeo_login_registry(server: str) -> str:
    from urllib.parse import urlparse

    text = str(server or "").strip().strip("'\"")
    if not text:
        return ""
    if "://" in text:
        parsed = urlparse(text)
        host = (parsed.hostname or "").strip()
        if not host:
            return ""
        if parsed.port:
            return f"{host}:{parsed.port}"
        return host
    return text.rstrip("/")


def _docker_login_spec(parts: list[str]) -> tuple[str, list[str]] | None:
    if not parts or _tool_basename(parts[0]) != "docker":
        return None
    rest = parts[1:]
    if not rest or _tool_basename(rest[0]) != "login":
        return None
    flags: list[str] = []
    server = ""
    index = 1
    while index < len(rest):
        text = str(rest[index] or "").strip().strip("'\"")
        index += 1
        if not text:
            continue
        if text in _DOCKER_LOGIN_BOOL_FLAGS:
            flags.append(text)
            continue
        if text.startswith("--username=") or text.startswith("--password="):
            flags.append(text)
            continue
        if text in _DOCKER_LOGIN_VALUE_FLAGS:
            if index >= len(rest):
                return None
            flags.extend([text, str(rest[index] or "").strip().strip("'\"")])
            index += 1
            continue
        if text.startswith("-"):
            return None
        if server:
            return None
        server = text
    if not server:
        return None
    return server, flags


def lan_bound_docker_login_argv(command: str) -> list[str] | None:
    """``docker login`` of an on-link RFC1918 registry via skopeo + LAN HTTP proxy.

    Dockerd authenticates through the engine and cannot source-bind the home NIC.
    ``skopeo login --tls-verify=false`` honors HTTP_PROXY and writes
    ``~/.docker/config.json`` so later pull/push reuse the same creds.
    When skopeo is missing, the helper authenticates ``GET /v2/`` through the
    LAN proxy and writes the same auth file. Skip pipes, Docker Hub, and
    interactive logins with no username/password.
    """
    text = str(command or "").strip()
    if not text or _UNSAFE_SHELL.search(text):
        return None
    try:
        parts = shlex.split(text, posix=os.name != "nt")
    except ValueError:
        return None
    spec = _docker_login_spec(parts)
    if spec is None:
        return None
    server, flags = spec
    registry = _skopeo_login_registry(server)
    if not registry:
        return None
    from ..security.hexstrike_defensive import bindable_lan_host

    host = bindable_lan_host(registry)
    if not _lan_bind_ip_for_host(host):
        return None
    exe = resolve_skopeo()
    authfile = Path(_docker_config_authfile())
    try:
        authfile.parent.mkdir(parents=True, exist_ok=True)
    except OSError:
        return None
    if exe:
        return [exe, "login", "--tls-verify=false", "--authfile", str(authfile), *flags, registry]
    from .lan_skopeo_load import _login_creds

    if _login_creds(flags) is None:
        return None
    python = sys.executable or shutil.which("python3") or "python3"
    helper = str(Path(__file__).resolve().parent / "lan_skopeo_load.py")
    return [python, helper, "--login", "--authfile", str(authfile), *flags, registry]


_COMPOSE_FILENAMES = ("compose.yaml", "compose.yml", "docker-compose.yaml", "docker-compose.yml")
_COMPOSE_FILE_FLAGS = frozenset({"-f", "--file"})
_COMPOSE_PULL_QUIET = frozenset({"-q", "--quiet"})
_BRACE_VAR = re.compile(
    r"\$\{([A-Za-z_][A-Za-z0-9_]*)(?:(:-)|-)([^}]*)\}|\$\{([A-Za-z_][A-Za-z0-9_]*)\}"
)
_SIMPLE_VAR = re.compile(r"\$([A-Za-z_][A-Za-z0-9_]*)")
_ARG_DECL = re.compile(r"^\s*ARG\s+([A-Za-z_][A-Za-z0-9_]*)(?:\s*=\s*(.*))?\s*$", re.I)


def expand_image_vars(text: str, args: dict[str, str] | None = None) -> str | None:
    """Expand ``${VAR}``, ``${VAR:-default}``, ``${VAR-default}``, and ``$VAR``.

    Returns None when a required variable is unset so callers skip interpolations
    that docker would still leave unresolved.
    """
    source = str(text or "").strip()
    if "$" not in source:
        return source
    values = dict(args or {})
    missing = False

    def brace(match: re.Match[str]) -> str:
        nonlocal missing
        bare = match.group(4)
        if bare:
            if bare not in values:
                missing = True
                return match.group(0)
            return values[bare]
        name = match.group(1)
        colon = match.group(2)
        default = match.group(3) if match.group(3) is not None else ""
        if colon:
            val = values.get(name, "")
            return val if val else default
        if name in values:
            return values[name]
        return default

    out = _BRACE_VAR.sub(brace, source)

    def simple(match: re.Match[str]) -> str:
        nonlocal missing
        name = match.group(1)
        if name not in values:
            missing = True
            return match.group(0)
        return values[name]

    out = _SIMPLE_VAR.sub(simple, out)
    if missing or "$" in out:
        return None
    return out.strip().strip("'\"")


def _load_compose(path: Path) -> dict:
    try:
        import yaml
    except ImportError:
        return {}
    try:
        payload = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, yaml.YAMLError):
        return {}
    return payload if isinstance(payload, dict) else {}


def _compose_include_paths(path: Path) -> list[Path]:
    """Compose files listed in ``include:`` (string, mapping, or list). Skip interpolations."""
    raw = _load_compose(path).get("include")
    items: list[object] = []
    if isinstance(raw, list):
        items = list(raw)
    elif raw not in (None, ""):
        items = [raw]
    out: list[Path] = []
    seen: set[str] = set()
    for item in items:
        rel = ""
        if isinstance(item, str):
            rel = item.strip()
        elif isinstance(item, dict):
            rel = str(item.get("path") or "").strip()
        if "$" in rel:
            rel = expand_image_vars(rel, dict(os.environ)) or ""
        if not rel:
            continue
        candidate = Path(rel)
        if not candidate.is_absolute():
            candidate = path.parent / candidate
        key = str(candidate)
        if key in seen or not candidate.is_file():
            continue
        seen.add(key)
        out.append(candidate)
    return out


def _compose_raw_services(path: Path) -> dict[str, dict]:
    services = _load_compose(path).get("services")
    if not isinstance(services, dict):
        return {}
    return {str(name): spec for name, spec in services.items() if isinstance(spec, dict)}


def _absolutize_compose_build(spec: dict, origin: Path) -> dict:
    """Resolve ``build`` paths against the file that declared them (extends.file)."""
    build = spec.get("build")
    origin_dir = origin.parent
    if isinstance(build, str):
        text = build.strip()
        if text and "$" not in text and "://" not in text and not Path(text).is_absolute():
            return {**spec, "build": str(origin_dir / text)}
        return spec
    if isinstance(build, dict):
        extra = dict(build)
        ctx = str(extra.get("context") or ".").strip()
        if ctx and "$" not in ctx and "://" not in ctx and not Path(ctx).is_absolute():
            extra["context"] = str(origin_dir / ctx)
        return {**spec, "build": extra}
    return spec


def _compose_merged_service(path: Path, spec: dict, seen: set[str] | None = None) -> dict:
    """Merge ``extends`` (same file or ``file:``) then local keys. Local build dict keys win."""
    watching = set() if seen is None else seen
    ext = spec.get("extends")
    local = {key: val for key, val in spec.items() if key != "extends"}
    if not ext:
        return _absolutize_compose_build(local, path)
    file_rel = ""
    svc = ""
    if isinstance(ext, str):
        svc = ext.strip()
    elif isinstance(ext, dict):
        file_rel = str(ext.get("file") or "").strip()
        svc = str(ext.get("service") or "").strip()
        if "$" in file_rel:
            file_rel = expand_image_vars(file_rel, dict(os.environ)) or ""
    if not svc or "$" in svc:
        return _absolutize_compose_build(local, path)
    other = path if not file_rel else Path(file_rel)
    if file_rel and not other.is_absolute():
        other = path.parent / file_rel
    key = f"{other}:{svc}"
    if key in watching:
        return _absolutize_compose_build(local, path)
    watching.add(key)
    parent_spec = _compose_raw_services(other).get(svc)
    if not isinstance(parent_spec, dict):
        return _absolutize_compose_build(local, path)
    parent = _compose_merged_service(other, parent_spec, watching)
    child = _absolutize_compose_build(local, path)
    merged = {**parent, **child}
    if isinstance(parent.get("build"), dict) and isinstance(child.get("build"), dict):
        merged["build"] = {**parent["build"], **child["build"]}
    return merged


def _compose_services(path: Path) -> dict[str, dict]:
    return {
        name: _compose_merged_service(path, spec)
        for name, spec in _compose_raw_services(path).items()
    }


def compose_service_images(path: Path) -> dict[str, str]:
    """Map compose service name → image ref. Skip build-only services and unresolved interpolations."""
    images: dict[str, str] = {}
    for name, spec in _compose_services(path).items():
        image = str(spec.get("image") or "").strip()
        image = expand_image_vars(image, dict(os.environ)) or ""
        if not image:
            continue
        images[str(name)] = image
    return images


def compose_service_dockerfiles(path: Path) -> dict[str, Path]:
    """Map compose service name → Dockerfile. Skip interpolations, inline, and git contexts."""
    compose_dir = path.parent
    files: dict[str, Path] = {}
    for name, spec in _compose_services(path).items():
        build = spec.get("build")
        context = ""
        dockerfile = ""
        if isinstance(build, str):
            context = build.strip()
        elif isinstance(build, dict):
            if str(build.get("dockerfile_inline") or "").strip():
                continue
            context = str(build.get("context") or ".").strip()
            dockerfile = str(build.get("dockerfile") or "").strip()
        else:
            continue
        if not context or "$" in context or "$" in dockerfile or "://" in context:
            continue
        ctx = Path(context)
        if not ctx.is_absolute():
            ctx = compose_dir / ctx
        df = Path(dockerfile) if dockerfile else ctx / "Dockerfile"
        if dockerfile and not df.is_absolute():
            df = ctx / dockerfile
        if df.is_file():
            files[str(name)] = df
    return files


def compose_service_inline_dockerfiles(path: Path) -> dict[str, str]:
    """Map compose service name → ``build.dockerfile_inline`` text."""
    result: dict[str, str] = {}
    for name, spec in _compose_services(path).items():
        build = spec.get("build")
        if not isinstance(build, dict):
            continue
        text = str(build.get("dockerfile_inline") or "")
        if text.strip():
            result[str(name)] = text
    return result


def _parse_build_arg_mapping(raw: object, env: dict[str, str] | None = None) -> dict[str, str]:
    values = dict(env if env is not None else os.environ)
    out: dict[str, str] = {}
    items: list[tuple[str, str]] = []
    if isinstance(raw, dict):
        items = [(str(key).strip(), str(val if val is not None else "").strip()) for key, val in raw.items()]
    elif isinstance(raw, list):
        for item in raw:
            text = str(item or "").strip()
            if "=" not in text:
                key = text.strip()
                if key and "$" not in key and key in values:
                    items.append((key, str(values[key])))
                continue
            key, _, val = text.partition("=")
            items.append((key.strip(), val.strip()))
    for name, text in items:
        if not name or "$" in name:
            continue
        expanded = expand_image_vars(text, values) if "$" in text else text
        if expanded is None:
            continue
        out[name] = expanded.strip().strip("'\"")
        values[name] = out[name]
    return out


def _image_from_named_context(raw: str, env: dict[str, str] | None = None) -> str | None:
    """Image ref inside ``docker-image://`` / ``container-image://`` named contexts."""
    text = str(raw or "").strip().strip("'\"")
    if not text:
        return None
    if "$" in text:
        text = expand_image_vars(text, env if env is not None else os.environ) or ""
        text = text.strip().strip("'\"")
        if not text:
            return None
    match = re.match(r"^(?:docker-image|container-image)://(.+)$", text, re.I)
    if not match:
        return None
    image = match.group(1).strip().strip("'\"")
    return image or None


def _parse_named_context_images(raw: object, env: dict[str, str] | None = None) -> list[str]:
    items: list[str] = []
    if isinstance(raw, dict):
        items = [str(val if val is not None else "") for val in raw.values()]
    elif isinstance(raw, list):
        for item in raw:
            text = str(item or "").strip()
            if "=" in text:
                _, _, rhs = text.partition("=")
                items.append(rhs)
            else:
                items.append(text)
    out: list[str] = []
    seen: set[str] = set()
    for item in items:
        image = _image_from_named_context(item, env)
        if not image or image in seen:
            continue
        seen.add(image)
        out.append(image)
    return out


def compose_service_context_images(path: Path) -> dict[str, list[str]]:
    """Map compose service name → ``build.additional_contexts`` image refs."""
    result: dict[str, list[str]] = {}
    for name, spec in _compose_services(path).items():
        build = spec.get("build")
        if not isinstance(build, dict):
            continue
        images = _parse_named_context_images(build.get("additional_contexts"))
        if images:
            result[str(name)] = images
    return result


_CACHE_SKIP_TYPES = frozenset({"local", "gha", "s3", "azblob", "inline", "gcs", "oss"})


def _image_from_cache_source(raw: str, env: dict[str, str] | None = None) -> str | None:
    """Image ref in ``--cache-from`` / ``--cache-to`` / compose / bake cache fields."""
    text = str(raw or "").strip().strip("'\"")
    if not text:
        return None
    if "$" in text:
        text = expand_image_vars(text, env if env is not None else os.environ) or ""
        text = text.strip().strip("'\"")
        if not text:
            return None
    lowered = text.lower()
    if "type=" in lowered and ("," in text or lowered.startswith("type=")):
        fields: dict[str, str] = {}
        for part in text.split(","):
            key, sep, val = part.partition("=")
            if sep:
                fields[key.strip().lower()] = val.strip().strip("'\"")
        if fields.get("type", "").lower() in _CACHE_SKIP_TYPES:
            return None
        ref = fields.get("ref") or fields.get("image") or ""
        if not ref:
            return None
        named = _image_from_named_context(ref, env)
        if named:
            return named
        if "://" in ref:
            return None
        return ref
    named = _image_from_named_context(text, env)
    if named:
        return named
    if "://" in text:
        return None
    return text


def _parse_cache_images(raw: object, env: dict[str, str] | None = None) -> list[str]:
    items: list[object] = []
    if isinstance(raw, list):
        items = list(raw)
    elif raw not in (None, ""):
        items = [raw]
    out: list[str] = []
    seen: set[str] = set()
    for item in items:
        if isinstance(item, dict):
            kind = str(item.get("type") or "").strip().lower()
            if kind in _CACHE_SKIP_TYPES:
                continue
            ref = str(item.get("ref") or item.get("image") or "").strip()
            image = _image_from_cache_source(ref, env) if ref else None
        else:
            image = _image_from_cache_source(str(item), env)
        if not image or image in seen:
            continue
        seen.add(image)
        out.append(image)
    return out


def compose_service_cache_images(path: Path) -> dict[str, list[str]]:
    """Map compose service name → ``build.cache_from`` image refs."""
    result: dict[str, list[str]] = {}
    for name, spec in _compose_services(path).items():
        build = spec.get("build")
        if not isinstance(build, dict):
            continue
        images = _parse_cache_images(build.get("cache_from"))
        if images:
            result[str(name)] = images
    return result


def compose_service_cache_to_images(path: Path) -> dict[str, list[str]]:
    """Map compose service name → ``build.cache_to`` registry image refs."""
    result: dict[str, list[str]] = {}
    for name, spec in _compose_services(path).items():
        build = spec.get("build")
        if not isinstance(build, dict):
            continue
        images = _parse_cache_images(build.get("cache_to"))
        if images:
            result[str(name)] = images
    return result


def compose_service_build_args(path: Path) -> dict[str, dict[str, str]]:
    """Map compose service name → ``build.args`` used as Dockerfile ARG values."""
    result: dict[str, dict[str, str]] = {}
    for name, spec in _compose_services(path).items():
        build = spec.get("build")
        if not isinstance(build, dict):
            continue
        args = _parse_build_arg_mapping(build.get("args"))
        if args:
            result[str(name)] = args
    return result


def compose_service_depends(path: Path) -> dict[str, list[str]]:
    """Map compose service name → depends_on names. Skip interpolations."""
    deps: dict[str, list[str]] = {}
    for name, spec in _compose_services(path).items():
        raw = spec.get("depends_on")
        names: list[str] = []
        if isinstance(raw, list):
            names = [str(item).strip() for item in raw]
        elif isinstance(raw, dict):
            names = [str(item).strip() for item in raw]
        elif isinstance(raw, str):
            names = [raw.strip()]
        kept = [item for item in names if item and "$" not in item]
        if kept:
            deps[str(name)] = kept
    return deps


def _compose_service_closure(deps: dict[str, list[str]], services: list[str]) -> list[str]:
    chosen: list[str] = []
    seen: set[str] = set()
    stack = list(reversed(services))
    while stack:
        name = stack.pop()
        if name in seen:
            continue
        seen.add(name)
        chosen.append(name)
        for dep in reversed(deps.get(name, [])):
            if dep not in seen:
                stack.append(dep)
    return chosen


def _default_compose_files(cwd: str | None) -> list[Path]:
    root = Path(cwd or os.getcwd())
    found = [root / name for name in _COMPOSE_FILENAMES if (root / name).is_file()]
    return found[:1]


def _resolved_compose_paths(files: list[str], cwd: str | None) -> list[Path] | None:
    root = Path(cwd or os.getcwd())
    paths: list[Path] = []
    for item in files:
        if not item:
            continue
        candidate = Path(item)
        if not candidate.is_absolute():
            candidate = root / candidate
        paths.append(candidate)
    if not paths:
        paths = _default_compose_files(str(root))
    if not paths:
        return None
    for path in paths:
        if not path.is_file():
            return None
    expanded: list[Path] = []
    seen: set[str] = set()

    def walk(item: Path) -> None:
        key = str(item)
        if key in seen:
            return
        seen.add(key)
        for child in _compose_include_paths(item):
            walk(child)
        expanded.append(item)

    for path in paths:
        walk(path)
    return expanded


def _compose_pull_spec(parts: list[str]) -> tuple[list[str], list[str], bool] | None:
    if not parts:
        return None
    stem = _tool_basename(parts[0])
    rest = parts[1:]
    if stem == "docker":
        if not rest or _tool_basename(rest[0]) != "compose":
            return None
        rest = rest[1:]
    elif stem not in {"docker-compose", "docker_compose"}:
        return None
    files: list[str] = []
    quiet = False
    index = 0
    while index < len(rest):
        text = str(rest[index] or "").strip().strip("'\"")
        index += 1
        if not text:
            continue
        if text in _COMPOSE_PULL_QUIET:
            quiet = True
            continue
        if text.startswith("--file="):
            files.append(text.split("=", 1)[1].strip())
            continue
        if text in _COMPOSE_FILE_FLAGS:
            if index >= len(rest):
                return None
            files.append(str(rest[index] or "").strip().strip("'\""))
            index += 1
            continue
        if text == "pull":
            break
        if text.startswith("-"):
            return None
        return None
    else:
        return None
    services: list[str] = []
    while index < len(rest):
        text = str(rest[index] or "").strip().strip("'\"")
        index += 1
        if not text:
            continue
        if text in _COMPOSE_PULL_QUIET:
            quiet = True
            continue
        if text.startswith("-"):
            return None
        services.append(text)
    return files, services, quiet


def skopeo_copy_lan_images_argv(
    images: list[str],
    *,
    quiet: bool = False,
    follow: list[str] | None = None,
    push: bool = False,
    push_after: list[str] | None = None,
    then: list[str] | None = None,
    all_tags: bool = False,
    platform_flags: list[str] | None = None,
    fetches: list[tuple[str, str]] | None = None,
    cleanup: str | None = None,
) -> list[str] | None:
    exe = resolve_skopeo()
    docker = shutil.which("docker") or shutil.which("docker.exe")
    tagged = (
        [_docker_repo_name(image) for image in images]
        if all_tags
        else [_docker_image_with_tag(image) for image in images]
    )
    after = [_docker_image_with_tag(image) for image in (push_after or [])]
    follow_cmd = list(follow or [])
    then_cmd = list(then or [])
    overrides = list(platform_flags or [])
    fetch_pairs = [(str(url), str(path)) for url, path in (fetches or []) if url and path]
    needs_copy = bool(tagged or after)
    python_copy = needs_copy and not exe
    if python_copy and not docker:
        return None
    if not needs_copy and not (fetch_pairs and follow_cmd):
        return None
    if not python_copy and not fetch_pairs and len(tagged) == 1 and not follow_cmd and not after and not then_cmd and not all_tags:
        argv = [exe, "copy", *overrides]
        if quiet:
            argv.append("--quiet")
        if push:
            argv.extend(["--dest-tls-verify=false", f"docker-daemon:{tagged[0]}", f"docker://{tagged[0]}"])
        else:
            argv.extend(["--src-tls-verify=false", f"docker://{tagged[0]}", f"docker-daemon:{tagged[0]}"])
        return argv
    if not python_copy and not fetch_pairs and len(after) == 1 and not tagged and not follow_cmd and not then_cmd and not overrides:
        argv = [exe, "copy"]
        if quiet:
            argv.append("--quiet")
        argv.extend(["--dest-tls-verify=false", f"docker-daemon:{after[0]}", f"docker://{after[0]}"])
        return argv
    python = sys.executable or shutil.which("python3") or "python3"
    helper = str(Path(__file__).resolve().parent / "lan_skopeo_load.py")
    argv = [python, helper]
    if quiet:
        argv.append("--quiet")
    if push:
        argv.append("--push")
    if python_copy:
        argv.append("--python-copy")
    if all_tags:
        argv.append("--all-tags")
    argv.extend(overrides)
    for image in after:
        argv.extend(["--push-after", image])
    if cleanup:
        argv.extend(["--cleanup", cleanup])
    for url, path in fetch_pairs:
        argv.extend(["--fetch", f"{url}={path}"])
    if needs_copy:
        if python_copy:
            argv.extend(tagged)
        else:
            argv.extend([exe, *tagged])
    if follow_cmd or then_cmd:
        argv.append("--")
        argv.extend(follow_cmd)
        if then_cmd:
            argv.extend(["--", *then_cmd])
    return argv


def lan_bound_compose_pull_argv(command: str, cwd: str | None = None) -> list[str] | None:
    """``docker compose pull`` of on-link RFC1918 images via skopeo + LAN HTTP proxy.

    Dockerd cannot source-bind. Skip pipes, interpolations, unknown flags, and
    stacks whose pull set has no LAN image. Public Hub services still use
    ``docker compose pull`` after the LAN images load.
    """
    text = str(command or "").strip()
    if not text or _UNSAFE_SHELL.search(text):
        return None
    try:
        parts = shlex.split(text, posix=os.name != "nt")
    except ValueError:
        return None
    spec = _compose_pull_spec(parts)
    if spec is None:
        return None
    files, services, quiet = spec
    paths = _resolved_compose_paths(files, cwd)
    if not paths:
        return None
    images: dict[str, str] = {}
    for path in paths:
        images.update(compose_service_images(path))
    if not images:
        return None
    chosen = {name: images[name] for name in services if name in images} if services else dict(images)
    if services and not chosen:
        return None
    lan: list[str] = []
    public: list[str] = []
    for name, image in chosen.items():
        host = docker_registry_host_from_image(image)
        if _lan_bind_ip_for_host(host):
            lan.append(image)
        else:
            public.append(name)
    if not lan:
        return None
    follow: list[str] | None = None
    if public:
        compose_bin = shutil.which("docker") or shutil.which("docker.exe")
        if not compose_bin:
            return None
        follow = [compose_bin, "compose"]
        for path in paths:
            follow.extend(["-f", str(path)])
        follow.append("pull")
        if quiet:
            follow.append("--quiet")
        follow.extend(public)
    return skopeo_copy_lan_images_argv(lan, quiet=quiet, follow=follow)


def _compose_push_spec(parts: list[str]) -> tuple[list[str], list[str], bool, bool] | None:
    if not parts:
        return None
    stem = _tool_basename(parts[0])
    rest = parts[1:]
    if stem == "docker":
        if not rest or _tool_basename(rest[0]) != "compose":
            return None
        rest = rest[1:]
    elif stem not in {"docker-compose", "docker_compose"}:
        return None
    files: list[str] = []
    quiet = False
    index = 0
    while index < len(rest):
        text = str(rest[index] or "").strip().strip("'\"")
        index += 1
        if not text:
            continue
        if text in _COMPOSE_PULL_QUIET:
            quiet = True
            continue
        if text.startswith("--file="):
            files.append(text.split("=", 1)[1].strip())
            continue
        if text in _COMPOSE_FILE_FLAGS:
            if index >= len(rest):
                return None
            files.append(str(rest[index] or "").strip().strip("'\""))
            index += 1
            continue
        if text == "push":
            break
        if text.startswith("-"):
            return None
        return None
    else:
        return None
    services: list[str] = []
    include_deps = False
    while index < len(rest):
        text = str(rest[index] or "").strip().strip("'\"")
        index += 1
        if not text:
            continue
        if text in _COMPOSE_PULL_QUIET:
            quiet = True
            continue
        if text == "--include-deps":
            include_deps = True
            continue
        if text == "--ignore-push-failures":
            continue
        if text.startswith("-"):
            return None
        services.append(text)
    return files, services, quiet, include_deps


def lan_bound_compose_push_argv(command: str, cwd: str | None = None) -> list[str] | None:
    """``docker compose push`` of on-link RFC1918 images via skopeo + LAN HTTP proxy.

    Dockerd cannot source-bind. Skip pipes, interpolations, unknown flags, and
    stacks whose push set has no LAN image. Public Hub services still use
    ``docker compose push`` after the LAN images upload. ``--include-deps``
    walks ``depends_on``.
    """
    text = str(command or "").strip()
    if not text or _UNSAFE_SHELL.search(text):
        return None
    try:
        parts = shlex.split(text, posix=os.name != "nt")
    except ValueError:
        return None
    spec = _compose_push_spec(parts)
    if spec is None:
        return None
    files, services, quiet, include_deps = spec
    paths = _resolved_compose_paths(files, cwd)
    if not paths:
        return None
    images: dict[str, str] = {}
    deps: dict[str, list[str]] = {}
    for path in paths:
        images.update(compose_service_images(path))
        for name, kids in compose_service_depends(path).items():
            deps.setdefault(name, [])
            for kid in kids:
                if kid not in deps[name]:
                    deps[name].append(kid)
    if not images:
        return None
    wanted = list(services)
    if wanted and include_deps:
        wanted = _compose_service_closure(deps, wanted)
    chosen = {name: images[name] for name in wanted if name in images} if wanted else dict(images)
    if services and not chosen:
        return None
    lan: list[str] = []
    public: list[str] = []
    for name, image in chosen.items():
        host = docker_registry_host_from_image(image)
        if _lan_bind_ip_for_host(host):
            lan.append(image)
        else:
            public.append(name)
    if not lan:
        return None
    follow: list[str] | None = None
    if public:
        compose_bin = shutil.which("docker") or shutil.which("docker.exe")
        if not compose_bin:
            return None
        follow = [compose_bin, "compose"]
        for path in paths:
            follow.extend(["-f", str(path)])
        follow.append("push")
        if quiet:
            follow.append("--quiet")
        follow.extend(public)
    return skopeo_copy_lan_images_argv(lan, quiet=quiet, follow=follow, push=True)


_COMPOSE_BUILD_VALUE_FLAGS = frozenset(
    {
        "--build-arg",
        "--build-context",
        "--builder",
        "--cache-from",
        "--cache-to",
        "--memory",
        "-m",
        "--ssh",
    }
)
_COMPOSE_BUILD_BOOL_FLAGS = frozenset(
    {
        "--no-cache",
        "--with-dependencies",
        "--push",
        "--dry-run",
    }
)
_COMPOSE_BUILD_PULL_KEEP = frozenset({"--pull=never", "--pull=false", "--pull=missing"})


def _compose_build_spec(parts: list[str]) -> tuple[list[str], list[str], bool, bool, bool] | None:
    if not parts:
        return None
    stem = _tool_basename(parts[0])
    rest = parts[1:]
    if stem == "docker":
        if not rest or _tool_basename(rest[0]) != "compose":
            return None
        rest = rest[1:]
    elif stem not in {"docker-compose", "docker_compose"}:
        return None
    files: list[str] = []
    quiet = False
    index = 0
    while index < len(rest):
        text = str(rest[index] or "").strip().strip("'\"")
        index += 1
        if not text:
            continue
        if text in _COMPOSE_PULL_QUIET:
            quiet = True
            continue
        if text.startswith("--file="):
            files.append(text.split("=", 1)[1].strip())
            continue
        if text in _COMPOSE_FILE_FLAGS:
            if index >= len(rest):
                return None
            files.append(str(rest[index] or "").strip().strip("'\""))
            index += 1
            continue
        if text == "build":
            break
        if text.startswith("-"):
            return None
        return None
    else:
        return None
    services: list[str] = []
    with_deps = False
    wants_push = False
    while index < len(rest):
        text = str(rest[index] or "").strip().strip("'\"")
        index += 1
        if not text:
            continue
        if text in _COMPOSE_PULL_QUIET:
            quiet = True
            continue
        if text == "--with-dependencies":
            with_deps = True
            continue
        if text == "--push":
            wants_push = True
            continue
        if text in _COMPOSE_BUILD_BOOL_FLAGS or text in {"--pull"}:
            continue
        if text.startswith("--pull="):
            continue
        if text.startswith("--") and "=" in text:
            key = text.split("=", 1)[0]
            if key in _COMPOSE_BUILD_VALUE_FLAGS:
                continue
            return None
        if text in _COMPOSE_BUILD_VALUE_FLAGS:
            if index >= len(rest):
                return None
            index += 1
            continue
        if text.startswith("-"):
            return None
        services.append(text)
    return files, services, quiet, with_deps, wants_push


def _compose_build_without_pull(parts: list[str]) -> list[str]:
    out: list[str] = []
    for item in parts:
        text = str(item)
        if text == "--pull":
            continue
        if text.startswith("--pull=") and text not in _COMPOSE_BUILD_PULL_KEEP:
            continue
        out.append(text)
    return out


def _compose_build_without_push(parts: list[str]) -> list[str]:
    return [item for item in parts if str(item) != "--push"]


def _compose_follow_argv(parts: list[str]) -> list[str] | None:
    if not parts:
        return None
    stem = _tool_basename(parts[0])
    exe = shutil.which(stem) or shutil.which(f"{stem}.exe")
    if not exe:
        return None
    return [exe, *parts[1:]]


def lan_bound_compose_build_argv(command: str, cwd: str | None = None) -> list[str] | None:
    """``docker compose build`` of a service whose Dockerfile ``FROM`` or ``image:`` is on-link RFC1918.

    Dockerd cannot source-bind. Skopeo loads LAN bases through the loopback proxy,
    then compose build (without ``--pull``) uses the local daemon copies. ``--push``
    of a LAN ``image:`` becomes a local build plus skopeo upload. Skip pipes,
    interpolations, inline Dockerfiles, git contexts, unknown flags, and missing skopeo.
    """
    text = str(command or "").strip()
    if not text or _UNSAFE_SHELL.search(text):
        return None
    try:
        parts = shlex.split(text, posix=os.name != "nt")
    except ValueError:
        return None
    spec = _compose_build_spec(parts)
    if spec is None:
        return None
    files, services, quiet, with_deps, wants_push = spec
    paths = _resolved_compose_paths(files, cwd)
    if not paths:
        return None
    dockerfiles: dict[str, Path] = {}
    images: dict[str, str] = {}
    file_args: dict[str, dict[str, str]] = {}
    file_contexts: dict[str, list[str]] = {}
    file_cache_to: dict[str, list[str]] = {}
    inlines: dict[str, str] = {}
    for path in paths:
        dockerfiles.update(compose_service_dockerfiles(path))
        inlines.update(compose_service_inline_dockerfiles(path))
        images.update(compose_service_images(path))
        for name, args in compose_service_build_args(path).items():
            file_args.setdefault(name, {}).update(args)
        for name, extras in compose_service_context_images(path).items():
            file_contexts.setdefault(name, [])
            for image in extras:
                if image not in file_contexts[name]:
                    file_contexts[name].append(image)
        for name, extras in compose_service_cache_images(path).items():
            file_contexts.setdefault(name, [])
            for image in extras:
                if image not in file_contexts[name]:
                    file_contexts[name].append(image)
        for name, extras in compose_service_cache_to_images(path).items():
            file_cache_to.setdefault(name, [])
            for image in extras:
                if image not in file_cache_to[name]:
                    file_cache_to[name].append(image)
    if not dockerfiles and not inlines:
        return None
    if services and not with_deps:
        chosen = {name: dockerfiles[name] for name in services if name in dockerfiles}
        chosen_inline = {name: inlines[name] for name in services if name in inlines}
        if not chosen and not chosen_inline:
            return None
    else:
        chosen = dict(dockerfiles)
        chosen_inline = dict(inlines)
    cli_args = _docker_build_args(parts)
    lan: list[str] = []
    seen: set[str] = set()
    for name, dockerfile in chosen.items():
        merged = {**file_args.get(name, {}), **cli_args}
        for image in dockerfile_from_images(dockerfile, merged):
            if image in seen:
                continue
            if not _lan_bind_ip_for_host(docker_registry_host_from_image(image)):
                continue
            seen.add(image)
            lan.append(image)
        for image in file_contexts.get(name, ()):
            if image in seen:
                continue
            if not _lan_bind_ip_for_host(docker_registry_host_from_image(image)):
                continue
            seen.add(image)
            lan.append(image)
    for name, text in chosen_inline.items():
        merged = {**file_args.get(name, {}), **cli_args}
        for image in dockerfile_images_from_text(text, merged):
            if image in seen:
                continue
            if not _lan_bind_ip_for_host(docker_registry_host_from_image(image)):
                continue
            seen.add(image)
            lan.append(image)
        for image in file_contexts.get(name, ()):
            if image in seen:
                continue
            if not _lan_bind_ip_for_host(docker_registry_host_from_image(image)):
                continue
            seen.add(image)
            lan.append(image)
    for image in (*_docker_build_context_images(parts), *_docker_build_cache_images(parts)):
        if image in seen:
            continue
        if not _lan_bind_ip_for_host(docker_registry_host_from_image(image)):
            continue
        seen.add(image)
        lan.append(image)
    lan_tags: list[str] = []
    seen_tags: set[str] = set()
    public: list[str] = []
    for name in (*chosen, *chosen_inline):
        image = images.get(name) or ""
        if not image:
            continue
        if not _lan_bind_ip_for_host(docker_registry_host_from_image(image)):
            public.append(name)
            continue
        if image in seen_tags:
            continue
        seen_tags.add(image)
        lan_tags.append(image)
    lan_cache_map: dict[str, list[str]] = {}
    cli_cache_to = _docker_build_cache_to_images(parts)
    for name in (*chosen, *chosen_inline):
        refs = list(file_cache_to.get(name, []))
        refs.extend(cli_cache_to)
        tagged = _lan_tagged_refs(refs)
        if tagged:
            lan_cache_map[name] = tagged
    lan_cache_to = _lan_tagged_refs([img for extras in lan_cache_map.values() for img in extras])
    add_plan = _compose_materialize_lan_add(
        chosen, file_args, cli_args, cache_to=lan_cache_map, inlines=chosen_inline
    )
    if not lan and not (wants_push and lan_tags) and add_plan is None and not lan_cache_to:
        return None
    follow = _compose_follow_argv(parts)
    if not follow:
        if add_plan is not None:
            shutil.rmtree(add_plan[2], ignore_errors=True)
        return None
    follow = _compose_build_without_pull(follow)
    fetches: list[tuple[str, str]] = []
    cleanup = ""
    if add_plan is not None:
        overlay, fetches, cleanup = add_plan
        follow = _compose_insert_override(follow, overlay)
    if lan_cache_to:
        follow = _docker_build_rewrite_lan_cache_to(follow, lan_cache_to, add_tags=False)
    then: list[str] | None = None
    push_after: list[str] | None = None
    if wants_push and lan_tags:
        follow = _compose_build_without_push(follow)
        push_after = list(lan_tags)
        if public:
            stem = _tool_basename(parts[0])
            then = [follow[0]]
            if stem == "docker":
                then.append("compose")
            for path in paths:
                then.extend(["-f", str(path)])
            then.append("push")
            if quiet:
                then.append("--quiet")
            then.extend(public)
    if lan_cache_to:
        push_after = list(dict.fromkeys([*(push_after or []), *lan_cache_to]))
    return _skopeo_follow_or_cleanup(
        lan,
        quiet=quiet,
        follow=follow,
        fetches=fetches,
        cleanup=cleanup,
        push_after=push_after,
        then=then,
    )


_COMPOSE_UP_BOOL_FLAGS = frozenset(
    {
        "-d",
        "--detach",
        "--build",
        "--no-build",
        "--force-recreate",
        "--no-recreate",
        "--no-deps",
        "--remove-orphans",
        "--wait",
        "--abort-on-container-exit",
        "--renew-anon-volumes",
        "-V",
        "--no-color",
        "--no-log-prefix",
        "--attach-dependencies",
        "--quiet-pull",
        "-y",
        "--yes",
        "--always-recreate-deps",
        "--no-start",
        "--watch",
    }
)
_COMPOSE_UP_VALUE_FLAGS = frozenset(
    {
        "--pull",
        "--wait-timeout",
        "--exit-code-from",
        "--scale",
        "--timeout",
        "-t",
        "--attach",
        "--no-attach",
        "--menu",
    }
)


def _compose_up_spec(parts: list[str]) -> tuple[list[str], list[str], bool, bool, bool] | None:
    if not parts:
        return None
    stem = _tool_basename(parts[0])
    rest = parts[1:]
    if stem == "docker":
        if not rest or _tool_basename(rest[0]) != "compose":
            return None
        rest = rest[1:]
    elif stem not in {"docker-compose", "docker_compose"}:
        return None
    files: list[str] = []
    quiet = False
    index = 0
    while index < len(rest):
        text = str(rest[index] or "").strip().strip("'\"")
        index += 1
        if not text:
            continue
        if text in _COMPOSE_PULL_QUIET:
            quiet = True
            continue
        if text.startswith("--file="):
            files.append(text.split("=", 1)[1].strip())
            continue
        if text in _COMPOSE_FILE_FLAGS:
            if index >= len(rest):
                return None
            files.append(str(rest[index] or "").strip().strip("'\""))
            index += 1
            continue
        if text in {"up", "create"}:
            break
        if text.startswith("-"):
            return None
        return None
    else:
        return None
    services: list[str] = []
    do_build = False
    no_build = False
    no_deps = False
    while index < len(rest):
        text = str(rest[index] or "").strip().strip("'\"")
        index += 1
        if not text:
            continue
        if text in _COMPOSE_PULL_QUIET:
            quiet = True
            continue
        if text == "--build":
            do_build = True
            continue
        if text == "--no-build":
            no_build = True
            continue
        if text == "--no-deps":
            no_deps = True
            continue
        if text in _COMPOSE_UP_BOOL_FLAGS:
            continue
        if text.startswith("--pull="):
            continue
        if text.startswith("--") and "=" in text:
            key = text.split("=", 1)[0]
            if key in _COMPOSE_UP_VALUE_FLAGS:
                continue
            return None
        if text in _COMPOSE_UP_VALUE_FLAGS:
            if index >= len(rest):
                return None
            index += 1
            continue
        if text.startswith("-"):
            return None
        services.append(text)
    if no_build:
        do_build = False
    return files, services, quiet, do_build, no_deps


def _compose_up_without_always_pull(parts: list[str]) -> list[str]:
    out: list[str] = []
    skip_value = False
    for item in parts:
        if skip_value:
            skip_value = False
            text = str(item).strip().lower()
            if text == "always":
                out.append("missing")
            else:
                out.append(str(item))
            continue
        text = str(item)
        if text == "--pull":
            out.append(text)
            skip_value = True
            continue
        if text == "--pull=always":
            out.append("--pull=missing")
            continue
        out.append(text)
    if skip_value:
        out.append("missing")
    return out


def _compose_lan_copy_images(
    paths: list[Path],
    services: list[str],
    *,
    do_build: bool,
    no_deps: bool,
    build_services: list[str] | None = None,
) -> list[str]:
    images: dict[str, str] = {}
    dockerfiles: dict[str, Path] = {}
    file_args: dict[str, dict[str, str]] = {}
    file_contexts: dict[str, list[str]] = {}
    deps: dict[str, list[str]] = {}
    inlines: dict[str, str] = {}
    for path in paths:
        images.update(compose_service_images(path))
        if do_build:
            dockerfiles.update(compose_service_dockerfiles(path))
            inlines.update(compose_service_inline_dockerfiles(path))
            for name, args in compose_service_build_args(path).items():
                file_args.setdefault(name, {}).update(args)
            for name, extras in compose_service_context_images(path).items():
                file_contexts.setdefault(name, [])
                for image in extras:
                    if image not in file_contexts[name]:
                        file_contexts[name].append(image)
            for name, extras in compose_service_cache_images(path).items():
                file_contexts.setdefault(name, [])
                for image in extras:
                    if image not in file_contexts[name]:
                        file_contexts[name].append(image)
        for name, kids in compose_service_depends(path).items():
            deps.setdefault(name, [])
            for kid in kids:
                if kid not in deps[name]:
                    deps[name].append(kid)
    wanted = list(services)
    if wanted and not no_deps:
        wanted = _compose_service_closure(deps, wanted)
    if wanted:
        images = {name: images[name] for name in wanted if name in images}
        build_wanted = list(build_services) if build_services is not None else wanted
        dockerfiles = {name: dockerfiles[name] for name in build_wanted if name in dockerfiles}
        inlines = {name: inlines[name] for name in build_wanted if name in inlines}
        file_contexts = {name: file_contexts[name] for name in build_wanted if name in file_contexts}
    lan: list[str] = []
    seen: set[str] = set()
    for image in images.values():
        if image in seen:
            continue
        if not _lan_bind_ip_for_host(docker_registry_host_from_image(image)):
            continue
        seen.add(image)
        lan.append(image)
    for name, dockerfile in dockerfiles.items():
        for image in dockerfile_from_images(dockerfile, file_args.get(name)):
            if image in seen:
                continue
            if not _lan_bind_ip_for_host(docker_registry_host_from_image(image)):
                continue
            seen.add(image)
            lan.append(image)
    for name, text in inlines.items():
        for image in dockerfile_images_from_text(text, file_args.get(name)):
            if image in seen:
                continue
            if not _lan_bind_ip_for_host(docker_registry_host_from_image(image)):
                continue
            seen.add(image)
            lan.append(image)
    for extras in file_contexts.values():
        for image in extras:
            if image in seen:
                continue
            if not _lan_bind_ip_for_host(docker_registry_host_from_image(image)):
                continue
            seen.add(image)
            lan.append(image)
    return lan


def lan_bound_compose_up_argv(command: str, cwd: str | None = None) -> list[str] | None:
    """``docker compose up`` / ``create`` of on-link RFC1918 images / ``FROM`` via skopeo.

    Dockerd cannot source-bind. Skopeo loads LAN ``image:`` refs (including
    ``depends_on`` unless ``--no-deps``) and, when ``--build`` is set, LAN
    Dockerfile bases. ``--pull always`` becomes ``missing``. Skip pipes,
    interpolations, unknown flags, and missing skopeo.
    """
    text = str(command or "").strip()
    if not text or _UNSAFE_SHELL.search(text):
        return None
    try:
        parts = shlex.split(text, posix=os.name != "nt")
    except ValueError:
        return None
    spec = _compose_up_spec(parts)
    if spec is None:
        return None
    files, services, quiet, do_build, no_deps = spec
    paths = _resolved_compose_paths(files, cwd)
    if not paths:
        return None
    lan = _compose_lan_copy_images(paths, services, do_build=do_build, no_deps=no_deps)
    add_plan = (
        _compose_lan_add_for_build(paths, services, no_deps=no_deps, cli_args=_docker_build_args(parts))
        if do_build
        else None
    )
    if not lan and add_plan is None:
        return None
    follow = _compose_follow_argv(parts)
    if not follow:
        if add_plan is not None:
            shutil.rmtree(add_plan[2], ignore_errors=True)
        return None
    follow = _compose_up_without_always_pull(follow)
    fetches: list[tuple[str, str]] = []
    cleanup = ""
    if add_plan is not None:
        overlay, fetches, cleanup = add_plan
        follow = _compose_insert_override(follow, overlay)
    lan_cache_to = _compose_lan_cache_to(paths, services or None) if do_build else []
    return _skopeo_follow_or_cleanup(
        lan,
        quiet=quiet,
        follow=follow,
        fetches=fetches,
        cleanup=cleanup,
        push_after=lan_cache_to or None,
    )


_COMPOSE_RUN_BOOL_FLAGS = frozenset(
    {
        "-d",
        "--detach",
        "--build",
        "--no-deps",
        "--rm",
        "--quiet-pull",
        "--remove-orphans",
        "-T",
        "--no-TTY",
        "--service-ports",
        "--use-aliases",
        "-i",
        "--interactive",
        "--privileged",
        "--no-build",
    }
)
_COMPOSE_RUN_VALUE_FLAGS = frozenset(
    {
        "--entrypoint",
        "-e",
        "--env",
        "--env-from-file",
        "-l",
        "--label",
        "--name",
        "-p",
        "--publish",
        "--pull",
        "-u",
        "--user",
        "-v",
        "--volume",
        "-w",
        "--workdir",
        "--cap-add",
        "--cap-drop",
    }
)
_COMPOSE_RUN_SHORT_BOOL = frozenset("ditT")


def _compose_run_short_bool(text: str) -> bool:
    if len(text) < 2 or not text.startswith("-") or text.startswith("--"):
        return False
    return all(ch in _COMPOSE_RUN_SHORT_BOOL for ch in text[1:])


def _compose_run_spec(parts: list[str]) -> tuple[list[str], str, bool, bool, bool] | None:
    if not parts:
        return None
    stem = _tool_basename(parts[0])
    rest = parts[1:]
    if stem == "docker":
        if not rest or _tool_basename(rest[0]) != "compose":
            return None
        rest = rest[1:]
    elif stem not in {"docker-compose", "docker_compose"}:
        return None
    files: list[str] = []
    quiet = False
    index = 0
    while index < len(rest):
        text = str(rest[index] or "").strip().strip("'\"")
        index += 1
        if not text:
            continue
        if text in _COMPOSE_PULL_QUIET:
            quiet = True
            continue
        if text.startswith("--file="):
            files.append(text.split("=", 1)[1].strip())
            continue
        if text in _COMPOSE_FILE_FLAGS:
            if index >= len(rest):
                return None
            files.append(str(rest[index] or "").strip().strip("'\""))
            index += 1
            continue
        if text == "run":
            break
        if text.startswith("-"):
            return None
        return None
    else:
        return None
    do_build = False
    no_build = False
    no_deps = False
    service = ""
    while index < len(rest):
        text = str(rest[index] or "").strip().strip("'\"")
        index += 1
        if not text:
            continue
        if text == "--":
            break
        if text in _COMPOSE_PULL_QUIET:
            quiet = True
            continue
        if text == "--build":
            do_build = True
            continue
        if text == "--no-build":
            no_build = True
            continue
        if text == "--no-deps":
            no_deps = True
            continue
        if text in _COMPOSE_RUN_BOOL_FLAGS or _compose_run_short_bool(text):
            continue
        if text.startswith("--pull="):
            continue
        if text.startswith("--") and "=" in text:
            key = text.split("=", 1)[0]
            if key in _COMPOSE_RUN_VALUE_FLAGS:
                continue
            return None
        if text in _COMPOSE_RUN_VALUE_FLAGS:
            if index >= len(rest):
                return None
            index += 1
            continue
        if text.startswith("-"):
            return None
        service = text
        break
    if not service:
        return None
    if no_build:
        do_build = False
    return files, service, quiet, do_build, no_deps


def lan_bound_compose_run_argv(command: str, cwd: str | None = None) -> list[str] | None:
    """``docker compose run`` of an on-link RFC1918 image / ``FROM`` via skopeo.

    Dockerd cannot source-bind. Skopeo loads the service ``image:`` and its
    ``depends_on`` (unless ``--no-deps``). ``--build`` also loads LAN Dockerfile
    bases for that service. ``--pull always`` becomes ``missing``. Skip pipes,
    interpolations, unknown flags, and missing skopeo.
    """
    text = str(command or "").strip()
    if not text or _UNSAFE_SHELL.search(text):
        return None
    try:
        parts = shlex.split(text, posix=os.name != "nt")
    except ValueError:
        return None
    spec = _compose_run_spec(parts)
    if spec is None:
        return None
    files, service, quiet, do_build, no_deps = spec
    paths = _resolved_compose_paths(files, cwd)
    if not paths:
        return None
    lan = _compose_lan_copy_images(
        paths,
        [service],
        do_build=do_build,
        no_deps=no_deps,
        build_services=[service],
    )
    add_plan = (
        _compose_lan_add_for_build(
            paths,
            [service],
            no_deps=no_deps,
            build_services=[service],
            cli_args=_docker_build_args(parts),
        )
        if do_build
        else None
    )
    if not lan and add_plan is None:
        return None
    follow = _compose_follow_argv(parts)
    if not follow:
        if add_plan is not None:
            shutil.rmtree(add_plan[2], ignore_errors=True)
        return None
    follow = _compose_up_without_always_pull(follow)
    fetches: list[tuple[str, str]] = []
    cleanup = ""
    if add_plan is not None:
        overlay, fetches, cleanup = add_plan
        follow = _compose_insert_override(follow, overlay)
    lan_cache_to = _compose_lan_cache_to(paths, [service]) if do_build else []
    return _skopeo_follow_or_cleanup(
        lan,
        quiet=quiet,
        follow=follow,
        fetches=fetches,
        cleanup=cleanup,
        push_after=lan_cache_to or None,
    )


_DOCKERFILE_FROM = re.compile(
    r"^\s*FROM\s+(?:--platform=\S+\s+)?(\S+)(?:\s+AS\s+\S+)?\s*$",
    re.I,
)
_DOCKERFILE_COPY_FROM = re.compile(
    r"^\s*(?:COPY|ADD)\b(?:\s+\S+)*?\s--from=(\S+)",
    re.I,
)
_DOCKERFILE_RUN = re.compile(r"^\s*RUN\b", re.I)
_DOCKERFILE_MOUNT = re.compile(r"--mount=(\S+)", re.I)
_DOCKER_BUILD_VALUE_FLAGS = frozenset(
    {
        "-f",
        "--file",
        "-t",
        "--tag",
        "--target",
        "--build-arg",
        "--platform",
        "-m",
        "--memory",
        "--network",
        "--label",
        "--add-host",
        "--iidfile",
        "--cache-from",
        "--cache-to",
        "--secret",
        "--ssh",
        "--build-context",
        "--progress",
        "--output",
        "-o",
        "--shm-size",
        "--ulimit",
        "--cgroup-parent",
        "--metadata-file",
        "--cpu-shares",
        "--cpuset-cpus",
        "--isolation",
        "--security-opt",
        "--builder",
        "--allow",
        "--attest",
        "--sbom",
        "--provenance",
        "--annotation",
    }
)


def dockerfile_from_images(path: Path, build_args: dict[str, str] | None = None) -> list[str]:
    """Image refs in Dockerfile ``FROM`` / ``COPY --from=`` / ``RUN --mount=from=``.

    Skip scratch and interpolations that still have no value after ARG /
    ``${VAR:-default}`` / ``--build-arg`` substitution.
    """
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return []
    return dockerfile_images_from_text(text, build_args)


def dockerfile_images_from_text(text: str, build_args: dict[str, str] | None = None) -> list[str]:
    """Same as ``dockerfile_from_images`` for already-loaded Dockerfile text."""
    declared = dict(build_args or {})
    images: list[str] = []
    seen: set[str] = set()
    for raw in str(text or "").splitlines():
        line = raw.split("#", 1)[0]
        arg_match = _ARG_DECL.match(line)
        if arg_match:
            name = arg_match.group(1)
            if name in declared:
                continue
            default = arg_match.group(2)
            if default is None:
                continue
            declared[name] = default.strip().strip("'\"")
            continue
        candidates: list[str] = []
        match = _DOCKERFILE_FROM.match(line) or _DOCKERFILE_COPY_FROM.search(line)
        if match:
            candidates.append(match.group(1).strip().strip("'\""))
        if _DOCKERFILE_RUN.match(line):
            for mount in _DOCKERFILE_MOUNT.finditer(line):
                for part in mount.group(1).split(","):
                    key, sep, val = part.partition("=")
                    if not sep or key.strip().lower() != "from":
                        continue
                    text_val = val.strip().strip("'\"")
                    if text_val:
                        candidates.append(text_val)
        for raw_image in candidates:
            image = expand_image_vars(raw_image, declared)
            if not image or image.lower() == "scratch":
                continue
            if image in seen:
                continue
            seen.add(image)
            images.append(image)
    return images


_DOCKERFILE_ADD = re.compile(r"^\s*ADD\b(.*)$", re.I)
_ADD_HTTP_SCHEMES = ("http://", "https://", "ftp://", "ftps://")
_ADD_VALUE_FLAGS = frozenset(
    {"--checksum", "--chown", "--chmod", "--keep-git-dir", "--exclude"}
)
_ADD_DROP_FLAGS = frozenset({"--checksum", "--keep-git-dir"})


def _dockerfile_logical_lines(text: str) -> list[str]:
    lines: list[str] = []
    buf = ""
    for raw in str(text or "").splitlines():
        stripped = raw.rstrip()
        if stripped.endswith("\\") and not stripped.lstrip().startswith("#"):
            buf += stripped[:-1] + " "
            continue
        lines.append(buf + raw)
        buf = ""
    if buf:
        lines.append(buf.rstrip())
    return lines


def _is_http_add_url(token: str) -> bool:
    text = str(token or "").strip().strip("'\"")
    lower = text.lower()
    if not lower.startswith(_ADD_HTTP_SCHEMES):
        return False
    path = (urlparse(text).path or "").lower()
    if path.endswith(".git") or lower.rstrip("/").endswith(".git"):
        return False
    return True


def _add_url_filename(url: str) -> str:
    path = unquote(urlparse(str(url) or "").path or "")
    name = Path(path).name
    if not name or name in {".", ".."}:
        return "download"
    return name.replace("\x00", "")[:180]


def _parse_add_instruction(line: str) -> tuple[list[str], list[str], str] | None:
    match = _DOCKERFILE_ADD.match(str(line or "").split("#", 1)[0].strip())
    if not match:
        return None
    rest = match.group(1).strip()
    if not rest:
        return None
    if rest.startswith("["):
        try:
            items = json.loads(rest)
        except json.JSONDecodeError:
            return None
        if not isinstance(items, list) or len(items) < 2:
            return None
        sources = [str(item).strip() for item in items[:-1] if str(item).strip()]
        dest = str(items[-1]).strip()
        if not sources or not dest:
            return None
        return [], sources, dest
    try:
        tokens = shlex.split(rest, posix=True)
    except ValueError:
        return None
    flags: list[str] = []
    index = 0
    while index < len(tokens):
        tok = str(tokens[index])
        if not tok.startswith("--"):
            break
        key = tok.split("=", 1)[0].lower()
        if key.startswith("--from"):
            return None
        flags.append(tok)
        index += 1
        if "=" not in tok and key in _ADD_VALUE_FLAGS and index < len(tokens):
            flags.append(str(tokens[index]))
            index += 1
    positional = [str(item) for item in tokens[index:] if str(item)]
    if len(positional) < 2:
        return None
    return flags, positional[:-1], positional[-1]


def _copy_flags_from_add(flags: list[str]) -> list[str]:
    kept: list[str] = []
    skip_value = False
    for flag in flags:
        if skip_value:
            skip_value = False
            continue
        key = str(flag).split("=", 1)[0].lower()
        if key in _ADD_DROP_FLAGS:
            if "=" not in str(flag):
                skip_value = True
            continue
        kept.append(flag)
    return kept


def rewrite_dockerfile_lan_add(
    path: Path, build_args: dict[str, str] | None = None
) -> tuple[str, list[tuple[str, str, str]]]:
    """Rewrite LAN ``ADD http(s)|ftp(s)://`` and ``RUN wget`` / ``RUN curl``
    (including ``&&`` / ``;`` chains and ``sh -c`` / ``bash -lc``) of those URLs
    into ``COPY --from=jarvisaddN``.

    Returns rewritten text and ``(url, context, filename)`` fetches. Unchanged
    text and an empty list when there is no on-link RFC1918 fetch.
    """
    try:
        original = path.read_text(encoding="utf-8")
    except OSError:
        return "", []
    return rewrite_dockerfile_lan_add_text(original, build_args)


_RUN_LINE = re.compile(r"^(\s*RUN)((?:\s+--\S+)*)\s+(\S.*)$", re.I | re.S)
_RUN_PIPE_SHELLS = frozenset({"sh", "bash", "ash", "dash"})
_WGET_OUTPUT_FLAGS = frozenset({"-O", "--output-document"})
_CURL_OUTPUT_FLAGS = frozenset({"-o", "--output"})
_CURL_REMOTE_FLAGS = frozenset({"-O", "--remote-name"})


def _run_fetch_url_dest(
    argv: list[str], declared: dict[str, str]
) -> tuple[str, str] | None:
    """Return ``(url, dest)`` for a wget/curl argv. dest ``-`` means stdout."""
    if not argv:
        return None
    stem = _tool_basename(argv[0]).lower().removesuffix(".exe")
    if stem not in {"wget", "curl"}:
        return None
    dest = ""
    urls: list[str] = []
    index = 1
    while index < len(argv):
        tok = str(argv[index])
        index += 1
        if stem == "wget" and tok in _WGET_OUTPUT_FLAGS:
            if index >= len(argv):
                return None
            dest = str(argv[index])
            index += 1
            continue
        if stem == "wget" and tok.startswith("--output-document="):
            dest = tok.split("=", 1)[1]
            continue
        if stem == "curl" and tok in _CURL_OUTPUT_FLAGS:
            if index >= len(argv):
                return None
            dest = str(argv[index])
            index += 1
            continue
        if stem == "curl" and tok.startswith("--output="):
            dest = tok.split("=", 1)[1]
            continue
        if stem == "curl" and tok in _CURL_REMOTE_FLAGS:
            continue
        if tok.startswith("-") and not tok.startswith("--") and len(tok) > 2:
            cluster = tok[1:]
            if stem == "wget" and "O" in cluster:
                if cluster.endswith("O-") or tok.endswith("O-"):
                    dest = "-"
                    continue
                if cluster.endswith("O"):
                    if index >= len(argv):
                        return None
                    dest = str(argv[index])
                    index += 1
                    continue
            if stem == "curl" and cluster.endswith("o") and "o" in cluster:
                if index >= len(argv):
                    return None
                dest = str(argv[index])
                index += 1
                continue
            continue
        if tok.startswith("-"):
            continue
        expanded = expand_image_vars(tok.strip("'\""), declared)
        if expanded and _is_http_add_url(expanded):
            urls.append(expanded)
    if len(urls) != 1:
        return None
    url = urls[0]
    if not _lan_bind_for_http_target(url):
        return None
    if dest == "-":
        return url, "-"
    if dest:
        expanded_dest = expand_image_vars(dest.strip("'\""), declared)
        return url, expanded_dest or dest
    return url, _add_url_filename(url)


_GLUED_SHELL_OP = re.compile(r"(&&|\|\||\|&|;|\|)")


def _run_shell_argv(body: str) -> list[str] | None:
    """Tokenize a shell RUN body, splitting glued ``&&`` / ``;`` / ``|``."""
    try:
        tokens = shlex.split(body, posix=True)
    except ValueError:
        return None
    out: list[str] = []
    for tok in tokens:
        if any(ch.isspace() for ch in tok):
            out.append(tok)
            continue
        out.extend(part for part in _GLUED_SHELL_OP.split(tok) if part)
    return out


def _split_run_chain(argv: list[str]) -> tuple[list[list[str]], list[str]] | None:
    """Split a shell RUN argv on ``&&`` / ``;``. Skip ``||`` / background ``&``."""
    if any(tok in {"||", "&", "|&"} for tok in argv):
        return None
    segments: list[list[str]] = []
    ops: list[str] = []
    current: list[str] = []
    for tok in argv:
        if tok in {"&&", ";"}:
            if not current:
                return None
            segments.append(current)
            ops.append(tok)
            current = []
            continue
        current.append(tok)
    if not current:
        return None
    segments.append(current)
    if len(ops) != len(segments) - 1:
        return None
    return segments, ops


def _run_segment_pipe(argv: list[str]) -> tuple[list[str], str] | None:
    if argv.count("|") == 1:
        cut = argv.index("|")
        right = argv[cut + 1 :]
        if (
            len(right) == 1
            and _tool_basename(right[0]).lower().removesuffix(".exe") in _RUN_PIPE_SHELLS
        ):
            return argv[:cut], _tool_basename(right[0]).lower().removesuffix(".exe")
        return None
    if "|" in argv:
        return None
    return argv, ""


def _run_fetch_copy_lines(
    argv: list[str],
    declared: dict[str, str],
    fetches: list[tuple[str, str, str]],
    indent: str,
) -> list[str] | None:
    parsed = _run_segment_pipe(argv)
    if parsed is None:
        return None
    argv, pipe_shell = parsed
    spec = _run_fetch_url_dest(argv, declared)
    if spec is None:
        return None
    url, dest = spec
    if dest == "-" and not pipe_shell:
        return None
    if dest == "-":
        dest = ""
    if pipe_shell and dest and dest != _add_url_filename(url):
        return None
    filename = _add_url_filename(url)
    context = f"jarvisadd{len(fetches)}"
    fetches.append((url, context, filename))
    if pipe_shell:
        staged = f"/tmp/{context}-{filename}"
        return [
            f"{indent}COPY --from={context} {filename} {staged}",
            f"{indent}RUN {pipe_shell} {staged}",
        ]
    copy_dest = dest or filename
    return [f"{indent}COPY --from={context} {filename} {copy_dest}"]


def _unwrap_run_shell_c(argv: list[str]) -> list[str] | None:
    """Return tokens of ``sh -c SCRIPT`` / ``bash -lc SCRIPT`` when that is the whole argv."""
    if len(argv) < 3:
        return None
    stem = _tool_basename(argv[0]).lower().removesuffix(".exe")
    if stem not in _RUN_PIPE_SHELLS:
        return None
    c_at: int | None = None
    for index, tok in enumerate(argv[1:], 1):
        if tok == "-c":
            c_at = index
            break
        if (
            index == 1
            and tok.startswith("-")
            and not tok.startswith("--")
            and "c" in tok[1:]
            and all(ch in {"c", "i", "l", "s"} for ch in tok[1:])
        ):
            c_at = index
            break
        if tok.startswith("-") and not tok.startswith("--"):
            continue
        return None
    if c_at is None or c_at + 2 != len(argv):
        return None
    return _run_shell_argv(argv[c_at + 1])


def _rewrite_lan_run_fetch(
    line: str, declared: dict[str, str], fetches: list[tuple[str, str, str]]
) -> list[str] | None:
    """Replace LAN ``RUN wget`` / ``RUN curl`` (including ``&&`` / ``;`` chains and ``sh -c``) with ``COPY --from=``."""
    match = _RUN_LINE.match(str(line or ""))
    if match is None:
        return None
    indent = re.match(r"^(\s*)", str(line or "")).group(1)
    run_flags = match.group(2) or ""
    body = match.group(3).strip()
    argv: list[str]
    if body.startswith("["):
        try:
            loaded = json.loads(body)
        except json.JSONDecodeError:
            return None
        if not isinstance(loaded, list) or not all(isinstance(item, str) for item in loaded):
            return None
        argv = list(loaded)
    else:
        parsed = _run_shell_argv(body)
        if parsed is None:
            return None
        argv = parsed
    unwrapped = _unwrap_run_shell_c(argv)
    if unwrapped is not None:
        argv = unwrapped
    split = _split_run_chain(argv)
    if split is None:
        return None
    segments, ops = split
    trial = list(fetches)
    copies: list[list[str] | None] = []
    for seg in segments:
        if not seg:
            return None
        if _run_segment_pipe(seg) is None:
            return None
        copies.append(_run_fetch_copy_lines(seg, declared, trial, indent))
    if not any(item is not None for item in copies):
        return None
    fetches.extend(trial[len(fetches) :])
    out: list[str] = []
    run_buf: list[str] = []
    run_ops: list[str] = []

    def flush_run() -> None:
        if not run_buf:
            return
        joined = run_buf[0]
        for op, piece in zip(run_ops, run_buf[1:], strict=True):
            joined = f"{joined} {op} {piece}"
        out.append(f"{indent}RUN{run_flags} {joined}")
        run_buf.clear()
        run_ops.clear()

    for index, (seg, copy_lines) in enumerate(zip(segments, copies, strict=True)):
        if copy_lines is not None:
            flush_run()
            out.extend(copy_lines)
            continue
        if run_buf:
            run_ops.append(ops[index - 1])
        run_buf.append(shlex.join(seg))
    flush_run()
    return out or None


def rewrite_dockerfile_lan_add_text(
    original: str, build_args: dict[str, str] | None = None
) -> tuple[str, list[tuple[str, str, str]]]:
    declared = dict(build_args or {})
    fetches: list[tuple[str, str, str]] = []
    out: list[str] = []
    changed = False
    for raw in _dockerfile_logical_lines(original):
        line = raw.split("#", 1)[0]
        arg_match = _ARG_DECL.match(line)
        if arg_match:
            name = arg_match.group(1)
            if name not in declared:
                default = arg_match.group(2)
                if default is not None:
                    declared[name] = default.strip().strip("'\"")
            out.append(raw)
            continue
        parsed = _parse_add_instruction(line)
        if parsed is None:
            run_lines = _rewrite_lan_run_fetch(raw, declared, fetches)
            if run_lines is None:
                out.append(raw)
                continue
            changed = True
            out.extend(run_lines)
            continue
        flags, sources, dest = parsed
        lan_sources: list[tuple[str, str]] = []
        public_sources: list[str] = []
        for source in sources:
            expanded = expand_image_vars(source, declared)
            if expanded is None:
                public_sources.append(source)
                continue
            if not _is_http_add_url(expanded):
                public_sources.append(source)
                continue
            if not _lan_bind_for_http_target(expanded):
                public_sources.append(source)
                continue
            lan_sources.append((expanded, _add_url_filename(expanded)))
        if not lan_sources:
            out.append(raw)
            continue
        changed = True
        copy_flags = _copy_flags_from_add(flags)
        for url, filename in lan_sources:
            context = f"jarvisadd{len(fetches)}"
            fetches.append((url, context, filename))
            pieces = ["COPY", f"--from={context}", *copy_flags, filename, dest]
            out.append(" ".join(pieces))
        if public_sources:
            pieces = ["ADD", *flags, *public_sources, dest]
            out.append(" ".join(pieces))
    if not changed:
        return original, []
    return "\n".join(out) + ("\n" if original.endswith("\n") else ""), fetches


def _materialize_lan_add(
    dockerfile: Path | None,
    build_args: dict[str, str] | None = None,
    *,
    root: Path | None = None,
    leaf: str = "",
    source_text: str = "",
) -> tuple[Path, list[tuple[str, str]], list[tuple[str, str]], str] | None:
    if source_text:
        rewritten, plan = rewrite_dockerfile_lan_add_text(source_text, build_args)
    elif dockerfile is not None:
        rewritten, plan = rewrite_dockerfile_lan_add(dockerfile, build_args)
    else:
        return None
    if not plan:
        return None
    created = False
    if root is None:
        root = Path(tempfile.mkdtemp(prefix="jarvis-lan-add-"))
        created = True
    dest = root / leaf if leaf else root
    try:
        dest.mkdir(parents=True, exist_ok=True)
        df = dest / "Dockerfile"
        df.write_text(rewritten, encoding="utf-8")
        fetches: list[tuple[str, str]] = []
        contexts: list[tuple[str, str]] = []
        for url, context, filename in plan:
            ctx_dir = dest / context
            ctx_dir.mkdir(parents=True, exist_ok=True)
            fetches.append((url, str(ctx_dir / filename)))
            contexts.append((context, str(ctx_dir)))
        return df, fetches, contexts, str(root)
    except OSError:
        if created:
            shutil.rmtree(root, ignore_errors=True)
        return None


def _dump_compose_overlay(services: dict[str, dict]) -> str:
    prepared: dict[str, dict] = {}
    hand_roll = False
    for name, spec in services.items():
        build = dict(spec.get("build") or {})
        cache_tags = [str(item) for item in (build.pop("lan_cache_to", None) or []) if item]
        reset_inline = bool(build.pop("reset_dockerfile_inline", False))
        if cache_tags or reset_inline:
            hand_roll = True
        prepared[name] = {
            "build": build,
            "cache_tags": cache_tags,
            "reset_inline": reset_inline,
        }
    if not hand_roll:
        payload = {"services": {name: {"build": spec["build"]} for name, spec in prepared.items()}}
        try:
            import yaml

            return yaml.safe_dump(payload, sort_keys=False)
        except ImportError:
            return json.dumps(payload, indent=2)
    lines = ["services:"]
    for name, spec in prepared.items():
        key = name if re.fullmatch(r"[A-Za-z0-9._-]+", name or "") else json.dumps(name)
        lines.append(f"  {key}:")
        lines.append("    build:")
        build = spec["build"]
        if spec["reset_inline"]:
            lines.append("      dockerfile_inline: !reset")
        dockerfile = build.get("dockerfile")
        if dockerfile:
            lines.append(f"      dockerfile: {json.dumps(str(dockerfile))}")
        extra = build.get("additional_contexts") or {}
        if extra:
            lines.append("      additional_contexts:")
            for ctx, directory in extra.items():
                ck = str(ctx)
                ck = ck if re.fullmatch(r"[A-Za-z0-9._-]+", ck) else json.dumps(ck)
                lines.append(f"        {ck}: {json.dumps(str(directory))}")
        if spec["cache_tags"]:
            lines.append("      cache_to: !override")
            lines.append("        - type=inline")
            lines.append("      tags:")
            for tag in spec["cache_tags"]:
                lines.append(f"        - {json.dumps(str(tag))}")
    return "\n".join(lines) + "\n"


def _compose_materialize_lan_add(
    chosen: dict[str, Path],
    file_args: dict[str, dict[str, str]],
    cli_args: dict[str, str],
    cache_to: dict[str, list[str]] | None = None,
    inlines: dict[str, str] | None = None,
) -> tuple[str, list[tuple[str, str]], str] | None:
    """Compose overlay whose services use rewritten ADD Dockerfiles + extra contexts."""
    inlines = inlines or {}
    if not chosen and not inlines:
        return None
    cache_to = cache_to or {}
    root = Path(tempfile.mkdtemp(prefix="jarvis-lan-add-"))
    fetches: list[tuple[str, str]] = []
    services: dict[str, dict] = {}
    names = list(dict.fromkeys([*chosen, *inlines]))
    for index, name in enumerate(names):
        leaf = re.sub(r"[^A-Za-z0-9._-]+", "_", name) or f"svc{index}"
        text = inlines.get(name, "")
        spec = _materialize_lan_add(
            chosen.get(name),
            {**file_args.get(name, {}), **cli_args},
            root=root,
            leaf=leaf,
            source_text=text,
        )
        lan_to = _lan_tagged_refs(cache_to.get(name, []))
        if spec is None and not lan_to:
            continue
        build: dict[str, object] = {}
        if spec is not None:
            df, more, contexts, _cleanup = spec
            fetches.extend(more)
            build["dockerfile"] = str(df)
            if contexts:
                build["additional_contexts"] = {ctx: directory for ctx, directory in contexts}
            if text:
                build["reset_dockerfile_inline"] = True
        if lan_to:
            build["lan_cache_to"] = lan_to
        services[name] = {"build": build}
    if not services:
        shutil.rmtree(root, ignore_errors=True)
        return None
    overlay = root / "compose.jarvis-lan.yaml"
    overlay.write_text(_dump_compose_overlay(services), encoding="utf-8")
    return str(overlay), fetches, str(root)


def _compose_lan_cache_to(paths: list[Path], names: list[str] | None) -> list[str]:
    images: list[str] = []
    seen: set[str] = set()
    for path in paths:
        mapping = compose_service_cache_to_images(path)
        wanted = names if names else list(mapping)
        for name in wanted:
            for image in mapping.get(name, []):
                if image in seen:
                    continue
                seen.add(image)
                images.append(image)
    return _lan_tagged_refs(images)


def _compose_lan_add_for_build(
    paths: list[Path],
    services: list[str],
    *,
    no_deps: bool,
    build_services: list[str] | None = None,
    cli_args: dict[str, str] | None = None,
) -> tuple[str, list[tuple[str, str]], str] | None:
    dockerfiles: dict[str, Path] = {}
    file_args: dict[str, dict[str, str]] = {}
    deps: dict[str, list[str]] = {}
    cache_to: dict[str, list[str]] = {}
    inlines: dict[str, str] = {}
    for path in paths:
        dockerfiles.update(compose_service_dockerfiles(path))
        inlines.update(compose_service_inline_dockerfiles(path))
        for name, args in compose_service_build_args(path).items():
            file_args.setdefault(name, {}).update(args)
        for name, extras in compose_service_cache_to_images(path).items():
            cache_to.setdefault(name, [])
            for image in extras:
                if image not in cache_to[name]:
                    cache_to[name].append(image)
        for name, kids in compose_service_depends(path).items():
            deps.setdefault(name, [])
            for kid in kids:
                if kid not in deps[name]:
                    deps[name].append(kid)
    wanted = list(services)
    if wanted and not no_deps:
        wanted = _compose_service_closure(deps, wanted)
    build_wanted = list(build_services) if build_services is not None else wanted
    if build_wanted:
        chosen = {name: dockerfiles[name] for name in build_wanted if name in dockerfiles}
        inlines = {name: inlines[name] for name in build_wanted if name in inlines}
        cache_to = {name: cache_to[name] for name in build_wanted if name in cache_to}
    else:
        chosen = dict(dockerfiles)
    return _compose_materialize_lan_add(
        chosen, file_args, cli_args or {}, cache_to=cache_to, inlines=inlines
    )


def _compose_insert_override(parts: list[str], overlay: str) -> list[str]:
    out = list(parts)
    insert_at: int | None = None
    index = 0
    while index < len(out):
        text = str(out[index])
        if text in {"-f", "--file"} and index + 1 < len(out):
            insert_at = index + 2
            index += 2
            continue
        if text.startswith("--file="):
            insert_at = index + 1
            index += 1
            continue
        index += 1
    extra = ["-f", overlay]
    if insert_at is None:
        insert_at = 1
        for i, item in enumerate(out):
            if _tool_basename(item) in {"compose", "docker-compose", "docker_compose"}:
                insert_at = i + 1
                break
    return out[:insert_at] + extra + out[insert_at:]


def _skopeo_follow_or_cleanup(
    lan: list[str],
    *,
    quiet: bool,
    follow: list[str],
    fetches: list[tuple[str, str]],
    cleanup: str,
    push_after: list[str] | None = None,
    then: list[str] | None = None,
) -> list[str] | None:
    argv = skopeo_copy_lan_images_argv(
        lan,
        quiet=quiet,
        follow=follow,
        push_after=push_after,
        then=then,
        fetches=fetches,
        cleanup=cleanup or None,
    )
    if argv is None and cleanup:
        shutil.rmtree(cleanup, ignore_errors=True)
    return argv


def _docker_build_with_add_contexts(
    parts: list[str], dockerfile: str, contexts: list[tuple[str, str]]
) -> list[str]:
    out: list[str] = []
    skip_value = False
    inserted = False
    for item in parts:
        if skip_value:
            skip_value = False
            continue
        text = str(item)
        if text in {"-f", "--file"}:
            skip_value = True
            continue
        if text.startswith("--file="):
            continue
        out.append(text)
        if not inserted and text == "build":
            out.extend(["-f", dockerfile])
            for name, directory in contexts:
                out.extend(["--build-context", f"{name}={directory}"])
            inserted = True
    if not inserted:
        out.extend(["-f", dockerfile])
        for name, directory in contexts:
            out.extend(["--build-context", f"{name}={directory}"])
    return out


def _docker_build_without_pull(parts: list[str]) -> list[str]:
    out: list[str] = []
    inserted = False
    for item in parts:
        text = str(item)
        if text in {"--pull", "--pull=true"} or text.startswith("--pull="):
            continue
        out.append(text)
        if not inserted and text == "build":
            out.append("--pull=false")
            inserted = True
    if not inserted:
        return parts
    return out


def _docker_build_tags(parts: list[str]) -> list[str]:
    tags: list[str] = []
    index = 0
    while index < len(parts):
        text = str(parts[index] or "").strip().strip("'\"")
        index += 1
        if text in {"-t", "--tag"}:
            if index >= len(parts):
                break
            tags.append(str(parts[index] or "").strip().strip("'\""))
            index += 1
            continue
        if text.startswith("--tag="):
            tags.append(text.split("=", 1)[1].strip().strip("'\""))
            continue
        if text.startswith("--output=") or text.startswith("-o="):
            value = text.split("=", 1)[1]
        elif text in {"-o", "--output"}:
            if index >= len(parts):
                break
            value = str(parts[index] or "")
            index += 1
        else:
            continue
        for piece in value.split(","):
            piece = piece.strip()
            if piece.startswith("name="):
                tags.append(piece.split("=", 1)[1].strip())
    return [tag for tag in tags if tag]


def _docker_build_args(parts: list[str]) -> dict[str, str]:
    args: dict[str, str] = {}
    index = 0
    while index < len(parts):
        text = str(parts[index] or "").strip()
        index += 1
        raw = ""
        if text in {"--build-arg"}:
            if index >= len(parts):
                break
            raw = str(parts[index] or "").strip().strip("'\"")
            index += 1
        elif text.startswith("--build-arg="):
            raw = text.split("=", 1)[1].strip().strip("'\"")
        else:
            continue
        if "=" not in raw:
            key = raw.strip()
            if key and key in os.environ:
                args[key] = os.environ[key]
            continue
        key, _, value = raw.partition("=")
        key = key.strip()
        if key:
            args[key] = value
    return args


def _docker_build_context_images(parts: list[str]) -> list[str]:
    """Image refs from ``--build-context name=docker-image://...``."""
    out: list[str] = []
    seen: set[str] = set()
    index = 0
    while index < len(parts):
        text = str(parts[index] or "").strip()
        index += 1
        raw = ""
        if text in {"--build-context"}:
            if index >= len(parts):
                break
            raw = str(parts[index] or "").strip().strip("'\"")
            index += 1
        elif text.startswith("--build-context="):
            raw = text.split("=", 1)[1].strip().strip("'\"")
        else:
            continue
        if "=" not in raw:
            continue
        _, _, rhs = raw.partition("=")
        image = _image_from_named_context(rhs)
        if not image or image in seen:
            continue
        seen.add(image)
        out.append(image)
    return out


def _docker_build_cache_images(parts: list[str]) -> list[str]:
    """Image refs from ``--cache-from IMAGE`` / ``type=registry,ref=IMAGE``."""
    return _docker_build_cache_flag_images(parts, "--cache-from")


def _docker_build_cache_to_images(parts: list[str]) -> list[str]:
    """Image refs from ``--cache-to type=registry,ref=IMAGE``."""
    return _docker_build_cache_flag_images(parts, "--cache-to")


def _docker_build_cache_flag_images(parts: list[str], flag: str) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    index = 0
    equals = f"{flag}="
    while index < len(parts):
        text = str(parts[index] or "").strip()
        index += 1
        raw = ""
        if text == flag:
            if index >= len(parts):
                break
            raw = str(parts[index] or "").strip().strip("'\"")
            index += 1
        elif text.startswith(equals):
            raw = text.split("=", 1)[1].strip().strip("'\"")
        else:
            continue
        image = _image_from_cache_source(raw)
        if not image or image in seen:
            continue
        seen.add(image)
        out.append(image)
    return out


def _lan_tagged_refs(images: list[str]) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    for image in images:
        if not image or not _lan_bind_ip_for_host(docker_registry_host_from_image(image)):
            continue
        tagged = _docker_image_with_tag(image)
        if tagged in seen:
            continue
        seen.add(tagged)
        out.append(tagged)
    return out


def _docker_build_rewrite_lan_cache_to(
    parts: list[str], lan_refs: list[str], *, add_tags: bool = True
) -> list[str]:
    """Drop LAN ``--cache-to type=registry``, add ``type=inline`` and ``-t`` cache tags."""
    wanted = {_docker_image_with_tag(item) for item in lan_refs if item}
    if not wanted:
        return parts
    out: list[str] = []
    index = 0
    dropped = False
    has_inline = False
    while index < len(parts):
        text = str(parts[index])
        index += 1
        raw: str | None = None
        joined = False
        if text == "--cache-to":
            if index >= len(parts):
                break
            raw = str(parts[index] or "")
            index += 1
        elif text.startswith("--cache-to="):
            raw = text.split("=", 1)[1]
            joined = True
        if raw is None:
            out.append(text)
            continue
        stripped = raw.strip().strip("'\"")
        lowered = stripped.lower()
        image = _image_from_cache_source(stripped)
        if "type=inline" in lowered.replace(" ", ""):
            has_inline = True
            if joined:
                out.append(text)
            else:
                out.extend(["--cache-to", raw])
            continue
        if image and _docker_image_with_tag(image) in wanted:
            dropped = True
            continue
        if joined:
            out.append(text)
        else:
            out.extend(["--cache-to", raw])
    extra_tags = (
        [item for item in lan_refs if item not in set(_docker_build_tags(out))] if add_tags else []
    )
    if not dropped and not extra_tags:
        return out
    rebuilt: list[str] = []
    placed = False
    for item in out:
        rebuilt.append(item)
        if placed or item != "build":
            continue
        placed = True
        if dropped and not has_inline:
            rebuilt.extend(["--cache-to", "type=inline"])
        for tag in extra_tags:
            rebuilt.extend(["-t", tag])
    if not placed:
        if dropped and not has_inline:
            rebuilt.extend(["--cache-to", "type=inline"])
        for tag in extra_tags:
            rebuilt.extend(["-t", tag])
    return rebuilt


def _docker_build_wants_push(parts: list[str]) -> bool:
    skip = False
    for item in parts:
        if skip:
            skip = False
            text = str(item)
            if "type=registry" in text or text.startswith("type=registry"):
                return True
            continue
        text = str(item)
        if text == "--push":
            return True
        if text.startswith("--output=") or text.startswith("-o="):
            if "type=registry" in text:
                return True
            continue
        if text in {"-o", "--output"}:
            skip = True
    return False


def _docker_build_for_local_load(parts: list[str], *, buildx: bool) -> list[str]:
    out: list[str] = []
    pending_output = ""
    has_load = False
    inserted = False
    for item in parts:
        text = str(item)
        if pending_output:
            flag = pending_output
            pending_output = ""
            if "type=registry" in text:
                continue
            out.extend([flag, text])
            continue
        if text == "--push":
            continue
        if text.startswith("--output=") or text.startswith("-o="):
            if "type=registry" in text:
                continue
            out.append(text)
            continue
        if text in {"-o", "--output"}:
            pending_output = text
            continue
        if text in {"--pull", "--pull=true"} or text.startswith("--pull="):
            continue
        if text == "--load":
            has_load = True
        out.append(text)
        if not inserted and text == "build":
            out.append("--pull=false")
            inserted = True
    if buildx and not has_load:
        rebuilt: list[str] = []
        placed = False
        for item in out:
            rebuilt.append(item)
            if not placed and item == "build":
                rebuilt.append("--load")
                placed = True
        return rebuilt
    return out


def _docker_build_spec(parts: list[str], cwd: str | None) -> tuple[Path, bool] | None:
    if not parts or _tool_basename(parts[0]) != "docker":
        return None
    rest = parts[1:]
    if rest and _tool_basename(rest[0]) == "image":
        rest = rest[1:]
    if rest and _tool_basename(rest[0]) == "buildx":
        rest = rest[1:]
    if not rest or rest[0] != "build":
        return None
    dockerfile = ""
    context = ""
    quiet = False
    index = 1
    while index < len(rest):
        text = str(rest[index] or "").strip().strip("'\"")
        index += 1
        if not text:
            continue
        if text in _DOCKER_PULL_QUIET:
            quiet = True
            continue
        if text.startswith("--file="):
            dockerfile = text.split("=", 1)[1].strip()
            continue
        if text in {"-f", "--file"}:
            if index >= len(rest):
                return None
            dockerfile = str(rest[index] or "").strip().strip("'\"")
            index += 1
            continue
        if text.startswith("--") and "=" in text:
            continue
        if text in _DOCKER_BUILD_VALUE_FLAGS:
            if index >= len(rest):
                return None
            index += 1
            continue
        if text.startswith("-"):
            continue
        if context:
            return None
        context = text
    if not context or context == "-" or "://" in context:
        return None
    root = Path(cwd or os.getcwd())
    ctx = Path(context)
    if not ctx.is_absolute():
        ctx = root / ctx
    if dockerfile:
        df = Path(dockerfile)
        if not df.is_absolute():
            df = root / df
    else:
        df = ctx / "Dockerfile"
    if not df.is_file():
        return None
    return df, quiet


def lan_bound_docker_build_from_parts(parts: list[str], cwd: str | None = None) -> list[str] | None:
    spec = _docker_build_spec(parts, cwd)
    if spec is None:
        return None
    dockerfile, quiet = spec
    lan = [
        image
        for image in dockerfile_from_images(dockerfile, _docker_build_args(parts))
        if _lan_bind_ip_for_host(docker_registry_host_from_image(image))
    ]
    seen = set(lan)
    for image in (*_docker_build_context_images(parts), *_docker_build_cache_images(parts)):
        if image in seen:
            continue
        if not _lan_bind_ip_for_host(docker_registry_host_from_image(image)):
            continue
        seen.add(image)
        lan.append(image)
    tags = _docker_build_tags(parts)
    lan_tags = [
        tag
        for tag in tags
        if _lan_bind_ip_for_host(docker_registry_host_from_image(tag))
    ]
    lan_cache_to = _lan_tagged_refs(_docker_build_cache_to_images(parts))
    wants_push = _docker_build_wants_push(parts)
    docker = shutil.which("docker") or shutil.which("docker.exe")
    if not docker:
        return None
    add_spec = _materialize_lan_add(dockerfile, _docker_build_args(parts))
    if not lan and not (wants_push and lan_tags) and add_spec is None and not lan_cache_to:
        return None
    follow_src = [docker, *parts[1:]]
    buildx = any(_tool_basename(item) == "buildx" for item in parts[1:3])
    fetches: list[tuple[str, str]] = []
    cleanup = ""
    if lan_cache_to or (wants_push and lan_tags):
        follow = _docker_build_for_local_load(follow_src, buildx=buildx)
        push_after = list(dict.fromkeys([*lan_tags, *lan_cache_to]))
    else:
        follow = _docker_build_without_pull(follow_src)
        push_after = None
    if lan_cache_to:
        follow = _docker_build_rewrite_lan_cache_to(follow, lan_cache_to)
    if add_spec is not None:
        rewritten, fetches, contexts, cleanup = add_spec
        follow = _docker_build_with_add_contexts(follow, str(rewritten), contexts)
    if not lan and not fetches and not push_after:
        if cleanup:
            shutil.rmtree(cleanup, ignore_errors=True)
        return None
    argv = skopeo_copy_lan_images_argv(
        lan,
        quiet=quiet,
        follow=follow,
        push_after=push_after,
        fetches=fetches,
        cleanup=cleanup or None,
    )
    if argv is None and cleanup:
        shutil.rmtree(cleanup, ignore_errors=True)
    return argv


def lan_bound_docker_build_argv(command: str, cwd: str | None = None) -> list[str] | None:
    """``docker build`` / ``docker buildx build`` of a LAN ``FROM`` or ``ADD`` URL.

    Dockerd / BuildKit cannot source-bind. Skopeo loads LAN bases through the
    loopback proxy, then ``docker build --pull=false`` / ``docker buildx build --pull=false``
    uses the local daemon copies. ``ADD http(s)|ftp(s)://`` of an on-link RFC1918
    URL is prefetched into ``--build-context`` and rewritten to ``COPY --from=``.
    ``--push`` of a LAN tag becomes ``--load`` plus skopeo upload. ``--cache-to
    type=registry,ref=LAN`` becomes ``type=inline`` plus ``-t`` of that ref and
    skopeo upload. Skip pipes, stdin context, interpolations, and missing skopeo
    when a LAN image copy is required.
    """
    text = str(command or "").strip()
    if not text or _UNSAFE_SHELL.search(text):
        return None
    try:
        parts = shlex.split(text, posix=os.name != "nt")
    except ValueError:
        return None
    return lan_bound_docker_build_from_parts(parts, cwd=cwd)


_BAKE_FILENAMES = (
    "docker-bake.json",
    "docker-bake.hcl",
    "docker-bake.override.json",
    "docker-bake.override.hcl",
)
_BAKE_VALUE_FLAGS = frozenset(
    {
        "-f",
        "--file",
        "--builder",
        "--set",
        "--progress",
        "--metadata-file",
        "--allow",
        "--sbom",
        "--provenance",
        "--attest",
    }
)
_HCL_DOCKERFILE = re.compile(r"dockerfile\s*=\s*\"([^\"]+)\"", re.I)
_HCL_DOCKERFILE_INLINE = re.compile(
    r"dockerfile-inline\s*=\s*\"((?:\\.|[^\"])*)\"", re.I
)
_HCL_HEREDOC_INLINE = re.compile(
    r"dockerfile-inline\s*=\s*<<([-~]?)([A-Za-z_][A-Za-z0-9_]*)\s*\n",
    re.I,
)
_HCL_CONTEXT = re.compile(r"context\s*=\s*\"([^\"]+)\"", re.I)
_HCL_TAGS = re.compile(r"tags\s*=\s*\[([^\]]*)\]", re.I)
_HCL_ARG_ITEM = re.compile(r"([A-Za-z_][A-Za-z0-9_]*)\s*=\s*\"([^\"]*)\"")
_HCL_TARGET_OPEN = re.compile(r"target\s+\"([^\"]+)\"\s*\{", re.I)


def _hcl_named_targets(text: str) -> list[tuple[str, str]]:
    blocks: list[tuple[str, str]] = []
    for match in _HCL_TARGET_OPEN.finditer(text):
        name = match.group(1).strip()
        start = match.end()
        depth = 1
        index = start
        while index < len(text) and depth:
            char = text[index]
            if char == "{":
                depth += 1
            elif char == "}":
                depth -= 1
            index += 1
        if depth == 0 and name:
            blocks.append((name, text[start : index - 1]))
    return blocks


def _hcl_target_blocks(text: str) -> list[str]:
    return [body for _, body in _hcl_named_targets(text)]


def _hcl_named_map(block: str, key: str) -> dict[str, str]:
    match = re.search(rf"{re.escape(key)}\s*=\s*\{{", block, re.I)
    if not match:
        return {}
    start = match.end()
    depth = 1
    index = start
    while index < len(block) and depth:
        char = block[index]
        if char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
        index += 1
    if depth != 0:
        return {}
    return {item.group(1): item.group(2) for item in _HCL_ARG_ITEM.finditer(block[start : index - 1])}


def _hcl_args(block: str) -> dict[str, str]:
    return _hcl_named_map(block, "args")


def _hcl_quoted_list(block: str, key: str) -> list[str]:
    match = re.search(rf"{re.escape(key)}\s*=\s*\[([^\]]*)\]", block, re.I)
    if not match:
        return []
    return [item.group(1) for item in re.finditer(r"\"([^\"]*)\"", match.group(1)) if item.group(1)]


def _hcl_dockerfile_inline(block: str) -> str | None:
    """Quoted ``dockerfile-inline = "…"`` or heredoc ``<<EOF`` / ``<<-EOF`` / ``<<~EOF``."""
    quoted = _HCL_DOCKERFILE_INLINE.search(block)
    if quoted:
        return (
            quoted.group(1)
            .replace("\\\\", "\0")
            .replace("\\n", "\n")
            .replace('\\"', '"')
            .replace("\0", "\\")
        )
    match = _HCL_HEREDOC_INLINE.search(block)
    if not match:
        return None
    strip, marker = match.group(1), match.group(2)
    lines: list[str] = []
    for raw in block[match.end() :].splitlines():
        if raw.strip() == marker:
            break
        if strip == "-":
            raw = raw.lstrip("\t")
        elif strip == "~":
            raw = raw.lstrip(" \t")
        lines.append(raw)
    if not lines:
        return ""
    return "\n".join(lines) + "\n"


def _bake_resolve_dockerfile(file_dir: Path, cwd: Path, context: str, dockerfile: str) -> Path | None:
    if "$" in context or "$" in dockerfile:
        return None
    ctx = Path(context or ".")
    df_name = dockerfile or "Dockerfile"
    df = Path(df_name)
    roots = []
    if ctx.is_absolute():
        roots.append(ctx)
    else:
        roots.extend([file_dir / ctx, cwd / ctx])
    for root in roots:
        candidate = df if df.is_absolute() else root / df_name
        if candidate.is_file():
            return candidate
    return None


def bake_file_dockerfiles_and_tags(
    path: Path, cwd: Path
) -> tuple[list[tuple[str, Path, dict[str, str], list[str], list[str]]], list[str], list[str], dict[str, str]]:
    """Named Dockerfiles (args, tags, cache-to refs), all tags, named-context images, inline texts."""
    suffix = path.suffix.lower()
    dockerfiles: list[tuple[str, Path, dict[str, str], list[str], list[str]]] = []
    tags: list[str] = []
    extra: list[str] = []
    inlines: dict[str, str] = {}
    seen_extra: set[str] = set()

    def _add_extra(images: list[str]) -> None:
        for image in images:
            if not image or image in seen_extra:
                continue
            seen_extra.add(image)
            extra.append(image)

    if suffix in {".yaml", ".yml"}:
        files = compose_service_dockerfiles(path)
        args = compose_service_build_args(path)
        images = compose_service_images(path)
        cache_to = compose_service_cache_to_images(path)
        for name, df in files.items():
            tgt_tags = [images[name]] if name in images else []
            dockerfiles.append(
                (str(name), df, dict(args.get(name, {})), tgt_tags, list(cache_to.get(name, [])))
            )
        inlines.update(compose_service_inline_dockerfiles(path))
        for name, text in inlines.items():
            tgt_tags = [images[name]] if name in images else []
            dockerfiles.append(
                (str(name), Path(), dict(args.get(name, {})), tgt_tags, list(cache_to.get(name, [])))
            )
        tags.extend(images.values())
        for extras in compose_service_context_images(path).values():
            _add_extra(extras)
        for extras in compose_service_cache_images(path).values():
            _add_extra(extras)
        return dockerfiles, tags, extra, inlines
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return [], [], [], {}
    file_dir = path.parent
    if suffix == ".json":
        import json

        try:
            payload = json.loads(text)
        except json.JSONDecodeError:
            return [], [], [], {}
        targets = payload.get("target") if isinstance(payload, dict) else None
        if not isinstance(targets, dict):
            return [], [], [], {}
        for name, spec in targets.items():
            if not isinstance(spec, dict):
                continue
            inline = str(spec.get("dockerfile-inline") or "").strip()
            context = str(spec.get("context") or ".").strip()
            dockerfile = str(spec.get("dockerfile") or "").strip()
            resolved = None if inline else _bake_resolve_dockerfile(file_dir, cwd, context, dockerfile)
            tgt_tags: list[str] = []
            raw_tags = spec.get("tags")
            if isinstance(raw_tags, list):
                tgt_tags = [
                    str(item).strip()
                    for item in raw_tags
                    if str(item).strip() and "$" not in str(item)
                ]
                tags.extend(tgt_tags)
            tgt_cache = _parse_cache_images(spec.get("cache-to") or spec.get("cache_to"))
            if inline:
                inlines[str(name)] = str(spec.get("dockerfile-inline") or "")
                dockerfiles.append(
                    (str(name), Path(), _parse_build_arg_mapping(spec.get("args")), tgt_tags, tgt_cache)
                )
            elif resolved:
                dockerfiles.append(
                    (str(name), resolved, _parse_build_arg_mapping(spec.get("args")), tgt_tags, tgt_cache)
                )
            _add_extra(_parse_named_context_images(spec.get("contexts")))
            _add_extra(_parse_cache_images(spec.get("cache-from") or spec.get("cache_from")))
        return dockerfiles, tags, extra, inlines
    for name, block in _hcl_named_targets(text):
        inline = _hcl_dockerfile_inline(block)
        if inline is None and "dockerfile-inline" in block:
            continue
        inline = inline or ""
        context_match = _HCL_CONTEXT.search(block)
        df_match = _HCL_DOCKERFILE.search(block)
        context = context_match.group(1).strip() if context_match else "."
        dockerfile = df_match.group(1).strip() if df_match else ""
        resolved = None if inline else _bake_resolve_dockerfile(file_dir, cwd, context, dockerfile)
        tgt_tags: list[str] = []
        tags_match = _HCL_TAGS.search(block)
        if tags_match:
            tgt_tags = [
                item.strip().strip("'\"")
                for item in tags_match.group(1).split(",")
                if item.strip().strip("'\"") and "$" not in item
            ]
            tags.extend(tgt_tags)
        tgt_cache = _parse_cache_images(_hcl_quoted_list(block, "cache-to"))
        if inline:
            inlines[name] = inline
            dockerfiles.append((name, Path(), _hcl_args(block), tgt_tags, tgt_cache))
        elif resolved:
            dockerfiles.append((name, resolved, _hcl_args(block), tgt_tags, tgt_cache))
        _add_extra(_parse_named_context_images(_hcl_named_map(block, "contexts")))
        _add_extra(_parse_cache_images(_hcl_quoted_list(block, "cache-from")))
    return dockerfiles, tags, extra, inlines


def _bake_materialize_lan_add(
    named: list[tuple[str, Path, dict[str, str]]],
    extra_args: dict[str, str],
    inlines: dict[str, str] | None = None,
) -> tuple[list[str], list[tuple[str, str]], str] | None:
    if not named:
        return None
    inlines = inlines or {}
    root = Path(tempfile.mkdtemp(prefix="jarvis-lan-add-"))
    fetches: list[tuple[str, str]] = []
    sets: list[str] = []
    cached: dict[str, tuple[Path, list[tuple[str, str]]] | None] = {}
    for index, (name, dockerfile, args, *_rest) in enumerate(named):
        text = inlines.get(name, "")
        key = f"inline:{name}" if text else str(dockerfile)
        if key not in cached:
            leaf = re.sub(r"[^A-Za-z0-9._-]+", "_", name) or f"tgt{index}"
            spec = _materialize_lan_add(
                None if text else dockerfile,
                {**args, **extra_args},
                root=root,
                leaf=leaf,
                source_text=text,
            )
            cached[key] = None if spec is None else (spec[0], spec[2])
            if spec is not None:
                fetches.extend(spec[1])
        hit = cached.get(key)
        if not hit or not re.fullmatch(r"[A-Za-z0-9._-]+", name or ""):
            continue
        df, contexts = hit
        sets.append(f"{name}.dockerfile={df}")
        if text:
            sets.append(f"{name}.dockerfile-inline=")
        for ctx, directory in contexts:
            sets.append(f"{name}.contexts.{ctx}={directory}")
    if not sets:
        shutil.rmtree(root, ignore_errors=True)
        return None
    return sets, fetches, str(root)


def _bake_insert_sets(parts: list[str], sets: list[str]) -> list[str]:
    extra: list[str] = []
    for spec in sets:
        extra.extend(["--set", spec])
    out = list(parts)
    for i, item in enumerate(out):
        if item == "bake":
            return out[: i + 1] + extra + out[i + 1 :]
    return out + extra


def _bake_set_tags(value: str) -> list[str]:
    text = str(value or "").strip().strip("'\"")
    if not text or "$" in text:
        return []
    lowered = text.lower()
    if ".tags=" not in lowered and not lowered.startswith("tags="):
        return []
    _, _, rhs = text.partition("=")
    return [
        item.strip().strip("'\"")
        for item in rhs.split(",")
        if item.strip().strip("'\"") and "$" not in item
    ]


def _bake_set_args(value: str) -> dict[str, str]:
    """Parse ``--set app.args.BASE=image`` / ``*.args.BASE=image`` overrides."""
    text = str(value or "").strip().strip("'\"")
    if not text or "$" in text:
        return {}
    key_path, sep, rhs = text.partition("=")
    if not sep or not rhs.strip() or "$" in rhs:
        return {}
    lowered = key_path.lower()
    if ".args." not in lowered and not lowered.startswith("args."):
        return {}
    name = key_path.rsplit(".", 1)[-1].strip()
    if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", name or ""):
        return {}
    return {name: rhs.strip().strip("'\"")}


def _bake_set_context_images(value: str) -> list[str]:
    """Parse ``--set app.contexts.assets=docker-image://...`` overrides."""
    text = str(value or "").strip().strip("'\"")
    if not text:
        return []
    key_path, sep, rhs = text.partition("=")
    if not sep:
        return []
    lowered = key_path.lower()
    if ".contexts." not in lowered and not lowered.startswith("contexts."):
        return []
    image = _image_from_named_context(rhs)
    return [image] if image else []


def _docker_bake_spec(
    parts: list[str], cwd: str | None
) -> tuple[list[Path], bool, bool, list[str], dict[str, str], list[str]] | None:
    if not parts or _tool_basename(parts[0]) != "docker":
        return None
    rest = parts[1:]
    if rest and _tool_basename(rest[0]) == "buildx":
        rest = rest[1:]
    if not rest or rest[0] != "bake":
        return None
    files: list[str] = []
    extra_tags: list[str] = []
    extra_args: dict[str, str] = {}
    extra_contexts: list[str] = []
    quiet = False
    wants_push = False
    index = 1
    while index < len(rest):
        text = str(rest[index] or "").strip().strip("'\"")
        index += 1
        if not text:
            continue
        if text == "--print":
            return None
        if text in _DOCKER_PULL_QUIET:
            quiet = True
            continue
        if text == "--push":
            wants_push = True
            continue
        if text in {"--load", "--no-cache", "--pull"} or text.startswith("--pull="):
            continue
        if text.startswith("--file="):
            files.append(text.split("=", 1)[1].strip())
            continue
        if text in {"-f", "--file"}:
            if index >= len(rest):
                return None
            files.append(str(rest[index] or "").strip().strip("'\""))
            index += 1
            continue
        if text.startswith("--set="):
            raw = text.split("=", 1)[1]
            extra_tags.extend(_bake_set_tags(raw))
            extra_args.update(_bake_set_args(raw))
            extra_contexts.extend(_bake_set_context_images(raw))
            continue
        if text == "--set":
            if index >= len(rest):
                return None
            raw = str(rest[index] or "").strip().strip("'\"")
            extra_tags.extend(_bake_set_tags(raw))
            extra_args.update(_bake_set_args(raw))
            extra_contexts.extend(_bake_set_context_images(raw))
            index += 1
            continue
        if text.startswith("--") and "=" in text:
            continue
        if text in _BAKE_VALUE_FLAGS:
            if index >= len(rest):
                return None
            index += 1
            continue
        if text.startswith("-"):
            return None
        continue
    root = Path(cwd or os.getcwd())
    paths: list[Path] = []
    for item in files:
        candidate = Path(item)
        if not candidate.is_absolute():
            candidate = root / candidate
        paths.append(candidate)
    if not paths:
        paths = [root / name for name in (*_BAKE_FILENAMES, *_COMPOSE_FILENAMES) if (root / name).is_file()]
    if not paths:
        return None
    for path in paths:
        if not path.is_file():
            return None
    return paths, quiet, wants_push, extra_tags, extra_args, extra_contexts


def _docker_bake_for_local_load(parts: list[str], *, drop_push: bool) -> list[str]:
    out: list[str] = []
    has_load = False
    is_buildx = False
    for item in parts:
        text = str(item)
        if _tool_basename(text) == "buildx":
            is_buildx = True
        if drop_push and text == "--push":
            continue
        if text in {"--pull", "--pull=true"} or text.startswith("--pull="):
            continue
        if text == "--load":
            has_load = True
        out.append(text)
    if drop_push and is_buildx and not has_load:
        rebuilt: list[str] = []
        placed = False
        for item in out:
            rebuilt.append(item)
            if not placed and item == "bake":
                rebuilt.append("--load")
                placed = True
        return rebuilt
    return out


def lan_bound_docker_bake_argv(command: str, cwd: str | None = None) -> list[str] | None:
    """``docker buildx bake`` of a target whose Dockerfile ``FROM`` or tag is on-link RFC1918.

    Skopeo loads LAN bases, bake runs with ``--load`` instead of ``--push``, then
    LAN tags upload through skopeo. Skip ``--print``, interpolations, pipes, and
    missing skopeo.
    """
    text = str(command or "").strip()
    if not text or _UNSAFE_SHELL.search(text):
        return None
    try:
        parts = shlex.split(text, posix=os.name != "nt")
    except ValueError:
        return None
    spec = _docker_bake_spec(parts, cwd)
    if spec is None:
        return None
    paths, quiet, wants_push, extra_tags, extra_args, extra_contexts = spec
    root = Path(cwd or os.getcwd())
    named: list[tuple[str, Path, dict[str, str], list[str], list[str]]] = []
    tags: list[str] = []
    extra_images: list[str] = []
    inlines: dict[str, str] = {}
    seen_names: set[str] = set()
    for path in paths:
        files, found_tags, found_contexts, found_inlines = bake_file_dockerfiles_and_tags(path, root)
        for name, df, args, tgt_tags, tgt_cache in files:
            if name in seen_names:
                continue
            seen_names.add(name)
            named.append((name, df, args, tgt_tags, tgt_cache))
        tags.extend(found_tags)
        extra_images.extend(found_contexts)
        inlines.update(found_inlines)
    if extra_tags:
        tags = list(extra_tags)
    lan: list[str] = []
    seen: set[str] = set()
    seen_df: set[str] = set()
    for name, dockerfile, args, *_rest in named:
        text = inlines.get(name, "")
        key = f"inline:{name}" if text else str(dockerfile)
        if key in seen_df:
            continue
        seen_df.add(key)
        merged = {**args, **extra_args}
        images = (
            dockerfile_images_from_text(text, merged)
            if text
            else dockerfile_from_images(dockerfile, merged)
        )
        for image in images:
            if image in seen:
                continue
            if not _lan_bind_ip_for_host(docker_registry_host_from_image(image)):
                continue
            seen.add(image)
            lan.append(image)
    for image in [*extra_images, *extra_contexts]:
        if image in seen:
            continue
        if not _lan_bind_ip_for_host(docker_registry_host_from_image(image)):
            continue
        seen.add(image)
        lan.append(image)
    lan_tags = [
        tag
        for tag in tags
        if _lan_bind_ip_for_host(docker_registry_host_from_image(tag))
    ]
    cache_sets: list[str] = []
    lan_cache_to: list[str] = []
    for name, _df, _args, tgt_tags, tgt_cache in named:
        lan_to = _lan_tagged_refs(tgt_cache)
        if not lan_to or not re.fullmatch(r"[A-Za-z0-9._-]+", name or ""):
            continue
        cache_sets.append(f"{name}.cache-to=type=inline")
        tag_src = list(extra_tags) if extra_tags else list(tgt_tags)
        merged = list(dict.fromkeys([*tag_src, *lan_to]))
        if merged:
            cache_sets.append(f"{name}.tags=" + ",".join(merged))
        for item in lan_to:
            if item not in lan_cache_to:
                lan_cache_to.append(item)
    add_plan = _bake_materialize_lan_add(named, extra_args, inlines=inlines)
    if not lan and not (wants_push and lan_tags) and add_plan is None and not lan_cache_to:
        return None
    follow = _compose_follow_argv(parts)
    if not follow:
        if add_plan is not None:
            shutil.rmtree(add_plan[2], ignore_errors=True)
        return None
    follow = _docker_bake_for_local_load(
        follow, drop_push=bool((wants_push and lan_tags) or lan_cache_to)
    )
    fetches: list[tuple[str, str]] = []
    cleanup = ""
    if add_plan is not None:
        sets, fetches, cleanup = add_plan
        follow = _bake_insert_sets(follow, sets)
    if cache_sets:
        follow = _bake_insert_sets(follow, cache_sets)
    push_after: list[str] | None = list(lan_tags) if wants_push and lan_tags else None
    if lan_cache_to:
        push_after = list(dict.fromkeys([*(push_after or []), *lan_cache_to]))
    return _skopeo_follow_or_cleanup(
        lan,
        quiet=quiet,
        follow=follow,
        fetches=fetches,
        cleanup=cleanup,
        push_after=push_after,
    )


def container_direct_argv(command: str) -> list[str] | None:
    """Run registry/package-manager/S3 CLIs as argv so LAN HTTP_PROXY reaches a NAS."""
    return _direct_stem_argv(command, _LAN_HTTP_TOOL_STEMS)


def git_direct_argv(command: str) -> list[str] | None:
    """Run git as argv so LAN HTTP_PROXY and GIT_SSH_COMMAND BindAddress apply."""
    return _direct_stem_argv(command, frozenset({"git"}))


def _direct_stem_argv(command: str, stems: frozenset[str]) -> list[str] | None:
    text = str(command or "").strip()
    if not text or _UNSAFE_SHELL.search(text):
        return None
    try:
        parts = shlex.split(text, posix=os.name != "nt")
    except ValueError:
        return None
    if not parts:
        return None
    name = _tool_basename(parts[0])
    if name not in stems:
        return None
    exe = shutil.which(name) or shutil.which(f"{name}.exe")
    if not exe:
        return None
    return [exe, *parts[1:]]


def adapt_shell(command: str, shell: str) -> str:
    """Run cmd.exe idioms with cmd so PowerShell does not parse switches as parameters."""
    chosen = (shell or default_shell()).strip().lower()
    if chosen != "powershell":
        return chosen
    if _POWERSHELL_MARKERS.search(command or ""):
        return chosen
    if _CMD_IDIOMS.search(command or ""):
        return "cmd"
    return chosen


def _approved_from_context() -> bool:
    """True only when a validated ApprovalGrant (or legacy owner resume) is in context.

    Model tool args never populate this — only the agent loop after an ApprovalGrant.
    """
    from .registry import REGISTRY

    ctx = REGISTRY._context
    if ctx.get("approval_grant_id"):
        return True
    return bool(ctx.get("approved"))


def _decode(data: bytes | bytearray) -> str:
    return bytes(data).decode("utf-8", errors="replace")


def _python_interpreter_name(name: str) -> bool:
    text = Path(name or "").name.lower()
    if text.endswith(".exe"):
        text = text[:-4]
    if text in {"python", "python3", "pythonw", "py"}:
        return True
    return bool(re.fullmatch(r"python\d+(\.\d+)*", text))


def python_direct_argv(command: str) -> list[str] | None:
    """Run ``python -c`` / ``python3 script.py`` as argv, not ``bash -lc``.

    Default Linux shell is bash. Without this, ``python3 -c`` inherits the
    proxy-free bash env and LAN ``socket.connect`` / requests follow the VPN.
    Semicolons inside ``-c`` are Python, not shell, once the command is argv.
    """
    text = str(command or "").strip()
    if not text or "\n" in text:
        return None
    try:
        parts = shlex.split(text, posix=os.name != "nt")
    except ValueError:
        return None
    if not parts or not _python_interpreter_name(parts[0]):
        return None
    if any(part in {"|", "||", "&", "&&", ";", ">", ">>", "<"} for part in parts):
        return None
    if any(part.startswith("$(") or part.startswith("`") for part in parts):
        return None
    python = sys.executable or shutil.which(parts[0]) or shutil.which("python3") or "python3"
    return [python, *parts[1:]]


def _python_args(command: str) -> list[str]:
    stripped = (command or "").strip()
    python = sys.executable or shutil.which("python") or shutil.which("python3") or "python3"
    if not stripped:
        return [python, "-c", ""]
    first = stripped.split()[0]
    looks_like_file = first.endswith(".py") or (os.path.isfile(first) and not any(ch in stripped for ch in ";=\n"))
    if looks_like_file:
        return [python, *stripped.split()]
    return [python, "-c", command]


def _child_env(args: list[str]) -> dict[str, str]:
    if args and (args[0] == sys.executable or _python_interpreter_name(args[0])):
        return python_child_env()
    from .lan_snmp import is_snmp_tool, snmp_lan_child_env

    if args and is_snmp_tool(args[0]):
        return snmp_lan_child_env(args)
    stem = _tool_basename(args[0]) if args else ""
    if stem == "git":
        return git_child_env()
    if stem in _LAN_HTTP_TOOL_STEMS:
        return lan_http_child_env()
    return direct_child_env()


def _command_args(command: str, shell: str, cwd: str | None = None) -> list[str] | ToolResult:
    bound = (
        lan_bound_http_argv(command)
        or lan_bound_ssh_argv(command)
        or lan_bound_scan_argv(command)
        or lan_bound_rsync_argv(command)
        or lan_bound_rclone_argv(command)
        or lan_bound_netcat_argv(command)
        or lan_bound_dns_argv(command)
        or lan_bound_snmp_argv(command)
        or lan_bound_cifs_argv(command)
        or lan_bound_nfs_argv(command)
        or lan_bound_smb_argv(command)
        or lan_bound_docker_pull_argv(command)
        or lan_bound_docker_push_argv(command)
        or lan_bound_docker_login_argv(command)
        or lan_bound_compose_pull_argv(command, cwd=cwd)
        or lan_bound_compose_push_argv(command, cwd=cwd)
        or lan_bound_compose_build_argv(command, cwd=cwd)
        or lan_bound_compose_up_argv(command, cwd=cwd)
        or lan_bound_compose_run_argv(command, cwd=cwd)
        or lan_bound_docker_build_argv(command, cwd=cwd)
        or lan_bound_docker_bake_argv(command, cwd=cwd)
    )
    if bound:
        return bound
    py = python_direct_argv(command)
    if py:
        return py
    git = git_direct_argv(command)
    if git:
        return git
    container = container_direct_argv(command)
    if container:
        return container
    if shell == "powershell":
        exe = shutil.which("powershell") or shutil.which("pwsh")
        if not exe:
            return ToolResult(False, "", error="PowerShell is not available on this machine")
        return [exe, "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", command]
    if shell == "cmd":
        return ["cmd", "/c", command]
    if shell == "python":
        return _python_args(command)
    if shell == "git":
        if command.startswith("git"):
            return command.split()
        return ["git", *command.split()]
    if shell in {"bash", "wsl"}:
        if sys.platform == "win32" and shutil.which("wsl") and shell == "wsl":
            return ["wsl", "-e", "bash", "-lc", command]
        if shutil.which("bash"):
            return ["bash", "-lc", command]
        return ToolResult(False, "", error="WSL/bash is not available on this machine")
    return _command_args(command, default_shell(), cwd=cwd)


async def _pump(job: BackgroundJob) -> None:
    async def _read(stream, bucket: bytearray) -> None:
        if stream is None:
            return
        while True:
            chunk = await stream.read(4096)
            if not chunk:
                return
            bucket.extend(chunk)
            if len(bucket) > 200_000:
                del bucket[:-120_000]

    await asyncio.gather(_read(job.proc.stdout, job.stdout), _read(job.proc.stderr, job.stderr))


def _job_snapshot(job: BackgroundJob, extra: dict[str, Any] | None = None) -> dict[str, Any]:
    alive = job.proc.returncode is None
    payload = {
        "pid": job.pid,
        "alive": alive,
        "command": job.command,
        "elapsed_seconds": round(time.time() - job.started, 2),
        "exit_code": job.proc.returncode,
        "stdout": _decode(job.stdout)[-8000:],
        "stderr": _decode(job.stderr)[-4000:],
    }
    if extra:
        payload.update(extra)
    return payload


def _format_inspect(payload: dict[str, Any]) -> str:
    lines = [
        f"pid={payload.get('pid')}",
        f"alive={payload.get('alive')}",
        f"status={payload.get('status') or ('running' if payload.get('alive') else 'exited')}",
        f"command={payload.get('command') or ''}",
        f"elapsed_seconds={payload.get('elapsed_seconds', '')}",
        f"exit_code={payload.get('exit_code') if payload.get('exit_code') is not None else ''}",
    ]
    if payload.get("cpu_percent") is not None:
        lines.append(f"cpu_percent={payload['cpu_percent']}")
    if payload.get("rss_mb") is not None:
        lines.append(f"rss_mb={payload['rss_mb']}")
    if "stdout" in payload:
        lines.append("--- stdout ---")
        lines.append(payload.get("stdout") or "")
        lines.append("--- stderr ---")
        lines.append(payload.get("stderr") or "")
    return "\n".join(lines)


class TerminalTool(Tool):
    name = "terminal"
    description = (
        "Run a local command. shell can be powershell, cmd, python, git, or bash/wsl. "
        "Default shell is PowerShell on Windows and bash on Linux. "
        "action=run (default) waits for the process. action=start returns a PID immediately; "
        "then use inspect/wait/kill with that pid to see if it is still alive and to collect output. "
        "inspect also works for other local PIDs. Captures stdout, stderr, exit code and duration. "
        "Omit working_directory to run in Documents. USB/`D:` extra drives are allowed. "
        "Do not use this to format disks or destroy backups."
    )
    risk = RiskLevel.HIGH
    parameters = {
        "type": "object",
        "properties": {
            "command": {"type": "string"},
            "shell": {
                "type": "string",
                "enum": ["powershell", "cmd", "python", "git", "bash", "wsl"],
                "default": "powershell" if os.name == "nt" else "bash",
            },
            "working_directory": {"type": "string"},
            "timeout_seconds": {"type": "integer", "default": 120},
            "action": {
                "type": "string",
                "enum": ["run", "start", "inspect", "wait", "kill"],
                "default": "run",
                "description": "run waits; start backgrounds; inspect/wait/kill use pid",
            },
            "pid": {"type": "integer", "description": "Process id for inspect, wait, or kill"},
            "background": {"type": "boolean", "default": False, "description": "If true, treated as action=start"},
        },
        "required": [],
    }

    def __init__(self, context_getter=None) -> None:
        self.context_getter = context_getter or (lambda: {})

    async def execute(self, **kwargs: Any) -> ToolResult:
        action = (kwargs.get("action") or "run").lower()
        if kwargs.get("background") and action == "run":
            action = "start"
        if action == "inspect":
            return await self._inspect(kwargs.get("pid"))
        if action == "wait":
            return await self._wait(kwargs.get("pid"), int(kwargs.get("timeout_seconds") or 120))
        if action == "kill":
            return await self._kill(kwargs.get("pid"))

        command = kwargs.get("command") or ""
        if not command.strip():
            return ToolResult(False, "", error="command is required for run/start")
        from ..policy.computer_permissions import tool_permission_error

        denied = tool_permission_error("terminal", kwargs)
        if denied:
            return ToolResult(False, "", error=denied)
        shell = adapt_shell(command, (kwargs.get("shell") or default_shell()).lower())
        raw_cwd = kwargs.get("working_directory")
        allowed = live_workspace_roots_from_context(self.context_getter() if callable(self.context_getter) else {})
        try:
            cwd = workspace_cwd(raw_cwd, allowed)
        except PermissionError as exc:
            return ToolResult(False, "", error=str(exc))
        if not cwd:
            cwd = os.getcwd()
        timeout = int(kwargs.get("timeout_seconds") or 120)
        risk = classify_command(command)
        approved = bool(kwargs.get("_approved")) or _approved_from_context()
        if risk == RiskLevel.IRREVERSIBLE and not approved:
            return ToolResult(False, "", error="Blocked irreversible command. Ask the user explicitly if this is required.")
        args = _command_args(command, shell, cwd=cwd)
        if isinstance(args, ToolResult):
            return args
        if action == "start":
            return await self._start(args, command, cwd)
        return await self._run(args, cwd, timeout, command=command)

    async def _run(self, args: list[str], cwd: str, timeout: int, command: str = "") -> ToolResult:
        started = time.time()
        try:
            proc = await asyncio.create_subprocess_exec(
                *args,
                cwd=cwd,
                env=_child_env(args),
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            try:
                stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=timeout)
            except TimeoutError:
                proc.kill()
                await proc.wait()
                return ToolResult(False, "", error=f"Command timed out after {timeout}s", data={"pid": proc.pid})
            duration = round((time.time() - started) * 1000, 1)
            out = stdout.decode("utf-8", errors="replace")
            err = stderr.decode("utf-8", errors="replace")
            code = 0 if proc.returncode is None else int(proc.returncode)
            text = (
                f"exit_code={code}\nduration_ms={duration}\npid={proc.pid}\n"
                f"--- stdout ---\n{out}\n--- stderr ---\n{err}"
            )
            ok = code == 0 or search_miss_ok(command, code)
            return ToolResult(
                ok,
                text,
                data={"exit_code": code, "duration_ms": duration, "pid": proc.pid, "alive": False},
                error="" if ok else err[-2000:],
            )
        except Exception as exc:
            return ToolResult(False, "", error=str(exc))

    async def _start(self, args: list[str], command: str, cwd: str) -> ToolResult:
        try:
            proc = await asyncio.create_subprocess_exec(
                *args,
                cwd=cwd,
                env=_child_env(args),
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
        except Exception as exc:
            return ToolResult(False, "", error=str(exc))
        if proc.pid is None:
            return ToolResult(False, "", error="Process started without a PID")
        job = BackgroundJob(pid=proc.pid, command=command, proc=proc)
        job.pump = asyncio.create_task(_pump(job))
        _JOBS[proc.pid] = job
        payload = _job_snapshot(job)
        return ToolResult(
            True,
            f"started pid={proc.pid}\ncommand={command}\nUse terminal action=inspect/wait/kill with this pid.",
            data=payload,
        )

    async def _inspect(self, pid: Any) -> ToolResult:
        if pid in (None, "", 0):
            jobs = [_job_snapshot(job) for job in list(_JOBS.values())]
            text = "No tracked background jobs." if not jobs else "\n\n".join(_format_inspect(item) for item in jobs)
            return ToolResult(True, text, data={"jobs": jobs})
        try:
            pid_i = int(pid)
        except (TypeError, ValueError):
            return ToolResult(False, "", error="pid must be an integer")
        extra: dict[str, Any] = {}
        job = _JOBS.get(pid_i)
        if job:
            payload = _job_snapshot(job)
        else:
            payload = {"pid": pid_i, "command": "", "stdout": "", "stderr": ""}
        try:
            proc = psutil.Process(pid_i)
            payload["alive"] = proc.is_running() and proc.status() != psutil.STATUS_ZOMBIE
            payload["status"] = proc.status()
            payload["command"] = payload.get("command") or " ".join(proc.cmdline()) or proc.name()
            payload["cpu_percent"] = proc.cpu_percent(interval=0.05)
            payload["rss_mb"] = round(proc.memory_info().rss / (1024 * 1024), 2)
            if payload.get("elapsed_seconds") is None:
                payload["elapsed_seconds"] = round(max(0.0, time.time() - proc.create_time()), 2)
        except psutil.NoSuchProcess:
            payload["alive"] = False
            payload["status"] = "not_found"
            payload["exit_code"] = job.proc.returncode if job else None
        extra.update(payload)
        return ToolResult(True, _format_inspect(payload), data=payload)

    async def _wait(self, pid: Any, timeout: int) -> ToolResult:
        try:
            pid_i = int(pid)
        except (TypeError, ValueError):
            return ToolResult(False, "", error="pid is required for wait")
        job = _JOBS.get(pid_i)
        if not job:
            return ToolResult(False, "", error=f"PID {pid_i} is not a process started by Jarvis")
        try:
            await asyncio.wait_for(job.proc.wait(), timeout=timeout)
        except TimeoutError:
            payload = _job_snapshot(job)
            payload["timed_out"] = True
            return ToolResult(False, _format_inspect(payload), data=payload, error=f"Still running after {timeout}s")
        if job.pump:
            try:
                await asyncio.wait_for(job.pump, timeout=2)
            except TimeoutError:
                pass
        payload = _job_snapshot(job)
        code = job.proc.returncode or 0
        return ToolResult(code == 0, _format_inspect(payload), data=payload, error="" if code == 0 else (payload.get("stderr") or "")[-2000:])

    async def _kill(self, pid: Any) -> ToolResult:
        try:
            pid_i = int(pid)
        except (TypeError, ValueError):
            return ToolResult(False, "", error="pid is required for kill")
        job = _JOBS.get(pid_i)
        if job and job.proc.returncode is None:
            job.proc.kill()
            await job.proc.wait()
            if job.pump:
                try:
                    await asyncio.wait_for(job.pump, timeout=2)
                except TimeoutError:
                    pass
            payload = _job_snapshot(job, extra={"killed": True, "alive": False})
            return ToolResult(True, _format_inspect(payload), data=payload)
        try:
            proc = psutil.Process(pid_i)
        except psutil.NoSuchProcess:
            return ToolResult(False, "", error=f"PID {pid_i} is not running")
        try:
            name = proc.name()
        except psutil.Error:
            name = f"pid {pid_i}"
        if is_protected_process(name, pid_i):
            return ToolResult(False, "", error=f"Refusing to kill protected process {name} ({pid_i}).")
        try:
            proc.terminate()
            gone, alive = psutil.wait_procs([proc], timeout=3)
            if alive:
                for leftover in alive:
                    leftover.kill()
                psutil.wait_procs(alive, timeout=2)
        except psutil.AccessDenied:
            return ToolResult(
                False,
                "",
                error=f"Access denied killing {name} ({pid_i}) — needs the elevated backend.",
            )
        except psutil.NoSuchProcess:
            pass
        payload = {"pid": pid_i, "killed": True, "alive": False, "command": name}
        return ToolResult(True, f"Stopped {name} (pid {pid_i}).", data=payload)
