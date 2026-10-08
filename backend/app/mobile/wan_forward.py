"""Owner-opt-in companion WAN reachability: UPnP, SSH reverse tunnel, gateway SSH.

Only TCP 4781 is ever mapped. Owner credentials are required; there is no password
guessing, no admin-UI scraping, and no mapping of 4780 / 8088 / SSH / router admin.
"""
from __future__ import annotations

import asyncio
import ipaddress
import os
import shutil
import socket
import sys
from pathlib import Path
from typing import Any

PORT = 4781
BEACON_PORT = 4782
FIREWALL_RULE_NAME = "Jarvis companion TLS 4781"
FIREWALL_BEACON_RULE_NAME = "Jarvis companion LAN beacon 4782"

WAN_METHODS = frozenset({"auto", "upnp", "ssh_reverse", "gateway_ssh"})
GATEWAY_PROFILES = frozenset({"openwrt_uci"})
_SSH_BINARIES = ("ssh", "ssh.exe")


def is_public_dial_host(host: str) -> bool:
    """True when a companion off-LAN could reasonably dial this name or address."""
    text = (host or "").strip().lower().rstrip(".")
    if not text or "/" in text or "\\" in text or "@" in text or ":" in text:
        return False
    from ..tools.safety import is_owner_local_host

    if is_owner_local_host(text) or text in {"router", "gateway"}:
        return False
    try:
        ip = ipaddress.ip_address(text)
    except ValueError:
        return "." in text
    if ip.version == 4:
        return is_literal_public_ipv4(text)
    return bool(ip.is_global)


def companion_wan_origin(host: str) -> str:
    if not is_public_dial_host(host):
        raise ValueError("Companion WAN origin must be a public hostname or global IPv4, not a LAN address")
    return f"https://{host.strip()}:{PORT}"


def is_literal_public_ipv4(host: str) -> bool:
    """True for a routed public IPv4, including documentation TEST-NET used in tests.

    Excludes RFC1918, loopback, link-local, multicast, and CGNAT. Python marks
    TEST-NET as is_private; companion WAN still treats those as public dials.
    """
    try:
        ip = ipaddress.ip_address((host or "").strip())
    except ValueError:
        return False
    if ip.version != 4 or ip.is_loopback or ip.is_link_local or ip.is_multicast:
        return False
    if is_rfc1918_ipv4(str(ip)):
        return False
    return ip not in ipaddress.ip_network("100.64.0.0/10")


def public_dial_host_for_gateway(configured: str, live_egress: str = "", fallback: str = "") -> str:
    """Keep a DDNS name; prefer live egress over a stale literal public IPv4."""
    named = (configured or "").strip()
    live = (live_egress or "").strip()
    alt = (fallback or "").strip()
    if named and not is_literal_public_ipv4(named) and is_public_dial_host(named):
        return named
    for candidate in (live, alt, named):
        if candidate and (is_public_dial_host(candidate) or is_literal_public_ipv4(candidate)):
            return candidate
    return named or live or alt


def firewall_4781_show_argv() -> list[str]:
    return ["netsh", "advfirewall", "firewall", "show", "rule", f"name={FIREWALL_RULE_NAME}"]


def firewall_4781_add_argv() -> list[str]:
    """Inbound TCP 4781 on every Windows profile.

    Home Wi-Fi is often classified Public on first join. Companion TLS still
    requires device auth; the phone talks only to 4781, never portal 4780.
    """
    return [
        "netsh",
        "advfirewall",
        "firewall",
        "add",
        "rule",
        f"name={FIREWALL_RULE_NAME}",
        "dir=in",
        "action=allow",
        "protocol=TCP",
        f"localport={PORT}",
        "profile=any",
    ]


def firewall_4781_upgrade_argv() -> list[str]:
    return ["netsh", "advfirewall", "firewall", "set", "rule", f"name={FIREWALL_RULE_NAME}", "new", "profile=any"]


