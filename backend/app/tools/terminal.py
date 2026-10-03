from __future__ import annotations

import asyncio
import os
import platform
import re
import shlex
import shutil
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import psutil

from ..config import live_workspace_roots_from_context
from .base import RiskLevel, Tool, ToolResult
from .owner_paths import direct_child_env, lan_http_child_env, python_child_env, workspace_cwd
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
    """Real curl/wget/IWR of an on-link RFC1918 URL, sourced from that NIC.

    PowerShell aliases ``curl``/``wget`` to Invoke-WebRequest, which cannot bind
    a source IP. A VPN default route would steal the hop to the home gateway.
    Skip pipes and explicit proxies.
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
    if name not in {"curl", "wget"}:
        return None
    flags = {part.split("=", 1)[0] for part in parts[1:] if str(part).startswith("-")}
    if flags & _PROXY_FLAGS:
        return None
    url = _http_target_from_argv(parts)
    bind = _lan_bind_for_http_target(url)
    if not bind:
        return None
    exe = shutil.which(name) or shutil.which(f"{name}.exe")
    rest = parts[1:]
    if name == "wget":
        if exe:
            return [exe, f"--bind-address={bind}", *rest]
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


_LAN_HTTP_TOOL_STEMS = frozenset({"skopeo", "podman", "buildah", "trivy", "grype", "crane", "oras"})
_DOCKER_PULL_QUIET = frozenset({"-q", "--quiet"})


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


def _docker_pull_image(parts: list[str]) -> str:
    image, _platform = _docker_pull_spec(parts)
    return image


def _docker_pull_spec(parts: list[str]) -> tuple[str, str]:
    if not parts or _tool_basename(parts[0]) != "docker":
        return "", ""
    rest = parts[1:]
    if rest and _tool_basename(rest[0]) == "image":
        rest = rest[1:]
    if not rest or _tool_basename(rest[0]) != "pull":
        return "", ""
    image = ""
    platform = ""
    index = 1
    while index < len(rest):
        text = str(rest[index] or "").strip().strip("'\"")
        index += 1
        if not text or text in _DOCKER_PULL_QUIET:
            continue
        if text.startswith("--platform="):
            if platform:
                return "", ""
            platform = text.split("=", 1)[1].strip()
            continue
        if text == "--platform":
            if platform or index >= len(rest):
                return "", ""
            platform = str(rest[index] or "").strip().strip("'\"")
            index += 1
            if not platform or platform.startswith("-"):
                return "", ""
            continue
        if text.startswith("-"):
            return "", ""
        if image:
            return "", ""
        image = text
    return image, platform


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
    Skip pipes, ``-a`` / ``--all-tags``, public Hub names, and missing skopeo.
    Optional ``-q`` / ``--quiet`` and ``--platform os/arch[/variant]``.
    """
    text = str(command or "").strip()
    if not text or _UNSAFE_SHELL.search(text):
        return None
    try:
        parts = shlex.split(text, posix=os.name != "nt")
    except ValueError:
        return None
    image, platform = _docker_pull_spec(parts)
    if not image:
        return None
    overrides = _skopeo_platform_flags(platform)
    if overrides is None:
        return None
    host = docker_registry_host_from_image(image)
    if not _lan_bind_ip_for_host(host):
        return None
    exe = shutil.which("skopeo") or shutil.which("skopeo.exe")
    if not exe:
        return None
    tagged = _docker_image_with_tag(image)
    argv = [exe, "copy", *overrides]
    if any(str(item) in _DOCKER_PULL_QUIET for item in parts[1:]):
        argv.append("--quiet")
    argv.extend(["--src-tls-verify=false", f"docker://{tagged}", f"docker-daemon:{tagged}"])
    return argv


def container_direct_argv(command: str) -> list[str] | None:
    """Run skopeo/podman/buildah/trivy as argv so LAN HTTP_PROXY reaches the registry."""
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
    if name not in _LAN_HTTP_TOOL_STEMS:
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
    if stem in _LAN_HTTP_TOOL_STEMS:
        return lan_http_child_env()
    return direct_child_env()


def _command_args(command: str, shell: str) -> list[str] | ToolResult:
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
    )
    if bound:
        return bound
    py = python_direct_argv(command)
    if py:
        return py
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
    return _command_args(command, default_shell())


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
        args = _command_args(command, shell)
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
