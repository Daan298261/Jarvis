"""RFC-0215: off-LAN companion reachability is Tailscale only.

Tailscale detection (``tailscale status --json``), endpoint classification and
ordering for the pairing QR (Tailscale first, then LAN), the reachability
self-test and exposure logging. Nothing here opens a port; ``Connectivity``
only advertises Tailscale endpoints when the owner switched remote access on.
"""
from __future__ import annotations

import ipaddress
import json
import logging
import shutil
import subprocess
import time
from pathlib import Path
from typing import Any, Callable, Literal
from urllib.parse import urlsplit


log = logging.getLogger(__name__)

PORT = 4781
EndpointKind = Literal["tailscale", "lan", "public_forward"]

# QR order: Tailscale first (the owner's chosen off-LAN path; it also works at
# home), then LAN. The phone still prefers an origin on its attached LAN itself.
KIND_RANK: dict[str, int] = {"public_forward": 0, "tailscale": 0, "lan": 1}

TAILSCALE_CGNAT = ipaddress.ip_network("100.64.0.0/10")
TAILSCALE_V6 = ipaddress.ip_network("fd7a:115c:a1e0::/48")


# ---------------------------------------------------------------- classification

def _host(origin: str) -> str:
    return (urlsplit(origin).hostname or "").strip().lower().rstrip(".")


def is_tailscale_host(host: str) -> bool:
    host = (host or "").lower().rstrip(".")
    if host.endswith(".ts.net"):
        return True
    try:
        address = ipaddress.ip_address(host)
    except ValueError:
        return False
    return address in TAILSCALE_CGNAT or address in TAILSCALE_V6


def _is_lan_ip(address: ipaddress._BaseAddress) -> bool:
    if address.is_loopback or address.is_link_local:
        return True
    if address.version == 4:
        return any(address in ipaddress.ip_network(b) for b in ("10.0.0.0/8", "172.16.0.0/12", "192.168.0.0/16"))
    return address in ipaddress.ip_network("fc00::/7") and address not in TAILSCALE_V6


def classify_endpoint(origin: str) -> EndpointKind | None:
    """Only LAN and Tailscale origins are ever advertised; anything else is dropped."""
    host = _host(origin)
    if is_tailscale_host(host):
        return "tailscale"
    if host in {"localhost", "router", "gateway"} or host.endswith((".local", ".lan", ".home.arpa")):
        return "lan"
    try:
        address = ipaddress.ip_address(host)
    except ValueError:
        return None
    return "lan" if _is_lan_ip(address) else None


def ordered_entries(endpoints: list[str], *, allow_public: bool = False) -> list[dict[str, str]]:
    """Dedupe and order origins as Tailscale then LAN; public or unknown hosts are refused."""
    seen: set[str] = set()
    entries: list[tuple[int, int, dict[str, str]]] = []
    for index, value in enumerate(endpoints):
        origin = str(value or "").rstrip("/")
        if not origin.startswith("https://") or origin in seen or not _host(origin):
            continue
        seen.add(origin)
        kind = classify_endpoint(origin)
        if kind is None and allow_public:
            from .wan_forward import is_public_dial_host
            if is_public_dial_host(_host(origin)):
                kind = "public_forward"
        if kind is None:
            continue
        entries.append((KIND_RANK[kind], index, {"url": origin, "kind": kind}))
    entries.sort(key=lambda item: (item[0], item[1]))
    return [entry for _, _, entry in entries]


# ---------------------------------------------------------------- Tailscale

def _tailscale_binary() -> str:
    found = shutil.which("tailscale")
    if found:
        return found
    for candidate in (
        r"C:\Program Files\Tailscale\tailscale.exe",
        r"C:\Program Files (x86)\Tailscale\tailscale.exe",
        "/Applications/Tailscale.app/Contents/MacOS/Tailscale",
    ):
        if Path(candidate).exists():
            return candidate
    return ""