def firewall_4782_show_argv() -> list[str]:
    return ["netsh", "advfirewall", "firewall", "show", "rule", f"name={FIREWALL_BEACON_RULE_NAME}"]


def firewall_4782_add_argv() -> list[str]:
    """Inbound UDP 4782 so the phone's LAN scanner can find this PC.

    LanScanner broadcasts probes to this port. Without an inbound rule on a
    Public-profile Wi-Fi network, TCP 4781 is reachable only after the owner
    already typed the LAN IP; beacon discovery never gets a reply.
    """
    return [
        "netsh",
        "advfirewall",
        "firewall",
        "add",
        "rule",
        f"name={FIREWALL_BEACON_RULE_NAME}",
        "dir=in",
        "action=allow",
        "protocol=UDP",
        f"localport={BEACON_PORT}",
        "profile=any",
    ]


def firewall_4782_upgrade_argv() -> list[str]:
    return [
        "netsh",
        "advfirewall",
        "firewall",
        "set",
        "rule",
        f"name={FIREWALL_BEACON_RULE_NAME}",
        "new",
        "profile=any",
    ]


def firewall_4781_covers_all_profiles(show_stdout: str) -> bool:
    text = (show_stdout or "").lower()
    if "any" in text:
        return True
    return "domain" in text and "private" in text and "public" in text


def _ensure_windows_firewall_rule(
    name: str,
    show_argv: list[str],
    add_argv: list[str],
    upgrade_argv: list[str],
) -> str:
    if os.name != "nt":
        return "skipped"
    import subprocess

    check = subprocess.run(
        show_argv,
        capture_output=True,
        text=True,
        timeout=8,
        check=False,
    )
    stdout = check.stdout or ""
    if check.returncode == 0 and name.lower() in stdout.lower():
        if firewall_4781_covers_all_profiles(stdout):
            return "present"
        upgraded = subprocess.run(
            upgrade_argv,
            capture_output=True,
            text=True,
            timeout=8,
            check=False,
        )
        if upgraded.returncode == 0:
            return "upgraded"
        return f"failed:{(upgraded.stderr or upgraded.stdout or '').strip()[:160]}"
    added = subprocess.run(
        add_argv,
        capture_output=True,
        text=True,
        timeout=8,
        check=False,
    )
    if added.returncode != 0:
        return f"failed:{(added.stderr or added.stdout or '').strip()[:160]}"
    return "added"


def ensure_private_firewall_4781() -> str:
    """Allow inbound TCP 4781 on every Windows firewall profile."""
    return _ensure_windows_firewall_rule(
        FIREWALL_RULE_NAME,
        firewall_4781_show_argv(),
        firewall_4781_add_argv(),
        firewall_4781_upgrade_argv(),
    )


def ensure_private_firewall_4782() -> str:
    """Allow inbound UDP 4782 on every Windows firewall profile (LAN beacon)."""
    return _ensure_windows_firewall_rule(
        FIREWALL_BEACON_RULE_NAME,
        firewall_4782_show_argv(),
        firewall_4782_add_argv(),
        firewall_4782_upgrade_argv(),
    )


def ensure_companion_firewall() -> dict[str, str]:
    """TCP 4781 companion TLS plus UDP 4782 LAN beacon, every Windows profile."""
    return {
        "tcp_4781": ensure_private_firewall_4781(),
        "udp_4782": ensure_private_firewall_4782(),
    }


def lookup_egress_ipv4() -> str:
    """Best-effort public IPv4 of this network after a mapping already exists."""
    from ..policy.network_http import gated_get_sync

    urls = ("https://api.ipify.org", "https://ipv4.icanhazip.com")
    last_error: Exception | None = None
    for url in urls:
        try:
            text = gated_get_sync(url, tool="web_fetch", timeout=3.0, trust_env=False).text.strip()
            address = ipaddress.ip_address(text.split()[0])
            if address.version == 4 and is_literal_public_ipv4(str(address)):
                return str(address)
            last_error = ValueError("egress lookup was not a public IPv4")
        except Exception as exc:
            last_error = exc
    raise ValueError(str(last_error) if last_error else "Could not learn public IPv4")


