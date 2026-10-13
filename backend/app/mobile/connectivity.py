"""Owner-enabled mobile ingress lifecycle: LAN TLS gateway plus Tailscale (RFC-0215)."""
from __future__ import annotations

import asyncio
from contextlib import contextmanager
import errno
import ipaddress
import logging
import socket
import ssl
import time
from urllib.parse import urlsplit

import httpx
import uvicorn
from fastapi import HTTPException

from .companion_security import GUARD
from .gateway import gateway_app, identity_covers, server_identity
from .lan_beacon import LanBeaconServer, public_beacon_payload
from .store import database, get, put

PORT = 4781
log = logging.getLogger(__name__)


def origin(value: str) -> str:
    parsed = urlsplit(value)
    if (parsed.scheme != "https" or not parsed.hostname or parsed.username is not None
            or parsed.password is not None or parsed.query or parsed.fragment or parsed.path.strip("/")):
        raise ValueError("Connection addresses must be HTTPS origins without credentials or paths")
    if parsed.port is not None and not 1 <= parsed.port <= 65535:
        raise ValueError("Invalid connection port")
    return value.rstrip("/")


def dial_host(value: str) -> str:
    """Hostname or IP the phone would present in SNI / hostname verification."""
    text = (value or "").strip()
    if not text:
        return ""
    if "://" in text:
        return (urlsplit(text).hostname or "").strip()
    return text.split("/")[0].strip()


def lan_hosts():
    from ..api.mobile import _lan_hosts
    from .wan_forward import is_rfc1918_ipv4

    return [host for host in _lan_hosts() if is_rfc1918_ipv4(host)]


def preferred_lan_ipv4(gateway: str = "") -> str:
    """RFC1918 address on the default-gateway subnet — not lexicographic lan_hosts()[0]."""
    from .wan_forward import default_gateway_ipv4, mapping_lan_ipv4

    gw = (gateway or "").strip()
    if not gw:
        try:
            gw = default_gateway_ipv4()
        except Exception:
            gw = ""
    return mapping_lan_ipv4(lan_hosts(), gw)


def _self_test_headers(endpoint: str) -> dict[str, str]:
    """The per-boot self-test secret only ever goes to this machine's own loopback."""
    from .gateway import SELF_TEST_HEADER, SELF_TEST_SECRET

    host = (urlsplit(endpoint).hostname or "").lower()
    if host in {"127.0.0.1", "::1", "localhost"}:
        return {SELF_TEST_HEADER: SELF_TEST_SECRET}
    return {}


class EmbeddedServer(uvicorn.Server):
    @contextmanager
    def capture_signals(self):
        # The main desktop server owns process signals.
        yield


