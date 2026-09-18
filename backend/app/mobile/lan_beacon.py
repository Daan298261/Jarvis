"""UDP LAN beacon so a phone on the same Wi-Fi can find this Jarvis."""
from __future__ import annotations

import asyncio
import json
import socket
from typing import Any

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


def public_beacon_payload(snapshot: dict[str, Any], *, prefer_host: str = "") -> dict[str, Any] | None:
    pin = str(snapshot.get("server_pin") or "").strip().lower()
    endpoints = [str(item).rstrip("/") for item in (snapshot.get("endpoints") or []) if item]
    if len(pin) != 64 or not endpoints:
        return None
    chosen = endpoints[0]
    if prefer_host:
        for item in endpoints:
            if prefer_host in item:
                chosen = item
                break
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

    def datagram_received(self, data, addr):
        parsed = parse_beacon(data)
        if not parsed:
            return
        payload = self._payload_factory()
        if not payload:
            return
        blob = encode_beacon(payload)
        if self._transport:
            self._transport.sendto(blob, addr)

    async def _broadcast_loop(self):
        try:
            while True:
                payload = self._payload_factory()
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
