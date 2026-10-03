"""Raw Python sockets to RFC1918 bind the home NIC, not the VPN."""
from __future__ import annotations

import socket
from types import SimpleNamespace

from app.tools.lan_socket_bind import _sendto, _source_bind, sendto_address


def test_source_bind_pins_lan_and_skips_public_and_loopback(monkeypatch):
    monkeypatch.setattr("app.mobile.wan_forward.lan_source_ipv4_for_peer", lambda peer: "192.168.1.12")
    recorded: list[tuple[str, int]] = []

    class Sock:
        family = socket.AF_INET

        def getsockname(self):
            return ("0.0.0.0", 0)

        def bind(self, address):
            recorded.append(address)

    _source_bind(Sock(), ("192.168.1.40", 80))
    assert recorded == [("192.168.1.12", 0)]
    recorded.clear()
    _source_bind(Sock(), ("8.8.8.8", 443))
    assert recorded == []
    recorded.clear()
    _source_bind(Sock(), ("127.0.0.1", 8888))
    assert recorded == []
    already = Sock()
    already.getsockname = lambda: ("10.8.0.2", 12345)  # type: ignore[method-assign]
    _source_bind(already, ("192.168.1.40", 80))
    assert recorded == []
    udp = SimpleNamespace(family=socket.AF_INET6)
    _source_bind(udp, ("192.168.1.40", 80))
    assert recorded == []


def test_sendto_address_two_and_three_arg_forms():
    assert sendto_address((("192.168.1.40", 161),), {}) == ("192.168.1.40", 161)
    assert sendto_address((0, ("192.168.1.40", 161)), {}) == ("192.168.1.40", 161)
    assert sendto_address((), {"address": ("10.0.0.1", 53)}) == ("10.0.0.1", 53)


def test_sendto_binds_lan_datagram_and_skips_public(monkeypatch):
    monkeypatch.setattr(
        "app.mobile.wan_forward.lan_source_ipv4_for_peer",
        lambda peer: "192.168.1.12" if str(peer).startswith("192.168.") else "",
    )
    recorded: list[tuple[str, int]] = []
    sent: list[tuple[bytes, tuple]] = []

    class Sock:
        family = socket.AF_INET
        type = socket.SOCK_DGRAM

        def getsockname(self):
            return ("0.0.0.0", 0)

        def bind(self, address):
            recorded.append(address)

    def fake_sendto(self, data, *args, **kwargs):
        sent.append((data, args))
        return len(data)

    monkeypatch.setattr("app.tools.lan_socket_bind._orig_sendto", fake_sendto)
    assert _sendto(Sock(), b"ping", ("192.168.1.40", 161)) == 4
    assert recorded == [("192.168.1.12", 0)]
    recorded.clear()
    assert _sendto(Sock(), b"ping", ("8.8.8.8", 53)) == 4
    assert recorded == []
    tcp = Sock()
    tcp.type = socket.SOCK_STREAM
    _sendto(tcp, b"x", ("192.168.1.40", 80))
    assert recorded == []