class Connectivity:
    def __init__(self):
        self.lock = asyncio.Lock()
        self.server = None
        self.server_task = None
        self.identity = None
        self.remote_prepared = False
        self.state = {
            "state": "starting",
            "activity": "Starting companion TLS gateway",
            "endpoints": [],
        }
        self.lan_beacon = LanBeaconServer()

    def report(self, **changes):
        self.state.update(changes, updated_at=time.time())

    def snapshot(self):
        payload = {**self.state, "heartbeat_at": time.time(), "worker": "Jarvis desktop"}
        payload.update(GUARD.snapshot())
        cfg = self.config()
        payload["remote"] = bool(cfg.get("remote"))
        payload["tailscale_enabled"] = cfg.get("tailscale", True) is not False
        return payload

    def config(self):
        with database() as db:
            stored = get(db, "network", "config")
            if stored is None:
                return {
                    "enabled": True,
                    "remote": False,
                    "remote_explicit": False,
                    "rfc0215_migrated": True,
                }
            if not stored.get("rfc0215_migrated"):
                # RFC-0215 one-time migration: older builds defaulted remote=True on any
                # connection POST, so only an explicit owner choice may keep it on.
                if not stored.get("remote_explicit"):
                    if stored.get("remote"):
                        log.warning("RFC-0215 migration: remote companion access switched off (it was not an explicit owner choice)")
                    stored["remote"] = False
                stored["rfc0215_migrated"] = True
                put(db, "network", "config", stored)
            return stored

    async def configure(self, enabled: bool, remote: bool | None, tailscale: bool | None = None):
        if self.lock.locked():
            raise HTTPException(409, "Connection setup is already running")
        async with self.lock:
            config = self.config()
            was_remote = bool(config.get("remote"))
            config.update(enabled=enabled)
            if remote is not None:
                config.update(remote=bool(remote), remote_explicit=True)
            if tailscale is not None:
                config["tailscale"] = bool(tailscale)
            if bool(config.get("remote")) != was_remote:
                # Codes minted for LAN-only use may live 60 minutes; any change of exposure burns them.
                from .identity import invalidate_unclaimed_pairing_codes

                invalidate_unclaimed_pairing_codes()
                log.warning("Remote companion access turned %s by the owner; unclaimed pairing codes invalidated",
                            "on" if config.get("remote") else "off")
            with database() as db:
                put(db, "network", "config", config)
            # The gateway caches the remote flag for 5 s; a toggle (above all *off*) must bite now.
            from .gateway import invalidate_remote_cache

            invalidate_remote_cache()
            await self.apply_remote(config)
        return self.snapshot()

    async def prepare_pairing(self):
        """Owner pair intent prepares LAN ingress without device discovery or WAN setup."""
        if GUARD.cooldown_active():
            raise HTTPException(409, "Pairing is paused during the security cooldown")
        async with self.lock:
            if GUARD.cooldown_active():
                raise HTTPException(409, "Pairing is paused during the security cooldown")
            snapshot = self.snapshot()
            if (self.config().get("enabled") and snapshot.get("local_verified")
                    and snapshot.get("endpoints") and snapshot.get("server_pin")
                    and self.server_task and not self.server_task.done()):
                return snapshot
            config = self.config()
            if not config.get("enabled"):
                config.update(enabled=True, remote=False)
                with database() as db:
                    put(db, "network", "config", config)
            await self.ensure_gateway_listening()
            snapshot = self.snapshot()
            if not snapshot.get("endpoints") or not snapshot.get("server_pin"):
                raise HTTPException(409, "Connect this desktop to Wi-Fi or Ethernet, then generate the pairing QR again")
            return snapshot

    async def stop_gateway(self, beacons: bool = True):
        if beacons:
            await self.stop_lan_beacon()
        external = bool(getattr(self, "_uses_external_listener", False))
        if self.server and not external:
            self.server.should_exit = True
        if self.server_task:
            if external:
                self.server_task.cancel()
                await asyncio.gather(self.server_task, return_exceptions=True)
            else:
                try:
                    await asyncio.wait_for(asyncio.shield(self.server_task), 5)
                except TimeoutError:
                    self.server_task.cancel()
                    await asyncio.gather(self.server_task, return_exceptions=True)
        self.server = self.server_task = None
        self._uses_external_listener = False

    async def start_lan_beacon(self):
        try:
            await self.lan_beacon.start(
                lambda peer="": public_beacon_payload(self.snapshot(), prefer_host=peer or "")
            )
        except Exception:
            pass

    async def stop_lan_beacon(self):
        try:
            await self.lan_beacon.stop()
        except Exception:
            pass

    async def on_security_cooldown(self):
        await self.stop_gateway()
        self.report(
            state="cooldown",
            activity="Companion gateway paused after a security alert",
            endpoints=[],
            local_verified=False,
            remote_verified=False,
        )

    async def _attach_external_gateway(self) -> None:
        """Port 4781 is already serving the companion TLS gateway on this machine."""
        self._uses_external_listener = True
        self.server = None
        if self.server_task and not self.server_task.done():
            return

        async def _hold() -> None:
            try:
                while True:
                    await asyncio.sleep(3600)
            except asyncio.CancelledError:
                raise

        self.server_task = asyncio.create_task(_hold(), name="jarvis-companion-gateway-external")

    async def start_gateway(self, identity, beacons: bool = True):
        from ..config import load_settings
        if self.server and self.server_task and not self.server_task.done() and self.server.started:
            return
        await self.stop_gateway(beacons=beacons)
        # Bind ourselves so port conflicts raise OSError instead of Uvicorn's SystemExit.
        listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        addr_in_use = getattr(errno, "WSAEADDRINUSE", 10048)
        try:
            listener.bind(("0.0.0.0", PORT))
            listener.listen(128)
            listener.setblocking(False)
            try:
                from .wan_forward import ensure_companion_firewall

                fw = await asyncio.to_thread(ensure_companion_firewall)
                tcp = str(fw.get("tcp_4781") or "")
                udp = str(fw.get("udp_4782") or "")
                self.report(firewall_4781=tcp, firewall_4782=udp)
                if tcp.startswith("failed"):
                    self.report(limitation=f"Windows firewall did not allow inbound TCP 4781 ({tcp})")
                elif udp.startswith("failed"):
                    self.report(limitation=f"Windows firewall did not allow inbound UDP 4782 ({udp})")
            except Exception as exc:
                self.report(firewall_4781="error", firewall_4782="error", limitation=f"Windows firewall helper failed: {exc}"[:240])
            settings = load_settings()
            config = uvicorn.Config(gateway_app(f"http://127.0.0.1:{settings.bind_port}"),
                ssl_keyfile=identity["key"], ssl_certfile=identity["certificate"],
                proxy_headers=False, access_log=False, limit_concurrency=32, log_level="warning")
            self.server = EmbeddedServer(config)
            self.server_task = asyncio.create_task(self.server.serve(sockets=[listener]))
            for _ in range(100):
                if self.server_task.done():
                    await self.server_task
                    raise RuntimeError("Mobile listener stopped before becoming ready")
                if self.server.started:
                    return
                await asyncio.sleep(.05)
            raise TimeoutError("Mobile listener did not start")
        except OSError as exc:
            listener.close()
            if exc.errno in (errno.EADDRINUSE, addr_in_use):
                try:
                    await self.probe(f"https://127.0.0.1:{PORT}", identity)
                    await self._attach_external_gateway()
                    return
                except Exception:
                    pass
            raise
        except BaseException:
            listener.close()
            raise

    async def probe_health(self, endpoint, identity):
        """RFC-0215 reachability self-test against the unauthenticated health route."""
        context = ssl.create_default_context(cafile=identity["certificate"])
        async with httpx.AsyncClient(verify=context, timeout=4, trust_env=False, follow_redirects=False) as client:
            result = await client.get(endpoint + "/api/companion/health", headers=_self_test_headers(endpoint))
        if result.status_code != 200 or result.json().get("ok") is not True:
            raise RuntimeError(f"health returned {result.status_code}")

    async def probe(self, endpoint, identity):
        context = ssl.create_default_context(cafile=identity["certificate"])
        async with httpx.AsyncClient(verify=context, timeout=4, trust_env=False, follow_redirects=False) as client:
            result = await client.get(endpoint + "/api/companion/models", headers=_self_test_headers(endpoint))
        if result.status_code != 401:
            raise RuntimeError("Mobile gateway is not enforcing device authentication or desktop API is unavailable")

    def _lan_endpoints(self, hosts: list[str]) -> list[str]:
        from .wan_forward import is_rfc1918_ipv4

        endpoints = []
        for host in hosts:
            if not host:
                continue
            try:
                ipaddress.ip_address(host)
            except ValueError:
                endpoints.append(f"https://{host}:{PORT}")
                continue
            if is_rfc1918_ipv4(host):
                endpoints.append(f"https://{host}:{PORT}")
        return endpoints

    async def ensure_gateway_listening(self):
        if GUARD.cooldown_active():
            return
        hosts = await asyncio.to_thread(lan_hosts)
        identity = await asyncio.to_thread(server_identity, hosts)
        self.identity = identity
        await self.start_gateway(identity)
        await self.probe(f"https://127.0.0.1:{PORT}", identity)
        endpoints = self._lan_endpoints([host for host in hosts if host])
        self.report(
            state="listening",
            activity="Companion TLS gateway listening on port 4781",
            endpoints=endpoints,
            local_verified=True,
            server_pin=identity["server_pin"],
        )

    async def cover_phone_dial_hosts(self, *hosts: str):
        """RFC-0123: every phone-dial IP/DNS name must be a SAN on the live gateway cert."""
        extra = [dial_host(host) for host in hosts]
        extra = [host for host in extra if host]
        if not extra:
            return self.identity
        current = self.identity
        if current and identity_covers(current, extra):
            return current
        identity = await asyncio.to_thread(server_identity, extra)
        self.identity = identity
        external = bool(getattr(self, "_uses_external_listener", False))
        running = bool(self.server_task and not self.server_task.done())
        if running and not external:
            await self.stop_gateway(beacons=False)
            await self.start_gateway(identity, beacons=False)
            await self.probe(f"https://127.0.0.1:{PORT}", identity)
        self.report(server_pin=identity["server_pin"])
        return identity

    async def _remote_endpoints(self, config) -> list[str]:
        """Tailscale is the only off-LAN path (RFC-0215)."""
        if not config.get("remote"):
            self.report(tailscale=None)
            return []
        from .remote_access import tailscale_status

        status = await asyncio.to_thread(tailscale_status)
        self.report(tailscale=status)
        if config.get("tailscale", True) is False:
            return []
        if not status.get("running"):
            self.report(limitation=status.get("hint") or "Tailscale is not connected on this PC")
        return list(status.get("endpoints") or [])

    async def apply_remote(self, config):
        """Advertise LAN endpoints, plus Tailscale when the owner switched remote access on."""
        self.remote_prepared = False
        hosts = await asyncio.to_thread(lan_hosts)
        endpoints = self._lan_endpoints(hosts)
        if not config["enabled"]:
            self.report(limitation="", endpoints=endpoints if self.identity else [], reachability=[], tailscale=None)
            return
        self.report(activity="Finding phone-reachable addresses", limitation="")
        try:
            if not self.identity or GUARD.cooldown_active():
                await self.ensure_gateway_listening()
            identity = self.identity
            if not identity:
                raise RuntimeError("Companion gateway is not listening")
            await self.probe(f"https://127.0.0.1:{PORT}", identity)
            for item in await self._remote_endpoints(config):
                if item not in endpoints:
                    endpoints.append(item)
            await self.cover_phone_dial_hosts(*endpoints)
            self.report(local_verified=True, server_pin=self.identity["server_pin"], endpoints=endpoints)
            await self.start_lan_beacon()
            self.remote_prepared = True
            await self._self_test(config, endpoints)
            self.report(
                state="ready",
                activity="Secure connection prepared" if endpoints else "No phone-reachable address found; connect this desktop to a local network",
                endpoints=endpoints,
            )
        except Exception as exc:
            log.warning("Companion connection setup failed: %s", exc)
            self.report(state="failed", activity=str(exc)[:300], endpoints=endpoints, local_verified=bool(self.server_task))

    async def _self_test(self, config, endpoints: list[str]) -> None:
        from .remote_access import exposure_summary, ordered_entries, self_test

        entries = ordered_entries(endpoints)
        identity = self.identity

        async def _probe(url: str):
            await self.probe_health(url, identity)

        results = await self_test(entries, _probe) if identity else []
        summary = exposure_summary(bool(config.get("remote")), entries)
        if summary != self.state.get("exposure"):
            (log.warning if config.get("remote") else log.info)(summary)
        self.report(reachability=results, exposure=summary)

    def _merge_live_lan_endpoints(self, live: list[str], current: list[str]) -> list[str]:
        """Keep Tailscale origins; replace stale RFC1918 dials with this PC's current LAN IPs."""
        from .wan_forward import is_rfc1918_ipv4

        live_set = set(live)
        kept: list[str] = []
        for endpoint in current:
            host = dial_host(endpoint)
            if is_rfc1918_ipv4(host) and endpoint not in live_set:
                continue
            if endpoint not in kept:
                kept.append(endpoint)
        merged: list[str] = []
        for endpoint in live:
            if endpoint not in merged:
                merged.append(endpoint)
        for endpoint in kept:
            if endpoint not in merged:
                merged.append(endpoint)
        return merged

    async def _refresh_endpoints(self) -> None:
        """Track LAN address and Tailscale changes so paired phones get them via /connection."""
        config = self.config()
        hosts = await asyncio.to_thread(lan_hosts)
        live = self._lan_endpoints(hosts) + await self._remote_endpoints(config)
        current = list(self.state.get("endpoints") or [])
        if sorted(live) != sorted(current):
            await self.cover_phone_dial_hosts(*live)
            self.report(endpoints=live)
            await self._self_test(config, live)

    async def run(self):
        GUARD.bind_connectivity(self)
        try:
            while True:
                async with self.lock:
                    if GUARD.cooldown_active():
                        if self.server_task:
                            await self.stop_gateway()
                        self.report(
                            state="cooldown",
                            activity="Companion gateway paused after a security alert",
                            cooldown_remaining_seconds=GUARD.cooldown_remaining_seconds(),
                        )
                    else:
                        if not self.server_task or self.server_task.done():
                            try:
                                await self.ensure_gateway_listening()
                            except Exception as exc:
                                log.warning("Companion gateway failed to start: %s", exc)
                                self.report(state="failed", activity=str(exc)[:300])
                        config = self.config()
                        if config["enabled"] and self.state.get("state") != "cooldown":
                            if self.state.get("state") != "ready" or not self.remote_prepared:
                                await self.apply_remote(config)
                            else:
                                try:
                                    await self._refresh_endpoints()
                                except Exception as exc:
                                    log.warning("Companion endpoint refresh failed: %s", exc)
                                    await self.apply_remote(config)
                await asyncio.sleep(30)
        finally:
            await self.stop_gateway()


CONNECTIVITY = Connectivity()
