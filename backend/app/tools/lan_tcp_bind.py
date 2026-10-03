"""Source-bind a TCP client that has no bind flag (redis-cli, psql, mongosh).

Listen on loopback, connect to the on-link RFC1918 peer from ``SOURCE``, and
rewrite the child ``-h``/``-p`` (or URI) to the loopback port so a VPN default
route cannot steal the session.
"""
from __future__ import annotations

import socket
import subprocess
import sys
import threading
from urllib.parse import urlparse, urlunparse


def loopback_client_argv(kind: str, argv: list[str], loop_host: str, loop_port: int) -> list[str]:
    """Rewrite a client argv so it dials ``loop_host:loop_port`` instead of the NAS."""
    if not argv:
        return argv
    mode = str(kind or "").strip().lower()
    host_flags = {"-h", "--host"}
    port_flags = {"-p", "--port"}
    uri_flags = {"-u", "--uri", "--url"}
    if mode == "psql":
        uri_flags = set()
    if mode == "mongosh":
        host_flags = {"--host"}
        port_flags = {"--port"}
        uri_flags = set()
    out: list[str] = [argv[0]]
    index = 1
    have_host = False
    have_port = False
    while index < len(argv):
        tok = str(argv[index])
        key = tok.split("=", 1)[0]
        if key in uri_flags or tok.startswith("--uri=") or tok.startswith("--url="):
            raw = tok.split("=", 1)[1] if "=" in tok and tok.startswith("--") else ""
            if not raw:
                if index + 1 >= len(argv):
                    break
                raw = str(argv[index + 1])
                index += 2
                out.extend([tok if tok.startswith("--") and "=" not in tok else key, _loopback_uri(raw, loop_host, loop_port)])
                have_host = True
                have_port = True
                continue
            out.append(f"{key}={_loopback_uri(raw, loop_host, loop_port)}")
            have_host = True
            have_port = True
            index += 1
            continue
        if tok.startswith("--host="):
            out.append(f"--host={loop_host}")
            have_host = True
            index += 1
            continue
        if tok.startswith("--port="):
            out.append(f"--port={loop_port}")
            have_port = True
            index += 1
            continue
        if key in host_flags:
            out.extend([tok, loop_host])
            have_host = True
            index += 2
            continue
        if key in port_flags:
            out.extend([tok, str(loop_port)])
            have_port = True
            index += 2
            continue
        if mode == "psql" and "://" in tok and tok.lower().startswith(("postgres://", "postgresql://")):
            out.append(_loopback_uri(tok, loop_host, loop_port))
            have_host = True
            have_port = True
            index += 1
            continue
        if mode == "mongosh" and tok.lower().startswith("mongodb://"):
            out.append(_loopback_uri(tok, loop_host, loop_port))
            have_host = True
            have_port = True
            index += 1
            continue
        out.append(tok)
        index += 1
    extra: list[str] = []
    if not have_host:
        extra.extend(["--host" if mode == "mongosh" else "-h", loop_host])
    if not have_port:
        extra.extend(["--port" if mode == "mongosh" else "-p", str(loop_port)])
    if extra:
        out[1:1] = extra
    return out


def _loopback_uri(raw: str, host: str, port: int) -> str:
    parsed = urlparse(str(raw or "").strip())
    if not parsed.scheme:
        return raw
    netloc = parsed.netloc
    user = ""
    if "@" in netloc:
        user, _peer = netloc.rsplit("@", 1)
        user = f"{user}@"
    return urlunparse(parsed._replace(netloc=f"{user}{host}:{port}"))


def _pump(src: socket.socket, dst: socket.socket) -> None:
    try:
        while True:
            chunk = src.recv(65536)
            if not chunk:
                break
            dst.sendall(chunk)
    except OSError:
        return
    try:
        dst.shutdown(socket.SHUT_WR)
    except OSError:
        return


def _bridge(client: socket.socket, peer: tuple[str, int], source: str) -> None:
    remote = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        if source:
            remote.bind((source, 0))
        remote.connect(peer)
    except OSError:
        client.close()
        remote.close()
        return
    first = threading.Thread(target=_pump, args=(client, remote), daemon=True)
    second = threading.Thread(target=_pump, args=(remote, client), daemon=True)
    first.start()
    second.start()
    first.join()
    second.join()
    try:
        client.close()
    except OSError:
        pass
    try:
        remote.close()
    except OSError:
        pass


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    if "--" not in args or len(args) < 6:
        return 2
    cut = args.index("--")
    spec = args[:cut]
    child = args[cut + 1 :]
    if len(spec) != 4 or not child:
        return 2
    kind, source, host, port_text = spec
    try:
        port = int(port_text)
    except ValueError:
        return 2
    if port < 1 or port > 65535:
        return 2
    listen = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    listen.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    listen.bind(("127.0.0.1", 0))
    listen.listen(16)
    loop_port = int(listen.getsockname()[1])
    stop = threading.Event()

    def accept_loop() -> None:
        listen.settimeout(0.25)
        while not stop.is_set():
            try:
                client, _addr = listen.accept()
            except TimeoutError:
                continue
            except OSError:
                break
            threading.Thread(
                target=_bridge,
                args=(client, (host, port), source),
                daemon=True,
            ).start()

    acceptor = threading.Thread(target=accept_loop, daemon=True)
    acceptor.start()
    rewritten = loopback_client_argv(kind, child, "127.0.0.1", loop_port)
    try:
        proc = subprocess.run(rewritten, check=False)
        return int(proc.returncode or 0)
    finally:
        stop.set()
        try:
            listen.close()
        except OSError:
            pass
        acceptor.join(timeout=1)


if __name__ == "__main__":
    raise SystemExit(main())
