"""Owner-scoped defensive HexStrike actions for RFC-0086.

This module intentionally exposes a small, typed action catalog instead of
forwarding arbitrary upstream paths, flags, commands, or MCP tools.
"""
from __future__ import annotations

import asyncio
import ipaddress
import json
import re
import shlex
import shutil
import socket
import threading
import uuid
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from ..config import data_dir, live_allowed_directories, load_settings
from .hexstrike import HEXSTRIKE, audit_hexstrike

_SCOPE_FILE = "hexstrike-scopes.json"
_JOB_FILE = "hexstrike-jobs.json"
_LOCK = threading.RLock()
_CONTAINER_RE = re.compile(r"^[a-z0-9][a-z0-9._/-]*(?::[a-zA-Z0-9._-]+|@sha256:[a-f0-9]{64})?$")
_CVE_RE = re.compile(r"^CVE-\d{4}-\d{4,}$", re.IGNORECASE)

SCOPE_KINDS = frozenset({"private_host", "private_cidr", "local_path", "container_image", "local_infrastructure"})
DEFAULT_LAN_SCOPE_ID = "lan"
_RFC1918 = (
    ipaddress.ip_network("10.0.0.0/8"),
    ipaddress.ip_network("172.16.0.0/12"),
    ipaddress.ip_network("192.168.0.0/16"),
)


@dataclass(frozen=True)
class DefensiveCapability:
    id: str
    title: str
    scope_kinds: tuple[str, ...]
    permission: str
    upstream_path: str

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


CAPABILITIES: tuple[DefensiveCapability, ...] = (
    DefensiveCapability("lan_inventory", "Private LAN inventory", ("private_host", "private_cidr"), "network.local", "api/tools/nmap"),
    DefensiveCapability("container_scan", "Container vulnerability scan", ("container_image", "local_path"), "blue.static_rules", "api/tools/trivy"),
    DefensiveCapability("iac_scan", "Infrastructure-as-code scan", ("local_path",), "blue.static_rules", "api/tools/checkov"),
    DefensiveCapability("host_baseline", "Local host benchmark", ("local_infrastructure",), "blue.static_rules", "api/tools/docker-bench-security"),
    DefensiveCapability("forensic_inspection", "Local forensic metadata", ("local_path",), "blue.static_rules", "api/tools/exiftool"),
    DefensiveCapability("threat_intel_lookup", "CVE intelligence lookup", ("local_infrastructure",), "blue.static_rules", "jarvis/nvd-cve"),
)
CAPABILITY_BY_ID = {item.id: item for item in CAPABILITIES}


def _utcnow() -> str:
    return datetime.now(timezone.utc).isoformat()


def _path(name: str) -> Path:
    target = data_dir() / name
    target.parent.mkdir(parents=True, exist_ok=True)
    return target


def _read(name: str, key: str) -> list[dict[str, Any]]:
    path = _path(name)
    if not path.exists():
        return []
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    rows = value.get(key, []) if isinstance(value, dict) else []
    return [row for row in rows if isinstance(row, dict)]


def _write(name: str, key: str, rows: list[dict[str, Any]]) -> None:
    path = _path(name)
    temp = path.with_suffix(path.suffix + ".tmp")
    temp.write_text(json.dumps({"version": 1, key: rows}, indent=2) + "\n", encoding="utf-8")
    temp.replace(path)


def _private_network(value: str, *, host: bool) -> str:
    try:
        parsed = ipaddress.ip_address(value) if host else ipaddress.ip_network(value, strict=False)
    except ValueError as exc:
        raise ValueError("scope must be a literal private IP address or CIDR") from exc
    if not (parsed.is_private or parsed.is_loopback or parsed.is_link_local):
        raise ValueError("public network targets are not allowed in the Blue release")
    return str(parsed)


def _local_path(value: str) -> str:
    candidate = Path(value).expanduser()
    if not candidate.is_absolute():
        raise ValueError("local evidence paths must be absolute")
    resolved = candidate.resolve(strict=False)
    settings = load_settings()
    roots = live_allowed_directories(settings.allowed_directories)
    from ..config import LOCAL_NETWORK_SCOPE
    from ..tools.safety import _is_unc_path, _private_lan_unc

    if LOCAL_NETWORK_SCOPE in roots and _is_unc_path(value) and _private_lan_unc(value):
        from ..tools.safety import resolve_allowed_path

        return str(resolve_allowed_path(value, roots))
    allowed = [Path(root).expanduser().resolve(strict=False) for root in roots if root != LOCAL_NETWORK_SCOPE]
    if not any(resolved == root or resolved.is_relative_to(root) for root in allowed):
        raise ValueError("local path is outside Jarvis allowed directories")
    if not re.fullmatch(r"[A-Za-z0-9_./:\\-]+", str(resolved)):
        raise ValueError("local path contains characters not safely supported by the pinned upstream interface")
    return str(resolved)


def normalize_scope(kind: str, value: str) -> str:
    normalized_kind = (kind or "").strip().lower()
    cleaned = (value or "").strip()
    if normalized_kind not in SCOPE_KINDS:
        raise ValueError(f"unsupported scope kind: {kind}")
    if normalized_kind == "private_host":
        return _private_network(cleaned, host=True)
    if normalized_kind == "private_cidr":
        return _private_network(cleaned, host=False)
    if normalized_kind == "local_path":
        return _local_path(cleaned)
    if normalized_kind == "container_image":
        if not _CONTAINER_RE.fullmatch(cleaned):
            raise ValueError("invalid container image reference")
        return cleaned
    if cleaned not in {"local", "localhost", "127.0.0.1"}:
        raise ValueError("local infrastructure scope must target this Jarvis host")
    return "local"


def list_scopes() -> list[dict[str, Any]]:
    with _LOCK:
        return _read(_SCOPE_FILE, "scopes")


def upsert_scope(scope_id: str, *, kind: str, value: str, label: str, attested_owned: bool) -> dict[str, Any]:
    if not attested_owned:
        raise PermissionError("the owner must attest that this scope is owned or authorized")
    ident = (scope_id or "").strip() or str(uuid.uuid4())
    if not re.fullmatch(r"[A-Za-z0-9._-]{1,80}", ident):
        raise ValueError("invalid scope id")
    normalized_kind = kind.strip().lower()
    normalized_value = normalize_scope(normalized_kind, value)
    now = _utcnow()
    with _LOCK:
        rows = _read(_SCOPE_FILE, "scopes")
        existing = next((row for row in rows if row.get("id") == ident), None)
        row = {
            "id": ident,
            "kind": normalized_kind,
            "value": normalized_value,
            "label": (label or ident).strip()[:120],
            "attested_owned": True,
            "enabled": True,
            "created_at": existing.get("created_at", now) if existing else now,
            "updated_at": now,
        }
        rows = [item for item in rows if item.get("id") != ident]
        rows.append(row)
        _write(_SCOPE_FILE, "scopes", rows)
    audit_hexstrike("scope_upserted", scope_id=ident, kind=normalized_kind)
    # RFC-0197: keep owner-attested HexStrike scopes mirrored into the target registry.
    _mirror_scope_to_target_registry(row)
    return row


def _mirror_scope_to_target_registry(scope: dict[str, Any]) -> None:
    """Best-effort bridge from RFC-0086 scopes → RFC-0197 security-targets.json."""
    try:
        from . import security_audit as security_audit_mod
        from . import target_registry as tr
    except Exception:
        return
    kind_map = {
        "private_host": "ipv4",
        "private_cidr": "cidr",
        "local_path": "local_path",
        "container_image": "container_image",
        "local_infrastructure": "hostname",
    }
    scope_kind = str(scope.get("kind") or "")
    registry_kind = kind_map.get(scope_kind)
    if not registry_kind:
        return
    value = str(scope.get("value") or "")
    if scope_kind == "local_infrastructure":
        value = "localhost"
    if not value:
        return
    # Use this module's data_dir so test patches stay isolated.
    previous_tr = tr.data_dir
    previous_audit = security_audit_mod.data_dir
    tr.data_dir = data_dir
    security_audit_mod.data_dir = data_dir
    try:
        if tr.is_registered_value(value):
            return
        target_id = str(scope.get("id") or "")
        if target_id and any(str(row.get("id") or "") == target_id for row in tr.list_targets()):
            target_id = ""
        tr.add_target(
            kind=registry_kind,
            value=value,
            notes=str(scope.get("label") or "hexstrike-scope")[:240],
            target_id=target_id or None,
        )
    except Exception:
        # Registry normalization may reject some private_host forms; ignore bridge failures.
        return
    finally:
        tr.data_dir = previous_tr
        security_audit_mod.data_dir = previous_audit


