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

from .companion_security import GUARD
from .gateway import gateway_app, identity_covers, server_identity
from .lan_beacon import LanBeaconServer, public_beacon_payload
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


def _miniupnpc_client(multicastif: str = ""):
    import miniupnpc

    if not multicastif:
        return miniupnpc.UPnP()
    try:
        return miniupnpc.UPnP(multicastif)
    except TypeError:
        try:
            return miniupnpc.UPnP(multicastif=multicastif)
        except TypeError:
            client = miniupnpc.UPnP()
            for attr in ("multicastif", "lanaddr"):
                try:
                    setattr(client, attr, multicastif)
                except Exception:
                    continue
            return client


def _upnp_multicast_ifs() -> list[str]:
    """Home LAN NIC first, then other RFC1918 NICs, then unbound default discover."""
    from .wan_forward import interface_ipv4_addresses, is_rfc1918_ipv4, mapping_lan_ipv4, rfc1918_mapping_gateways

    nics = [ip for ip in interface_ipv4_addresses() if is_rfc1918_ipv4(ip)]
    ordered: list[str] = []
    try:
        for gw in rfc1918_mapping_gateways():
            dest = mapping_lan_ipv4(nics, gw)
            if dest and dest not in ordered:
                ordered.append(dest)
    except Exception:
        pass
    for ip in nics:
        if ip not in ordered:
            ordered.append(ip)
    if not ordered:
        return [""]
    return [*ordered, ""]


def router_candidate(username: str = "", password: str = ""):
    last_error: Exception | None = None
    try:
        from .igd import apply_igd_logon, igd_auth_candidates

        delay = 2000 if igd_auth_candidates(username, password) else 1500
        for iface in _upnp_multicast_ifs():
            try:
                router = _miniupnpc_client(iface)
                router.discoverdelay = delay
                router.discover()
                router.selectigd()
                apply_igd_logon(router, username, password)
                address = ipaddress.ip_address(router.externalipaddress())
                from .wan_forward import is_literal_public_ipv4

                if address.version != 4 or not is_literal_public_ipv4(str(address)):
                    last_error = ValueError(
                        "Router has no public IPv4 address; hosted relay or SSH reverse tunnel is needed for remote access"
                    )
                    continue
                return router, str(address)
            except ImportError:
                raise
            except Exception as exc:
                last_error = exc
                continue
    except ImportError as exc:
        last_error = exc
    try:
        from .igd import stdlib_igd_candidate

        lan = preferred_lan_ipv4()
        return stdlib_igd_candidate(username, password, lanaddr=lan)
    except Exception as exc:
        last_error = exc
    raise ValueError(str(last_error) if last_error else "No IGD available")


def owned_mapping(mapping, host, marker):
    """True when TCP 4781 is our lease (marker), even if the internal client was CGNAT."""
    return bool(mapping and int(mapping[1]) == PORT and mapping[2] == marker)


def igd_mapping_dest(router) -> str:
    """Internal client for UPnP: an RFC1918 address this PC currently holds on the IGD subnet."""
    advertised = str(getattr(router, "lanaddr", "") or "").strip()
    from .wan_forward import is_rfc1918_ipv4, mapping_lan_ipv4

    hosts = lan_hosts()
    if is_rfc1918_ipv4(advertised):
        return mapping_lan_ipv4(hosts, advertised)
    return preferred_lan_ipv4()


def map_router(router, marker):
    dest = igd_mapping_dest(router)
    if not dest:
        raise RuntimeError("No RFC1918 address on this PC to map TCP 4781 to")
    mapping = router.getspecificportmapping(PORT, "TCP")
    if mapping and not owned_mapping(mapping, dest, marker):
        raise ValueError("Router port 4781 is already used by another mapping; existing mapping preserved")
    # Request a finite lease. Routers supporting permanent leases only use relay instead.
    if not router.addportmapping(PORT, "TCP", dest, PORT, marker, "", 3600):
        raise RuntimeError("Router declined the one-hour mobile gateway lease")


