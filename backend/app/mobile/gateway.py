"""TLS-only, allowlisted mobile ingress to the running localhost Jarvis API.

Run: python -m app.mobile.gateway --host 192.168.1.10
It creates a private local server identity; --host is a certificate SAN, not bind IP.
"""
from __future__ import annotations

import argparse
import hashlib
import ipaddress
import os
import time
from collections import defaultdict, deque
from datetime import datetime, timedelta, timezone

import httpx
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.x509.oid import NameOID
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, Response

from .store import root


def server_identity(hostnames: list[str]):
    folder = root() / "tls"
    folder.mkdir(exist_ok=True)
    key_path, cert_path = folder / "server.key", folder / "server.crt"
    if key_path.exists():
        key = serialization.load_pem_private_key(key_path.read_bytes(), password=None)
    else:
        key = ec.generate_private_key(ec.SECP256R1())
        fd = os.open(key_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        with os.fdopen(fd, "wb") as output:
            output.write(key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()))
    public = key.public_key().public_bytes(serialization.Encoding.DER, serialization.PublicFormat.SubjectPublicKeyInfo)
    names = []
    if cert_path.exists():
        previous = x509.load_pem_x509_certificate(cert_path.read_bytes())
        hostnames = list(hostnames)
        try:
            previous_names = previous.extensions.get_extension_for_class(x509.SubjectAlternativeName).value
            hostnames += [str(name.value) for name in previous_names]
        except x509.ExtensionNotFound:
            pass
    for hostname in set(hostnames + ["localhost", "127.0.0.1"]):
        try:
            names.append(x509.IPAddress(ipaddress.ip_address(hostname)))
        except ValueError:
            names.append(x509.DNSName(hostname))
    subject = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "Jarvis mobile gateway")])
    certificate = (x509.CertificateBuilder().subject_name(subject).issuer_name(subject).public_key(key.public_key())
                   .serial_number(x509.random_serial_number()).not_valid_before(datetime.now(timezone.utc) - timedelta(minutes=5))
                   .not_valid_after(datetime.now(timezone.utc) + timedelta(days=365))
                   .add_extension(x509.SubjectAlternativeName(names), critical=False).sign(key, hashes.SHA256()))
    cert_path.write_bytes(certificate.public_bytes(serialization.Encoding.PEM))
    return {"certificate": str(cert_path), "key": str(key_path), "server_pin": hashlib.sha256(public).hexdigest()}


def gateway_app(upstream: str = "http://127.0.0.1:4780"):
    from urllib.parse import urlsplit
    parsed = urlsplit(upstream)
    if parsed.hostname not in {"127.0.0.1", "::1", "localhost"} or parsed.scheme != "http":
        raise ValueError("Gateway upstream must be the local Jarvis listener")
    app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)
    attempts: dict[str, deque] = defaultdict(deque)

    @app.api_route("/{path:path}", methods=["GET", "POST", "PUT", "DELETE"])
    async def proxy(path: str, request: Request):
        # A path encoded to escape this prefix must never reach owner APIs.
        if not path.startswith("api/companion/") or any(part in {".", ".."} for part in path.split("/")) or "%" in path or "\\" in path:
            return JSONResponse({"detail": "Route unavailable on mobile gateway"}, 404)
        if path.startswith(("api/companion/enroll", "api/companion/session", "api/companion/challenge/")):
            key = request.client.host if request.client else "unknown"
            now = time.monotonic()
            if len(attempts) > 4096:
                attempts.clear()
            window = attempts[key]
            while window and window[0] < now - 60:
                window.popleft()
            if len(window) >= 30:
                return JSONResponse({"detail": "Too many pairing attempts; retry in one minute"}, 429)
            window.append(now)
        data = bytearray()
        async for chunk in request.stream():
            data.extend(chunk)
            if len(data) > 64 * 1024 * 1024:
                return JSONResponse({"detail": "Request exceeds 64 MiB"}, 413)
        headers = {name: request.headers[name] for name in ("authorization", "x-jarvis-device", "content-type", "x-filename") if name in request.headers}
        # Never forward cookies, owner keys, forwarding identity or arbitrary headers.
        async with httpx.AsyncClient(timeout=120, trust_env=False) as client:
            try:
                response = await client.request(request.method, f"{upstream}/{path}", params=request.query_params, content=bytes(data), headers=headers)
            except httpx.HTTPError:
                return JSONResponse({"detail": "Jarvis is offline. Start the desktop service."}, 503)
        return Response(response.content, status_code=response.status_code,
                        headers={name: response.headers[name] for name in ("content-type", "content-disposition") if name in response.headers})

    return app


def main():
    import uvicorn
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", action="append", default=[])
    parser.add_argument("--port", type=int, default=4781)
    parser.add_argument("--upstream", default="http://127.0.0.1:4780")
    args = parser.parse_args()
    identity = server_identity(args.host)
    print("Server fingerprint:", identity["server_pin"])
    uvicorn.run(gateway_app(args.upstream), host="0.0.0.0", port=args.port,
                ssl_keyfile=identity["key"], ssl_certfile=identity["certificate"], proxy_headers=False,
                access_log=False, limit_concurrency=32)


if __name__ == "__main__":
    main()
