"""QR / enroll payload fields for companion pairing sessions."""
from __future__ import annotations

from typing import Any

from .connectivity import CONNECTIVITY


def order_phone_reachable_endpoints(endpoints: list[str]) -> list[str]:
    """RFC-0215: Tailscale first, then LAN with home subnet before VPN/virtual NICs."""
    from urllib.parse import urlsplit

    from .remote_access import ordered_entries
    from .wan_forward import (
        interface_ipv4_inventory,
        is_rfc1918_ipv4,
        lan_host_rank,
        order_lan_hosts,
    )

    entries = ordered_entries(endpoints)
    tailscale = [entry["url"] for entry in entries if entry.get("kind") == "tailscale"]
    lan_urls = [entry["url"] for entry in entries if entry.get("kind") == "lan"]
    inventory = {str(row["ip"]): row for row in interface_ipv4_inventory()}
    ip_hosts = []
    for url in lan_urls:
        host = (urlsplit(url).hostname or "").strip()
        if host and is_rfc1918_ipv4(host):
            ip_hosts.append(host)
    ordered_ips = order_lan_hosts(ip_hosts)
    ip_rank = {host: index for index, host in enumerate(ordered_ips)}

    def sort_key(url: str) -> tuple[int, int, str]:
        host = (urlsplit(url).hostname or "").strip()
        if host in ip_rank:
            meta = inventory.get(host) or {}
            rank = lan_host_rank(
                host,
                prefix=meta.get("prefix") if isinstance(meta.get("prefix"), int) else None,
                ifname=str(meta.get("name") or ""),
            )
            # VPN/virtual IPs stay after .local hostnames; ordinary LAN stays before.
            if rank >= 3:
                return (2, ip_rank[host], url)
            return (0, ip_rank[host], url)
        return (1, 0, url)

    lan_urls = sorted(lan_urls, key=sort_key)
    return tailscale + lan_urls


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