def unmap_router(router, marker):
    if owned_mapping(router.getspecificportmapping(PORT, "TCP"), igd_mapping_dest(router), marker):
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
        self.natpmp_gateway = None
        self.ssh_gateway = None
        self.pcp_nonce = None
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
        from .wan_forward import redact_wan_config

        payload = {**self.state, "heartbeat_at": time.time(), "worker": "Jarvis desktop"}
        payload.update(GUARD.snapshot())
        cfg = self.config()
        payload["wan"] = redact_wan_config(cfg)
        payload["remote"] = bool(cfg.get("remote"))
        return payload

    def config(self):
        with database() as db:
            return get(db, "network", "config") or {
                "enabled": True,
                "remote": False,
                "marker": "Jarvis-" + str(uuid.uuid4()),
                "wan_method": "auto",
            }

    async def configure(self, enabled: bool, remote: bool, extras: dict | None = None):
        if self.lock.locked():
            raise HTTPException(409, "Connection setup is already running")
        async with self.lock:
            config = self.config()
            config.update(enabled=enabled, remote=remote)
            if extras:
                from .wan_forward import WAN_METHODS

                for key, value in extras.items():
                    if value is None:
                        continue
                    if key == "wan_method" and str(value).strip().lower() not in WAN_METHODS:
                        raise HTTPException(400, "Unknown WAN method")
                    config[key] = value
            with database() as db:
                put(db, "network", "config", config)
            await self.apply_remote(config)
        return self.snapshot()

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

    async def release_mapping(self):
        from .wan_forward import REVERSE_TUNNEL

        if self.router:
            try:
                await asyncio.to_thread(unmap_router, self.router, self.marker)
            except Exception:
                pass  # Finite lease expires if the router is unavailable during shutdown.
            self.router = None
        if self.natpmp_gateway:
            try:
                lan = preferred_lan_ipv4(self.natpmp_gateway)
                if self.pcp_nonce:
                    from .pcp import delete_pcp

                    await asyncio.to_thread(delete_pcp, self.natpmp_gateway, lan, self.pcp_nonce)
                else:
                    from .natpmp import delete_natpmp

                    await asyncio.to_thread(delete_natpmp, self.natpmp_gateway, lan)
            except Exception:
                pass
            self.natpmp_gateway = None
            self.pcp_nonce = None
        self.ssh_gateway = None
        self.public_ip = None
        self.report(mapped_lan_ip="", wan_path="")
        await REVERSE_TUNNEL.stop()

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
                from .wan_forward import ensure_private_firewall_4781

                fw = await asyncio.to_thread(ensure_private_firewall_4781)
                self.report(firewall_4781=fw)
                if str(fw).startswith("failed"):
                    self.report(limitation=f"Windows firewall did not allow inbound TCP 4781 ({fw})")
            except Exception as exc:
                self.report(firewall_4781="error", limitation=f"Windows firewall helper failed: {exc}"[:240])
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

    async def probe(self, endpoint, identity):
        context = ssl.create_default_context(cafile=identity["certificate"])
        async with httpx.AsyncClient(verify=context, timeout=4, trust_env=False, follow_redirects=False) as client:
            result = await client.get(endpoint + "/api/companion/models")
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
        relay = os.environ.get("JARVIS_RELAY_ENDPOINT", "")
        relay_host = ""
        if relay:
            try:
                relay_host = urlsplit(origin(relay)).hostname or ""
                if relay_host:
                    hosts.append(relay_host)
            except ValueError:
                relay_host = ""
        identity = await asyncio.to_thread(server_identity, hosts)
        self.identity = identity
        await self.start_gateway(identity)
        await self.probe(f"https://127.0.0.1:{PORT}", identity)
        endpoints = self._lan_endpoints([host for host in hosts if host and host != self.public_ip and host != relay_host])
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

    async def apply_remote(self, config):
        """Prepare connection: port-forward lease and relay only (gateway already listens)."""
        await self.release_mapping()
        self.remote_prepared = False
        if not config["enabled"]:
            self.report(
                limitation="",
                router="disabled",
                remote_verified=False,
            )
            if self.identity:
                hosts = await asyncio.to_thread(lan_hosts)
                self.report(endpoints=self._lan_endpoints(hosts))
            return
        self.report(activity="Finding phone-reachable addresses", router="disabled", limitation="", remote_verified=False)
        router, public_ip = None, None
        hosts = await asyncio.to_thread(lan_hosts)
        relay = os.environ.get("JARVIS_RELAY_ENDPOINT", "") if config["remote"] else ""
        endpoints = self._lan_endpoints(hosts)
        wan_path = ""
        try:
            relay = origin(relay) if relay else ""
            if relay:
                hosts.append(urlsplit(relay).hostname)
            if config["remote"]:
                from .wan_forward import wan_settings_from_config

                wan = wan_settings_from_config(config)
                method = wan["wan_method"]
                self.report(activity="Checking router support for encrypted remote access", router="discovering")
                if method in {"auto", "upnp"}:
                    try:
                        try:
                            router, public_ip = await asyncio.to_thread(
                                router_candidate,
                                wan.get("gateway_username") or "",
                                wan.get("gateway_password") or "",
                            )
                        except TypeError:
                            router, public_ip = await asyncio.to_thread(router_candidate)
                        hosts.append(public_ip)
                    except Exception as exc:
                        self.report(router="unavailable", limitation=str(exc)[:240])
                        router, public_ip = None, None
            if not self.identity or GUARD.cooldown_active():
                await self.ensure_gateway_listening()
            identity = self.identity
            if not identity:
                raise RuntimeError("Companion gateway is not listening")
            await self.probe(f"https://127.0.0.1:{PORT}", identity)
            relay_hostname = urlsplit(relay).hostname if relay else None
            endpoints = self._lan_endpoints([host for host in hosts if host != public_ip and host != relay_hostname])
            self.report(local_verified=True, server_pin=identity["server_pin"], endpoints=endpoints)
            await self.start_lan_beacon()
            wan_path = ""
            from .wan_forward import mapped_address_is_egress

            double_nat_limit = (
                "Router mapping is not this network's public IPv4 (typical of double NAT). "
                "Inner-router forwards will not reach a phone off this LAN; trying the next owner method."
            )
            if router:
                self.report(activity="Requesting a one-hour lease for the TLS gateway")
                try:
                    await asyncio.to_thread(map_router, router, config["marker"])
                    if not await asyncio.to_thread(mapped_address_is_egress, public_ip):
                        await asyncio.to_thread(unmap_router, router, config["marker"])
                        self.router = None
                        self.report(router="unavailable", limitation=double_nat_limit)
                    else:
                        self.router, self.marker = router, config["marker"]
                        self.public_ip = public_ip
                        endpoints.append(f"https://{public_ip}:{PORT}")
                        wan_path = "upnp"
                        self.report(
                            router="mapped",
                            wan_path=wan_path,
                            mapped_lan_ip=igd_mapping_dest(router),
                            limitation="Router lease created; internet reachability still needs verification from outside this network",
                        )
                except Exception as exc:
                    await asyncio.to_thread(unmap_router, router, config["marker"])
                    self.router = None
                    self.report(router="unavailable", limitation=str(exc)[:240])
            gw = ""
            if config["remote"] and not self.router and method in {"auto", "upnp"}:
                from .wan_forward import default_gateway_ipv4, mapping_lan_ipv4, rfc1918_default_gateways

                gateways: list[str] = []
                try:
                    gateways = [item for item in rfc1918_default_gateways() if item]
                except Exception:
                    gateways = []
                try:
                    primary = default_gateway_ipv4()
                except Exception as exc:
                    primary = ""
                    if not gateways:
                        prior = self.state.get("limitation") or ""
                        extra = str(exc)[:240]
                        self.report(limitation=(f"{prior} {extra}").strip() if prior else extra)
                else:
                    if primary:
                        gateways = [primary, *[item for item in gateways if item != primary]]
                gw = gateways[0] if gateways else ""
                nat_errors: list[str] = []
                for candidate in gateways:
                    lan_ip = mapping_lan_ipv4(hosts, candidate)
                    if not lan_ip:
                        continue
                    self.report(activity=f"Trying NAT-PMP on {candidate} for TCP 4781")
                    try:
                        from .natpmp import apply_natpmp

                        public_ip = await asyncio.to_thread(apply_natpmp, candidate, lan_ip)
                        if not await asyncio.to_thread(mapped_address_is_egress, public_ip):
                            nat_errors.append(f"{candidate}: inner mapping is not this network's public IPv4")
                            self.report(limitation=double_nat_limit)
                            continue
                        gw = candidate
                        self.natpmp_gateway = candidate
                        self.pcp_nonce = None
                        self.public_ip = public_ip
                        endpoints.append(f"https://{public_ip}:{PORT}")
                        wan_path = "natpmp"
                        self.report(
                            router="mapped",
                            wan_path=wan_path,
                            mapped_lan_ip=lan_ip,
                            limitation="NAT-PMP lease created; internet reachability still needs verification from outside this network",
                        )
                        break
                    except Exception as nat_exc:
                        self.report(activity=f"Trying PCP MAP on {candidate} for TCP 4781")
                        try:
                            from .pcp import apply_pcp

                            public_ip, nonce = await asyncio.to_thread(apply_pcp, candidate, lan_ip, None)
                            if not await asyncio.to_thread(mapped_address_is_egress, public_ip):
                                nat_errors.append(f"{candidate}: inner PCP mapping is not this network's public IPv4")
                                self.report(limitation=double_nat_limit)
                                continue
                            gw = candidate
                            self.natpmp_gateway = candidate
                            self.pcp_nonce = nonce
                            self.public_ip = public_ip
                            endpoints.append(f"https://{public_ip}:{PORT}")
                            wan_path = "pcp"
                            self.report(
                                router="mapped",
                                wan_path=wan_path,
                                mapped_lan_ip=lan_ip,
                                limitation="PCP lease created; internet reachability still needs verification from outside this network",
                            )
                            break
                        except Exception as pcp_exc:
                            nat_errors.append(f"{candidate}: {nat_exc}; {pcp_exc}")
                if not wan_path and nat_errors:
                    prior = self.state.get("limitation") or ""
                    extra = "; ".join(nat_errors)[:240]
                    self.report(limitation=(f"{prior} {extra}").strip() if prior else extra)
            if config["remote"] and not wan_path:
                from .wan_forward import apply_ssh_reverse, gateway_ssh_configured, wan_settings_from_config

                wan = wan_settings_from_config(config)
                method = wan["wan_method"]
                if (
                    method in {"auto", "gateway_ssh"}
                    and gateway_ssh_configured(wan)
                ):
                    try:
                        from .wan_forward import is_literal_public_ipv4, lookup_egress_ipv4, public_dial_host_for_gateway

                        named = str(wan.get("wan_public_host") or "").strip()
                        live_egress = ""
                        if not named or is_literal_public_ipv4(named):
                            try:
                                live_egress = await asyncio.to_thread(lookup_egress_ipv4)
                            except Exception:
                                live_egress = str(public_ip or "")
                        public_host = public_dial_host_for_gateway(
                            named, live_egress, str(public_ip or "")
                        )
                        mapped, detail, lan_ip = await self._try_gateway_ssh(
                            wan, hosts, str(public_host or "")
                        )
                        wan_path = "gateway_ssh"
                        if mapped:
                            endpoints.append(mapped)
                        self._remember_mapped_public_ip(mapped)
                        self.report(
                            router="mapped",
                            wan_path=wan_path,
                            limitation=detail,
                            mapped_lan_ip=lan_ip,
                        )
                    except Exception as exc:
                        prior = self.state.get("limitation") or ""
                        extra = str(exc)[:240]
                        self.report(
                            router="unavailable",
                            limitation=(f"{prior} {extra}").strip() if prior else extra,
                        )
                if not wan_path and method in {"auto", "ssh_reverse"} and wan["ssh_host"] and wan["ssh_user"]:
                    self.report(activity="Opening an SSH reverse tunnel for companion TLS")
                    try:
                        mapped = await apply_ssh_reverse(wan)
                        endpoints.append(mapped)
                        wan_path = "ssh_reverse"
                        prior = self.state.get("limitation") or ""
                        detail = "SSH reverse tunnel is up; the phone should use the SSH host on TCP 4781"
                        self.report(
                            router="tunneled",
                            wan_path=wan_path,
                            limitation=(f"{prior} {detail}").strip() if prior else detail,
                        )
                    except Exception as exc:
                        self.report(router="unavailable", limitation=str(exc)[:240])
            if config.get("remote"):
                from .wan_forward import companion_wan_origin, is_literal_public_ipv4, is_public_dial_host

                named = str(config.get("wan_public_host") or "").strip()
                if is_public_dial_host(named):
                    origin_name = companion_wan_origin(named)
                    stale_literal = (
                        bool(wan_path)
                        and is_literal_public_ipv4(named)
                        and origin_name not in endpoints
                    )
                    if origin_name not in endpoints and not stale_literal:
                        endpoints.append(origin_name)
            await self.cover_phone_dial_hosts(
                *endpoints,
                relay,
                str(public_ip or ""),
                str(self.public_ip or ""),
            )
            identity = self.identity or identity
            if relay:
                try:
                    await self.probe(relay, identity)
                    endpoints.append(relay)
                    self.report(remote_verified=True)
                except Exception:
                    self.report(limitation="Configured relay did not reach this gateway; check relay service and credentials")
            if config["remote"] and not relay and not self.router and not wan_path:
                prior = self.state.get("limitation") or ""
                named = str(config.get("wan_public_host") or "").strip()
                if named:
                    extra = (
                        " Automatic router mapping was not created. Using the owner public hostname; "
                        "confirm the router forwards TCP 4781 to this PC."
                    )
                else:
                    extra = (
                        " No UPnP, NAT-PMP, or PCP lease, gateway SSH, SSH reverse tunnel, or hosted relay is ready. "
                        "Set SSH reverse-tunnel or OpenWrt gateway credentials, or JARVIS_RELAY_ENDPOINT."
                    )
                self.report(limitation=(prior + extra).strip())
            self.remote_prepared = True
            self.report(
                state="ready",
                activity="Secure connection prepared" if endpoints else "No phone-reachable address found; connect this desktop to a local network",
                endpoints=endpoints,
                next_renewal_at=time.time() + 1200,
            )
        except Exception as exc:
            await self.release_mapping()
            self.report(state="failed", activity=str(exc)[:300], endpoints=endpoints, local_verified=bool(self.server_task))

    async def apply(self, config):
        """Backward-compatible entry: refresh remote access without stopping LAN listen."""
        await self.apply_remote(config)

    def _gateway_ssh_candidates(self, wan: dict) -> list[str]:
        """Typed OpenWrt host, else RFC1918 defaults with the last working router first."""
        from .wan_forward import gateway_ssh_hosts

        explicit = str(wan.get("gateway_host") or "").strip()
        if explicit:
            return [explicit]
        hosts = [item for item in gateway_ssh_hosts(wan) if item]
        remembered = str(self.ssh_gateway or "")
        if remembered:
            hosts = [remembered, *[item for item in hosts if item != remembered]]
        return hosts

    async def _try_gateway_ssh(self, wan: dict, hosts, public_host: str):
        """SSH each candidate router until one maps TCP 4781 onto this PC."""
        from .wan_forward import apply_gateway_ssh, mapping_lan_ipv4

        errors: list[str] = []
        for candidate in self._gateway_ssh_candidates(wan):
            lan_ip = mapping_lan_ipv4(hosts, candidate)
            if not lan_ip:
                errors.append(f"{candidate}: Gateway SSH dest IP is not on the router subnet")
                continue
            attempt = dict(wan)
            attempt["gateway_host"] = candidate
            self.report(activity=f"Logging into {candidate} over SSH to map TCP 4781")
            try:
                mapped, detail = await apply_gateway_ssh(
                    attempt, lan_ip, public_host=str(public_host or "")
                )
            except Exception as exc:
                errors.append(f"{candidate}: {exc}")
                continue
            self.ssh_gateway = candidate
            return mapped, detail, lan_ip
        if errors:
            raise RuntimeError("; ".join(errors)[:240])
        raise RuntimeError(
            "Gateway SSH needs a LAN IPv4 on the router subnet; trying the next owner method."
        )

    async def _renew_gateway_ssh(self, config) -> None:
        """Re-apply the OpenWrt TCP 4781 redirect so DHCP / router reboot cannot drop WAN."""
        from .wan_forward import (
            gateway_ssh_configured,
            is_literal_public_ipv4,
            lookup_egress_ipv4,
            public_dial_host_for_gateway,
            wan_settings_from_config,
        )

        wan = wan_settings_from_config(config)
        if not gateway_ssh_configured(wan):
            raise RuntimeError("Gateway SSH credentials are no longer configured")
        named = str(wan.get("wan_public_host") or "").strip()
        live_egress = ""
        if not named or is_literal_public_ipv4(named):
            try:
                live_egress = await asyncio.to_thread(lookup_egress_ipv4)
            except Exception:
                live_egress = str(self.public_ip or "")
        public_host = public_dial_host_for_gateway(named, live_egress, str(self.public_ip or ""))
        previous_pub = str(self.public_ip or "")
        mapped, detail, lan_ip = await self._try_gateway_ssh(wan, lan_hosts(), public_host)
        endpoints = list(self.state.get("endpoints") or [])
        if previous_pub:
            endpoints = [item for item in endpoints if dial_host(item) != previous_pub]
        if named and is_literal_public_ipv4(named) and mapped and dial_host(mapped) != named:
            endpoints = [item for item in endpoints if dial_host(item) != named]
        if mapped and mapped not in endpoints:
            endpoints.append(mapped)
        self._remember_mapped_public_ip(mapped)
        self.report(
            router="mapped",
            wan_path="gateway_ssh",
            limitation=detail,
            endpoints=endpoints,
            mapped_lan_ip=lan_ip,
        )

    def _remember_mapped_public_ip(self, origin: str | None) -> None:
        host = dial_host(origin or "")
        from .wan_forward import is_literal_public_ipv4

        if is_literal_public_ipv4(host):
            self.public_ip = host

    def _merge_live_lan_endpoints(self, live: list[str], current: list[str]) -> list[str]:
        """Keep WAN/relay origins; replace stale RFC1918 dials with this PC's current LAN IPs."""
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

    def _live_wan_dest_ip(self) -> str:
        """Internal client the live WAN method would map TCP 4781 to right now."""
        path = str(self.state.get("wan_path") or "")
        if self.router:
            return igd_mapping_dest(self.router)
        if self.natpmp_gateway:
            return preferred_lan_ipv4(self.natpmp_gateway)
        if path == "gateway_ssh":
            from .wan_forward import mapping_lan_ipv4, wan_settings_from_config

            wan = wan_settings_from_config(self.config())
            gw = str(self.ssh_gateway or "")
            if not gw:
                candidates = self._gateway_ssh_candidates(wan)
                gw = candidates[0] if candidates else ""
            return mapping_lan_ipv4(lan_hosts(), gw)
        return ""

    def _wan_mapping_dest_changed(self) -> bool:
        previous = str(self.state.get("mapped_lan_ip") or "")
        dest = self._live_wan_dest_ip()
        return bool(previous and dest and dest != previous)

    def _wan_mapping_dest_left_this_pc(self, live_hosts: set[str] | None = None) -> bool:
        """True when the mapped internal client is no longer an address on this machine."""
        previous = str(self.state.get("mapped_lan_ip") or "")
        if not previous:
            return False
        hosts = live_hosts if live_hosts is not None else set(lan_hosts())
        return previous not in hosts

    async def _live_wan_public_ip(self) -> str:
        """Public IPv4 the live WAN method currently advertises.

        UPnP and NAT-PMP are query-only. PCP has no public-IP opcode, so one MAP
        renew reads the assigned address (and keeps the one-hour lease alive).
        """
        if self.router:
            try:
                return str(await asyncio.to_thread(self.router.externalipaddress) or "")
            except Exception:
                return ""
        if self.natpmp_gateway:
            lan = preferred_lan_ipv4(self.natpmp_gateway)
            if self.pcp_nonce:
                from .pcp import apply_pcp

                try:
                    public_ip, nonce = await asyncio.to_thread(
                        apply_pcp, self.natpmp_gateway, lan, self.pcp_nonce
                    )
                    self.pcp_nonce = nonce
                    return str(public_ip or "")
                except Exception:
                    return ""
            from .natpmp import query_public_ip

            try:
                return str(await asyncio.to_thread(query_public_ip, self.natpmp_gateway, lan) or "")
            except Exception:
                return ""
        if str(self.state.get("wan_path") or "") == "gateway_ssh":
            from .wan_forward import is_literal_public_ipv4, lookup_egress_ipv4

            named = str((self.config() or {}).get("wan_public_host") or "").strip()
            if named and not is_literal_public_ipv4(named):
                return ""
            try:
                return str(await asyncio.to_thread(lookup_egress_ipv4) or "")
            except Exception:
                return ""
        return ""

    def _wan_public_ip_changed(self, live: str) -> bool:
        previous = str(self.public_ip or "")
        return bool(previous and live and live != previous)

    async def _refresh_lan_dial_endpoints(self, *, remap_wan: bool = True) -> None:
        hosts = await asyncio.to_thread(lan_hosts)
        live = self._lan_endpoints(hosts)
        current = list(self.state.get("endpoints") or [])
        merged = self._merge_live_lan_endpoints(live, current)
        if not merged:
            return
        await self.cover_phone_dial_hosts(*merged)
        if merged != current:
            self.report(endpoints=merged)
        if not remap_wan:
            return
        live_hosts = set(hosts)
        if self._wan_mapping_dest_left_this_pc(live_hosts):
            await self.apply_remote(self.config())
            return
        if self._wan_mapping_dest_changed():
            await self._renew_wan_mapping(self.config())
            return
        live_pub = await self._live_wan_public_ip()
        if self._wan_public_ip_changed(live_pub):
            await self.apply_remote(self.config())

    async def _renew_wan_mapping(self, config) -> None:
        """Keep the one-hour UPnP/NAT-PMP/PCP lease and the OpenWrt redirect alive."""
        await self.probe(f"https://127.0.0.1:{PORT}", self.identity)
        path = str(self.state.get("wan_path") or "")
        if self.router:
            if await asyncio.to_thread(self.router.externalipaddress) != self.public_ip:
                raise RuntimeError("Router address changed")
            await asyncio.to_thread(map_router, self.router, self.marker)
            self.report(mapped_lan_ip=igd_mapping_dest(self.router))
        elif self.natpmp_gateway:
            lan = preferred_lan_ipv4(self.natpmp_gateway)
            if self.pcp_nonce:
                from .pcp import apply_pcp

                public_ip, nonce = await asyncio.to_thread(
                    apply_pcp, self.natpmp_gateway, lan, self.pcp_nonce
                )
                self.pcp_nonce = nonce
            else:
                from .natpmp import apply_natpmp

                public_ip = await asyncio.to_thread(apply_natpmp, self.natpmp_gateway, lan)
            if public_ip != self.public_ip:
                raise RuntimeError("Mapped public address changed")
            self.public_ip = public_ip
            self.report(mapped_lan_ip=lan)
        elif path == "gateway_ssh":
            await self._renew_gateway_ssh(config)
        await self._refresh_lan_dial_endpoints(remap_wan=False)
        self.report(next_renewal_at=time.time() + 1200)

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
                        from .wan_forward import REVERSE_TUNNEL, apply_ssh_reverse, wan_settings_from_config

                        if not self.server_task or self.server_task.done():
                            try:
                                await self.ensure_gateway_listening()
                            except Exception as exc:
                                self.report(state="failed", activity=str(exc)[:300])
                        config = self.config()
                        if config["enabled"]:
                            tunnel_dead = self.state.get("wan_path") == "ssh_reverse" and not REVERSE_TUNNEL.alive()
                            if self.state.get("state") == "cooldown":
                                pass
                            elif self.state.get("state") != "ready" or not self.remote_prepared:
                                await self.apply_remote(config)
                            elif tunnel_dead:
                                try:
                                    mapped = await apply_ssh_reverse(wan_settings_from_config(config))
                                    endpoints = list(self.state.get("endpoints") or [])
                                    if mapped not in endpoints:
                                        endpoints.append(mapped)
                                    self.report(
                                        router="tunneled",
                                        wan_path="ssh_reverse",
                                        endpoints=endpoints,
                                        limitation="SSH reverse tunnel reconnected",
                                        next_renewal_at=time.time() + 1200,
                                    )
                                except Exception:
                                    await self.apply_remote(config)
                            elif time.time() >= self.state.get("next_renewal_at", 0):
                                try:
                                    await self._renew_wan_mapping(config)
                                except Exception:
                                    await self.apply_remote(config)
                            else:
                                try:
                                    await self._refresh_lan_dial_endpoints()
                                except Exception:
                                    await self.apply_remote(config)
                await asyncio.sleep(30)
        finally:
            await self.release_mapping()
            await self.stop_gateway()


CONNECTIVITY = Connectivity()
