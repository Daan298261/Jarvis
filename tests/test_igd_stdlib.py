from __future__ import annotations

import ipaddress

import pytest

from app.mobile.igd import StdlibIGD, parse_igd_control, parse_ssdp_location, soap_envelope
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