def get_scope(scope_id: str) -> dict[str, Any]:
    scope = next((row for row in list_scopes() if row.get("id") == scope_id and row.get("enabled", True)), None)
    if scope is None:
        raise KeyError(scope_id)
    return scope


def preferred_lan_cidrs() -> list[str]:
    """RFC1918 interface CIDRs with the default-gateway subnet first (home LAN before VPN)."""
    cidrs = discover_private_lan_cidrs()
    if not cidrs:
        return []
    gw = ""
    try:
        from ..mobile.wan_forward import default_gateway_ipv4

        gw = default_gateway_ipv4()
    except Exception:
        gw = ""
    try:
        gateway = ipaddress.ip_address((gw or "").strip())
    except ValueError:
        return list(cidrs)
    preferred: list[str] = []
    rest: list[str] = []
    for cidr in cidrs:
        try:
            network = ipaddress.ip_network(cidr, strict=False)
        except ValueError:
            continue
        if gateway in network:
            preferred.append(cidr)
        else:
            rest.append(cidr)
    return preferred + rest


def extra_lan_scope_id(cidr: str) -> str:
    return "lan-" + str(cidr).replace(".", "-").replace("/", "-")


def _upsert_additional_lan_scopes(cidrs: list[str]) -> None:
    for cidr in cidrs:
        ident = extra_lan_scope_id(cidr)
        if ident == DEFAULT_LAN_SCOPE_ID:
            continue
        upsert_scope(
            ident,
            kind="private_cidr",
            value=cidr,
            label=f"This PC's LAN {cidr}",
            attested_owned=True,
        )


def rfc1918_nic_addrs() -> list[tuple[str, ipaddress.IPv4Interface]]:
    """(interface name, IPv4Interface) for every RFC1918 NIC this PC currently holds."""
    try:
        import psutil
    except ImportError:
        return []
    found: list[tuple[str, ipaddress.IPv4Interface]] = []
    try:
        nics = psutil.net_if_addrs().items()
    except Exception:
        return []
    for name, addrs in nics:
        for addr in addrs:
            if getattr(addr, "family", None) != socket.AF_INET:
                continue
            ip_text = (getattr(addr, "address", None) or "").split("%", 1)[0]
            mask = getattr(addr, "netmask", None) or "255.255.255.0"
            try:
                interface = ipaddress.IPv4Interface(f"{ip_text}/{mask}")
            except ValueError:
                continue
            if not any(interface.ip in net for net in _RFC1918):
                continue
            if interface.network.prefixlen < 8 or interface.network.prefixlen > 30:
                continue
            found.append((str(name or ""), interface))
    return found


def discover_private_lan_cidrs() -> list[str]:
    """RFC1918 CIDRs from this PC's interfaces — owner LAN only, never CGNAT or public."""
    found: list[str] = []
    seen: set[str] = set()
    for _name, interface in rfc1918_nic_addrs():
        cidr = str(interface.network)
        if cidr in seen:
            continue
        seen.add(cidr)
        found.append(cidr)
    return found


def lan_bind_nic(target: str) -> tuple[str, str]:
    """On-link RFC1918 (iface, source IP) for an IP, CIDR, or LAN hostname.

    ``lan_scan_bind`` only accepts literal IPs. gobuster of ``http://nas.local/``
    must still pin the home NIC after mDNS/DNS yields an RFC1918 address.
    """
    iface, source = lan_scan_bind(target)
    if source:
        return iface, source
    host = bindable_lan_host(target) or (target or "").strip()
    if not host:
        return ("", "")
    from ..mobile.wan_forward import lan_http_bind_for_url, lan_source_ipv4_for_peer

    bind = lan_source_ipv4_for_peer(host)
    if not bind:
        bind = lan_http_bind_for_url(f"http://{host}")
    if not bind:
        return ("", "")
    for name, interface in rfc1918_nic_addrs():
        if str(interface.ip) == bind:
            return (name, bind)
    return ("", bind)


def lan_nic_detail(target: str) -> tuple[str, str, str]:
    """On-link RFC1918 (iface, source IP, broadcast) for nmblookup ``-i``/``-B``."""
    iface, source = lan_bind_nic(target)
    if not source:
        return ("", "", "")
    for name, interface in rfc1918_nic_addrs():
        if str(interface.ip) == source:
            return (name or iface, source, str(interface.network.broadcast_address))
    return (iface, source, "")


def preferred_lan_bind_target() -> str:
    """Home-LAN CIDR for NetBIOS broadcasts that name no host (``nmblookup '*'``)."""
    cidrs = preferred_lan_cidrs()
    return cidrs[0] if cidrs else ""


def lan_scan_bind(target: str) -> tuple[str, str]:
    """This PC's (interface name, IPv4) on the same RFC1918 network as *target*.

    LAN inventory must send from that NIC. A VPN default route would otherwise
    make nmap probe the tunnel instead of the owner's LAN.
    """
    cleaned = (target or "").strip()
    if not cleaned:
        return ("", "")
    try:
        if "/" in cleaned:
            needle: ipaddress.IPv4Address | ipaddress.IPv4Network = ipaddress.ip_network(
                cleaned, strict=False
            )
            host_mode = False
        else:
            needle = ipaddress.ip_address(cleaned)
            host_mode = True
    except ValueError:
        return ("", "")
    if getattr(needle, "version", 4) != 4:
        return ("", "")
    matches: list[tuple[int, str, str]] = []
    for name, interface in rfc1918_nic_addrs():
        if host_mode:
            if needle not in interface.network and needle != interface.ip:
                continue
        elif interface.ip not in needle and not needle.overlaps(interface.network):
            continue
        matches.append((interface.network.prefixlen, name, str(interface.ip)))
    if not matches:
        return ("", "")
    matches.sort(key=lambda item: (-item[0], item[1], item[2]))
    return (matches[0][1], matches[0][2])


def nmap_lan_bind_args(target: str) -> list[str]:
    """nmap argv that pins the scan to the on-link RFC1918 NIC for *target*."""
    iface, source = lan_scan_bind(target)
    args: list[str] = []
    if source:
        args.extend(["-S", source])
    if iface:
        args.extend(["-e", iface])
    return args


def hexstrike_nmap_can_bind_interface(iface: str) -> bool:
    """HexStrike nmap uses additional_args.split(); spaced Windows NIC names cannot round-trip."""
    text = str(iface or "")
    return bool(text) and not any(ch.isspace() for ch in text)


def lan_inventory_uses_host_nmap(target: str) -> bool:
    """Prefer argv host nmap when HexStrike would split a Windows NIC name like Ethernet 2."""
    return lan_uses_host_iface_argv(target)


def lan_uses_host_iface_argv(target: str) -> bool:
    """True when the on-link NIC name would be split by HexStrike additional_args.split()."""
    iface, source = lan_bind_nic(target)
    return bool(iface) and bool(source) and not hexstrike_nmap_can_bind_interface(iface)


def nmap_lan_additional_args(target: str, base: str = "-T3") -> str:
    """HexStrike nmap additional_args: timing plus source bind.

    Interface names with whitespace are omitted from the string payload (HexStrike
    splits additional_args). LAN inventory then uses host nmap argv so ``-e`` still
    binds that NIC. ``-S`` remains on the suite string when the scan still goes
    through HexStrike.
    """
    iface, source = lan_scan_bind(target)
    parts = [str(base or "").strip()]
    if source:
        parts.extend(["-S", source])
    if hexstrike_nmap_can_bind_interface(iface):
        parts.extend(["-e", iface])
    return " ".join(part for part in parts if part)


