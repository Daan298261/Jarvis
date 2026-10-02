"""Bind Python TCP connects to this PC's on-link RFC1918 NIC.

``HTTP_PROXY`` only covers urllib/requests/httpx. A scanner that uses
``socket.connect`` (or httpx with ``trust_env=False``) still follows the VPN
default route. Patching ``socket.socket.connect`` pins LAN peers to the home
NIC; public and loopback destinations are unchanged.
"""
from __future__ import annotations

import ipaddress
import socket
from typing import Any

_RFC1918 = (
    ipaddress.ip_network("10.0.0.0/8"),
    ipaddress.ip_network("172.16.0.0/12"),
    ipaddress.ip_network("192.168.0.0/16"),
)
_installed = False
_orig_connect = socket.socket.connect
_orig_connect_ex = socket.socket.connect_ex


def _peer_ipv4(address: Any) -> str:
    if not isinstance(address, tuple) or not address:
        return ""
    host = address[0]
    if isinstance(host, bytes):
        try:
            host = host.decode("ascii")
        except UnicodeDecodeError:
            return ""
    text = str(host or "").strip().strip("[]")
    if not text:
        return ""
    try:
        addr = ipaddress.ip_address(text)
        return str(addr) if addr.version == 4 else ""
    except ValueError:
        pass
    try:
        infos = socket.getaddrinfo(text, None, socket.AF_INET, socket.SOCK_STREAM)
    except OSError:
        return ""
    if not infos or not infos[0][4]:
        return ""
    return str(infos[0][4][0])


def _source_bind(sock: socket.socket, address: Any) -> None:
    if getattr(sock, "family", None) != socket.AF_INET:
        return
    ip = _peer_ipv4(address)
    if not ip:
        return
    try:
        parsed = ipaddress.ip_address(ip)
    except ValueError:
        return
    if parsed.is_loopback or parsed.is_unspecified:
        return
    if not any(parsed in net for net in _RFC1918):
        return
    from ..mobile.wan_forward import lan_source_ipv4_for_peer

    bind = lan_source_ipv4_for_peer(ip)
    if not bind:
        return
    try:
        current = sock.getsockname()[0]
    except OSError:
        current = "0.0.0.0"
    if current not in {"0.0.0.0", ""}:
        return
    try:
        sock.bind((bind, 0))
    except OSError:
        return


def _connect(self: socket.socket, address: Any) -> None:
    _source_bind(self, address)
    return _orig_connect(self, address)


def _connect_ex(self: socket.socket, address: Any) -> int:
    _source_bind(self, address)
    return _orig_connect_ex(self, address)


def install_lan_bind() -> None:
    """Idempotent wrap of ``socket.socket.connect`` / ``connect_ex``."""
    global _installed
    if _installed:
        return
    socket.socket.connect = _connect  # type: ignore[method-assign]
    socket.socket.connect_ex = _connect_ex  # type: ignore[method-assign]
    _installed = True
