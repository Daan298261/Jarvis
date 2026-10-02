"""Owner-opt-in companion WAN reachability: UPnP, SSH reverse tunnel, gateway SSH.

Only TCP 4781 is ever mapped. Owner credentials are required; there is no password
guessing, no admin-UI scraping, and no mapping of 4780 / 8088 / SSH / router admin.
"""
from __future__ import annotations

import asyncio
import ipaddress
import shutil
from pathlib import Path
from typing import Any

PORT = 4781

WAN_METHODS = frozenset({"auto", "upnp", "ssh_reverse", "gateway_ssh"})
GATEWAY_PROFILES = frozenset({"openwrt_uci"})
_SSH_BINARIES = ("ssh", "ssh.exe")


def _private_ipv4(value: str) -> str:
    address = ipaddress.ip_address((value or "").strip())
    if address.version != 4 or not address.is_private or address.is_loopback:
        raise ValueError("Gateway port-forward destination must be a private LAN IPv4 address")
    return str(address)


def ssh_executable() -> str:
    for name in _SSH_BINARIES:
        found = shutil.which(name)
        if found:
            return found
    raise RuntimeError("OpenSSH client is not installed; cannot create an SSH reverse tunnel")


def _identity_args(identity_file: str) -> list[str]:
    path = Path(identity_file or "").expanduser()
    if not str(path) or not path.is_file():
        raise ValueError("SSH identity file is required and must exist")
    return ["-i", str(path)]


def reverse_tunnel_argv(
    *,
    host: str,
    user: str,
    identity_file: str,
    port: int = 22,
    bind_host: str = "0.0.0.0",
) -> list[str]:
    """ssh -R 4781:127.0.0.1:4781 so the companion can dial the owner's SSH host."""
    host = (host or "").strip()
    user = (user or "").strip()
    if not host or not user:
        raise ValueError("SSH reverse tunnel needs host and user")
    if "/" in host or "\\" in host or "@" in host:
        raise ValueError("SSH host must be a hostname or address")
    if not 1 <= int(port) <= 65535:
        raise ValueError("Invalid SSH port")
    bind = (bind_host or "0.0.0.0").strip() or "0.0.0.0"
    spec = f"{bind}:{PORT}:127.0.0.1:{PORT}"
    return [
        ssh_executable(),
        "-N",
        "-o",
        "BatchMode=yes",
        "-o",
        "ExitOnForwardFailure=yes",
        "-o",
        "ServerAliveInterval=30",
        "-o",
        "ServerAliveCountMax=3",
        "-o",
        "StrictHostKeyChecking=accept-new",
        *_identity_args(identity_file),
        "-p",
        str(int(port)),
        "-R",
        spec,
        f"{user}@{host}",
    ]


def openwrt_redirect_script(lan_ip: str) -> str:
    dest = _private_ipv4(lan_ip)
    # Bounded UCI batch: one named redirect for companion TLS only.
    return (
        "set -e\n"
        "uci -q delete firewall.jarvis_companion_4781 || true\n"
        "uci set firewall.jarvis_companion_4781=redirect\n"
        "uci set firewall.jarvis_companion_4781.name='Jarvis companion TLS'\n"
        "uci set firewall.jarvis_companion_4781.src='wan'\n"
        f"uci set firewall.jarvis_companion_4781.src_dport='{PORT}'\n"
        "uci set firewall.jarvis_companion_4781.dest='lan'\n"
        f"uci set firewall.jarvis_companion_4781.dest_ip='{dest}'\n"
        f"uci set firewall.jarvis_companion_4781.dest_port='{PORT}'\n"
        "uci set firewall.jarvis_companion_4781.proto='tcp'\n"
        "uci set firewall.jarvis_companion_4781.target='DNAT'\n"
        "uci commit firewall\n"
        "/etc/init.d/firewall reload\n"
    )


def gateway_ssh_argv(
    *,
    host: str,
    user: str,
    identity_file: str,
    lan_ip: str,
    port: int = 22,
    profile: str = "openwrt_uci",
) -> list[str]:
    if (profile or "").strip() not in GATEWAY_PROFILES:
        raise ValueError("Unsupported gateway profile; only openwrt_uci is implemented")
    host = (host or "").strip()
    user = (user or "").strip()
    if not host or not user:
        raise ValueError("Gateway SSH needs host and user")
    script = openwrt_redirect_script(lan_ip)
    return [
        ssh_executable(),
        "-o",
        "BatchMode=yes",
        "-o",
        "StrictHostKeyChecking=accept-new",
        *_identity_args(identity_file),
        "-p",
        str(int(port)),
        f"{user}@{host}",
        "sh",
        "-s",
        script,
    ]


