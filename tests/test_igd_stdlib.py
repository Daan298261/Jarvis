from __future__ import annotations

import ipaddress

import pytest

from app.mobile.igd import (
    StdlibIGD,
    accept_ssdp_peer,
    is_wan_connection_service,
    parse_igd_control,
    parse_ssdp_location,
    soap_envelope,
)
from app.mobile.wan_forward import ensure_private_firewall_4781, lookup_egress_ipv4


SSDP = (
    "HTTP/1.1 200 OK\r\n"
    "CACHE-CONTROL: max-age=120\r\n"
    "LOCATION: http://192.168.1.1:5000/rootDesc.xml\r\n"
    "ST: urn:schemas-upnp-org:service:WANIPConnection:1\r\n"
    "\r\n"
)

DESC = """<?xml version="1.0"?>
<root>
  <device>
    <serviceList>
      <service>
        <serviceType>urn:schemas-upnp-org:service:WANIPConnection:1</serviceType>
        <controlURL>/upnp/control/WANIPConn1</controlURL>
      </service>
    </serviceList>
  </device>
</root>
"""


def test_ssdp_and_control_url_parsing():
    assert parse_ssdp_location(SSDP) == "http://192.168.1.1:5000/rootDesc.xml"
    control, service = parse_igd_control(DESC, "http://192.168.1.1:5000/rootDesc.xml")
    assert control == "http://192.168.1.1:5000/upnp/control/WANIPConn1"
    assert "WANIPConnection" in service
    with pytest.raises(ValueError):
        parse_ssdp_location("HTTP/1.1 200 OK\r\nLOCATION: http://8.8.8.8/desc.xml\r\n\r\n")
    with pytest.raises(ValueError):
        parse_ssdp_location("HTTP/1.1 200 OK\r\nLOCATION: https://evil.example/desc.xml\r\n\r\n")
    assert accept_ssdp_peer(("192.168.1.1", 1900))
    assert not accept_ssdp_peer(("8.8.8.8", 1900))
    assert is_wan_connection_service("urn:schemas-upnp-org:service:WANIPConnection:2")
    v2 = DESC.replace("WANIPConnection:1", "WANIPConnection:2")
    control, service = parse_igd_control(v2, "http://192.168.1.1:5000/rootDesc.xml")
    assert control.endswith("/upnp/control/WANIPConn1")
    assert service.endswith(":2")


def test_soap_addportmapping_is_tcp_4781_only():
    envelope = soap_envelope(
        "AddPortMapping",
        "urn:schemas-upnp-org:service:WANIPConnection:1",
        "<NewExternalPort>4781</NewExternalPort><NewProtocol>TCP</NewProtocol>",
    )
    assert "AddPortMapping" in envelope
    assert "4781" in envelope
    router = StdlibIGD("http://192.168.1.1:5000/upnp/control/WANIPConn1", "urn:schemas-upnp-org:service:WANIPConnection:1", "192.168.1.12")
    with pytest.raises(ValueError):
        router.addportmapping(22, "TCP", "192.168.1.12", 22, "Jarvis", "", 3600)
    with pytest.raises(ValueError):
        router.addportmapping(4781, "TCP", "8.8.8.8", 4781, "Jarvis", "", 3600)


def test_lookup_egress_ipv4_accepts_global_and_rejects_private(monkeypatch):
    class FakeClient:
        def __init__(self, *args, **kwargs):
            pass
        def __enter__(self):
            return self
        def __exit__(self, *args):
            return False
        def get(self, url):
            from types import SimpleNamespace

            if "ipify" in url:
                return SimpleNamespace(text="8.8.4.4")
            return SimpleNamespace(text="10.0.0.1")

    monkeypatch.setattr("app.mobile.wan_forward.httpx.Client", FakeClient)
    assert lookup_egress_ipv4() == "8.8.4.4"
    assert ipaddress.ip_address("8.8.4.4").is_global


def test_windows_firewall_helper_skips_on_linux():
    assert ensure_private_firewall_4781() == "skipped"


def test_stdlib_igd_maps_4781_and_treats_soap_fault_as_empty(monkeypatch):
    from types import SimpleNamespace

    from app.mobile.connectivity import map_router, unmap_router

    posts = []

    class FakeClient:
        def __init__(self, *args, **kwargs):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def post(self, url, content, headers, auth=None):
            body = content.decode("utf-8")
            posts.append(body)
            action = headers["SOAPAction"]
            if "GetSpecificPortMappingEntry" in action:
                return SimpleNamespace(
                    status_code=200,
                    text="<s:Envelope><s:Body><s:Fault><faultcode>s:Client</faultcode></s:Fault></s:Body></s:Envelope>",
                )
            if "AddPortMapping" in action:
                assert "4781" in body and "3600" in body and "192.168.1.12" in body
                return SimpleNamespace(status_code=200, text="<s:Envelope><s:Body><u:AddPortMappingResponse/></s:Body></s:Envelope>")
            if "DeletePortMapping" in action:
                return SimpleNamespace(status_code=200, text="<ok/>")
            raise AssertionError(action)

    monkeypatch.setattr("app.mobile.igd.httpx.Client", FakeClient)
    router = StdlibIGD(
        "http://192.168.1.1:5000/upnp/control/WANIPConn1",
        "urn:schemas-upnp-org:service:WANIPConnection:1",
        "192.168.1.12",
        username="admin",
        password="secret",
    )
    map_router(router, "Jarvis-owned")
    assert any("AddPortMapping" in item for item in posts)
    unmap_router(router, "Jarvis-owned")


def test_stdlib_igd_rejects_cgnat_and_explains_igd_logon(monkeypatch):
    from types import SimpleNamespace

    posts = []

    class FakeClient:
        def __init__(self, *args, **kwargs):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def post(self, url, content, headers, auth=None):
            posts.append(headers["SOAPAction"])
            return SimpleNamespace(
                status_code=401,
                text="Unauthorized",
            )

    monkeypatch.setattr("app.mobile.igd.httpx.Client", FakeClient)
    router = StdlibIGD(
        "http://192.168.1.1:5000/upnp/control/WANIPConn1",
        "urn:schemas-upnp-org:service:WANIPConnection:2",
        "192.168.1.12",
    )
    with pytest.raises(RuntimeError, match="username and password"):
        router.externalipaddress()
    assert posts

    class CgnatClient(FakeClient):
        def post(self, url, content, headers, auth=None):
            return SimpleNamespace(
                status_code=200,
                text="<s:Envelope><s:Body><NewExternalIPAddress>10.8.0.2</NewExternalIPAddress></s:Body></s:Envelope>",
            )

    monkeypatch.setattr("app.mobile.igd.httpx.Client", CgnatClient)
    with pytest.raises(ValueError, match="no public IPv4"):
        router.externalipaddress()
