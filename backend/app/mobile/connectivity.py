"""Owner-enabled mobile ingress lifecycle and bounded UPnP port leases."""
from __future__ import annotations

import asyncio
from contextlib import contextmanager
import errno
import ipaddress
import os
import socket
import ssl
import time
import uuid
from urllib.parse import urlsplit

import httpx
import uvicorn
from fastapi import HTTPException

from .gateway import gateway_app, server_identity
from .store import database, get, put

PORT = 4781


def origin(value: str) -> str:
    parsed = urlsplit(value)
    if (parsed.scheme != "https" or not parsed.hostname or parsed.username is not None
            or parsed.password is not None or parsed.query or parsed.fragment or parsed.path.strip("/")):
        raise ValueError("Connection addresses must be HTTPS origins without credentials or paths")
    if parsed.port is not None and not 1 <= parsed.port <= 65535:
        raise ValueError("Invalid connection port")
    return value.rstrip("/")


def lan_hosts():
    from ..api.mobile import _lan_hosts
    return [host for host in _lan_hosts() if ipaddress.ip_address(host).is_private
            and not ipaddress.ip_address(host).is_loopback and not ipaddress.ip_address(host).is_link_local]


def router_candidate():
    import miniupnpc
    router = miniupnpc.UPnP()
    router.discoverdelay = 1500
    router.discover()
    router.selectigd()
    address = ipaddress.ip_address(router.externalipaddress())
    if address.version != 4 or not address.is_global:
        raise ValueError("Router has no public IPv4 address; hosted relay is needed for remote access")
    return router, str(address)


def owned_mapping(mapping, host, marker):
    return bool(mapping and mapping[0] == host and int(mapping[1]) == PORT and mapping[2] == marker)


def map_router(router, marker):
    mapping = router.getspecificportmapping(PORT, "TCP")
    if mapping and not owned_mapping(mapping, router.lanaddr, marker):
        raise ValueError("Router port 4781 is already used by another mapping; existing mapping preserved")
    # Request a finite lease. Routers supporting permanent leases only use relay instead.
    if not router.addportmapping(PORT, "TCP", router.lanaddr, PORT, marker, "", 3600):
        raise RuntimeError("Router declined the one-hour mobile gateway lease")


