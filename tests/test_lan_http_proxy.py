"""Process-local LAN HTTP proxy for HexStrike tools without a source-bind flag."""
from __future__ import annotations

import socket
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import httpx
import pytest

from app.security.lan_http_proxy import (
    connect_lan,
    ensure_lan_http_proxy,
    peer_allowed,
    stop_lan_http_proxy,
)


@pytest.fixture(autouse=True)
def _stop_proxy():
    yield
    stop_lan_http_proxy()


class _OriginHandler(BaseHTTPRequestHandler):
    def log_message(self, format, *args):  # noqa: A002
        return

    def do_GET(self):
        body = b"lan-ok"
        self.send_response(200)
        self.send_header("Content-Type", "text/plain")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


def _serve_origin():
    server = ThreadingHTTPServer(("127.0.0.1", 0), _OriginHandler)
    server.daemon_threads = True
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    port = int(server.server_address[1])
    return server, port


def test_peer_allowed_private_not_public():
    assert peer_allowed("192.168.1.40")
    assert peer_allowed("10.0.0.1")
    assert peer_allowed("127.0.0.1")
    assert not peer_allowed("8.8.8.8")
    assert not peer_allowed("1.1.1.1")
    assert not peer_allowed("100.64.1.8")


def test_proxy_forwards_loopback_http_and_refuses_public():
    origin_server, origin_port = _serve_origin()
    try:
        proxy = ensure_lan_http_proxy()
        with httpx.Client(proxy=proxy, trust_env=False, timeout=5.0) as client:
            response = client.get(f"http://127.0.0.1:{origin_port}/status")
            assert response.status_code == 200
            assert response.text == "lan-ok"
            denied = client.get("http://8.8.8.8/")
            assert denied.status_code == 403
    finally:
        origin_server.shutdown()
        origin_server.server_close()


def test_connect_lan_binds_on_link_source(monkeypatch):
    recorded: list[tuple[str, int]] = []
    real_socket = socket.socket

    class RecordingSocket:
        def __init__(self, *args, **kwargs):
            self._sock = real_socket(*args, **kwargs)
            self.bound = None

        def bind(self, address):
            recorded.append(address)
            self.bound = address
            return self._sock.bind(address)

        def settimeout(self, value):
            return self._sock.settimeout(value)

        def connect(self, address):
            self.connected = address

        def close(self):
            self._sock.close()

        def __getattr__(self, name):
            return getattr(self._sock, name)

    monkeypatch.setattr("app.security.lan_http_proxy.socket.socket", RecordingSocket)
    monkeypatch.setattr("app.mobile.wan_forward.lan_source_ipv4_for_peer", lambda peer: "192.168.1.12")

    sock = connect_lan("192.168.1.40", 80, timeout=1.0)
    try:
        assert recorded == [("192.168.1.12", 0)]
        assert sock.connected == ("192.168.1.40", 80)
    finally:
        sock.close()


def test_connect_lan_rejects_public_destination():
    with pytest.raises(PermissionError, match="private LAN"):
        connect_lan("8.8.8.8", 80, timeout=1.0)