_RFC1918_V4 = (
    ipaddress.ip_network("10.0.0.0/8"),
    ipaddress.ip_network("172.16.0.0/12"),
    ipaddress.ip_network("192.168.0.0/16"),
)
_NOT_INTERNET_V4 = _RFC1918_V4 + (
    ipaddress.ip_network("100.64.0.0/10"),
    ipaddress.ip_network("127.0.0.0/8"),
    ipaddress.ip_network("169.254.0.0/16"),
)


def is_rfc1918_ipv4(value: str) -> bool:
    """True for 10/8, 172.16/12, 192.168/16 — not CGNAT, loopback, or link-local."""
    try:
        address = ipaddress.ip_address((value or "").strip())
    except ValueError:
        return False
    return address.version == 4 and any(address in net for net in _RFC1918_V4)


def mapping_lan_ipv4(hosts, gateway: str = "") -> str:
    """Dest IP for NAT-PMP / PCP / gateway SSH: RFC1918 on the gateway subnet, never CGNAT.

    ``lan_hosts()`` is lexicographically sorted, so a cellular 100.64 address would
    otherwise beat 192.168 and the inner router would map the wrong interface.
    """
    candidates = [str(host).strip() for host in (hosts or []) if is_rfc1918_ipv4(str(host))]
    if not candidates:
        return ""
    try:
        gw = ipaddress.ip_address((gateway or "").strip())
    except ValueError:
        return candidates[0]
    if gw.version != 4:
        return candidates[0]
    same_24 = ipaddress.ip_network(f"{gw}/24", strict=False)
    for host in candidates:
        if ipaddress.ip_address(host) in same_24:
            return host
    return ""


def interface_ipv4_addresses() -> list[str]:
    """Every non-loopback IPv4 this PC currently holds, including USB ethernet and VPN NICs.

    Hostname lookup plus a UDP connect to 1.1.1.1 only see the default-route
    address. A WireGuard default route would otherwise hide the home LAN IP
    the phone and the IGD both need.
    """
    found: list[str] = []
    seen: set[str] = set()
    try:
        import psutil
    except ImportError:
        return []
    try:
        nics = psutil.net_if_addrs().items()
    except Exception:
        return []
    for _name, addrs in nics:
        for addr in addrs:
            if getattr(addr, "family", None) != socket.AF_INET:
                continue
            ip = (getattr(addr, "address", None) or "").split("%", 1)[0].strip()
            if not ip or ip.startswith("127.") or ip in seen:
                continue
            seen.add(ip)
            found.append(ip)
    return found


def lan_source_ipv4_for_peer(peer: str) -> str:
    """This PC's RFC1918 address on the same network as *peer*.

    web_fetch and other LAN HTTP must source from that NIC. A VPN default
    route would otherwise steal the hop to the NAS or home gateway.
    """
    host = (peer or "").strip().split("%", 1)[0]
    if not host:
        return ""
    try:
        dest = ipaddress.ip_address(host)
    except ValueError:
        return ""
    if dest.version != 4 or not is_rfc1918_ipv4(str(dest)):
        return ""
    matches: list[tuple[int, str]] = []
    try:
        import psutil

        nics = psutil.net_if_addrs().items()
    except Exception:
        return mapping_lan_ipv4(interface_ipv4_addresses(), str(dest))
    for _name, addrs in nics:
        for addr in addrs:
            if getattr(addr, "family", None) != socket.AF_INET:
                continue
            ip_text = (getattr(addr, "address", None) or "").split("%", 1)[0].strip()
            mask = getattr(addr, "netmask", None) or "255.255.255.0"
            try:
                interface = ipaddress.IPv4Interface(f"{ip_text}/{mask}")
            except ValueError:
                continue
            if not is_rfc1918_ipv4(str(interface.ip)):
                continue
            if dest in interface.network or dest == interface.ip:
                matches.append((interface.network.prefixlen, str(interface.ip)))
    if not matches:
        return mapping_lan_ipv4(interface_ipv4_addresses(), str(dest))
    matches.sort(key=lambda item: -item[0])
    return matches[0][1]