def parse_tailscale_status(raw: str) -> dict[str, Any]:
    data = json.loads(raw or "{}")
    me = data.get("Self") or {}
    state = str(data.get("BackendState") or "")
    dns = str(me.get("DNSName") or "").rstrip(".")
    ips = [ip for ip in (me.get("TailscaleIPs") or []) if is_tailscale_host(str(ip))]
    running = state == "Running" and bool(me.get("Online", True))
    endpoints: list[str] = []
    if running:
        if dns:
            endpoints.append(f"https://{dns}:{PORT}")
        for ip in ips:
            address = ipaddress.ip_address(ip)
            endpoints.append(f"https://{ip}:{PORT}" if address.version == 4 else f"https://[{ip}]:{PORT}")
    return {
        "installed": True,
        "running": running,
        "backend_state": state or "unknown",
        "dns_name": dns,
        "ips": ips,
        "tailnet": str((data.get("CurrentTailnet") or {}).get("Name") or ""),
        "endpoints": endpoints,
        "hint": "" if running else (
            "Tailscale is installed but not connected. Open Tailscale on this PC and sign in."
            if state in {"NeedsLogin", "NoState", "Stopped", ""} else f"Tailscale state: {state}"
        ),
    }


def tailscale_status(runner: Callable[[list[str]], str] | None = None) -> dict[str, Any]:
    binary = _tailscale_binary() if runner is None else "tailscale"
    if not binary:
        return {
            "installed": False, "running": False, "backend_state": "not_installed", "dns_name": "", "ips": [],
            "tailnet": "", "endpoints": [],
            "hint": "Install Tailscale on this PC (tailscale.com/download) and on your phone, sign in to the same account on both, then press Refresh.",
        }

    def _run(args: list[str]) -> str:
        flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
        done = subprocess.run(args, capture_output=True, text=True, timeout=6, creationflags=flags)
        if done.returncode != 0:
            detail = (done.stderr or done.stdout or "").strip().splitlines()
            raise RuntimeError(f"tailscale status exited {done.returncode}: {detail[0][:160] if detail else 'no output'}")
        return done.stdout

    try:
        return parse_tailscale_status((runner or _run)([binary, "status", "--json"]))
    except Exception as exc:
        log.warning("Could not read Tailscale status; not advertising Tailscale endpoints", exc_info=True)
        return {
            "installed": True, "running": False, "backend_state": "error", "dns_name": "", "ips": [], "tailnet": "",
            "endpoints": [], "hint": f"Could not read Tailscale status ({str(exc)[:160] or type(exc).__name__}). Open Tailscale and make sure it is signed in and connected.",
        }


# ---------------------------------------------------------------- reachability

async def self_test(entries: list[dict[str, str]], probe: Callable[[str], Any]) -> list[dict[str, Any]]:
    """Probe each advertised endpoint's ``/api/companion/health`` through the TLS gateway.

    A Tailscale address answering from this PC proves the gateway listens on the
    tailnet interface, not that the phone's Tailscale is connected.
    """
    results: list[dict[str, Any]] = []
    for entry in entries:
        try:
            await probe(entry["url"])
            status, detail = "ok", ""
        except Exception as exc:
            status, detail = "failed", str(exc)[:160] or type(exc).__name__
        results.append({"url": entry["url"], "kind": entry["kind"], "status": status, "detail": detail, "checked_at": time.time()})
    return results


def exposure_summary(remote: bool, entries: list[dict[str, str]]) -> str:
    exposed = [f"{e['kind']}={e['url']}" for e in entries if e["kind"] != "lan"]
    if not remote or not exposed:
        return "Companion gateway: LAN only (remote access off)"
    transport = "owner-enabled forwarding" if any(e["kind"] == "public_forward" for e in entries) else "Tailscale"
    return ("Companion gateway reachable over " + transport + " on " + ", ".join(exposed)
            + "; unauthenticated routes: pairing (enroll/challenge/session) and health only")