def looks_like_nmap_tool(name: str) -> bool:
    """HexStrike MCP/HTTP ids such as ``mcp_hexstrike_ai_nmap`` or ``http:nmap``."""
    return hexstrike_tool_stem(name) == "nmap"


def hexstrike_tool_stem(name: str) -> str:
    """Last path/id segment: ``http:nuclei`` / ``api/tools/httpx`` / ``mcp_hexstrike_ai_naabu``."""
    text = str(name or "").strip().lower().replace("-", "_")
    if not text:
        return ""
    if "/" in text:
        text = text.rsplit("/", 1)[-1]
    if ":" in text:
        text = text.rsplit(":", 1)[-1]
    if "_" in text:
        text = text.rsplit("_", 1)[-1]
    return text


def hexstrike_lan_tool_id(tool: str) -> str:
    """Stem that keeps hyphenated LAN tools such as ``arp-scan`` (not last token ``scan``)."""
    text = str(tool or "").strip().lower().replace("-", "_")
    if "/" in text:
        text = text.rsplit("/", 1)[-1]
    if ":" in text:
        text = text.rsplit(":", 1)[-1]
    from ..tools.lan_snmp import SNMP_TOOL_STEMS

    for ident in ("arp_scan", *sorted(SNMP_TOOL_STEMS)):
        if text == ident or text.endswith(f"_{ident}"):
            return ident
    return hexstrike_tool_stem(tool)


def looks_like_snmp_tool(name: str) -> bool:
    """HexStrike MCP/HTTP ids such as ``mcp_hexstrike_ai_snmpwalk`` or ``http:snmpget``."""
    from ..tools.lan_snmp import SNMP_TOOL_STEMS

    return hexstrike_lan_tool_id(name) in SNMP_TOOL_STEMS


_SMB_TOOL_STEMS = frozenset({"smbclient", "smbget", "rpcclient", "smbtree"})


def looks_like_smb_tool(name: str) -> bool:
    """HexStrike MCP/HTTP ids such as ``mcp_hexstrike_ai_smbclient`` or ``http:smbget``."""
    return hexstrike_lan_tool_id(name) in _SMB_TOOL_STEMS


def looks_like_iface_host_tool(name: str) -> bool:
    """LAN scanners whose iface flags cannot round-trip a spaced Windows NIC name."""
    return hexstrike_lan_tool_id(name) in _IFACE_HOST_STEMS


def nmap_target_from_payload(payload: dict[str, Any] | None) -> str:
    row = payload if isinstance(payload, dict) else {}
    for key in ("target", "host", "ip", "address"):
        text = str(row.get(key) or "").strip()
        if text:
            return text
    return ""


def bindable_lan_host(raw: str) -> str:
    """Hostname/CIDR HexStrike can bind: URLs and ``host:port`` become the host."""
    text = str(raw or "").strip()
    if not text:
        return ""
    if "://" in text:
        return (urlparse(text).hostname or "").strip()
    if text.startswith("[") and "]" in text:
        return text[1 : text.index("]")]
    if "/" in text:
        return text
    if text.count(":") == 1:
        host, port = text.rsplit(":", 1)
        if port.isdigit():
            return host
    return text


def lan_bind_target(payload: dict[str, Any] | None) -> str:
    row = payload if isinstance(payload, dict) else {}
    raw = nmap_target_from_payload(row)
    if not raw:
        for key in ("url", "uri", "endpoint"):
            text = str(row.get(key) or "").strip()
            if text:
                raw = text
                break
    if not raw:
        urls = row.get("urls")
        if isinstance(urls, str) and urls.strip():
            raw = urls.strip()
        elif isinstance(urls, list):
            for item in urls:
                text = str(item or "").strip()
                if text:
                    raw = text
                    break
    return bindable_lan_host(raw)


_IPV4_IN_TEXT = re.compile(r"(?<![\d])(\d{1,3}(?:\.\d{1,3}){3}(?:/\d{1,2})?)(?![\d])")


def ipv4_or_lan_host_from_tokens(tokens: list[str]) -> str:
    """First RFC1918-looking IPv4, CIDR, or ``.local``/``.lan`` name in argv tokens."""
    for item in tokens:
        text = str(item or "").strip().strip("'\"")
        if not text:
            continue
        host = text.split("%", 1)[0]
        if re.fullmatch(r"\d{1,3}(?:\.\d{1,3}){3}(?:/\d{1,2})?(?::\d+)?", host):
            return host.split(":", 1)[0]
        lowered = host.lower().rstrip(".")
        if lowered.endswith((".local", ".lan", ".home.arpa")):
            return host.split(":", 1)[0] if host.count(":") == 1 and host.rsplit(":", 1)[-1].isdigit() else host
        match = _IPV4_IN_TEXT.search(text)
        if match:
            return match.group(1)
    return ""


def _hexstrike_args_key(payload: dict[str, Any]) -> str:
    for key in ("additional_args", "extra_args", "args"):
        if key in payload:
            return key
    return "additional_args"


def bind_hexstrike_nmap_payload(payload: dict[str, Any] | None) -> dict[str, Any]:
    """Pin HexStrike operator nmap of an on-link RFC1918 target to that NIC."""
    return bind_hexstrike_lan_payload("nmap", payload)


_PD_SOURCE_TOOLS = frozenset({"nuclei", "httpx", "naabu"})
# Tools with no source-bind CLI: forward HTTP through the process-local LAN proxy.
_HTTP_PROXY_FLAG = {
    "gobuster": "--proxy",
    "ffuf": "-x",
    "dirsearch": "--proxy",
    "feroxbuster": "--proxy",
    "sqlmap": "--proxy",
    "nikto": "-useproxy",
    "katana": "-proxy",
    "whatweb": "--proxy",
    "wpscan": "--proxy",
    "wafw00f": "--proxy",
    "wfuzz": "-p",
    "arjun": "--proxy",
    "gau": "--proxy",
    "dalfox": "--proxy",
}
_HTTP_PROXY_SKIP = {
    "gobuster": frozenset({"-p", "--proxy"}),
    "ffuf": frozenset({"-x"}),
    "dirsearch": frozenset({"--proxy"}),
    "feroxbuster": frozenset({"-p", "--proxy", "--replay-proxy"}),
    "sqlmap": frozenset({"--proxy"}),
    "nikto": frozenset({"-useproxy", "--useproxy"}),
    "katana": frozenset({"-proxy", "-p"}),
    "whatweb": frozenset({"--proxy"}),
    "wpscan": frozenset({"--proxy"}),
    "wafw00f": frozenset({"-p", "--proxy"}),
    "wfuzz": frozenset({"-p"}),
    "arjun": frozenset({"-p", "--proxy"}),
    "gau": frozenset({"--proxy"}),
    "dalfox": frozenset({"--proxy"}),
}
_PROXY_HOST_PORT = frozenset({"whatweb", "wfuzz"})
_CAPTURE_STEMS = frozenset({"tcpdump", "tshark", "dumpcap"})
_HPING_STEMS = frozenset({"hping", "hping3"})
_ARP_HOST_STEMS = frozenset({"arp_scan", "arping", "fping", "nmblookup"})
_SCAN_HOST_STEMS = _PD_SOURCE_TOOLS | frozenset({"masscan", "rustscan"})
_IFACE_HOST_STEMS = _CAPTURE_STEMS | _HPING_STEMS | _ARP_HOST_STEMS | _SCAN_HOST_STEMS
_IFACE_HOST_BINARY = {"arp_scan": "arp-scan"}
_IFACE_STRIP_FLAGS = {
    "arp_scan": frozenset({"-i", "--interface", "-I", "--arpspa", "--localip"}),
    "arping": frozenset({"-i", "--interface", "-I", "-s"}),
    "fping": frozenset({"-i", "--interface", "-I", "-S"}),
    "nmblookup": frozenset({"-i", "--interface", "-I", "-B", "--broadcast"}),
    "nuclei": frozenset({"-source-ip", "-interface", "--interface"}),
    "httpx": frozenset({"-source-ip", "-interface", "--interface"}),
    "naabu": frozenset({"-source-ip", "-interface", "--interface"}),
    "masscan": frozenset({"--source-ip", "-e", "-S", "--adapter-ip"}),
    "rustscan": frozenset({"-S", "-e", "-interface", "--interface"}),
    "smbclient": frozenset({"--option", "-s", "--configfile"}),
    "smbget": frozenset({"--option", "-s", "--configfile"}),
    "rpcclient": frozenset({"--option", "-s", "--configfile"}),
    "smbtree": frozenset({"--option", "-s", "--configfile"}),
}


