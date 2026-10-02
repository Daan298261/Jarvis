"""NAT-PMP client for companion TCP 4781 when UPnP/IGD is off.

Talks only to this PC's private default gateway on UDP 5351. Maps TCP 4781
for a one-hour lease. Does not scan, guess credentials, or map any other port.
"""
from __future__ import annotations

import ipaddress
import socket
import struct

from .wan_forward import PORT, default_gateway_ipv4, is_rfc1918_ipv4

NATPMP_PORT = 5351
LEASE_SECONDS = 3600
_OPCODE_PUBLIC = 0
_OPCODE_TCP = 2
_UNSUPPORTED_VERSION = 1


def require_private_gateway(host: str) -> str:
    address = ipaddress.ip_address((host or "").strip())
    if address.version != 4 or not address.is_private or address.is_loopback:
        raise ValueError("NAT-PMP gateway must be a private LAN IPv4 address")
    return str(address)


def encode_public_ip_request() -> bytes:
    return struct.pack("!BB", 0, _OPCODE_PUBLIC)


def encode_map_request(lifetime: int) -> bytes:
    return struct.pack("!BBHHHI", 0, _OPCODE_TCP, 0, PORT, PORT, int(lifetime))


def decode_public_ip(payload: bytes) -> str:
    if len(payload) < 12:
        raise ValueError("NAT-PMP public-IP reply was truncated")
    version, opcode, result, _epoch, raw_ip = struct.unpack("!BBHII", payload[:12])
    if version != 0 or opcode != (_OPCODE_PUBLIC | 0x80):
        raise ValueError("Not a NAT-PMP public-IP reply")
    if result == _UNSUPPORTED_VERSION:
        raise ValueError("NAT-PMP unsupported version")
    if result != 0:
        raise RuntimeError(f"NAT-PMP public IP refused ({result})")
    address = ipaddress.IPv4Address(raw_ip)
    if not address.is_global:
        raise ValueError("Router has no public IPv4 address")
    return str(address)


def decode_map_response(payload: bytes) -> tuple[int, int]:
    if len(payload) < 16:
        raise ValueError("NAT-PMP map reply was truncated")
    version, opcode, result, _epoch, internal, external, lifetime = struct.unpack("!BBHIHHI", payload[:16])
    if version != 0 or opcode != (_OPCODE_TCP | 0x80):
        raise ValueError("Not a NAT-PMP TCP map reply")
    if result == _UNSUPPORTED_VERSION:
        raise ValueError("NAT-PMP unsupported version")
    if result != 0:
        raise RuntimeError(f"NAT-PMP TCP map refused ({result})")
    if int(internal) != PORT or int(external) != PORT:
        raise ValueError("NAT-PMP mapped a port other than TCP 4781; mapping not used")
    return int(external), int(lifetime)


def udp_exchange(
    gateway: str,
    packet: bytes,
    expected: int,
    lan_ip: str = "",
    attempts: int = 3,
) -> bytes:
    """RFC 6886 retries: 250 ms, then double, talking only to the owner gateway."""
    gw = require_private_gateway(gateway)
    delay = 0.25
    last_error: Exception | None = None
    for _ in range(max(1, int(attempts))):
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.settimeout(delay)
        try:
            if lan_ip and is_rfc1918_ipv4(lan_ip):
                sock.bind((lan_ip.strip(), 0))
            sock.sendto(packet, (gw, NATPMP_PORT))
            data, addr = sock.recvfrom(512)
            peer = ipaddress.ip_address(addr[0])
            if str(peer) != gw:
                last_error = ValueError("NAT-PMP reply was not from the owner gateway")
                delay = min(delay * 2, 1.0)
                continue
            if len(data) < expected:
                last_error = ValueError("NAT-PMP reply was truncated")
                delay = min(delay * 2, 1.0)
                continue
            return data
        except (TimeoutError, socket.timeout, OSError) as exc:
            last_error = exc
            delay = min(delay * 2, 1.0)
        finally:
            sock.close()
    raise TimeoutError(str(last_error) if last_error else "No NAT-PMP reply")


def _exchange(gateway: str, packet: bytes, expected: int, lan_ip: str = "") -> bytes:
    return udp_exchange(gateway, packet, expected, lan_ip)


def apply_natpmp(gateway: str = "", lan_ip: str = "") -> str:
    """Map TCP 4781 for one hour. Returns the gateway's public IPv4."""
    gw = require_private_gateway(gateway or default_gateway_ipv4())
    public = decode_public_ip(udp_exchange(gw, encode_public_ip_request(), 12, lan_ip))
    decode_map_response(udp_exchange(gw, encode_map_request(LEASE_SECONDS), 16, lan_ip))
    return public


def delete_natpmp(gateway: str, lan_ip: str = "") -> None:
    gw = require_private_gateway(gateway)
    try:
        udp_exchange(gw, encode_map_request(0), 16, lan_ip, attempts=2)
    except (OSError, ValueError, RuntimeError, TimeoutError, socket.timeout):
        return
