"""Stdlib IGD/UPnP client for companion TCP 4781 when miniupnpc is missing.

This talks to the owner's Internet Gateway Device with optional HTTP basic
credentials. It does not guess passwords, scan foreign networks, or map any
port other than TCP 4781.
"""
from __future__ import annotations

import ipaddress
import socket
import time
import xml.etree.ElementTree as ET
from urllib.parse import urljoin, urlparse
from xml.sax.saxutils import escape

import httpx

from .wan_forward import PORT, is_literal_public_ipv4, is_rfc1918_ipv4, mapping_lan_ipv4

WANIP = "urn:schemas-upnp-org:service:WANIPConnection:1"
WANPPP = "urn:schemas-upnp-org:service:WANPPPConnection:1"
WAN_SERVICES = frozenset(
    {
        "urn:schemas-upnp-org:service:WANIPConnection:1",
        "urn:schemas-upnp-org:service:WANIPConnection:2",
        "urn:schemas-upnp-org:service:WANPPPConnection:1",
        "urn:schemas-upnp-org:service:WANPPPConnection:2",
    }
)
_SSDP_ST = (
    "urn:schemas-upnp-org:service:WANIPConnection:1",
    "urn:schemas-upnp-org:service:WANIPConnection:2",
    "urn:schemas-upnp-org:device:InternetGatewayDevice:1",
    "urn:schemas-upnp-org:device:InternetGatewayDevice:2",
)


def require_lan_http_url(url: str) -> str:
    """IGD control stays on the owner's LAN; never follow SSDP to a WAN host."""
    parsed = urlparse((url or "").strip())
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise ValueError("IGD URL must be http(s) on the LAN")
    host = parsed.hostname.strip().rstrip(".").lower()
    try:
        ip = ipaddress.ip_address(host)
    except ValueError:
        if host in {"localhost"} or host.endswith((".local", ".home.arpa", ".lan")) or "." not in host:
            return parsed.geturl()
        raise ValueError("IGD URL host must be on the LAN")
    if ip.is_loopback or ip.is_link_local:
        return parsed.geturl()
    if is_rfc1918_ipv4(str(ip)):
        return parsed.geturl()
    raise ValueError("IGD URL must not be a public address")


def parse_ssdp_location(datagram: str) -> str:
    for raw in datagram.replace("\r\n", "\n").split("\n"):
        if raw.lower().startswith("location:"):
            return require_lan_http_url(raw.split(":", 1)[1].strip())
    raise ValueError("IGD advertisement had no LOCATION")