def lan_http_bind_for_url(url: str) -> str:
    """Source IPv4 for http(s) to an on-link RFC1918 host, else empty (use default route)."""
    from urllib.parse import urlparse

    host = (urlparse(str(url) or "").hostname or "").strip()
    if not host:
        return ""
    bind = lan_source_ipv4_for_peer(host)
    if bind:
        return bind
    lowered = host.lower().rstrip(".")
    if not (lowered.endswith((".local", ".lan", ".home.arpa")) or "." not in lowered):
        return ""
    try:
        infos = socket.getaddrinfo(host, None, socket.AF_INET, socket.SOCK_STREAM)
    except OSError:
        return ""
    for info in infos:
        ip = ""
        if info and info[4]:
            ip = str(info[4][0] or "")
        bind = lan_source_ipv4_for_peer(ip)
        if bind:
            return bind
    return ""


def mapped_address_is_egress(mapped_ip: str) -> bool:
    """False when an inner router mapped an address that is not the internet egress (double NAT).

    RFC1918, loopback, link-local, and CGNAT mappings are never kept. Documentation
    TEST-NET addresses are treated as comparable public IPs so unit tests can prove
    mismatch. If egress cannot be learned, keep a non-RFC1918 mapping.
    """
    try:
        mapped = ipaddress.ip_address((mapped_ip or "").strip())
    except ValueError:
        return False
    if mapped.version != 4 or any(mapped in net for net in _NOT_INTERNET_V4):
        return False
    try:
        egress = ipaddress.ip_address(lookup_egress_ipv4())
    except Exception:
        return True
    return mapped == egress


def _private_ipv4(value: str) -> str:
    text = (value or "").strip()
    if not is_rfc1918_ipv4(text):
        raise ValueError("Gateway port-forward destination must be a private LAN IPv4 address")
    return text


def ssh_executable() -> str:
    for name in _SSH_BINARIES:
        found = shutil.which(name)
        if found:
            return found
    raise RuntimeError("OpenSSH client is not installed; cannot create an SSH reverse tunnel")


def _proc_net_route_candidates(text: str) -> list[tuple[int, str]]:
    found: list[tuple[int, str]] = []
    lines = (text or "").splitlines()
    for line in lines[1:]:
        parts = line.split()
        if len(parts) < 3 or parts[1] != "00000000":
            continue
        raw = int(parts[2], 16)
        address = ipaddress.IPv4Address(raw.to_bytes(4, "little"))
        if not is_rfc1918_ipv4(str(address)):
            continue
        metric = 0
        if len(parts) > 6:
            try:
                metric = int(parts[6], 0)
            except ValueError:
                metric = 0
        found.append((metric, str(address)))
    return found


def _windows_route_print_candidates(text: str) -> list[tuple[int, str]]:
    found: list[tuple[int, str]] = []
    for line in (text or "").splitlines():
        parts = line.split()
        if len(parts) < 3:
            continue
        if parts[0] != "0.0.0.0" or parts[1] != "0.0.0.0":
            continue
        try:
            address = ipaddress.ip_address(parts[2])
        except ValueError:
            continue
        if address.version != 4 or not is_rfc1918_ipv4(str(address)):
            continue
        metric = 0
        if len(parts) >= 5:
            try:
                metric = int(parts[-1])
            except ValueError:
                metric = 0
        found.append((metric, str(address)))
    return found


def _rfc1918_defaults_ordered(candidates: list[tuple[int, str]]) -> list[str]:
    """Home-LAN first (highest metric), then other RFC1918 defaults; skip duplicates."""
    ordered = sorted(candidates, key=lambda item: (-item[0], item[1]))
    out: list[str] = []
    seen: set[str] = set()
    for _metric, gateway in ordered:
        if gateway in seen:
            continue
        seen.add(gateway)
        out.append(gateway)
    return out