def unmap_router(router, marker):
    if owned_mapping(router.getspecificportmapping(PORT, "TCP"), router.lanaddr, marker):
        router.deleteportmapping(PORT, "TCP")


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
        self.router = None
        self.marker = ""
        self.identity = None
        self.public_ip = None
        self.state = {"state": "disabled", "activity": "Prepare a secure connection to get started", "endpoints": []}

    def report(self, **changes):
        self.state.update(changes, updated_at=time.time())

    def snapshot(self):
        return {**self.state, "heartbeat_at": time.time(), "worker": "Jarvis desktop"}

    def config(self):
        with database() as db:
            return get(db, "network", "config") or {"enabled": False, "remote": True, "marker": "Jarvis-" + str(uuid.uuid4())}

    async def configure(self, enabled: bool, remote: bool):
        if self.lock.locked():
            raise HTTPException(409, "Connection setup is already running")
        async with self.lock:
            config = self.config()
            config.update(enabled=enabled, remote=remote)
            with database() as db:
                put(db, "network", "config", config)
            await self.apply(config)
        return self.snapshot()

    async def stop_gateway(self):
        if self.server:
            self.server.should_exit = True
        if self.server_task:
            try:
                await asyncio.wait_for(asyncio.shield(self.server_task), 5)
            except TimeoutError:
                self.server_task.cancel()
                await asyncio.gather(self.server_task, return_exceptions=True)
        self.server = self.server_task = None

    async def release_mapping(self):
        if self.router:
            try:
                await asyncio.to_thread(unmap_router, self.router, self.marker)
            except Exception:
                pass  # Finite lease expires if the router is unavailable during shutdown.
            self.router = None

    async def start_gateway(self, identity):
        from ..config import load_settings
        if self.server and self.server_task and not self.server_task.done() and self.server.started:
            return
        await self.stop_gateway()
        # Bind ourselves so port conflicts raise OSError instead of Uvicorn's SystemExit.
        listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        addr_in_use = getattr(errno, "WSAEADDRINUSE", 10048)
        try:
            listener.bind(("0.0.0.0", PORT))
            listener.listen(128)
            listener.setblocking(False)
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
                    return
                except Exception:
                    pass
            raise
        except BaseException:
            listener.close()
            raise

    async def probe(self, endpoint, identity):
        context = ssl.create_default_context(cafile=identity["certificate"])
        async with httpx.AsyncClient(verify=context, timeout=4, trust_env=False, follow_redirects=False) as client:
            result = await client.get(endpoint + "/api/companion/models")
        if result.status_code != 401:
            raise RuntimeError("Mobile gateway is not enforcing device authentication or desktop API is unavailable")

    async def apply(self, config):
        await self.release_mapping()
        if not config["enabled"]:
            await self.stop_gateway()
            self.report(state="disabled", activity="Mobile gateway stopped", endpoints=[], local_verified=False, remote_verified=False)
            return
        self.report(state="running", activity="Finding local connection addresses", started_at=time.time(),
                    endpoints=[], local_verified=False, remote_verified=False, router="disabled", limitation="")
        router, public_ip = None, None
        hosts = await asyncio.to_thread(lan_hosts)
        relay = os.environ.get("JARVIS_RELAY_ENDPOINT", "") if config["remote"] else ""
        try:
            relay = origin(relay) if relay else ""
            if relay:
                hosts.append(urlsplit(relay).hostname)
            if config["remote"]:
                self.report(activity="Checking router support for encrypted remote access", router="discovering")
                try:
                    router, public_ip = await asyncio.to_thread(router_candidate)
                    hosts.append(public_ip)
                except Exception as exc:
                    self.report(router="unavailable", limitation=str(exc)[:240])
            self.report(activity="Starting and verifying the encrypted mobile gateway")
            identity = await asyncio.to_thread(server_identity, hosts)
            self.identity = identity
            self.public_ip = public_ip
            await self.start_gateway(identity)
            await self.probe(f"https://127.0.0.1:{PORT}", identity)
            local = [f"https://{host}:{PORT}" for host in hosts if host != public_ip and host != urlsplit(relay).hostname]
            endpoints = list(local)
            self.report(local_verified=True, server_pin=identity["server_pin"], endpoints=endpoints)
            if router:
                self.report(activity="Requesting a one-hour lease for the TLS gateway")
                try:
                    await asyncio.to_thread(map_router, router, config["marker"])
                    self.router, self.marker = router, config["marker"]
                    endpoints.append(f"https://{public_ip}:{PORT}")
                    self.report(router="mapped", limitation="Router lease created; internet reachability still needs verification from outside this network")
                except Exception as exc:
                    await asyncio.to_thread(unmap_router, router, config["marker"])
                    self.report(router="unavailable", limitation=str(exc)[:240])
            if relay:
                try:
                    await self.probe(relay, identity)
                    endpoints.append(relay)
                    self.report(remote_verified=True)
                except Exception:
                    self.report(limitation="Configured relay did not reach this gateway; check relay service and credentials")
            if config["remote"] and not relay and not self.router:
                self.report(limitation=self.state["limitation"] + ". Hosted relay is not configured on this installation.")
            self.report(state="ready", activity="Secure connection prepared" if endpoints else "No phone-reachable address found; connect this desktop to a local network",
                        endpoints=endpoints, next_renewal_at=time.time() + 1200)
        except Exception as exc:
            await self.release_mapping()
            await self.stop_gateway()
            self.report(state="failed", activity=str(exc)[:300], endpoints=[], local_verified=False)

    async def run(self):
        try:
            while True:
                async with self.lock:
                    config = self.config()
                    if config["enabled"]:
                        if self.state["state"] != "ready":
                            await self.apply(config)
                        elif time.time() >= self.state.get("next_renewal_at", 0):
                            # Renew without restarting the TLS listener or interrupting uploads/calls.
                            try:
                                await self.probe(f"https://127.0.0.1:{PORT}", self.identity)
                                if self.router:
                                    if await asyncio.to_thread(self.router.externalipaddress) != self.public_ip:
                                        raise RuntimeError("Router address changed")
                                    await asyncio.to_thread(map_router, self.router, self.marker)
                                self.report(next_renewal_at=time.time() + 1200)
                            except Exception:
                                await self.apply(config)
                await asyncio.sleep(30)
        finally:
            await self.release_mapping()
            await self.stop_gateway()


CONNECTIVITY = Connectivity()