def _local_name(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def is_wan_connection_service(service_type: str) -> bool:
    return (service_type or "").strip() in WAN_SERVICES


def accept_ssdp_peer(addr: tuple) -> bool:
    """SSDP replies must come from the owner's LAN, not a public advertiser."""
    try:
        ip = ipaddress.ip_address(addr[0])
    except (ValueError, TypeError, IndexError):
        return False
    return bool(ip.is_loopback or ip.is_link_local or is_rfc1918_ipv4(str(ip)))


def parse_igd_control(xml_text: str, base_url: str) -> tuple[str, str]:
    root = ET.fromstring(xml_text)
    for service in root.iter():
        if _local_name(service.tag) != "service":
            continue
        service_type = ""
        control = ""
        for child in list(service):
            name = _local_name(child.tag)
            if name == "serviceType":
                service_type = (child.text or "").strip()
            elif name == "controlURL":
                control = (child.text or "").strip()
        if is_wan_connection_service(service_type) and control:
            return require_lan_http_url(urljoin(base_url, control)), service_type
    raise ValueError("IGD description has no WANIPConnection control URL")


def soap_envelope(action: str, service_type: str, body: str) -> str:
    return (
        '<?xml version="1.0"?>'
        '<s:Envelope xmlns:s="http://schemas.xmlsoap.org/soap/envelope/" '
        's:encodingStyle="http://schemas.xmlsoap.org/soap/encoding/">'
        f"<s:Body><u:{action} xmlns:u=\"{service_type}\">{body}</u:{action}></s:Body>"
        "</s:Envelope>"
    )


def _soap_text(xml_text: str, tag: str) -> str:
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError:
        return ""
    for node in root.iter():
        if _local_name(node.tag) == tag:
            return (node.text or "").strip()
    return ""


def _is_soap_fault(xml_text: str) -> bool:
    lowered = (xml_text or "").lower()
    if "fault" in lowered and ("s:fault" in lowered or "soap:fault" in lowered or "<fault" in lowered):
        return True
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError:
        return False
    return any(_local_name(node.tag) == "Fault" for node in root.iter())


def _response_header(response, name: str) -> str:
    headers = getattr(response, "headers", None) or {}
    getter = getattr(headers, "get", None)
    if not callable(getter):
        return ""
    return str(getter(name) or getter(name.title()) or getter(name.lower()) or "")


def igd_auth_candidates(username: str = "", password: str = "") -> list[tuple[str, str]]:
    """HTTP identities for owner IGD logon. Never guesses a password.

    A password with a blank username tries ``admin`` (typical home router), then
    empty-user HTTP basic (``:password``). An explicit username is the only try.
    """
    user = (username or "").strip()
    secret = password or ""
    if user:
        return [(user, secret)]
    if secret:
        return [("admin", secret), ("", secret)]
    return []


def apply_igd_logon(router, username: str = "", password: str = "") -> str:
    """Attach the first IGD identity to a miniupnpc client. Returns the username used."""
    candidates = igd_auth_candidates(username, password)
    if not candidates:
        return ""
    user, secret = candidates[0]
    router.username = user
    router.password = secret
    return user


def lan_igd_request(client, method: str, url: str, username: str = "", password: str = "", **kwargs):
    """Owner IGD logon: HTTP basic first, then digest if the LAN box asks for it."""
    sender = getattr(client, method)
    candidates = igd_auth_candidates(username, password)
    if not candidates:
        return sender(url, auth=None, **kwargs)
    last = None
    for user, secret in candidates:
        last = sender(url, auth=(user, secret), **kwargs)
        challenge = _response_header(last, "www-authenticate").lower()
        if last.status_code in {401, 403} and "digest" in challenge:
            last = sender(url, auth=httpx.DigestAuth(user, secret), **kwargs)
        if last.status_code not in {401, 403}:
            return last
    return last


def igd_http_bind(local_address: str = "") -> str:
    """Source IPv4 for IGD HTTP so a VPN default route cannot steal the LAN hop."""
    bind = (local_address or "").strip()
    return bind if is_rfc1918_ipv4(bind) else ""


def lan_http_client(local_address: str = "") -> httpx.Client:
    kwargs: dict = {
        "timeout": 4,
        "trust_env": False,
        "follow_redirects": False,
        "verify": False,
    }
    bind = igd_http_bind(local_address)
    if bind:
        kwargs["transport"] = httpx.HTTPTransport(local_address=bind)
    return httpx.Client(**kwargs)


class StdlibIGD:
    def __init__(self, control_url: str, service_type: str, lanaddr: str, username: str = "", password: str = ""):
        parsed = urlparse(control_url)
        if parsed.scheme not in {"http", "https"} or not parsed.hostname:
            raise ValueError("IGD control URL must be http(s)")
        self.control_url = require_lan_http_url(control_url)
        self.service_type = service_type or WANIP
        self.lanaddr = lanaddr
        self.username = username
        self.password = password or ""

    def _auth(self) -> tuple[str, str] | None:
        candidates = igd_auth_candidates(self.username, self.password)
        return candidates[0] if candidates else None

    def _post(self, action: str, inner: str) -> str:
        envelope = soap_envelope(action, self.service_type, inner)
        # LAN IGD boxes often present a self-signed certificate; the URL already passed require_lan_http_url.
        with lan_http_client(self.lanaddr) as client:
            response = lan_igd_request(
                client,
                "post",
                self.control_url,
                self.username,
                self.password,
                content=envelope.encode("utf-8"),
                headers={
                    "Content-Type": 'text/xml; charset="utf-8"',
                    "SOAPAction": f'"{self.service_type}#{action}"',
                },
            )
        if response.status_code in {401, 403}:
            raise RuntimeError("IGD requires the owner router username and password")
        if response.status_code >= 400 or _is_soap_fault(response.text):
            raise RuntimeError(f"IGD {action} returned HTTP {response.status_code}")
        return response.text

    def externalipaddress(self) -> str:
        text = self._post("GetExternalIPAddress", "")
        value = _soap_text(text, "NewExternalIPAddress")
        address = ipaddress.ip_address(value)
        if address.version != 4 or not is_literal_public_ipv4(str(address)):
            raise ValueError("Router has no public IPv4 address")
        return str(address)

    def getspecificportmapping(self, port: int, protocol: str):
        inner = (
            "<NewRemoteHost></NewRemoteHost>"
            f"<NewExternalPort>{int(port)}</NewExternalPort>"
            f"<NewProtocol>{protocol}</NewProtocol>"
        )
        try:
            text = self._post("GetSpecificPortMappingEntry", inner)
        except (RuntimeError, ET.ParseError):
            return None
        try:
            host = _soap_text(text, "NewInternalClient")
        except ET.ParseError:
            return None
        internal = _soap_text(text, "NewInternalPort") or str(port)
        desc = _soap_text(text, "NewPortMappingDescription")
        if not host:
            return None
        return (host, int(internal), desc)

    def addportmapping(self, ext_port, protocol, lanaddr, int_port, marker, _remote, lease) -> bool:
        if int(ext_port) != PORT or str(protocol).upper() != "TCP" or int(int_port) != PORT:
            raise ValueError("Only TCP 4781 may be mapped")
        dest = ipaddress.ip_address(str(lanaddr))
        if not is_rfc1918_ipv4(str(dest)):
            raise ValueError("IGD internal client must be a private LAN IPv4 address")
        inner = (
            "<NewRemoteHost></NewRemoteHost>"
            f"<NewExternalPort>{PORT}</NewExternalPort>"
            "<NewProtocol>TCP</NewProtocol>"
            f"<NewInternalPort>{PORT}</NewInternalPort>"
            f"<NewInternalClient>{dest}</NewInternalClient>"
            "<NewEnabled>1</NewEnabled>"
            f"<NewPortMappingDescription>{escape(str(marker)[:80])}</NewPortMappingDescription>"
            f"<NewLeaseDuration>{int(lease)}</NewLeaseDuration>"
        )
        self._post("AddPortMapping", inner)
        return True

    def deleteportmapping(self, port, protocol) -> None:
        if int(port) != PORT or str(protocol).upper() != "TCP":
            return
        inner = (
            "<NewRemoteHost></NewRemoteHost>"
            f"<NewExternalPort>{PORT}</NewExternalPort>"
            "<NewProtocol>TCP</NewProtocol>"
        )
        try:
            self._post("DeletePortMapping", inner)
        except RuntimeError:
            return


_SSDP_MCAST = ("239.255.255.250", 1900)


def _ssdp_msearch(st: str) -> bytes:
    return (
        "M-SEARCH * HTTP/1.1\r\n"
        "HOST: 239.255.255.250:1900\r\n"
        'MAN: "ssdp:discover"\r\n'
        "MX: 1\r\n"
        f"ST: {st}\r\n"
        "\r\n"
    ).encode("ascii")


def _ssdp_bind_ips() -> list[str]:
    """RFC1918 NIC addresses, home LAN first so VPN steal-default cannot hide the IGD."""
    from .wan_forward import interface_ipv4_addresses, mapping_lan_ipv4, rfc1918_mapping_gateways

    nics = [ip for ip in interface_ipv4_addresses() if is_rfc1918_ipv4(ip)]
    preferred: list[str] = []
    try:
        for gw in rfc1918_mapping_gateways():
            dest = mapping_lan_ipv4(nics, gw)
            if dest and dest not in preferred:
                preferred.append(dest)
    except Exception:
        pass
    return preferred + [ip for ip in nics if ip not in preferred]


def ssdp_probe_plan(
    bind_ips: list[str] | None = None,
    gateways: list[str] | None = None,
) -> list[tuple[str, str, int]]:
    """(bind_ip, dest_ip, dest_port) for M-SEARCH. Unicast each on-link gateway.

    An unbound multicast socket follows the default route. A VPN that stole
    0.0.0.0 would never reach the home IGD. Bind each RFC1918 NIC and unicast
    UDP 1900 at that subnet's gateway.
    """
    binds = [ip for ip in (bind_ips if bind_ips is not None else _ssdp_bind_ips()) if is_rfc1918_ipv4(ip)]
    if gateways is None:
        try:
            from .wan_forward import rfc1918_mapping_gateways

            gws = [item for item in rfc1918_mapping_gateways() if is_rfc1918_ipv4(item)]
        except Exception:
            gws = []
    else:
        gws = [item for item in gateways if is_rfc1918_ipv4(item)]
    plan: list[tuple[str, str, int]] = []
    seen: set[tuple[str, str, int]] = set()

    def add(bind: str, dest: str, port: int) -> None:
        key = (bind, dest, port)
        if key in seen:
            return
        seen.add(key)
        plan.append(key)

    if binds:
        for bind in binds:
            add(bind, _SSDP_MCAST[0], _SSDP_MCAST[1])
            for gw in gws:
                try:
                    same = ipaddress.ip_network(f"{bind}/24", strict=False)
                    if ipaddress.ip_address(gw) in same:
                        add(bind, gw, 1900)
                except ValueError:
                    continue
    else:
        add("", _SSDP_MCAST[0], _SSDP_MCAST[1])
        for gw in gws:
            add("", gw, 1900)
    return plan


def _prefer_home_lan_locations(locations: list[str]) -> list[str]:
    from .wan_forward import mapping_lan_ipv4, rfc1918_mapping_gateways

    home = ""
    try:
        gateways = rfc1918_mapping_gateways()
        home = gateways[0] if gateways else ""
    except Exception:
        home = ""
    preferred: list[str] = []
    rest: list[str] = []
    for location in locations:
        host = (urlparse(location).hostname or "").strip()
        if home and host and mapping_lan_ipv4([host], home) == host:
            preferred.append(location)
        else:
            rest.append(location)
    return preferred + rest


def ssdp_search_locations(timeout: float = 1.2) -> list[str]:
    """Every LAN IGD LOCATION, home-router subnet first."""
    import select

    plan = ssdp_probe_plan()
    if not plan:
        plan = [("", _SSDP_MCAST[0], _SSDP_MCAST[1])]
    sockets: list[socket.socket] = []
    last_error: Exception | None = None
    found: list[str] = []
    seen: set[str] = set()
    by_bind: dict[str, list[tuple[str, int]]] = {}
    for bind, dest, port in plan:
        by_bind.setdefault(bind, []).append((dest, port))
    try:
        for bind, dests in by_bind.items():
            sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP)
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            sock.settimeout(0.25)
            try:
                sock.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_TTL, 2)
            except OSError:
                pass
            if bind:
                try:
                    sock.bind((bind, 0))
                    sock.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_IF, socket.inet_aton(bind))
                except OSError as exc:
                    last_error = exc
                    sock.close()
                    continue
            sockets.append(sock)
            for dest, port in dests:
                for st in _SSDP_ST:
                    try:
                        sock.sendto(_ssdp_msearch(st), (dest, port))
                    except Exception as exc:
                        last_error = exc
        if not sockets:
            raise last_error or TimeoutError("No IGD SSDP response")
        deadline = time.monotonic() + max(0.4, float(timeout))
        while time.monotonic() < deadline:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                break
            try:
                ready, _, _ = select.select(sockets, [], [], min(0.25, remaining))
            except (ValueError, OSError) as exc:
                last_error = exc
                break
            if not ready:
                continue
            for sock in ready:
                try:
                    data, addr = sock.recvfrom(8192)
                except (TimeoutError, socket.timeout):
                    continue
                except Exception as exc:
                    last_error = exc
                    continue
                if not accept_ssdp_peer(addr):
                    last_error = ValueError("IGD advertisement was not from the LAN")
                    continue
                try:
                    location = parse_ssdp_location(data.decode("utf-8", errors="replace"))
                except Exception as exc:
                    last_error = exc
                    continue
                if location not in seen:
                    seen.add(location)
                    found.append(location)
        if not found:
            raise last_error or TimeoutError("No IGD SSDP response")
        return _prefer_home_lan_locations(found)
    finally:
        for sock in sockets:
            sock.close()