def parse_proc_net_route(text: str) -> str:
    """Home-LAN RFC1918 default gateway from /proc/net/route (skips CGNAT and VPN steal-default)."""
    return _home_lan_default_gateway(_proc_net_route_candidates(text))


def parse_proc_net_route_gateways(text: str) -> list[str]:
    return _rfc1918_defaults_ordered(_proc_net_route_candidates(text))


def parse_windows_route_print(text: str) -> str:
    return _home_lan_default_gateway(_windows_route_print_candidates(text))


def parse_windows_route_print_gateways(text: str) -> list[str]:
    return _rfc1918_defaults_ordered(_windows_route_print_candidates(text))


def _home_lan_default_gateway(candidates: list[tuple[int, str]]) -> str:
    """Pick the on-link home router, not a VPN that stole 0.0.0.0 with metric 0–1."""
    ordered = _rfc1918_defaults_ordered(candidates)
    if not ordered:
        raise ValueError("No private default gateway")
    return ordered[0]


def rfc1918_default_gateways() -> list[str]:
    """RFC1918 default-route gateways, home LAN first, then other on-link routers."""
    if os.name == "nt":
        import subprocess

        printed = subprocess.run(
            ["route", "print", "-4"],
            capture_output=True,
            text=True,
            timeout=8,
            check=False,
        )
        return parse_windows_route_print_gateways((printed.stdout or "") + "\n" + (printed.stderr or ""))
    route = Path("/proc/net/route")
    if route.is_file():
        return parse_proc_net_route_gateways(route.read_text(encoding="utf-8", errors="replace"))
    return []


def default_gateway_ipv4() -> str:
    """Home LAN router — not a VPN that stole the default route with a lower metric."""
    gateways = rfc1918_default_gateways()
    if not gateways:
        raise ValueError("No private default gateway")
    return gateways[0]


def rfc1918_mapping_gateways() -> list[str]:
    """RFC1918 default-route gateways with ``default_gateway_ipv4()`` first.

    Tests that only patch the single-gateway helper still get a candidate, and
    a VPN that stole 0.0.0.0 cannot hide the home LAN router from NAT-PMP or
    OpenWrt SSH.
    """
    gateways: list[str] = []
    try:
        gateways = [item for item in rfc1918_default_gateways() if item]
    except Exception:
        gateways = []
    try:
        primary = default_gateway_ipv4()
    except Exception:
        primary = ""
    if primary:
        gateways = [primary, *[item for item in gateways if item != primary]]
    return gateways


def gateway_ssh_hosts(settings: dict[str, Any]) -> list[str]:
    """Owner-typed gateway, or every RFC1918 default (home LAN first)."""
    host = str(settings.get("gateway_host") or "").strip()
    if host:
        return [host]
    return rfc1918_mapping_gateways()


def resolved_gateway_host(settings: dict[str, Any]) -> str:
    host = str(settings.get("gateway_host") or "").strip()
    return host or default_gateway_ipv4()


def resolved_gateway_user(settings: dict[str, Any]) -> str:
    user = str(settings.get("gateway_user") or settings.get("gateway_username") or "").strip()
    if user:
        return user
    if str(settings.get("gateway_profile") or "openwrt_uci").strip() == "openwrt_uci":
        return "root"
    raise ValueError("Gateway SSH needs a username")


def gateway_ssh_configured(settings: dict[str, Any]) -> bool:
    has_key = bool(str(settings.get("gateway_identity_file") or "").strip())
    has_password = bool(str(settings.get("gateway_password") or "").strip())
    return has_key or has_password


def _identity_args(identity_file: str) -> list[str]:
    path = Path(identity_file or "").expanduser()
    if not str(path) or not path.is_file():
        raise ValueError("SSH identity file is required and must exist")
    return ["-i", str(path)]


