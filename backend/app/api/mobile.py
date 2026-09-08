from __future__ import annotations

import hashlib
import json
import platform
import secrets
import socket
import subprocess
import time
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel

from ..auth import generate_private_key, get_effective_private_key
from ..config import data_dir, load_settings, repo_root

router = APIRouter(prefix="/api/mobile", tags=["mobile"])
PAIR_TTL_SECONDS = 10 * 60


class PairExchange(BaseModel):
    token: str


class ApkBuildRequest(BaseModel):
    install_build_tools: bool = False


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


def _pair_store_path() -> Path:
    return data_dir() / "mobile_pairing.json"


def _load_pairs() -> dict[str, Any]:
    path = _pair_store_path()
    if not path.exists():
        return {}
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
        return raw if isinstance(raw, dict) else {}
    except Exception:
        return {}


def _save_pairs(rows: dict[str, Any]) -> None:
    path = _pair_store_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(rows, indent=2), encoding="utf-8")


def _token_hash(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def _prune_pairs(rows: dict[str, Any]) -> dict[str, Any]:
    now = time.time()
    return {
        key: value
        for key, value in rows.items()
        if isinstance(value, dict) and float(value.get("expires_at") or 0) > now
    }


def _apk_path() -> Path:
    return data_dir() / "setup" / "JarvisPhone.apk"


def mobile_snapshot() -> dict[str, Any]:
    settings = load_settings()
    port = settings.bind_port
    hosts = _lan_hosts()
    lan_urls = [f"http://{host}:{port}" for host in hosts]
    apk = _apk_path()
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
        "package": {
            "apk_ready": apk.exists() and apk.stat().st_size > 0,
            "apk_download": "/api/mobile/apk" if apk.exists() else "",
            "pwa_ready": True,
            "build_script": "scripts/build-android-client.ps1",
        },
        "pairing": {
            "install": "Open the LAN/Tailscale Phone URL. Android can install it as an app from Chrome; an APK can also be built from the Phone page.",
            "auth": "Use Create pairing link on the PC. The link is one-time and expires after 10 minutes; the long-lived Jarvis key is not placed in the link.",
            "lan": "LAN access uses the private Windows firewall profile. Remote access should use Tailscale rather than a public router port.",
        },
    }


@router.get("")
async def mobile_info():
    return mobile_snapshot()


@router.post("/pairing")
async def create_pairing():
    settings = load_settings()
    private_key = get_effective_private_key(settings) or generate_private_key()
    token = secrets.token_urlsafe(32)
    token_hash = _token_hash(token)
    rows = _prune_pairs(_load_pairs())
    rows[token_hash] = {"expires_at": time.time() + PAIR_TTL_SECONDS}
    _save_pairs(rows)

    snapshot = mobile_snapshot()
    bases = snapshot["urls"].get("lan") or [snapshot["urls"]["local"]]
    pair_urls = [f"{base}/phone?pair_token={token}" for base in bases]
    return {
        "token": token,
        "expires_in_seconds": PAIR_TTL_SECONDS,
        "urls": pair_urls,
        "private_key_ready": bool(private_key),
    }


@router.post("/pair/exchange")
async def exchange_pairing(body: PairExchange):
    token = str(body.token or "").strip()
    if not token:
        raise HTTPException(400, "Pairing token required")
    rows = _prune_pairs(_load_pairs())
    digest = _token_hash(token)
    row = rows.pop(digest, None)
    _save_pairs(rows)
    if not row:
        raise HTTPException(401, "Pairing link is invalid, expired, or already used")
    key = get_effective_private_key(load_settings())
    if not key:
        raise HTTPException(409, "Jarvis private key is not configured")
    return {"ok": True, "private_key": key}


@router.post("/apk/build")
async def build_apk(body: ApkBuildRequest):
    if platform.system() != "Windows":
        raise HTTPException(400, "Android APK auto-build is currently supported on the Windows Jarvis host")
    script = repo_root() / "scripts" / "build-android-client.ps1"
    if not script.exists():
        raise HTTPException(404, "Android build script is missing")
    settings = load_settings()
    args = [
        "powershell.exe",
        "-NoProfile",
        "-ExecutionPolicy",
        "Bypass",
        "-File",
        str(script),
        "-JarvisUrl",
        f"http://127.0.0.1:{settings.bind_port}",
    ]
    if body.install_build_tools:
        args.append("-InstallBuildTools")
    log_path = data_dir() / "setup" / "android-build.log"
    log_path.parent.mkdir(parents=True, exist_ok=True)
    log_handle = open(log_path, "a", encoding="utf-8")
    try:
        subprocess.Popen(  # noqa: S603 - fixed local script, no user command input
            args,
            cwd=str(repo_root()),
            stdout=log_handle,
            stderr=subprocess.STDOUT,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
    except Exception as exc:
        log_handle.close()
        raise HTTPException(500, f"Could not start Android build: {exc}") from exc
    return {"started": True, "log": str(log_path), "apk": str(_apk_path())}


@router.get("/apk")
async def download_apk():
    path = _apk_path()
    if not path.exists() or path.stat().st_size <= 0:
        raise HTTPException(404, "Android APK has not been built on this PC yet")
    return FileResponse(path, media_type="application/vnd.android.package-archive", filename="JarvisPhone.apk")
