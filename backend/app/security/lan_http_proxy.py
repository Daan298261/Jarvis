"""Loopback HTTP proxy that sources RFC1918 hops from the on-link NIC.

HexStrike gobuster/ffuf/dirsearch (and sqlmap/nikto/feroxbuster) have no
``--source-ip`` flag. A VPN default route would steal directory brute-force of
the NAS or gateway. This process-local proxy listens on 127.0.0.1 and connects
to on-link RFC1918 peers with ``SO_BINDTODEVICE``-equivalent ``bind(lan_ip)``.
Public internet destinations are refused.
"""
from __future__ import annotations

import ipaddress
import select
import socket
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any
from urllib.parse import urlsplit

_RFC1918 = (
    ipaddress.ip_network("10.0.0.0/8"),
    ipaddress.ip_network("172.16.0.0/12"),
    ipaddress.ip_network("192.168.0.0/16"),
)
_HOP_BY_HOP = frozenset(
    {
        "connection",
        "keep-alive",
        "proxy-authenticate",
        "proxy-authorization",
        "proxy-connection",
        "te",
        "trailers",
        "transfer-encoding",
        "upgrade",
    }
)
_LOCK = threading.Lock()
_SERVER: ThreadingHTTPServer | None = None
_THREAD: threading.Thread | None = None
_ORIGIN = ""


def peer_allowed(ip: str) -> bool:
    """True for loopback, link-local, or RFC1918 — never CGNAT or public."""
    try:
        addr = ipaddress.ip_address((ip or "").strip())
    except ValueError:
        return False
    if addr.version != 4:
        return False
    if addr.is_loopback or addr.is_link_local:
        return True
    return any(addr in net for net in _RFC1918)


def resolve_ipv4(host: str) -> str:
    text = (host or "").strip().strip("[]")
    if not text:
        raise ValueError("empty host")
    try:
        addr = ipaddress.ip_address(text)
        if addr.version != 4:
            raise ValueError("not ipv4")
        return str(addr)
    except ValueError:
        pass
    infos = socket.getaddrinfo(text, None, socket.AF_INET, socket.SOCK_STREAM)
    if not infos or not infos[0][4]:
        raise OSError(f"cannot resolve {text}")
    return str(infos[0][4][0])


def connect_lan(host: str, port: int, *, timeout: float = 30.0) -> socket.socket:
    """TCP connect to a private peer, sourced from this PC's on-link RFC1918 NIC."""
    ip = resolve_ipv4(host)
    if not peer_allowed(ip):
        raise PermissionError("lan http proxy only forwards private LAN addresses")
    dest_port = int(port)
    if dest_port < 1 or dest_port > 65535:
        raise ValueError("invalid port")
    from ..mobile.wan_forward import lan_source_ipv4_for_peer

    bind = lan_source_ipv4_for_peer(ip)
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.settimeout(timeout)
    if bind:
        try:
            sock.bind((bind, 0))
        except OSError:
            pass
    sock.connect((ip, dest_port))
    return sock


def _tunnel(left: socket.socket, right: socket.socket, *, timeout: float = 120.0) -> None:
    deadline = time.monotonic() + timeout
    sockets = (left, right)
    try:
        while time.monotonic() < deadline:
            readable, _, _ = select.select(sockets, [], [], 1.0)
            if not readable:
                continue
            for src in readable:
                dst = right if src is left else left
                try:
                    data = src.recv(65536)
                except OSError:
                    return
                if not data:
                    return
                try:
                    dst.sendall(data)
                except OSError:
                    return
    finally:
        try:
            right.close()
        except OSError:
            pass