_ASKPASS_SOURCE = """import os
import sys

path = os.environ.get("JARVIS_SSH_ASKPASS_FILE", "")
if not path:
    sys.exit(1)
try:
    with open(path, "r", encoding="utf-8") as handle:
        sys.stdout.write(handle.read())
finally:
    try:
        os.remove(path)
    except OSError:
        pass
"""


def ssh_askpass_executable() -> str:
    """Small OpenSSH askpass helper. Never receives the secret on argv."""
    from .store import root as mobile_root

    folder = mobile_root()
    folder.mkdir(parents=True, exist_ok=True)
    script = folder / "ssh-askpass.py"
    body = f"#!{os.path.abspath(sys.executable)}\n{_ASKPASS_SOURCE}"
    if not script.exists() or script.read_text(encoding="utf-8") != body:
        script.write_text(body, encoding="utf-8")
    script.chmod(0o700)
    if os.name == "nt":
        cmd = folder / "ssh-askpass.cmd"
        cmd.write_text(f'@echo off\r\n"{os.path.abspath(sys.executable)}" "{script}"\r\n', encoding="utf-8")
        return str(cmd)
    return str(script)


def prepare_ssh_password_env(password: str) -> tuple[dict[str, str], str]:
    secret = (password or "")
    if not secret:
        raise ValueError("Gateway password is empty")
    import tempfile

    handle, path = tempfile.mkstemp(prefix="jarvis-ssh-askpass-")
    try:
        os.write(handle, secret.encode("utf-8"))
    finally:
        os.close(handle)
    os.chmod(path, 0o600)
    env = os.environ.copy()
    env["DISPLAY"] = env.get("DISPLAY") or "jarvis:0"
    env["SSH_ASKPASS"] = ssh_askpass_executable()
    env["SSH_ASKPASS_REQUIRE"] = "force"
    env["JARVIS_SSH_ASKPASS_FILE"] = path
    env.pop("SSH_AUTH_SOCK", None)
    return env, path


def reverse_tunnel_argv(
    *,
    host: str,
    user: str,
    identity_file: str = "",
    port: int = 22,
    bind_host: str = "0.0.0.0",
    password: str = "",
) -> list[str]:
    """ssh -R 4781:127.0.0.1:4781 so the companion can dial the owner's SSH host."""
    host = (host or "").strip()
    user = (user or "").strip()
    if not host or not user:
        raise ValueError("SSH reverse tunnel needs host and user")
    if not is_public_dial_host(host):
        raise ValueError("SSH reverse tunnel host must be a public hostname or global IPv4")
    if not 1 <= int(port) <= 65535:
        raise ValueError("Invalid SSH port")
    has_key = bool((identity_file or "").strip())
    has_password = bool((password or "").strip())
    if not has_key and not has_password:
        raise ValueError("SSH reverse tunnel needs an identity file or the owner SSH password")
    bind = (bind_host or "0.0.0.0").strip() or "0.0.0.0"
    spec = f"{bind}:{PORT}:127.0.0.1:{PORT}"
    options = [
        "-N",
        "-o",
        "ExitOnForwardFailure=yes",
        "-o",
        "ServerAliveInterval=30",
        "-o",
        "ServerAliveCountMax=3",
        "-o",
        "StrictHostKeyChecking=accept-new",
    ]
    if has_key:
        options = ["-o", "BatchMode=yes", *options, *_identity_args(identity_file)]
    else:
        options += [
            "-o",
            "BatchMode=no",
            "-o",
            "PreferredAuthentications=password,keyboard-interactive",
            "-o",
            "NumberOfPasswordPrompts=1",
        ]
    return [
        ssh_executable(),
        *options,
        "-p",
        str(int(port)),
        "-R",
        spec,
        f"{user}@{host}",
    ]


