"""Companion LAN networking helpers: firewall rules, RFC1918 addressing, default gateways.

RFC-0215: off-LAN access is Tailscale only, so no router mapping or tunnel code lives here.
"""
from __future__ import annotations

import ipaddress
import os
import socket
from pathlib import Path

PORT = 4781
BEACON_PORT = 4782
FIREWALL_RULE_NAME = "Jarvis companion TLS 4781"
FIREWALL_BEACON_RULE_NAME = "Jarvis companion LAN beacon 4782"


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


_RFC1918_V4 = (
    ipaddress.ip_network("10.0.0.0/8"),
    ipaddress.ip_network("172.16.0.0/12"),
    ipaddress.ip_network("192.168.0.0/16"),
)


def is_rfc1918_ipv4(value: str) -> bool:
    """True for 10/8, 172.16/12, 192.168/16 — not CGNAT, loopback, or link-local."""
    try:
        address = ipaddress.ip_address((value or "").strip())
    except ValueError:
        return False
    return address.version == 4 and any(address in net for net in _RFC1918_V4)


def mapping_lan_ipv4(hosts, gateway: str = "") -> str:
    """This PC's RFC1918 LAN address on the default gateway's subnet, never CGNAT.

    ``lan_hosts()`` is lexicographically sorted, so a cellular 100.64 address would
    otherwise beat 192.168 and the phone would be given the wrong interface.
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
    the phone needs.
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
    a VPN that stole 0.0.0.0 cannot hide the home LAN router from LAN endpoint
    selection.
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


_ASKPASS_SOURCE = """import os

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


