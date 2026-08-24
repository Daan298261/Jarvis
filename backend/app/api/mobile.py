from __future__ import annotations

import socket
from typing import Any

from fastapi import APIRouter

from ..config import load_settings
from ..auth import get_effective_private_key

router = APIRouter(prefix="/api/mobile", tags=["mobile"])


def _lan_hosts() -> list[str]:
    found: set[str] = set()
    try:
        hostname = socket.gethostname()
        for info in socket.getaddrinfo(hostname, None, socket.AF_INET):
            ip = info[4][0]
            if ip and not ip.startswith("127."):
                found.add(ip)
    except OSError:
        pass
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.settimeout(0.3)
        sock.connect(("1.1.1.1", 80))
        ip = sock.getsockname()[0]
        sock.close()
        if ip and not ip.startswith("127."):
            found.add(ip)
    except OSError:
        pass
    return sorted(found)


def mobile_snapshot() -> dict[str, Any]:
    settings = load_settings()
    port = settings.bind_port
    hosts = _lan_hosts()
    lan_urls = [f"http://{host}:{port}" for host in hosts]
    return {
        "app": "Jarvis",
        "client": "android-pwa",
        "bind_host": settings.bind_host,
        "bind_port": port,
        "lan_access": settings.lan_access,
        "auth_required": settings.auth_required,
        "has_key": bool(get_effective_private_key(settings)),
        "urls": {
            "local": f"http://127.0.0.1:{port}",
            "phone": f"http://127.0.0.1:{port}/phone",
            "lan": lan_urls,
            "lan_phone": [f"{url}/phone" for url in lan_urls],
        },
        "pairing": {
            "install": "On Android Chrome or Samsung Internet, open the LAN URL, then Add to Home screen.",
            "auth": "Paste the Jarvis private key on the Phone page. Do not share the key in chat or email.",
            "lan": "Enable LAN access in Settings and bind on the PC before opening the URL from a phone.",
        },
    }


@router.get("")
async def mobile_info():
    return mobile_snapshot()