def openwrt_redirect_script(lan_ip: str) -> str:
    dest = _private_ipv4(lan_ip)
    # Bounded UCI batch: one named redirect for companion TLS only.
    return (
        "set -e\n"
        "uci -q delete firewall.jarvis_companion_4781 || true\n"
        "uci set firewall.jarvis_companion_4781=redirect\n"
        "uci set firewall.jarvis_companion_4781.name='Jarvis companion TLS'\n"
        "uci set firewall.jarvis_companion_4781.src='wan'\n"
        f"uci set firewall.jarvis_companion_4781.src_dport='{PORT}'\n"
        "uci set firewall.jarvis_companion_4781.dest='lan'\n"
        f"uci set firewall.jarvis_companion_4781.dest_ip='{dest}'\n"
        f"uci set firewall.jarvis_companion_4781.dest_port='{PORT}'\n"
        "uci set firewall.jarvis_companion_4781.proto='tcp'\n"
        "uci set firewall.jarvis_companion_4781.target='DNAT'\n"
        "uci set firewall.jarvis_companion_4781.enabled='1'\n"
        "uci set firewall.jarvis_companion_4781.reflection='1'\n"
        "uci set firewall.jarvis_companion_4781.reflection_src='internal'\n"
        "uci commit firewall\n"
        "/etc/init.d/firewall reload\n"
    )


def gateway_ssh_argv(
    *,
    host: str,
    user: str,
    identity_file: str = "",
    lan_ip: str,
    port: int = 22,
    profile: str = "openwrt_uci",
    password: str = "",
) -> list[str]:
    if (profile or "").strip() not in GATEWAY_PROFILES:
        raise ValueError("Unsupported gateway profile; only openwrt_uci is implemented")
    host = (host or "").strip()
    user = (user or "").strip()
    if not host or not user:
        raise ValueError("Gateway SSH needs host and user")
    auth = _identity_args(identity_file) if (identity_file or "").strip() else []
    if not auth and not (password or "").strip():
        raise ValueError("Gateway SSH needs an identity file or the owner router password")
    dest = _private_ipv4(lan_ip)
    script = openwrt_redirect_script(dest)
    options = ["-o", "StrictHostKeyChecking=accept-new"]
    if auth:
        options = ["-o", "BatchMode=yes", *options, *auth]
    else:
        options += [
            "-o",
            "BatchMode=no",
            "-o",
            "PreferredAuthentications=password,keyboard-interactive",
            "-o",
            "NumberOfPasswordPrompts=1",
        ]
    return [
        ssh_executable(),
        "-b",
        dest,
        *options,
        "-p",
        str(int(port)),
        f"{user}@{host}",
        "sh",
        "-s",
        script,
    ]


def redact_wan_config(config: dict[str, Any]) -> dict[str, Any]:
    public = {
        key: value
        for key, value in config.items()
        if key not in {"gateway_password", "ssh_password"}
    }
    if config.get("gateway_password"):
        public["gateway_password_set"] = True
    if config.get("ssh_password"):
        public["ssh_password_set"] = True
    return public


def wan_settings_from_config(config: dict[str, Any]) -> dict[str, Any]:
    method = str(config.get("wan_method") or "auto").strip().lower() or "auto"
    if method not in WAN_METHODS:
        method = "auto"
    return {
        "wan_method": method,
        "ssh_host": str(config.get("ssh_host") or "").strip(),
        "ssh_port": int(config.get("ssh_port") or 22),
        "ssh_user": str(config.get("ssh_user") or "").strip(),
        "ssh_identity_file": str(config.get("ssh_identity_file") or "").strip(),
        "ssh_password": str(config.get("ssh_password") or ""),
        "gateway_host": str(config.get("gateway_host") or "").strip(),
        "gateway_port": int(config.get("gateway_port") or 22),
        "gateway_user": str(config.get("gateway_user") or "").strip(),
        "gateway_identity_file": str(config.get("gateway_identity_file") or "").strip(),
        "gateway_profile": str(config.get("gateway_profile") or "openwrt_uci").strip() or "openwrt_uci",
        "gateway_username": str(config.get("gateway_username") or "").strip(),
        "gateway_password": str(config.get("gateway_password") or ""),
        "wan_public_host": str(config.get("wan_public_host") or "").strip(),
    }