def _proxy_arg_value(stem: str, origin: str) -> str:
    if stem not in _PROXY_HOST_PORT:
        return origin
    from urllib.parse import urlparse

    parsed = urlparse(origin)
    host = parsed.hostname or "127.0.0.1"
    port = parsed.port or 80
    return f"{host}:{port}"


def _tokens_have_flag(tokens: list[str], names: frozenset[str]) -> bool:
    for token in tokens:
        key = str(token).split("=", 1)[0]
        if key in names:
            return True
    return False


def bind_hexstrike_lan_payload(tool: str, payload: dict[str, Any] | None) -> dict[str, Any]:
    """Pin HexStrike LAN scanners to this PC's on-link RFC1918 NIC.

    nmap uses ``-S``/``-e``. ProjectDiscovery nuclei/httpx/naabu use ``-source-ip``
    / ``-interface``. masscan uses ``--source-ip``/``-e``. curl uses ``--interface``.
    wget uses ``--bind-address``. rustscan forwards nmap ``-S``/``-e`` after ``--``.
    arp-scan uses ``--arpspa``/``-I``; arping ``-s``/``-I``; fping ``-S``/``-I``.
    iperf/iperf3 use ``-B``. mtr uses ``-a``. nmblookup uses ``-B``/``-i``.
    tcpdump/tshark/dumpcap use ``-i``. hping3 uses ``-I``. When the Windows NIC
    name has a space, HexStrike ``additional_args.split()`` cannot round-trip
    ``-i``/``-I``/``-e``/``-interface``; operator/MCP host-execute argv for
    capture, hping3, arp-scan, arping, fping, nmblookup, nuclei, httpx, naabu,
    masscan, and rustscan when the binary is on PATH (else the suite keeps
    source-IP flags).
    snmpwalk has no bind flag; LAN operator/MCP calls host-execute with
    ``SNMPCONFPATH`` ``clientaddr``.
    smbclient/smbget/rpcclient/smbtree use ``--option=client addr=`` as one argv
    token (HexStrike ``additional_args.split()`` cannot round-trip the space);
    operator/MCP host-execute when the binary is on PATH.
    gobuster/ffuf/dirsearch/feroxbuster/sqlmap/nikto/katana/whatweb/wpscan/wafw00f/
    wfuzz/arjun/gau/dalfox have no source-bind CLI; they get a loopback LAN proxy
    flag. Public internet targets are left unchanged. Spaced Windows NIC names
    omit ``-interface``/``-e``/``-I``/``-i`` (HexStrike ``additional_args.split()``).
    """
    bound = dict(payload or {})
    stem = hexstrike_lan_tool_id(tool)
    if stem == "nmap" or looks_like_nmap_tool(tool):
        target = nmap_target_from_payload(bound)
        if not lan_scan_bind(target)[1]:
            return bound
        existing = str(bound.get("additional_args") or "").strip() or "-T3"
        tokens = existing.split()
        if "-S" in tokens:
            bound["additional_args"] = existing
            return bound
        bound["additional_args"] = nmap_lan_additional_args(target, base=existing)
        return bound

    target = lan_bind_target(bound)
    if stem == "nmblookup" and not lan_bind_nic(target)[1]:
        host = (target or "").strip()
        if not host or host == "*":
            target = preferred_lan_bind_target()
        else:
            try:
                ipaddress.ip_address(host)
            except ValueError:
                if "." not in host:
                    target = preferred_lan_bind_target()
    if stem in _CAPTURE_STEMS and not lan_bind_nic(target)[1]:
        maybe = ipv4_or_lan_host_from_tokens(
            str(bound.get(_hexstrike_args_key(bound)) or "").split()
        )
        if maybe:
            target = maybe
    iface, source = lan_bind_nic(target)
    if not source:
        return bound
    key = _hexstrike_args_key(bound)
    existing = str(bound.get(key) or "").strip()
    tokens = existing.split()
    flags: list[str] = []
    if stem in _PD_SOURCE_TOOLS:
        if "-source-ip" in tokens:
            return bound
        flags.extend(["-source-ip", source])
        if hexstrike_nmap_can_bind_interface(iface) and "-interface" not in tokens:
            flags.extend(["-interface", iface])
    elif stem == "masscan":
        if "--source-ip" in tokens:
            return bound
        flags.extend(["--source-ip", source])
        if hexstrike_nmap_can_bind_interface(iface) and "-e" not in tokens:
            flags.extend(["-e", iface])
    elif stem == "curl":
        if "--interface" in tokens or "--local-addr" in tokens:
            return bound
        flags.extend(
            ["--interface", iface if hexstrike_nmap_can_bind_interface(iface) else source]
        )
    elif stem == "wget":
        if _tokens_have_flag(tokens, frozenset({"--bind-address", "--bindaddress"})):
            return bound
        flags.append(f"--bind-address={source}")
    elif stem == "rustscan":
        if "-S" in tokens:
            return bound
        extra: list[str] = []
        if source:
            extra.extend(["-S", source])
        if hexstrike_nmap_can_bind_interface(iface) and "-e" not in tokens:
            extra.extend(["-e", iface])
        if extra:
            flags.extend(["--", *extra] if "--" not in tokens else extra)
    elif stem == "arp_scan":
        if _tokens_have_flag(tokens, frozenset({"-I", "--interface", "--arpspa", "--localip"})):
            return bound
        flags.extend(["--arpspa", source])
        if hexstrike_nmap_can_bind_interface(iface) and "-I" not in tokens:
            flags.extend(["-I", iface])
    elif stem == "arping":
        if _tokens_have_flag(tokens, frozenset({"-I", "-i", "-s"})):
            return bound
        flags.extend(["-s", source])
        if hexstrike_nmap_can_bind_interface(iface) and "-I" not in tokens:
            flags.extend(["-I", iface])
    elif stem == "fping":
        if _tokens_have_flag(tokens, frozenset({"-I", "-S"})):
            return bound
        flags.extend(["-S", source])
        if hexstrike_nmap_can_bind_interface(iface) and "-I" not in tokens:
            flags.extend(["-I", iface])
    elif stem in {"iperf", "iperf3"}:
        if _tokens_have_flag(tokens, frozenset({"-B", "--bind"})):
            return bound
        flags.extend(["-B", source])
    elif stem == "mtr":
        if _tokens_have_flag(tokens, frozenset({"-a", "--address"})):
            return bound
        flags.extend(["-a", source])
    elif stem == "nmblookup":
        if _tokens_have_flag(tokens, frozenset({"-i", "-B", "--broadcast"})):
            return bound
        _iface, _source, broadcast = lan_nic_detail(target)
        if broadcast:
            flags.extend(["-B", broadcast])
        if hexstrike_nmap_can_bind_interface(iface) and "-i" not in tokens:
            flags.extend(["-i", iface])
        if not flags:
            return bound
    elif stem in _CAPTURE_STEMS:
        if _tokens_have_flag(tokens, frozenset({"-i", "--interface"})):
            return bound
        if not hexstrike_nmap_can_bind_interface(iface):
            return bound
        flags.extend(["-i", iface])
    elif stem in _HPING_STEMS:
        if _tokens_have_flag(tokens, frozenset({"-I", "--interface"})):
            return bound
        if not hexstrike_nmap_can_bind_interface(iface):
            return bound
        flags.extend(["-I", iface])
    elif stem in _HTTP_PROXY_FLAG:
        skip = _HTTP_PROXY_SKIP.get(stem, frozenset({"--proxy", "-x"}))
        if _tokens_have_flag(tokens, skip):
            return bound
        from .lan_http_proxy import ensure_lan_http_proxy

        origin = ensure_lan_http_proxy()
        flags.extend([_HTTP_PROXY_FLAG[stem], _proxy_arg_value(stem, origin)])
    else:
        return bound
    bound[key] = " ".join([*tokens, *flags]).strip()
    return bound


