"""Companion pairing QR payload ordering for off-LAN reachability."""
from __future__ import annotations

from app.mobile.pairing_payload import order_phone_reachable_endpoints


def test_order_phone_reachable_endpoints_prefers_wan_and_relay():
    ordered = order_phone_reachable_endpoints(
        [
            "https://10.2.0.2:4781",
            "https://relay.example.test:4781",
            "https://203.0.113.4:4781",
            "https://192.168.0.12:4781",
        ],
    )
    assert ordered[0] == "https://relay.example.test:4781"
    assert ordered[1] == "https://203.0.113.4:4781"
    assert "https://10.2.0.2:4781" in ordered[2:]
    assert ordered[-1] == "https://192.168.0.12:4781"
