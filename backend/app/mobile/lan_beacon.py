"""UDP LAN beacon so a phone on the same Wi-Fi can find this Jarvis."""
from __future__ import annotations

import asyncio
import ipaddress
import json
import socket
from typing import Any
from urllib.parse import urlsplit

BEACON_PORT = 4782
BEACON_MAGIC = b"JARVIS1\n"
BEACON_SERVICE = "jarvis-companion"


def encode_beacon(payload: dict[str, Any]) -> bytes:
    body = {
        "service": BEACON_SERVICE,
        "version": 1,
        "https": payload["https"],
        "server_pin": str(payload["server_pin"]).lower(),
        "name": str(payload.get("name") or "Jarvis")[:80],
        "lan_pair": True,
    }
    blob = BEACON_MAGIC + json.dumps(body, separators=(",", ":")).encode()
    if len(blob) > 1200:
        raise ValueError("Beacon payload too large")
    return blob


def parse_beacon(raw: bytes) -> dict[str, Any] | None:
    if not raw:
        return None
    text = raw.strip()
    if text.startswith(BEACON_MAGIC):
        text = text[len(BEACON_MAGIC) :]
    try:
        body = json.loads(text.decode())
    except (UnicodeDecodeError, json.JSONDecodeError):
        return None
    if not isinstance(body, dict):
        return None
    if body.get("probe") is True:
        return {"probe": True}
    if body.get("service") != BEACON_SERVICE:
        return None
    pin = str(body.get("server_pin") or "").strip().lower()
    https = str(body.get("https") or "").strip()
    if len(pin) != 64 or any(ch not in "0123456789abcdef" for ch in pin):
        return None
    if not https.startswith("https://"):
        return None
    return {
        "service": BEACON_SERVICE,
        "https": https.rstrip("/"),
        "server_pin": pin,
        "name": str(body.get("name") or "Jarvis")[:80],
        "lan_pair": True,
    }


def _lan_origin_host(item: str) -> str:
    return (urlsplit(item).hostname or "").strip().lower().rstrip(".")


def _is_lan_origin(item: str) -> bool:
    from .wan_forward import is_rfc1918_ipv4

    host = _lan_origin_host(item)
    if not host:
        return False
    if host.endswith((".local", ".lan", ".home.arpa")) or host in {"localhost", "router", "gateway"}:
        return True
    return is_rfc1918_ipv4(host)


def prefer_lan_https(endpoints: list[str], prefer_host: str = "") -> str:
    """LAN beacons must advertise an RFC1918 / .local origin, not the public hairpin.

    A VPN NIC often sorts ahead of 192.168. Prefer the origin on the same /24 as
    the phone that probed, or the mapped home-LAN dest, never a WAN hostname.
    """
    from .wan_forward import is_rfc1918_ipv4

    values = [str(item).rstrip("/") for item in endpoints if item]
    lan_items = [item for item in values if _is_lan_origin(item)]
    if not lan_items:
        return ""
    prefer = (prefer_host or "").strip().lower().rstrip(".")
    if prefer:
        for item in lan_items:
            if _lan_origin_host(item) == prefer:
                return item
        try:
            peer = ipaddress.ip_address(prefer)
            net = ipaddress.ip_network(f"{peer}/24", strict=False)
        except ValueError:
            net = None
        if net is not None:
            for item in lan_items:
                host = _lan_origin_host(item)
                try:
                    if is_rfc1918_ipv4(host) and ipaddress.ip_address(host) in net:
                        return item
                except ValueError:
                    continue
    return lan_items[0]


def public_beacon_payload(snapshot: dict[str, Any], *, prefer_host: str = "") -> dict[str, Any] | None:
    pin = str(snapshot.get("server_pin") or "").strip().lower()
    endpoints = [str(item).rstrip("/") for item in (snapshot.get("endpoints") or []) if item]
    if len(pin) != 64 or not endpoints:
        return None
    host = (prefer_host or "").strip() or str(snapshot.get("mapped_lan_ip") or "").strip()
    chosen = prefer_lan_https(endpoints, host)
    if not chosen:
        return None
    return {
        "https": chosen,
        "server_pin": pin,
        "name": "Jarvis",
        "lan_pair": True,
        "service": BEACON_SERVICE,
        "version": 1,
    }


class LanBeaconServer:
    def __init__(self, port: int = BEACON_PORT):
        self.port = port
        self._transport: asyncio.DatagramTransport | None = None
        self._protocol: _BeaconProtocol | None = None

    async def start(self, payload_factory) -> None:
        await self.stop()
        loop = asyncio.get_running_loop()
        transport, protocol = await loop.create_datagram_endpoint(
            lambda: _BeaconProtocol(payload_factory),
            local_addr=("0.0.0.0", self.port),
            allow_broadcast=True,
        )
        self._transport = transport
        self._protocol = protocol

    async def stop(self) -> None:
        if self._protocol:
            self._protocol.close()
        if self._transport:
            self._transport.close()
        self._transport = None
        self._protocol = None


class _BeaconProtocol(asyncio.DatagramProtocol):
    def __init__(self, payload_factory):
        self._payload_factory = payload_factory
        self._transport: asyncio.DatagramTransport | None = None
        self._broadcast_task: asyncio.Task | None = None

    def connection_made(self, transport):
        self._transport = transport
        sock = transport.get_extra_info("socket")
        if sock is not None:
            try:
                sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
            except OSError:
                pass
        self._broadcast_task = asyncio.create_task(self._broadcast_loop())

    def _payload(self, peer_host: str = "") -> dict[str, Any] | None:
        factory = self._payload_factory
        try:
            return factory(peer_host)
        except TypeError:
            return factory()

    def datagram_received(self, data, addr):
        parsed = parse_beacon(data)
        if not parsed:
            return
        peer = addr[0] if addr else ""
        payload = self._payload(str(peer or ""))
        if not payload:
            return
        blob = encode_beacon(payload)
        if self._transport:
            self._transport.sendto(blob, addr)

    async def _broadcast_loop(self):
        try:
            while True:
                payload = self._payload()
                if payload and self._transport:
                    blob = encode_beacon(payload)
                    try:
                        self._transport.sendto(blob, ("255.255.255.255", self.port))
                    except OSError:
                        pass
                await asyncio.sleep(2)
        except asyncio.CancelledError:
            return

    def close(self):
        if self._broadcast_task:
            self._broadcast_task.cancel()
            self._broadcast_task = None