_NMAP_FLAG = re.compile(r"^--?[A-Za-z0-9][A-Za-z0-9_-]*$")
_NMAP_UNSAFE = re.compile(r"[;&|`$<>\n]")


def _nmap_flag_tokens(raw: str) -> list[str]:
    text = str(raw or "").strip()
    if not text:
        return []
    parts = shlex.split(text, posix=True)
    if any(_NMAP_UNSAFE.search(part) for part in parts):
        raise ValueError("nmap arguments contain unsafe shell characters")
    return parts


def _strip_nmap_bind_tokens(parts: list[str]) -> list[str]:
    out: list[str] = []
    index = 0
    while index < len(parts):
        if parts[index] in {"-S", "-e"} and index + 1 < len(parts):
            index += 2
            continue
        out.append(parts[index])
        index += 1
    return out


def _strip_iface_tokens(parts: list[str], stem: str = "") -> list[str]:
    skip = _IFACE_STRIP_FLAGS.get(stem, frozenset({"-i", "--interface", "-I"}))
    out: list[str] = []
    index = 0
    while index < len(parts):
        token = str(parts[index])
        key = token.split("=", 1)[0]
        if key in skip:
            if "=" in token:
                index += 1
                continue
            index += 2
            continue
        out.append(parts[index])
        index += 1
    return out


def _iface_host_binary(stem: str) -> str | None:
    name = _IFACE_HOST_BINARY.get(stem, stem)
    found = shutil.which(name) or shutil.which(f"{name}.exe")
    if found:
        return found
    folders: list[Path] = []
    try:
        from .hexstrike import resolve_install

        root = resolve_install()
    except Exception:
        root = None
    if root is not None:
        folders.extend(
            [
                root / "hexstrike-env" / "Scripts",
                root / "hexstrike-env" / "bin",
                root / ".venv" / "Scripts",
                root / ".venv" / "bin",
                root,
            ]
        )
    folders.append(Path.home() / "go" / "bin")
    for folder in folders:
        for candidate in (folder / name, folder / f"{name}.exe"):
            try:
                if candidate.is_file():
                    return str(candidate)
            except OSError:
                continue
    return None


def should_host_exec_iface(tool: str, target: str) -> bool:
    """Host argv when HexStrike would split a spaced NIC, and the binary is runnable."""
    if not lan_uses_host_iface_argv(target):
        return False
    stem = hexstrike_lan_tool_id(tool)
    if stem not in _IFACE_HOST_STEMS:
        return False
    if stem in _SCAN_HOST_STEMS and not _iface_host_binary(stem):
        return False
    return True


def _iface_host_bind_flags(stem: str, target: str, iface: str, source: str) -> list[str]:
    if stem in _PD_SOURCE_TOOLS:
        return ["-source-ip", source, "-interface", iface]
    if stem == "masscan":
        return ["--source-ip", source, "-e", iface]
    if stem == "rustscan":
        return ["-S", source, "-e", iface]
    if stem == "arp_scan":
        return ["--arpspa", source, "-I", iface]
    if stem == "arping":
        return ["-s", source, "-I", iface]
    if stem == "fping":
        return ["-S", source, "-I", iface]
    if stem == "nmblookup":
        _iface, _source, broadcast = lan_nic_detail(target)
        flags: list[str] = []
        if broadcast:
            flags.extend(["-B", broadcast])
        flags.extend(["-i", iface])
        return flags
    if stem in _HPING_STEMS:
        return ["-I", iface]
    return ["-i", iface]


def _iface_cli_target(payload: dict[str, Any] | None, stem: str) -> str:
    row = payload if isinstance(payload, dict) else {}
    if stem in _PD_SOURCE_TOOLS:
        for key in ("url", "uri", "endpoint", "target", "host", "ip", "address"):
            text = str(row.get(key) or "").strip()
            if text:
                return text
    return _iface_lan_target(row)


async def _host_nmap_lan_scan(payload: dict[str, Any]) -> dict[str, Any]:
    """Host nmap argv for a private LAN target, including spaced Windows NIC names."""
    cleaned = _require_private_lan_target(nmap_target_from_payload(payload) or str(payload.get("target") or ""))
    binary = shutil.which("nmap")
    if not binary:
        raise RuntimeError(
            "HexStrike cannot bind this Windows NIC name through additional_args.split(), "
            "and nmap is not on PATH. Install nmap to scan the private LAN."
        )
    scan_tokens = _nmap_flag_tokens(str(payload.get("scan_type") or "-sn"))
    if scan_tokens and not all(_NMAP_FLAG.fullmatch(token) for token in scan_tokens):
        raise ValueError("nmap scan_type must be nmap flags")
    extra = _strip_nmap_bind_tokens(_nmap_flag_tokens(str(payload.get("additional_args") or "")))
    argv = [binary, *scan_tokens, *extra, *nmap_lan_bind_args(cleaned)]
    ports = str(payload.get("ports") or "").strip()
    if ports:
        if _NMAP_UNSAFE.search(ports) or not re.fullmatch(r"[0-9,\-T:]+", ports):
            raise ValueError("nmap ports are invalid")
        argv.extend(["-p", ports])
    argv.extend(["--", cleaned])
    proc = await asyncio.create_subprocess_exec(
        *argv,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    try:
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=180)
    except TimeoutError as exc:
        proc.kill()
        await proc.wait()
        raise RuntimeError("host nmap LAN scan timed out") from exc
    text = (stdout or b"").decode("utf-8", errors="replace")
    err = (stderr or b"").decode("utf-8", errors="replace")
    if proc.returncode not in {0, 1}:
        raise RuntimeError((err or text or "nmap failed").strip()[:400])
    return {
        "source": "host-nmap",
        "target": cleaned,
        "hosts": parse_nmap_ping_hosts(text),
        "stdout": text[:4000],
    }


async def execute_operator_nmap(payload: dict[str, Any] | None) -> dict[str, Any]:
    """Operator ``api/tools/nmap``: bind the home LAN NIC; host argv when HexStrike would split ``-e``."""
    bound = bind_hexstrike_nmap_payload(payload)
    target = nmap_target_from_payload(bound)
    if lan_inventory_uses_host_nmap(target):
        return await _host_nmap_lan_scan({**bound, "target": target})
    return await HEXSTRIKE.post_operator("api/tools/nmap", bound)


