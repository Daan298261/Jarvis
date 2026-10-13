"""QR / enroll payload fields for companion pairing sessions."""
from __future__ import annotations

from typing import Any

from .connectivity import CONNECTIVITY


def order_phone_reachable_endpoints(endpoints: list[str]) -> list[str]:
    """RFC-0215: only Tailscale (first) and LAN origins reach the QR; anything else is dropped."""
    from .remote_access import ordered_entries

    return [entry["url"] for entry in ordered_entries(endpoints)]


def build_qr_envelope(code: str) -> dict[str, Any]:
    """Same JSON shape as Android bootstrap.json, using a six-digit code."""
    snapshot = CONNECTIVITY.snapshot()
    endpoints = order_phone_reachable_endpoints(list(snapshot.get("endpoints") or []))
    endpoint = endpoints[0] if endpoints else ""
    server_pin = str(snapshot.get("server_pin") or "")
    payload: dict[str, Any] = {"endpoint": endpoint, "server_pin": server_pin, "code": code}
    if endpoints:
        payload["endpoints"] = endpoints
    return payload


def enrich_pairing_session(payload: dict[str, Any]) -> dict[str, Any]:
    """Attach LAN/TLS endpoint + server pin for portal QR rendering."""
    code = str(payload.get("code") or "")
    if not code:
        return payload
    snapshot = CONNECTIVITY.snapshot()
    endpoints = order_phone_reachable_endpoints(list(snapshot.get("endpoints") or []))
    server_pin = str(snapshot.get("server_pin") or "")
    endpoint = endpoints[0] if endpoints else ""
    enriched = dict(payload)
    enriched["endpoints"] = endpoints
    enriched["server_pin"] = server_pin
    enriched["endpoint"] = endpoint
    enriched["remote"] = bool(snapshot.get("remote"))
    if endpoint and server_pin:
        enriched["qr"] = build_qr_envelope(code)
    return enriched
