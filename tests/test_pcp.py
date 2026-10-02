from __future__ import annotations

import struct

import pytest

from app.mobile.pcp import (
    PORT,
    decode_assigned_ipv4,
    decode_map_response,
    encode_map_request,
    ipv4_mapped,
)


def _nonce() -> bytes:
    return b"\x01\x02\x03\x04\x05\x06\x07\x08\x09\x0a\x0b\x0c"


def test_pcp_map_request_is_tcp_4781_only():
    nonce = _nonce()
    packet = encode_map_request("192.168.1.12", nonce, 3600)
    assert len(packet) == 60
    version, opcode, reserved, lifetime = struct.unpack("!BBHI", packet[:8])
    assert version == 2 and opcode == 1 and reserved == 0 and lifetime == 3600
    assert packet[8:24] == ipv4_mapped("192.168.1.12")
    assert packet[24:36] == nonce
    protocol, _reserved, internal, external = struct.unpack("!B3sHH", packet[36:44])
    assert protocol == 6 and internal == PORT == external == 4781
    assert packet[44:60] == b"\x00" * 16
    with pytest.raises(ValueError):
        ipv4_mapped("8.8.8.8")
    with pytest.raises(ValueError):
        ipv4_mapped("100.64.1.8")


def test_pcp_map_reply_must_be_4781_and_public():
    nonce = _nonce()
    public = b"\x00" * 10 + b"\xff\xff" + bytes([8, 8, 4, 4])
    body = nonce + struct.pack("!B3sHH", 6, b"\x00\x00\x00", 4781, 4781) + public
    header = struct.pack("!BBHI", 2, 0x81, 0, 3600) + (b"\x00" * 16)
    assert decode_map_response(header + body, nonce) == ("8.8.4.4", 3600)
    other = nonce + struct.pack("!B3sHH", 6, b"\x00\x00\x00", 4781, 443) + public
    with pytest.raises(ValueError, match="other than TCP 4781"):
        decode_map_response(header + other, nonce)
    refused_header = struct.pack("!BBHI", 2, 0x81, 11, 0) + (b"\x00" * 16)
    with pytest.raises(RuntimeError, match="refused"):
        decode_map_response(refused_header + body, nonce)
    cgnat = b"\x00" * 10 + b"\xff\xff" + bytes([10, 8, 0, 2])
    with pytest.raises(ValueError, match="no public IPv4"):
        decode_assigned_ipv4(cgnat)
    with pytest.raises(ValueError, match="nonce"):
        decode_map_response(header + body, b"\x00" * 12)
