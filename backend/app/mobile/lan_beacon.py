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


def _rfc1918_bind_ips(bind_ips: list[str] | None = None) -> list[str]:
    from .wan_forward import interface_ipv4_addresses, is_rfc1918_ipv4, mapping_lan_ipv4, rfc1918_mapping_gateways

    nics = [
        ip
        for ip in (bind_ips if bind_ips is not None else interface_ipv4_addresses())
        if is_rfc1918_ipv4(ip)
    ]
    ordered: list[str] = []
    try:
        for gw in rfc1918_mapping_gateways():
            dest = mapping_lan_ipv4(nics, gw)
            if dest and dest not in ordered:
                ordered.append(dest)
    except Exception:
        pass
    return ordered + [ip for ip in nics if ip not in ordered]


def beacon_reply_source(peer: str, bind_ips: list[str] | None = None) -> str:
    """Source IPv4 on the same /24 as the phone, so a VPN default route cannot steal the reply."""
    from .wan_forward import is_rfc1918_ipv4, mapping_lan_ipv4

    host = (peer or "").strip()
    if not is_rfc1918_ipv4(host):
        return ""
    return mapping_lan_ipv4(_rfc1918_bind_ips(bind_ips), host)


def beacon_send_plan(bind_ips: list[str] | None = None) -> list[tuple[str, str]]:
    """(source_ip, dest_ip) for directed subnet broadcast plus limited broadcast per NIC."""
    plan: list[tuple[str, str]] = []
    seen: set[tuple[str, str]] = set()
    for ip in _rfc1918_bind_ips(bind_ips):
        net = ipaddress.ip_network(f"{ip}/24", strict=False)
        for dest in (str(net.broadcast_address), "255.255.255.255"):
            key = (ip, dest)
            if key in seen:
                continue
            seen.add(key)
            plan.append(key)
    return plan


def send_beacon_datagram(blob: bytes, dest: str, port: int, source: str = "") -> None:
    from .wan_forward import is_rfc1918_ipv4

    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
        bind = (source or "").strip()
        if is_rfc1918_ipv4(bind):
            sock.bind((bind, 0))
        sock.sendto(blob, (dest, int(port)))
    finally:
        sock.close()


class LanBeaconServer:
    def __init__(self, port: int = BEACON_PORT):
        self.port = port
        self._transport: asyncio.DatagramTransport | None = None
        self._protocol: _BeaconProtocol | None = None

    async def start(self, payload_factory) -> None:
        await self.stop()
        loop = asyncio.get_running_loop()
        transport, protocol = await loop.create_datagram_endpoint(
            lambda: _BeaconProtocol(payload_factory, port=self.port),
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
    def __init__(self, payload_factory, port: int = BEACON_PORT):
        self._payload_factory = payload_factory
        self._port = int(port or BEACON_PORT)
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
        dest_port = int(addr[1]) if addr and len(addr) > 1 else self._port
        source = beacon_reply_source(str(peer or ""))
        if source:
            try:
                send_beacon_datagram(blob, str(peer), dest_port, source)
                return
            except OSError:
                pass
        if self._transport:
            self._transport.sendto(blob, addr)

    async def _broadcast_loop(self):
        try:
            while True:
                payload = self._payload()
                if payload:
                    blob = encode_beacon(payload)
                    for source, dest in beacon_send_plan():
                        try:
                            send_beacon_datagram(blob, dest, self._port, source)
                        except OSError:
                            continue
                    if self._transport:
                        try:
                            self._transport.sendto(blob, ("255.255.255.255", self._port))
                        except OSError:
                            pass
                await asyncio.sleep(2)
        except asyncio.CancelledError:
            return

    def close(self):
        if self._broadcast_task:
            self._broadcast_task.cancel()
            self._broadcast_task = None