class _Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    close_connection = True
    timeout = 30

    def log_message(self, format: str, *args: Any) -> None:
        return

    def do_CONNECT(self) -> None:  # noqa: N802
        host, _, port_text = (self.path or "").rpartition(":")
        host = host.strip("[]")
        try:
            port = int(port_text or 443)
            sock = connect_lan(host, port)
        except PermissionError:
            self.send_error(403, "Public destinations are not forwarded")
            return
        except Exception:
            self.send_error(502, "Tunnel failed")
            return
        self.send_response(200, "Connection Established")
        self.end_headers()
        try:
            self.wfile.flush()
        except OSError:
            sock.close()
            return
        _tunnel(self.connection, sock)

    def do_GET(self) -> None:  # noqa: N802
        self._forward_http()

    def do_POST(self) -> None:  # noqa: N802
        self._forward_http()

    def do_HEAD(self) -> None:  # noqa: N802
        self._forward_http()

    def do_PUT(self) -> None:  # noqa: N802
        self._forward_http()

    def do_DELETE(self) -> None:  # noqa: N802
        self._forward_http()

    def do_PATCH(self) -> None:  # noqa: N802
        self._forward_http()

    def do_OPTIONS(self) -> None:  # noqa: N802
        self._forward_http()

    def _destination(self) -> tuple[str, int, str]:
        parsed = urlsplit(self.path or "")
        if parsed.scheme in {"http", "https"} and parsed.hostname:
            port = parsed.port or (443 if parsed.scheme == "https" else 80)
            path = parsed.path or "/"
            if parsed.query:
                path = f"{path}?{parsed.query}"
            return parsed.hostname, int(port), path
        host_hdr = (self.headers.get("Host") or "").strip()
        host, _, port_text = host_hdr.rpartition(":")
        if not host:
            host, port_text = host_hdr, ""
        port = int(port_text) if port_text.isdigit() else 80
        return host, port, self.path or "/"

    def _forward_http(self) -> None:
        try:
            host, port, path = self._destination()
        except Exception:
            self.send_error(400, "Bad proxy request")
            return
        try:
            length = int(self.headers.get("Content-Length") or 0)
        except ValueError:
            length = 0
        if length < 0 or length > 8 * 1024 * 1024:
            self.send_error(413, "Body too large")
            return
        body = self.rfile.read(length) if length else b""
        try:
            sock = connect_lan(host, port)
        except PermissionError:
            self.send_error(403, "Public destinations are not forwarded")
            return
        except Exception:
            self.send_error(502, "Upstream connect failed")
            return
        lines = [f"{self.command} {path} HTTP/1.1"]
        host_sent = False
        for key, value in self.headers.items():
            lowered = key.lower()
            if lowered in _HOP_BY_HOP:
                continue
            if lowered == "host":
                host_sent = True
            lines.append(f"{key}: {value}")
        if not host_sent:
            lines.append(f"Host: {host}" if port in {80, 443} else f"Host: {host}:{port}")
        lines.append("Connection: close")
        lines.append("")
        payload = ("\r\n".join(lines) + "\r\n").encode("latin-1", errors="replace") + body
        try:
            sock.sendall(payload)
            while True:
                chunk = sock.recv(65536)
                if not chunk:
                    break
                self.wfile.write(chunk)
            self.wfile.flush()
        except OSError:
            pass
        finally:
            try:
                sock.close()
            except OSError:
                pass


def ensure_lan_http_proxy() -> str:
    """Start the process-local proxy once; return ``http://127.0.0.1:<port>``."""
    global _SERVER, _THREAD, _ORIGIN
    with _LOCK:
        if _ORIGIN:
            return _ORIGIN
        server = ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
        server.daemon_threads = True
        port = int(server.server_address[1])
        thread = threading.Thread(
            target=server.serve_forever,
            name="jarvis-lan-http-proxy",
            daemon=True,
        )
        thread.start()
        _SERVER = server
        _THREAD = thread
        _ORIGIN = f"http://127.0.0.1:{port}"
        return _ORIGIN


def stop_lan_http_proxy() -> None:
    global _SERVER, _THREAD, _ORIGIN
    with _LOCK:
        server = _SERVER
        _SERVER = None
        _THREAD = None
        _ORIGIN = ""
    if server is not None:
        try:
            server.shutdown()
        except Exception:
            pass
        try:
            server.server_close()
        except Exception:
            pass


def lan_http_proxy_origin() -> str:
    return ensure_lan_http_proxy()
