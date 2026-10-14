"""Phone-facing LAN candidate ordering: home subnet before VPN/virtual NICs."""
from __future__ import annotations

from types import SimpleNamespace

import pytest


def test_lan_host_rank_prefers_gateway_subnet_over_vpn_prefix(monkeypatch):
    from app.mobile.wan_forward import lan_host_rank, order_lan_hosts

    monkeypatch.setattr(
        "app.mobile.wan_forward.interface_ipv4_inventory",
        lambda: [
            {"ip": "10.2.0.2", "name": "ProtonVPN", "prefix": 32},
            {"ip": "172.30.208.1", "name": "vEthernet (WSL (Hyper-V firewall))", "prefix": 20},
            {"ip": "192.168.1.212", "name": "Ethernet", "prefix": 24},
        ],
    )
    monkeypatch.setattr("app.mobile.wan_forward.default_gateway_ipv4", lambda: "192.168.1.1")

    assert lan_host_rank("192.168.1.212", gateway="192.168.1.1", prefix=24, ifname="Ethernet") == 0
    assert lan_host_rank("10.2.0.2", gateway="192.168.1.1", prefix=32, ifname="ProtonVPN") == 3
    assert lan_host_rank("172.30.208.1", gateway="192.168.1.1", prefix=20, ifname="vEthernet (WSL)") == 3

    assert order_lan_hosts(["10.2.0.2", "172.30.208.1", "192.168.1.212"]) == [
        "192.168.1.212",
        "10.2.0.2",
        "172.30.208.1",
    ]


def test_order_phone_reachable_puts_home_lan_before_vpn(monkeypatch):
    from app.mobile.pairing_payload import order_phone_reachable_endpoints

    monkeypatch.setattr(
        "app.mobile.wan_forward.interface_ipv4_inventory",
        lambda: [
            {"ip": "10.2.0.2", "name": "ProtonVPN", "prefix": 32},
            {"ip": "192.168.1.212", "name": "Ethernet", "prefix": 24},
        ],
    )
    monkeypatch.setattr("app.mobile.wan_forward.default_gateway_ipv4", lambda: "192.168.1.1")

    ordered = order_phone_reachable_endpoints(
        [
            "https://10.2.0.2:4781",
            "https://192.168.1.212:4781",
            "https://vrpc.tail1.ts.net:4781",
            "https://100.90.1.2:4781",
        ]
    )
    assert ordered[0] == "https://vrpc.tail1.ts.net:4781"
    assert ordered[1] == "https://100.90.1.2:4781"
    assert ordered[2] == "https://192.168.1.212:4781"
    assert ordered[3] == "https://10.2.0.2:4781"


def test_prefer_lan_https_without_peer_skips_vpn(monkeypatch):
    from app.mobile.lan_beacon import prefer_lan_https

    monkeypatch.setattr(
        "app.mobile.wan_forward.interface_ipv4_inventory",
        lambda: [
            {"ip": "10.2.0.2", "name": "ProtonVPN", "prefix": 32},
            {"ip": "192.168.1.212", "name": "Ethernet", "prefix": 24},
        ],
    )
    monkeypatch.setattr("app.mobile.wan_forward.default_gateway_ipv4", lambda: "192.168.1.1")

    chosen = prefer_lan_https(
        ["https://10.2.0.2:4781", "https://192.168.1.212:4781"],
        prefer_host="",
    )
    assert chosen == "https://192.168.1.212:4781"


def test_public_beacon_payload_lists_all_candidates(monkeypatch):
    from app.mobile.lan_beacon import encode_beacon, parse_beacon, public_beacon_payload

    monkeypatch.setattr(
        "app.mobile.wan_forward.interface_ipv4_inventory",
        lambda: [
            {"ip": "10.2.0.2", "name": "ProtonVPN", "prefix": 32},
            {"ip": "192.168.1.212", "name": "Ethernet", "prefix": 24},
        ],
    )
    monkeypatch.setattr("app.mobile.wan_forward.default_gateway_ipv4", lambda: "192.168.1.1")

    payload = public_beacon_payload(
        {
            "server_pin": "a" * 64,
            "endpoints": ["https://10.2.0.2:4781", "https://192.168.1.212:4781"],
        }
    )
    assert payload is not None
    assert payload["https"] == "https://192.168.1.212:4781"
    assert payload["endpoints"][0] == "https://192.168.1.212:4781"
    assert "https://10.2.0.2:4781" in payload["endpoints"]

    parsed = parse_beacon(encode_beacon(payload))
    assert parsed is not None
    assert parsed["https"] == "https://192.168.1.212:4781"
    assert parsed["endpoints"][0] == "https://192.168.1.212:4781"
    assert "https://10.2.0.2:4781" in parsed["endpoints"]


def test_lan_hosts_orders_via_inventory(monkeypatch):
    from app.api import mobile
    from app.mobile import connectivity

    monkeypatch.setattr(
        "app.mobile.wan_forward.interface_ipv4_addresses",
        lambda: ["10.2.0.2", "192.168.1.212", "172.30.0.1"],
    )
    monkeypatch.setattr(
        "app.mobile.wan_forward.interface_ipv4_inventory",
        lambda: [
            {"ip": "10.2.0.2", "name": "ProtonVPN", "prefix": 32},
            {"ip": "192.168.1.212", "name": "Ethernet", "prefix": 24},
            {"ip": "172.30.0.1", "name": "vEthernet (Default Switch)", "prefix": 20},
        ],
    )
    monkeypatch.setattr("app.mobile.wan_forward.default_gateway_ipv4", lambda: "192.168.1.1")
    monkeypatch.setattr(mobile.socket, "gethostname", lambda: (_ for _ in ()).throw(OSError("no hostname")))

    class _Boom:
        def __init__(self, *a, **k):
            raise OSError("no udp")

    monkeypatch.setattr(mobile.socket, "socket", _Boom)
    assert connectivity.lan_hosts()[0] == "192.168.1.212"
    assert connectivity.lan_hosts()[-1] in {"10.2.0.2", "172.30.0.1"}