def ssdp_search(timeout: float = 1.2) -> str:
    found = ssdp_search_locations(timeout)
    if not found:
        raise TimeoutError("No IGD SSDP response")
    return found[0]


def _igd_lan_hosts(lanaddr: str = "") -> list[str]:
    hosts: list[str] = []
    try:
        from ..api.mobile import _lan_hosts

        hosts.extend(host for host in _lan_hosts() if is_rfc1918_ipv4(host))
    except Exception:
        pass
    if lanaddr.strip():
        hosts.append(lanaddr.strip())
    udp = _udp_lan_ipv4()
    if udp:
        hosts.append(udp)
    return hosts


def stdlib_igd_candidate(username: str = "", password: str = "", lanaddr: str = "") -> tuple[StdlibIGD, str]:
    last_error: Exception | None = None
    try:
        locations = list(ssdp_search_locations())
    except Exception as exc:
        last_error = exc
        locations = []
    if not locations:
        raise last_error or TimeoutError("No IGD SSDP response")
    hosts = _igd_lan_hosts(lanaddr)
    for location in locations:
        try:
            igd_host = urlparse(location).hostname or ""
            host = mapping_lan_ipv4(hosts, igd_host)
            if not is_rfc1918_ipv4(host):
                raise ValueError("No private LAN IPv4 for IGD internal client")
            with lan_http_client(host) as client:
                description = lan_igd_request(client, "get", location, username, password)
            if description.status_code in {401, 403}:
                raise RuntimeError("IGD requires the owner router username and password")
            if description.status_code >= 400:
                raise RuntimeError(f"IGD description HTTP {description.status_code}")
            control, service = parse_igd_control(description.text, location)
            router = StdlibIGD(control, service, str(ipaddress.ip_address(host)), username, password)
            return router, router.externalipaddress()
        except Exception as exc:
            last_error = exc
            continue
    raise last_error or ValueError("No IGD available")


def _udp_lan_ipv4() -> str:
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        sock.connect(("1.1.1.1", 80))
        host = sock.getsockname()[0]
    finally:
        sock.close()
    return host if is_rfc1918_ipv4(host) else ""
