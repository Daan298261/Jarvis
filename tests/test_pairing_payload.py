"""Companion pairing QR payload ordering (RFC-0215: Tailscale first, then LAN; nothing else)."""
from __future__ import annotations

from app.mobile.pairing_payload import build_qr_envelope, order_phone_reachable_endpoints


def test_order_puts_tailscale_first_and_drops_public_and_hostnames():
    ordered = order_phone_reachable_endpoints(
        [
            "https://relay.example.test:4781",
            "https://203.0.113.4:4781",
            "https://192.168.0.12:4781",
            "https://100.90.1.2:4781",
            "https://vrpc.tail1.ts.net:4781",
        ],
    )
    assert ordered == [
        "https://100.90.1.2:4781",
        "https://vrpc.tail1.ts.net:4781",
        "https://192.168.0.12:4781",
    ]


def test_mdns_counts_as_lan():
    ordered = order_phone_reachable_endpoints(["https://jarvis.local:4781", "https://10.2.0.2:4781"])
    assert ordered == ["https://jarvis.local:4781", "https://10.2.0.2:4781"]


def test_qr_envelope_tailscale_first(monkeypatch):
    from app.mobile import pairing_payload

    monkeypatch.setattr(
        pairing_payload.CONNECTIVITY, "snapshot",
        lambda: {"endpoints": ["https://10.0.0.4:4781", "https://vrpc.tail1.ts.net:4781", "https://8.8.8.8:4781"],
                 "server_pin": "a" * 64},
    )
    qr = build_qr_envelope("123456")
    assert qr["endpoint"] == "https://vrpc.tail1.ts.net:4781"
    assert qr["endpoints"] == ["https://vrpc.tail1.ts.net:4781", "https://10.0.0.4:4781"]
    assert "endpoint_kinds" not in qr


def test_mdns_stays_before_bare_rfc1918_without_inventory(monkeypatch):
    """CI has no ProtonVPN NIC metadata; .local must still beat bare 10/8."""
    monkeypatch.setattr("app.mobile.wan_forward.interface_ipv4_inventory", lambda: [])
    monkeypatch.setattr(
        "app.mobile.wan_forward.default_gateway_ipv4",
        lambda: (_ for _ in ()).throw(ValueError("no gw")),
    )
    ordered = order_phone_reachable_endpoints(
        ["https://10.2.0.2:4781", "https://jarvis.local:4781"]
    )
    assert ordered == ["https://jarvis.local:4781", "https://10.2.0.2:4781"]



def test_vrpc_mix_home_lan_before_vpn_and_virtual(monkeypatch):
    """Real VRPC NIC mix: mDNS + gateway LAN first, then ProtonVPN / Hyper-V."""
    from app.mobile import wan_forward

    monkeypatch.setattr(
        wan_forward, "interface_ipv4_inventory",
        lambda: [
            {"ip": "192.168.1.212", "name": "Ethernet", "prefix": 24},
            {"ip": "10.2.0.2", "name": "ProtonVPN", "prefix": 32},
            {"ip": "172.30.112.1", "name": "vEthernet (Default Switch)", "prefix": 20},
        ],
    )
    monkeypatch.setattr(wan_forward, "default_gateway_ipv4", lambda: "192.168.1.1")
    ordered = order_phone_reachable_endpoints(
        [
            "https://10.2.0.2:4781",
            "https://172.30.112.1:4781",
            "https://192.168.1.212:4781",
            "https://jarvis.local:4781",
        ],
    )
    assert ordered[:2] == ["https://jarvis.local:4781", "https://192.168.1.212:4781"]
    assert set(ordered[2:]) == {"https://10.2.0.2:4781", "https://172.30.112.1:4781"}
