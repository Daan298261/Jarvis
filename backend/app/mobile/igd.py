"""Stdlib IGD/UPnP client for companion TCP 4781 when miniupnpc is missing.

This talks to the owner's Internet Gateway Device with optional HTTP basic
credentials. It does not guess passwords, scan foreign networks, or map any
port other than TCP 4781.
"""
from __future__ import annotations

import ipaddress
import socket
import xml.etree.ElementTree as ET
from urllib.parse import urljoin, urlparse

import httpx

from .wan_forward import PORT

WANIP = "urn:schemas-upnp-org:service:WANIPConnection:1"
WANPPP = "urn:schemas-upnp-org:service:WANPPPConnection:1"
_SSDP_ST = (
    "urn:schemas-upnp-org:service:WANIPConnection:1",
    "urn:schemas-upnp-org:device:InternetGatewayDevice:1",
)


def parse_ssdp_location(datagram: str) -> str:
    for raw in datagram.replace("\r\n", "\n").split("\n"):
        if raw.lower().startswith("location:"):
            location = raw.split(":", 1)[1].strip()
            parsed = urlparse(location)
            if parsed.scheme in {"http", "https"} and parsed.hostname:
                return location
    raise ValueError("IGD advertisement had no LOCATION")


def _local_name(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


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
        if service_type in {WANIP, WANPPP} and control:
            return urljoin(base_url, control), service_type
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
    root = ET.fromstring(xml_text)
    for node in root.iter():
        if _local_name(node.tag) == tag:
            return (node.text or "").strip()
    return ""


class StdlibIGD:
    def __init__(self, control_url: str, service_type: str, lanaddr: str, username: str = "", password: str = ""):
        parsed = urlparse(control_url)
        if parsed.scheme not in {"http", "https"} or not parsed.hostname:
            raise ValueError("IGD control URL must be http(s)")
        self.control_url = control_url
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
        with httpx.Client(timeout=4, trust_env=False, follow_redirects=False) as client:
            response = client.post(
                self.control_url,
                content=envelope.encode("utf-8"),
                headers={
                    "Content-Type": 'text/xml; charset="utf-8"',
                    "SOAPAction": f'"{self.service_type}#{action}"',
                },
                auth=self._auth(),
            )
        if response.status_code >= 400:
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
        except RuntimeError:
            return None
        host = _soap_text(text, "NewInternalClient")
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
            f"<NewPortMappingDescription>{marker}</NewPortMappingDescription>"
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


def ssdp_search(timeout: float = 1.5) -> str:
    payload = (
        "M-SEARCH * HTTP/1.1\r\n"
        "HOST: 239.255.255.250:1900\r\n"
        'MAN: "ssdp:discover"\r\n'
        "MX: 1\r\n"
        f"ST: {_SSDP_ST[0]}\r\n"
        "\r\n"
    ).encode("ascii")
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP)
    sock.settimeout(timeout)
    try:
        sock.sendto(payload, ("239.255.255.250", 1900))
        data, _addr = sock.recvfrom(8192)
    finally:
        sock.close()
    return parse_ssdp_location(data.decode("utf-8", errors="replace"))


def stdlib_igd_candidate(username: str = "", password: str = "", lanaddr: str = "") -> tuple[StdlibIGD, str]:
    location = ssdp_search()
    with httpx.Client(timeout=4, trust_env=False, follow_redirects=True) as client:
        description = client.get(location, auth=(username, password) if username else None)
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
