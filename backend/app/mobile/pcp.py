"""PCP MAP client for companion TCP 4781 when NAT-PMP version 0 is off.

RFC 6887 Port Control Protocol on UDP 5351 to this PC's private default
gateway only. Maps TCP 4781 for a one-hour lease. Does not scan, guess
credentials, or map any other port.
"""
from __future__ import annotations

import ipaddress
import os
import struct

from .natpmp import LEASE_SECONDS, PORT, require_private_gateway, udp_exchange
from .wan_forward import default_gateway_ipv4, is_rfc1918_ipv4

_OPCODE_MAP = 1
_PROTO_TCP = 6
_RESPONSE = 0x80


def ipv4_mapped(host: str) -> bytes:
    text = (host or "").strip()
    if not is_rfc1918_ipv4(text):
        raise ValueError("PCP client address must be a private LAN IPv4")
    address = ipaddress.ip_address(text)
    return b"\x00" * 10 + b"\xff\xff" + address.packed


def decode_assigned_ipv4(raw: bytes) -> str:
    if len(raw) < 16:
        raise ValueError("PCP assigned address was truncated")
    if raw[:12] == b"\x00" * 10 + b"\xff\xff" or raw[:12] == b"\x00" * 12:
        address = ipaddress.IPv4Address(raw[12:16])
    else:
        raise ValueError("PCP assigned address was not IPv4")
    if not address.is_global:
        raise ValueError("Router has no public IPv4 address")
    return str(address)


def encode_map_request(lan_ip: str, nonce: bytes, lifetime: int) -> bytes:
    if len(nonce) != 12:
        raise ValueError("PCP nonce must be 12 bytes")
    header = struct.pack("!BBHI", 2, _OPCODE_MAP, 0, int(lifetime)) + ipv4_mapped(lan_ip)
    body = nonce + struct.pack("!B3sHH", _PROTO_TCP, b"\x00\x00\x00", PORT, PORT) + (b"\x00" * 16)
    return header + body


def decode_map_response(payload: bytes, nonce: bytes) -> tuple[str, int]:
    if len(payload) < 60:
        raise ValueError("PCP MAP reply was truncated")
    version, opcode, reserved_result, lifetime = struct.unpack("!BBHI", payload[:8])
    if version != 2 or opcode != (_OPCODE_MAP | _RESPONSE):
        raise ValueError("Not a PCP MAP reply")
    result = reserved_result & 0xFF
    if result != 0:
        raise RuntimeError(f"PCP MAP refused ({result})")
    body = payload[24:60]
    got_nonce = body[:12]
    if got_nonce != nonce:
        raise ValueError("PCP MAP reply nonce did not match")
    protocol, _reserved, internal, external = struct.unpack("!B3sHH", body[12:20])
    if int(protocol) != _PROTO_TCP or int(internal) != PORT or int(external) != PORT:
        raise ValueError("PCP mapped a port other than TCP 4781; mapping not used")
    public = decode_assigned_ipv4(body[20:36])
    return public, int(lifetime)


def apply_pcp(gateway: str = "", lan_ip: str = "", nonce: bytes | None = None) -> tuple[str, bytes]:
    """Map TCP 4781 for one hour. Returns (public IPv4, nonce used for renew/unmap)."""
    gw = require_private_gateway(gateway or default_gateway_ipv4())
    client = (lan_ip or "").strip()
    if not client:
        raise ValueError("PCP needs this PC's private LAN IPv4")
    token = nonce if nonce and len(nonce) == 12 else os.urandom(12)
    packet = encode_map_request(client, token, LEASE_SECONDS)
    public, _lifetime = decode_map_response(udp_exchange(gw, packet, 60, client), token)
    return public, token


def delete_pcp(gateway: str, lan_ip: str = "", nonce: bytes | None = None) -> None:
    gw = require_private_gateway(gateway)
    client = (lan_ip or "").strip()
    if not client:
        return
    token = nonce if nonce and len(nonce) == 12 else os.urandom(12)
    try:
        udp_exchange(gw, encode_map_request(client, token, 0), 60, client, attempts=2)
    except (OSError, ValueError, RuntimeError, TimeoutError):
        return