def snmp_host_argv(tool: str, payload: dict[str, Any] | None) -> list[str]:
    """Host snmpwalk argv for an on-link RFC1918 peer (HexStrike cannot set SNMPCONFPATH)."""
    from ..tools.lan_snmp import SNMP_TOOL_STEMS

    row = payload if isinstance(payload, dict) else {}
    stem = hexstrike_lan_tool_id(tool)
    if stem not in SNMP_TOOL_STEMS:
        stem = "snmpwalk"
    binary = shutil.which(stem) or shutil.which(f"{stem}.exe")
    if not binary:
        raise RuntimeError(
            f"{stem} is not on PATH. Install net-snmp so HexStrike LAN SNMP can bind the home NIC."
        )
    target = lan_bind_target(row) or nmap_target_from_payload(row)
    if not lan_bind_nic(target)[1]:
        raise ValueError("snmp LAN target is required")
    extra = _nmap_flag_tokens(str(row.get("additional_args") or row.get("extra_args") or row.get("args") or ""))
    community = str(row.get("community") or "").strip()
    if community:
        if not re.fullmatch(r"[A-Za-z0-9._:-]{1,64}", community):
            raise ValueError("snmp community is invalid")
        if "-c" not in extra:
            extra = [*extra, "-c", community]
    oid = str(row.get("oid") or row.get("object") or "").strip()
    if oid and not re.fullmatch(r"[A-Za-z0-9._:-]+", oid):
        raise ValueError("snmp oid is invalid")
    argv = [binary, *extra]
    if target not in extra:
        argv.append(target)
    if oid:
        argv.append(oid)
    return argv


async def _host_snmp_lan(tool: str, payload: dict[str, Any] | None) -> dict[str, Any]:
    """Host net-snmp of an on-link RFC1918 peer with ``clientaddr`` on the home NIC."""
    from ..tools.lan_snmp import snmp_lan_child_env

    argv = snmp_host_argv(tool, payload)
    env = snmp_lan_child_env(argv)
    target = lan_bind_target(payload) or nmap_target_from_payload(payload)
    proc = await asyncio.create_subprocess_exec(
        *argv,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        env=env,
    )
    try:
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=180)
    except TimeoutError as exc:
        proc.kill()
        await proc.wait()
        raise RuntimeError("host snmp LAN walk timed out") from exc
    text = (stdout or b"").decode("utf-8", errors="replace")
    err = (stderr or b"").decode("utf-8", errors="replace")
    if proc.returncode not in {0, 1}:
        raise RuntimeError((err or text or "snmp failed").strip()[:400])
    return {
        "source": "host-snmp",
        "target": target,
        "stdout": text[:4000],
        "stderr": err[:800],
    }


async def execute_operator_snmp(path: str, payload: dict[str, Any] | None) -> dict[str, Any]:
    """Operator snmpwalk of on-link RFC1918: host argv + SNMPCONFPATH, not the suite env."""
    bound = dict(payload or {})
    target = lan_bind_target(bound) or nmap_target_from_payload(bound)
    if not lan_bind_nic(target)[1]:
        from .hexstrike import normalize_upstream_path

        return await HEXSTRIKE.post_operator(normalize_upstream_path(path), bound)
    return await _host_snmp_lan(path, bound)


def _smb_host_binary(stem: str) -> str | None:
    name = stem if stem in _SMB_TOOL_STEMS else "smbclient"
    return shutil.which(name) or shutil.which(f"{name}.exe")


def _smb_payload_host(payload: dict[str, Any] | None) -> str:
    row = payload if isinstance(payload, dict) else {}
    target = lan_bind_target(row) or nmap_target_from_payload(row)
    if target:
        return target
    for key in ("share", "url"):
        raw = str(row.get(key) or "").strip()
        if not raw:
            continue
        if raw.startswith("//"):
            return raw[2:].split("/", 1)[0].split("\\", 1)[0]
        if raw.startswith("\\\\"):
            return raw[2:].split("\\", 1)[0].split("/", 1)[0]
        return bindable_lan_host(raw) or raw
    return ""


def smb_host_argv(tool: str, payload: dict[str, Any] | None) -> list[str]:
    """Host smbclient argv with ``client addr`` as one token (HexStrike would split it)."""
    row = payload if isinstance(payload, dict) else {}
    stem = hexstrike_lan_tool_id(tool)
    if stem not in _SMB_TOOL_STEMS:
        stem = "smbclient"
    binary = _smb_host_binary(stem)
    if not binary:
        raise RuntimeError(
            f"{stem} is not on PATH. Install Samba so HexStrike LAN SMB can bind the home NIC."
        )
    target = _smb_payload_host(row)
    if stem == "smbtree" and not lan_bind_nic(target)[1]:
        target = preferred_lan_bind_target()
    _iface, source = lan_bind_nic(target)
    if not source:
        raise ValueError("smb LAN target is required")
    extra = _strip_iface_tokens(
        _nmap_flag_tokens(str(row.get("additional_args") or row.get("extra_args") or row.get("args") or "")),
        stem=stem,
    )
    blob = " ".join(extra)
    display = ""
    for key in ("url", "share", "target", "host", "ip", "address"):
        text = str(row.get(key) or "").strip()
        if text:
            display = text
            break
    if not display:
        display = target
    if display and display not in blob and stem != "smbtree":
        inserted = False
        for flag in ("-L", "--list"):
            if flag in extra:
                idx = extra.index(flag)
                nxt = extra[idx + 1] if idx + 1 < len(extra) else ""
                if not nxt or str(nxt).startswith("-"):
                    extra = extra[: idx + 1] + [display] + extra[idx + 1 :]
                    inserted = True
                break
        if not inserted:
            extra = [*extra, display]
    return [binary, f"--option=client addr={source}", *extra]


async def _host_smb_lan(tool: str, payload: dict[str, Any] | None) -> dict[str, Any]:
    """Host Samba of an on-link RFC1918 NAS with ``client addr`` on the home NIC."""
    argv = smb_host_argv(tool, payload)
    proc = await asyncio.create_subprocess_exec(
        *argv,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    try:
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=180)
    except TimeoutError as exc:
        proc.kill()
        await proc.wait()
        raise RuntimeError("host smb LAN call timed out") from exc
    text = (stdout or b"").decode("utf-8", errors="replace")
    err = (stderr or b"").decode("utf-8", errors="replace")
    if proc.returncode not in {0, 1}:
        raise RuntimeError((err or text or "smb failed").strip()[:400])
    return {
        "source": "host-smb",
        "target": _smb_payload_host(payload),
        "stdout": text[:4000],
        "stderr": err[:800],
    }


async def execute_operator_smb(path: str, payload: dict[str, Any] | None) -> dict[str, Any]:
    """Operator smbclient of on-link RFC1918: host argv so ``client addr`` stays one token."""
    bound = dict(payload or {})
    stem = hexstrike_lan_tool_id(path)
    target = _smb_payload_host(bound)
    if stem == "smbtree" and not lan_bind_nic(target)[1]:
        target = preferred_lan_bind_target()
        bound = {**bound, "target": target}
    from .hexstrike import normalize_upstream_path

    cleaned = path
    try:
        cleaned = normalize_upstream_path(path)
    except ValueError:
        cleaned = f"api/tools/{stem}"
    if not str(cleaned).startswith("api/tools/"):
        cleaned = f"api/tools/{stem}"
    if not lan_bind_nic(target)[1] or not _smb_host_binary(stem):
        return await HEXSTRIKE.post_operator(cleaned, bound)
    return await _host_smb_lan(path, bound)


def _iface_lan_target(payload: dict[str, Any] | None) -> str:
    row = payload if isinstance(payload, dict) else {}
    target = lan_bind_target(row) or nmap_target_from_payload(row)
    if lan_bind_nic(target)[1]:
        return target
    extra = str(row.get(_hexstrike_args_key(row)) or "")
    return ipv4_or_lan_host_from_tokens(extra.split())