class ReverseTunnel:
    def __init__(self) -> None:
        self.process: asyncio.subprocess.Process | None = None
        self.argv: list[str] = []
        self.endpoint = ""

    async def start(self, argv: list[str], endpoint: str, env: dict[str, str] | None = None) -> None:
        await self.stop()
        self.argv = list(argv)
        self.endpoint = endpoint
        kwargs: dict[str, Any] = {}
        if env is not None:
            kwargs["env"] = env
        self.process = await asyncio.create_subprocess_exec(
            *argv,
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.PIPE,
            stdin=asyncio.subprocess.DEVNULL,
            **kwargs,
        )
        try:
            await asyncio.wait_for(self.process.wait(), timeout=0.4)
        except TimeoutError:
            return
        err = b""
        if self.process.stderr:
            err = await self.process.stderr.read()
        code = self.process.returncode
        self.process = None
        detail = err.decode("utf-8", errors="replace").strip()[:240]
        raise RuntimeError(detail or f"SSH reverse tunnel exited ({code})")

    def alive(self) -> bool:
        return self.process is not None and self.process.returncode is None

    async def stop(self) -> None:
        proc = self.process
        self.process = None
        if proc is None:
            return
        if proc.returncode is None:
            proc.terminate()
            try:
                await asyncio.wait_for(proc.wait(), timeout=3)
            except TimeoutError:
                proc.kill()
                await proc.wait()


REVERSE_TUNNEL = ReverseTunnel()


async def apply_gateway_ssh(settings: dict[str, Any], lan_ip: str, public_host: str = "") -> tuple[str | None, str]:
    password = str(settings.get("gateway_password") or "")
    argv = gateway_ssh_argv(
        host=resolved_gateway_host(settings),
        user=resolved_gateway_user(settings),
        identity_file=str(settings.get("gateway_identity_file") or ""),
        lan_ip=lan_ip,
        port=int(settings.get("gateway_port") or 22),
        profile=str(settings.get("gateway_profile") or "openwrt_uci"),
        password=password,
    )
    env: dict[str, str] | None = None
    secret_path = ""
    if not str(settings.get("gateway_identity_file") or "").strip() and password:
        env, secret_path = prepare_ssh_password_env(password)
    proc: asyncio.subprocess.Process | None = None
    stderr = b""
    try:
        proc = await asyncio.create_subprocess_exec(
            *argv[:-1],
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            env=env,
        )
        _stdout, stderr = await asyncio.wait_for(proc.communicate(argv[-1].encode("utf-8")), timeout=45)
    finally:
        if secret_path:
            try:
                os.remove(secret_path)
            except OSError:
                pass
    if proc is None or proc.returncode != 0:
        detail = (stderr or b"").decode("utf-8", errors="replace").strip()[:240]
        raise RuntimeError(detail or "Gateway SSH port-forward failed")
    host = public_dial_host_for_gateway(
        str(settings.get("wan_public_host") or ""),
        public_host,
    )
    if not is_public_dial_host(host):
        return (
            None,
            "Gateway SSH mapped TCP 4781 on the router. Set a public hostname so the phone can dial it from outside this network.",
        )
    return companion_wan_origin(host), "Gateway SSH mapping applied; verify from outside this network"


async def apply_ssh_reverse(settings: dict[str, Any]) -> str:
    password = str(settings.get("ssh_password") or "")
    identity = str(settings.get("ssh_identity_file") or "")
    argv = reverse_tunnel_argv(
        host=settings["ssh_host"],
        user=settings["ssh_user"],
        identity_file=identity,
        port=int(settings["ssh_port"] or 22),
        password=password,
    )
    endpoint = companion_wan_origin(settings["ssh_host"])
    env: dict[str, str] | None = None
    secret_path = ""
    if not identity.strip() and password:
        env, secret_path = prepare_ssh_password_env(password)
    try:
        await REVERSE_TUNNEL.start(argv, endpoint, env=env)
    except Exception:
        if secret_path:
            try:
                os.remove(secret_path)
            except OSError:
                pass
        raise
    return endpoint
