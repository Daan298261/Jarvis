from __future__ import annotations

import struct

import pytest

from app.mobile.natpmp import (
    PORT,
    decode_map_response,
    decode_public_ip,
    encode_map_request,
    encode_public_ip_request,
    require_private_gateway,
)


def test_natpmp_packets_are_tcp_4781_only():
    assert encode_public_ip_request() == b"\x00\x00"
    packet = encode_map_request(3600)
    version, opcode, reserved, internal, external, lifetime = struct.unpack("!BBHHHI", packet)
    assert version == 0 and opcode == 2 and reserved == 0
    assert internal == PORT == external == 4781
    assert lifetime == 3600
    with pytest.raises(ValueError):
        require_private_gateway("8.8.8.8")
    assert require_private_gateway("192.168.1.1") == "192.168.1.1"


def test_natpmp_decodes_public_ip_and_rejects_cgnat():
    packed = int.from_bytes(bytes(int(p) for p in "8.8.4.4".split(".")), "big")
    public = struct.pack("!BBHII", 0, 128, 0, 1, packed)
    assert decode_public_ip(public) == "8.8.4.4"
    cgnat = struct.pack("!BBHII", 0, 128, 0, 1, int.from_bytes(bytes([10, 8, 0, 2]), "big"))
    with pytest.raises(ValueError, match="no public IPv4"):
        decode_public_ip(cgnat)


def test_natpmp_map_reply_must_be_4781():
    ok = struct.pack("!BBHIHHI", 0, 130, 0, 1, 4781, 4781, 3600)
    assert decode_map_response(ok) == (4781, 3600)
    other = struct.pack("!BBHIHHI", 0, 130, 0, 1, 4781, 443, 3600)
    with pytest.raises(ValueError, match="other than TCP 4781"):
        decode_map_response(other)
    refused = struct.pack("!BBHIHHI", 0, 130, 3, 1, 4781, 4781, 0)
    with pytest.raises(RuntimeError, match="refused"):
        decode_map_response(refused)