def iface_host_argv(tool: str, payload: dict[str, Any] | None) -> list[str]:
    """Host LAN argv that can pass a spaced Windows NIC name as one token."""
    row = payload if isinstance(payload, dict) else {}
    stem = hexstrike_lan_tool_id(tool)
    if stem not in _IFACE_HOST_STEMS:
        stem = "tcpdump"
    binary = _iface_host_binary(stem)
    if not binary:
        display = _IFACE_HOST_BINARY.get(stem, stem)
        raise RuntimeError(
            f"{display} is not on PATH. Install it so HexStrike can bind a Windows NIC name "
            "that additional_args.split() would break."
        )
    target = _iface_lan_target(row)
    iface, source = lan_bind_nic(target)
    if not iface or not source:
        raise ValueError("LAN capture/hping target is required")
    extra = _strip_iface_tokens(
        _nmap_flag_tokens(str(row.get("additional_args") or row.get("extra_args") or row.get("args") or "")),
        stem=stem,
    )
    bind = _iface_host_bind_flags(stem, target, iface, source)
    display_target = _iface_cli_target(row, stem)
    blob = " ".join(extra)
    if stem == "rustscan":
        argv = [binary, *extra]
        if "--" not in extra:
            argv.append("--")
        argv.extend(bind)
        if display_target and display_target not in blob and "-a" not in extra:
            argv[1:1] = ["-a", display_target]
        return argv
    argv = [binary, *bind, *extra]
    if display_target and display_target not in blob:
        if stem in _CAPTURE_STEMS:
            argv.extend(["net" if "/" in display_target else "host", display_target])
        elif stem in _PD_SOURCE_TOOLS:
            flag = "-host" if stem == "naabu" else "-u"
            if flag not in extra and "-target" not in extra:
                argv.extend([flag, display_target])
        else:
            argv.append(display_target)
    return argv


async def _host_iface_lan(tool: str, payload: dict[str, Any] | None) -> dict[str, Any]:
    """Host argv for LAN iface tools when HexStrike would split a spaced NIC name."""
    argv = iface_host_argv(tool, payload)
    proc = await asyncio.create_subprocess_exec(
        *argv,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    try:
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=180)
    except TimeoutError as exc:
        proc.kill()
        await proc.wait()
        raise RuntimeError("host LAN capture timed out") from exc
    text = (stdout or b"").decode("utf-8", errors="replace")
    err = (stderr or b"").decode("utf-8", errors="replace")
    if proc.returncode not in {0, 1}:
        raise RuntimeError((err or text or "capture failed").strip()[:400])
    return {
        "source": "host-iface",
        "target": _iface_lan_target(payload),
        "stdout": text[:4000],
        "stderr": err[:800],
    }


async def execute_operator_iface_tool(path: str, payload: dict[str, Any] | None) -> dict[str, Any]:
    """Operator iface tools: host argv when HexStrike would split ``-i``/``-I``/``-e``."""
    bound = bind_hexstrike_lan_payload(path, payload)
    target = _iface_lan_target(bound)
    if should_host_exec_iface(path, target):
        return await _host_iface_lan(path, bound)
    from .hexstrike import normalize_upstream_path

    cleaned = path
    try:
        cleaned = normalize_upstream_path(path)
    except ValueError:
        cleaned = f"api/tools/{hexstrike_lan_tool_id(path)}"
    if not str(cleaned).startswith("api/tools/"):
        cleaned = f"api/tools/{hexstrike_lan_tool_id(path)}"
    return await HEXSTRIKE.post_operator(cleaned, bound)


def ensure_default_lan_scope() -> dict[str, Any]:
    existing = next(
        (
            row
            for row in list_scopes()
            if row.get("id") == DEFAULT_LAN_SCOPE_ID and row.get("enabled", True)
        ),
        None,
    )
    cidrs = preferred_lan_cidrs()
    if existing and existing.get("kind") in {"private_host", "private_cidr"}:
        value = str(existing.get("value") or "")
        kind = str(existing.get("kind") or "")
        try:
            normalize_scope(kind, value)
        except ValueError:
            existing = None
        else:
            if kind == "private_cidr" and (not cidrs or value != cidrs[0]):
                existing = None
            elif existing is not None:
                _upsert_additional_lan_scopes(cidrs[1:])
                return existing
    if not cidrs:
        raise ValueError("No RFC1918 interface found; register a private LAN scope first")
    row = upsert_scope(
        DEFAULT_LAN_SCOPE_ID,
        kind="private_cidr",
        value=cidrs[0],
        label="This PC's LAN",
        attested_owned=True,
    )
    _upsert_additional_lan_scopes(cidrs[1:])
    return row


def resolve_lan_inventory_scope(scope_id: str) -> str:
    ident = (scope_id or "").strip()
    if not ident or ident in {"default", "local"}:
        return str(ensure_default_lan_scope()["id"])
    try:
        get_scope(ident)
        return ident
    except KeyError:
        if ident == DEFAULT_LAN_SCOPE_ID:
            return str(ensure_default_lan_scope()["id"])
        raise


def list_jobs() -> list[dict[str, Any]]:
    with _LOCK:
        return _read(_JOB_FILE, "jobs")[-100:]


def _save_job(job: dict[str, Any]) -> None:
    with _LOCK:
        rows = [item for item in _read(_JOB_FILE, "jobs") if item.get("id") != job["id"]]
        rows.append(job)
        _write(_JOB_FILE, "jobs", rows[-100:])


def _payload(capability: DefensiveCapability, scope: dict[str, Any], options: dict[str, Any]) -> dict[str, Any]:
    value = str(scope["value"])
    if capability.id == "lan_inventory":
        return {
            "target": value,
            "scan_type": "-sn",
            "ports": "",
            "additional_args": nmap_lan_additional_args(value),
            "use_recovery": False,
        }
    if capability.id == "container_scan":
        return {"target": value, "scan_type": "fs" if scope.get("kind") == "local_path" else "image", "output_format": "json"}
    if capability.id == "iac_scan":
        return {"directory": value, "framework": "all", "output_format": "json"}
    if capability.id == "host_baseline":
        return {"output_file": ""}
    if capability.id == "forensic_inspection":
        return {"file_path": value, "output_format": "json"}
    cve = str(options.get("cve") or "").upper().strip()
    if not _CVE_RE.fullmatch(cve):
        raise ValueError("threat intelligence lookup requires a CVE identifier")
    return {"cve_id": cve}


async def _lookup_cve(cve_id: str) -> dict[str, Any]:
    from ..policy.network_http import gated_get

    response = await gated_get(
        "https://services.nvd.nist.gov/rest/json/cves/2.0",
        tool="web_fetch",
        timeout=30.0,
        params={"cveId": cve_id},
    )
    if response.status_code >= 400:
        raise RuntimeError(f"NVD returned HTTP {response.status_code}")
    body = response.json()
    vulnerabilities = body.get("vulnerabilities", []) if isinstance(body, dict) else []
    if not vulnerabilities:
        raise ValueError(f"No NVD record found for {cve_id}")
    cve = vulnerabilities[0].get("cve", {}) if isinstance(vulnerabilities[0], dict) else {}
    return {"source": "NVD", "cve": cve}


def parse_nmap_ping_hosts(text: str) -> list[dict[str, str]]:
    hosts: list[dict[str, str]] = []
    for line in (text or "").splitlines():
        if not line.startswith("Nmap scan report for "):
            continue
        rest = line[len("Nmap scan report for ") :].strip()
        hostname = ""
        address = rest
        if rest.endswith(")") and " (" in rest:
            hostname, ip_part = rest.rsplit(" (", 1)
            address = ip_part.rstrip(")")
        hosts.append({"address": address, "hostname": hostname})
    return hosts


def _require_private_lan_target(target: str) -> str:
    """Host nmap and suite nmap may only ping RFC1918 / loopback / link-local."""
    cleaned = (target or "").strip()
    if not cleaned:
        raise ValueError("LAN inventory target is required")
    if "/" in cleaned:
        return _private_network(cleaned, host=False)
    return _private_network(cleaned, host=True)


async def _host_nmap_ping_scan(target: str) -> dict[str, Any]:
    cleaned = _require_private_lan_target(target)
    binary = shutil.which("nmap")
    if not binary:
        raise RuntimeError(
            "HexStrike is not running and nmap is not on PATH. "
            "Install HexStrike or nmap to inventory the private LAN."
        )
    proc = await asyncio.create_subprocess_exec(
        binary,
        "-sn",
        "-T3",
        "--max-retries",
        "1",
        *nmap_lan_bind_args(cleaned),
        "--",
        cleaned,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    try:
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=120)
    except TimeoutError as exc:
        proc.kill()
        await proc.wait()
        raise RuntimeError("host nmap ping scan timed out") from exc
    text = (stdout or b"").decode("utf-8", errors="replace")
    err = (stderr or b"").decode("utf-8", errors="replace")
    if proc.returncode not in {0, 1}:
        raise RuntimeError((err or text or "nmap failed").strip()[:400])
    return {
        "source": "host-nmap",
        "target": cleaned,
        "hosts": parse_nmap_ping_hosts(text),
        "stdout": text[:4000],
    }