def redact_wan_config(config: dict[str, Any]) -> dict[str, Any]:
    public = {
        key: value
        for key, value in config.items()
        if key not in {"gateway_password"}
    }
    if config.get("gateway_password"):
        public["gateway_password_set"] = True
    return public


def wan_settings_from_config(config: dict[str, Any]) -> dict[str, Any]:
    method = str(config.get("wan_method") or "auto").strip().lower() or "auto"
    if method not in WAN_METHODS:
        method = "auto"
    return {
        "wan_method": method,
        "ssh_host": str(config.get("ssh_host") or "").strip(),
        "ssh_port": int(config.get("ssh_port") or 22),
        "ssh_user": str(config.get("ssh_user") or "").strip(),
        "ssh_identity_file": str(config.get("ssh_identity_file") or "").strip(),
        "gateway_host": str(config.get("gateway_host") or "").strip(),
        "gateway_port": int(config.get("gateway_port") or 22),
        "gateway_user": str(config.get("gateway_user") or "").strip(),
        "gateway_identity_file": str(config.get("gateway_identity_file") or "").strip(),
        "gateway_profile": str(config.get("gateway_profile") or "openwrt_uci").strip() or "openwrt_uci",
        "gateway_username": str(config.get("gateway_username") or "").strip(),
        "gateway_password": str(config.get("gateway_password") or ""),
    }


class ReverseTunnel:
    def __init__(self) -> None:
        self.process: asyncio.subprocess.Process | None = None
        self.argv: list[str] = []
        self.endpoint = ""

    async def start(self, argv: list[str], endpoint: str) -> None:
        await self.stop()
        self.argv = list(argv)
        self.endpoint = endpoint
        self.process = await asyncio.create_subprocess_exec(
            *argv,
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.PIPE,
            stdin=asyncio.subprocess.DEVNULL,
        )
        try:
            await asyncio.wait_for(self.process.wait(), timeout=0.4)
        except TimeoutError:
            return
        err = b""
        if self.process.stderr:
            err = await self.process.stderr.read()
        code = self.process.returncode
        self.process = None
        detail = err.decode("utf-8", errors="replace").strip()[:240]
        raise RuntimeError(detail or f"SSH reverse tunnel exited ({code})")

    def alive(self) -> bool:
        return self.process is not None and self.process.returncode is None

    async def stop(self) -> None:
        proc = self.process
        self.process = None
        if proc is None:
            return
        if proc.returncode is None:
            proc.terminate()
            try:
                await asyncio.wait_for(proc.wait(), timeout=3)
            except TimeoutError:
                proc.kill()
                await proc.wait()


REVERSE_TUNNEL = ReverseTunnel()


async def apply_gateway_ssh(settings: dict[str, Any], lan_ip: str) -> str:
    argv = gateway_ssh_argv(
        host=settings["gateway_host"],
        user=settings["gateway_user"],
        identity_file=settings["gateway_identity_file"],
        lan_ip=lan_ip,
        port=int(settings.get("gateway_port") or 22),
        profile=settings["gateway_profile"],
    )
    # Remote script is the last argv item; OpenSSH passes remaining args to remote sh -s.
    proc = await asyncio.create_subprocess_exec(
        *argv[:-1],
        stdin=asyncio.subprocess.PIPE,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    _stdout, stderr = await asyncio.wait_for(proc.communicate(argv[-1].encode("utf-8")), timeout=45)
    if proc.returncode != 0:
        detail = (stderr or b"").decode("utf-8", errors="replace").strip()[:240]
        raise RuntimeError(detail or "Gateway SSH port-forward failed")
    return f"https://{settings['gateway_host']}:{PORT}"


async def apply_ssh_reverse(settings: dict[str, Any]) -> str:
    argv = reverse_tunnel_argv(
        host=settings["ssh_host"],
        user=settings["ssh_user"],
        identity_file=settings["ssh_identity_file"],
        port=int(settings["ssh_port"] or 22),
    )
    endpoint = f"https://{settings['ssh_host']}:{PORT}"
    await REVERSE_TUNNEL.start(argv, endpoint)
    return endpoint
