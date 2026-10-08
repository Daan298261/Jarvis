"""Bind Python TCP connects and UDP sendto to this PC's on-link RFC1918 NIC.

``HTTP_PROXY`` only covers urllib/requests/httpx. A scanner that uses
``socket.connect`` (or httpx with ``trust_env=False``) still follows the VPN
default route. UDP probes (SNMP, mDNS, DNS to the LAN resolver) use
``sendto`` and never call ``connect``. Patching both pins LAN peers to the
home NIC; public and loopback destinations are unchanged.
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
_orig_sendto = socket.socket.sendto
_orig_sendmsg = getattr(socket.socket, "sendmsg", None)


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


def sendto_address(args: tuple[Any, ...], kwargs: dict[str, Any]) -> Any:
    """Peer tuple from ``sendto(data, address)`` or ``sendto(data, flags, address)``."""
    if "address" in kwargs:
        return kwargs["address"]
    if not args:
        return None
    if len(args) == 1:
        return args[0]
    return args[-1]


def _datagram(sock: Any) -> bool:
    sock_type = int(getattr(sock, "type", 0) or 0)
    return (sock_type & socket.SOCK_DGRAM) == socket.SOCK_DGRAM


def _sendto(self: socket.socket, data: Any, *args: Any, **kwargs: Any) -> int:
    if _datagram(self):
        _source_bind(self, sendto_address(args, kwargs))
    return _orig_sendto(self, data, *args, **kwargs)


def sendmsg_address(args: tuple[Any, ...], kwargs: dict[str, Any]) -> Any:
    """Peer from ``sendmsg(buffers, ancdata, flags, address)``."""
    if "address" in kwargs:
        return kwargs["address"]
    if len(args) >= 3:
        return args[2]
    return None


def _sendmsg(self: socket.socket, buffers: Any, *args: Any, **kwargs: Any) -> Any:
    if _orig_sendmsg is None:
        raise OSError("sendmsg is not available on this platform")
    if _datagram(self):
        _source_bind(self, sendmsg_address(args, kwargs))
    return _orig_sendmsg(self, buffers, *args, **kwargs)


def install_lan_bind() -> None:
    """Idempotent wrap of ``connect`` / ``connect_ex`` / ``sendto`` / ``sendmsg``."""
    global _installed
    if _installed:
        return
    socket.socket.connect = _connect  # type: ignore[method-assign]
    socket.socket.connect_ex = _connect_ex  # type: ignore[method-assign]
    socket.socket.sendto = _sendto  # type: ignore[method-assign]
    if _orig_sendmsg is not None:
        socket.socket.sendmsg = _sendmsg  # type: ignore[method-assign]
    _installed = True