def lan_inventory_targets(scope: dict[str, Any], payload: dict[str, Any] | None = None) -> list[str]:
    """Default `lan` inventory covers every live RFC1918 NIC CIDR, home subnet first."""
    primary = str((scope or {}).get("value") or (payload or {}).get("target") or "").strip()
    extras: list[str] = []
    if str((scope or {}).get("id") or "") == DEFAULT_LAN_SCOPE_ID:
        extras = preferred_lan_cidrs()
    ordered: list[str] = []
    for item in [primary, *extras]:
        if item and item not in ordered:
            ordered.append(item)
    return ordered


def _merge_lan_inventory_results(results: list[dict[str, Any]], targets: list[str]) -> dict[str, Any]:
    hosts: list[dict[str, str]] = []
    seen: set[str] = set()
    stdout_parts: list[str] = []
    source = ""
    for item in results:
        if not isinstance(item, dict):
            continue
        source = str(item.get("source") or source)
        stdout_parts.append(str(item.get("stdout") or "")[:4000])
        for host in item.get("hosts") or []:
            if not isinstance(host, dict):
                continue
            address = str(host.get("address") or "")
            if not address or address in seen:
                continue
            seen.add(address)
            hosts.append({"address": address, "hostname": str(host.get("hostname") or "")})
    merged: dict[str, Any] = dict(results[0]) if len(results) == 1 and isinstance(results[0], dict) else {}
    merged.update(
        {
            "source": source or merged.get("source") or "host-nmap",
            "target": targets[0] if len(targets) == 1 else ",".join(targets),
            "targets": targets,
            "hosts": hosts if hosts or len(results) > 1 else list(merged.get("hosts") or hosts),
            "stdout": "\n".join(part for part in stdout_parts if part)[:4000] or merged.get("stdout") or "",
        }
    )
    return merged


async def _run_lan_inventory(scope: dict[str, Any], payload: dict[str, Any]) -> dict[str, Any]:
    targets = lan_inventory_targets(scope, payload)
    if not targets:
        raise ValueError("LAN inventory target is required")
    snapshot = await HEXSTRIKE.status(enrich=False)
    if not snapshot.running:
        snapshot = await HEXSTRIKE.ensure_started()
    results: list[dict[str, Any]] = []
    last_error: Exception | None = None
    for target in targets:
        item_payload = {
            **payload,
            "target": target,
            "additional_args": nmap_lan_additional_args(target),
        }
        try:
            if snapshot.running and not lan_inventory_uses_host_nmap(target):
                results.append(await HEXSTRIKE.post_defensive("api/tools/nmap", item_payload))
            else:
                results.append(await _host_nmap_ping_scan(target))
        except Exception as exc:
            last_error = exc
    if not results:
        if last_error is None:
            raise RuntimeError("LAN inventory failed")
        if snapshot.running:
            raise last_error
        suite_err = (snapshot.last_error or "HexStrike is not running").strip()
        raise RuntimeError(f"{suite_err} Host nmap fallback: {last_error}") from last_error
    return _merge_lan_inventory_results(results, targets)


async def execute_defensive(action: str, scope_id: str, options: dict[str, Any] | None = None) -> dict[str, Any]:
    capability = CAPABILITY_BY_ID.get((action or "").strip())
    if capability is None:
        audit_hexstrike("defensive_action_denied", capability=action, reason="unknown_action")
        raise ValueError("unknown defensive action")
    if capability.id == "lan_inventory":
        scope_id = resolve_lan_inventory_scope(scope_id)
    scope = get_scope(scope_id)
    try:
        scope = {
            **scope,
            "value": normalize_scope(str(scope.get("kind") or ""), str(scope.get("value") or "")),
        }
    except ValueError as exc:
        audit_hexstrike("defensive_action_denied", capability=action, scope_id=scope_id, reason="scope_not_private")
        raise PermissionError(str(exc)) from exc
    if scope.get("kind") not in capability.scope_kinds:
        audit_hexstrike("defensive_action_denied", capability=action, scope_id=scope_id, reason="scope_kind")
        raise PermissionError("scope kind is not valid for this defensive action")
    # RFC-0197: default-deny third-party / non-local scopes not in the owner registry.
    # local_infrastructure is this Jarvis host and does not need a registry row.
    from . import security_audit as security_audit_mod
    from . import target_registry as tr

    scope_kind = str(scope.get("kind") or "")
    scope_value = str(scope.get("value") or "")
    if scope_kind != "local_infrastructure" and scope_value:
        # Scopes written before RFC-0197 have no registry row; attested LAN
        # inventory must still run for the owner.
        _mirror_scope_to_target_registry(scope)
        previous_tr = tr.data_dir
        previous_audit = security_audit_mod.data_dir
        tr.data_dir = data_dir
        security_audit_mod.data_dir = data_dir
        try:
            tr.assert_value_allowed(
                scope_value,
                kind=None,
                capability_id=capability.id,
                source="hexstrike_defensive",
            )
        except tr.TargetDenied:
            audit_hexstrike(
                "defensive_action_denied",
                capability=action,
                scope_id=scope_id,
                reason="target_not_registered",
            )
            raise
        finally:
            tr.data_dir = previous_tr
            security_audit_mod.data_dir = previous_audit
    payload = _payload(capability, scope, options or {})
    job = {
        "id": str(uuid.uuid4()),
        "action": capability.id,
        "scope_id": scope_id,
        "status": "running",
        "started_at": _utcnow(),
        "finished_at": None,
        "upstream_pid": None,
        "result": {},
        "error": "",
    }
    _save_job(job)
    audit_hexstrike("defensive_action_started", job_id=job["id"], capability=capability.id, scope_id=scope_id)
    try:
        if capability.id == "threat_intel_lookup":
            result = await _lookup_cve(str(payload["cve_id"]))
        elif capability.id == "lan_inventory":
            result = await _run_lan_inventory(scope, payload)
        else:
            result = await HEXSTRIKE.post_defensive(capability.upstream_path, payload)
        if isinstance(result, dict):
            raw_pid = result.get("pid") or result.get("process_id")
            if isinstance(raw_pid, int):
                job["upstream_pid"] = raw_pid
        job["result"] = result if isinstance(result, dict) else {"value": result}
        job["status"] = "completed"
    except Exception as exc:
        job["status"] = "failed"
        job["error"] = str(exc)[:400]
        raise
    finally:
        job["finished_at"] = _utcnow()
        _save_job(job)
        audit_hexstrike("defensive_action_finished", job_id=job["id"], status=job["status"])
    return job


async def stop_managed_job(job_id: str) -> dict[str, Any]:
    job = next((item for item in list_jobs() if item.get("id") == job_id), None)
    if job is None:
        audit_hexstrike("managed_stop_denied", job_id=job_id, reason="unknown_job")
        raise KeyError(job_id)
    pid = job.get("upstream_pid")
    if not isinstance(pid, int) or pid <= 0:
        audit_hexstrike("managed_stop_denied", job_id=job_id, reason="untracked_pid")
        raise PermissionError("only tracked running HexStrike jobs can be stopped")
    result = await HEXSTRIKE.post_defensive(f"api/processes/terminate/{pid}", {})
    job["status"] = "stopped"
    job["finished_at"] = _utcnow()
    job["result"] = result if isinstance(result, dict) else {"value": result}
    _save_job(job)
    audit_hexstrike("managed_job_stopped", job_id=job_id, pid=pid)
    return job


def capability_snapshot() -> list[dict[str, Any]]:
    return [item.as_dict() for item in CAPABILITIES]
