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

from .wan_forward import PORT

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
    if ip.is_loopback or ip.is_link_local or ip.is_private:
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
    return bool(ip.is_private or ip.is_loopback or ip.is_link_local)


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
        if self.username:
            return (self.username, self.password)
        return None

    def _post(self, action: str, inner: str) -> str:
        envelope = soap_envelope(action, self.service_type, inner)
        # LAN IGD boxes often present a self-signed certificate; the URL already passed require_lan_http_url.
        with httpx.Client(timeout=4, trust_env=False, follow_redirects=False, verify=False) as client:
            response = client.post(
                self.control_url,
                content=envelope.encode("utf-8"),
                headers={
                    "Content-Type": 'text/xml; charset="utf-8"',
                    "SOAPAction": f'"{self.service_type}#{action}"',
                },
                auth=self._auth(),
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
        if address.version != 4 or not address.is_global:
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
        if dest.version != 4 or not dest.is_private or dest.is_loopback:
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


def ssdp_search(timeout: float = 1.2) -> str:
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    sock.settimeout(0.25)
    deadline = time.monotonic() + max(0.4, float(timeout))
    last_error: Exception | None = None
    try:
        for st in _SSDP_ST:
            payload = (
                "M-SEARCH * HTTP/1.1\r\n"
                "HOST: 239.255.255.250:1900\r\n"
                'MAN: "ssdp:discover"\r\n'
                "MX: 1\r\n"
                f"ST: {st}\r\n"
                "\r\n"
            ).encode("ascii")
            try:
                sock.sendto(payload, ("239.255.255.250", 1900))
            except Exception as exc:
                last_error = exc
        while time.monotonic() < deadline:
            try:
                data, addr = sock.recvfrom(8192)
            except TimeoutError:
                continue
            except socket.timeout:
                continue
            except Exception as exc:
                last_error = exc
                continue
            if not accept_ssdp_peer(addr):
                last_error = ValueError("IGD advertisement was not from the LAN")
                continue
            try:
                return parse_ssdp_location(data.decode("utf-8", errors="replace"))
            except Exception as exc:
                last_error = exc
        raise last_error or TimeoutError("No IGD SSDP response")
    finally:
        sock.close()


def stdlib_igd_candidate(username: str = "", password: str = "", lanaddr: str = "") -> tuple[StdlibIGD, str]:
    location = ssdp_search()
    with httpx.Client(timeout=4, trust_env=False, follow_redirects=False, verify=False) as client:
        description = client.get(location, auth=(username, password) if username else None)
    if description.status_code in {401, 403}:
        raise RuntimeError("IGD requires the owner router username and password")
    if description.status_code >= 400:
        raise RuntimeError(f"IGD description HTTP {description.status_code}")
    control, service = parse_igd_control(description.text, location)
    host = lanaddr.strip() if lanaddr else _udp_lan_ipv4()
    if not host:
        raise ValueError("No private LAN IPv4 for IGD internal client")
    dest = ipaddress.ip_address(host)
    if dest.version != 4 or not dest.is_private or dest.is_loopback:
        raise ValueError("IGD internal client must be a private LAN IPv4 address")
    router = StdlibIGD(control, service, str(dest), username, password)
    return router, router.externalipaddress()


def _udp_lan_ipv4() -> str:
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        sock.connect(("1.1.1.1", 80))
        host = sock.getsockname()[0]
    finally:
        sock.close()
    return host
