"""QR / enroll payload fields for companion pairing sessions."""
from __future__ import annotations

import ipaddress
from typing import Any
from urllib.parse import urlsplit

from .connectivity import CONNECTIVITY


def _is_lan_ip(host: str) -> bool:
    try:
        ip = ipaddress.ip_address(host)
    except ValueError:
        return False
    if ip.is_loopback or ip.is_link_local:
        return True
    if ip.version != 4:
        return ip.is_private
    return any(
        ip in ipaddress.ip_network(block)
        for block in ("10.0.0.0/8", "172.16.0.0/12", "192.168.0.0/16")
    )


def order_phone_reachable_endpoints(endpoints: list[str]) -> list[str]:
    """Prefer relay hostnames and public IPs before RFC1918 LAN addresses."""
    ranked: list[tuple[int, str]] = []
    for value in endpoints:
        try:
            origin = value.rstrip("/")
            host = urlsplit(origin).hostname or ""
            if _is_lan_ip(host):
                rank = 2
            else:
                try:
                    ipaddress.ip_address(host)
                    rank = 1
                except ValueError:
                    rank = 0
            ranked.append((rank, origin))
        except Exception:
            continue
    ranked.sort(key=lambda item: (item[0], item[1]))
    seen: set[str] = set()
    ordered: list[str] = []
    for _, origin in ranked:
        if origin in seen:
            continue
        seen.add(origin)
        ordered.append(origin)
    return ordered


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
    if endpoint and server_pin:
        enriched["qr"] = build_qr_envelope(code)
    return enriched
