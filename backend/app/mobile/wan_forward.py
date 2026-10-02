"""Owner-opt-in companion WAN reachability: UPnP, SSH reverse tunnel, gateway SSH.

Only TCP 4781 is ever mapped. Owner credentials are required; there is no password
guessing, no admin-UI scraping, and no mapping of 4780 / 8088 / SSH / router admin.
"""
from __future__ import annotations

import asyncio
import ipaddress
import os
import shutil
import sys
from pathlib import Path
from typing import Any

import httpx

PORT = 4781

WAN_METHODS = frozenset({"auto", "upnp", "ssh_reverse", "gateway_ssh"})
GATEWAY_PROFILES = frozenset({"openwrt_uci"})
_SSH_BINARIES = ("ssh", "ssh.exe")


def is_public_dial_host(host: str) -> bool:
    """True when a companion off-LAN could reasonably dial this name or address."""
    text = (host or "").strip().lower().rstrip(".")
    if not text or "/" in text or "\\" in text or "@" in text or ":" in text:
        return False
    if text in {"localhost", "router", "gateway"} or text.endswith((".local", ".home.arpa", ".lan")):
        return False
    try:
        ip = ipaddress.ip_address(text)
    except ValueError:
        return "." in text
    return bool(ip.is_global)


def companion_wan_origin(host: str) -> str:
    if not is_public_dial_host(host):
        raise ValueError("Companion WAN origin must be a public hostname or global IPv4, not a LAN address")
    return f"https://{host.strip()}:{PORT}"


def ensure_private_firewall_4781() -> str:
    """Allow inbound TCP 4781 on the Windows private profile only."""
    if os.name != "nt":
        return "skipped"
    import subprocess

    name = "Jarvis companion TLS 4781"
    check = subprocess.run(
        ["netsh", "advfirewall", "firewall", "show", "rule", f"name={name}"],
        capture_output=True,
        text=True,
        timeout=8,
        check=False,
    )
    if check.returncode == 0 and name.lower() in (check.stdout or "").lower():
        return "present"
    added = subprocess.run(
        [
            "netsh",
            "advfirewall",
            "firewall",
            "add",
            "rule",
            f"name={name}",
            "dir=in",
            "action=allow",
            "protocol=TCP",
            f"localport={PORT}",
            "profile=private",
        ],
        capture_output=True,
        text=True,
        timeout=8,
        check=False,
    )
    if added.returncode != 0:
        return f"failed:{(added.stderr or added.stdout or '').strip()[:160]}"
    return "added"


def lookup_egress_ipv4() -> str:
    """Best-effort public IPv4 of this network after a mapping already exists."""
    urls = ("https://api.ipify.org", "https://ipv4.icanhazip.com")
    last_error: Exception | None = None
    for url in urls:
        try:
            with httpx.Client(timeout=3, trust_env=False, follow_redirects=True) as client:
                text = client.get(url).text.strip()
            address = ipaddress.ip_address(text.split()[0])
            if address.version == 4 and address.is_global:
                return str(address)
            last_error = ValueError("egress lookup was not a public IPv4")
        except Exception as exc:
            last_error = exc
    raise ValueError(str(last_error) if last_error else "Could not learn public IPv4")


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


def parse_proc_net_route(text: str) -> str:
    """First private IPv4 default gateway from /proc/net/route."""
    lines = (text or "").splitlines()
    for line in lines[1:]:
        parts = line.split()
        if len(parts) < 3 or parts[1] != "00000000":
            continue
        raw = int(parts[2], 16)
        address = ipaddress.IPv4Address(raw.to_bytes(4, "little"))
        if address.is_private and not address.is_loopback:
            return str(address)
    raise ValueError("No private default gateway")


def parse_windows_route_print(text: str) -> str:
    for line in (text or "").splitlines():
        parts = line.split()
        if len(parts) < 3:
            continue
        if parts[0] != "0.0.0.0" or parts[1] != "0.0.0.0":
            continue
        try:
            address = ipaddress.ip_address(parts[2])
        except ValueError:
            continue
        if address.version == 4 and address.is_private and not address.is_loopback:
            return str(address)
    raise ValueError("No private default gateway")


def default_gateway_ipv4() -> str:
    """LAN router this PC already uses — used when the owner leaves gateway host blank."""
    if os.name == "nt":
        import subprocess

        printed = subprocess.run(
            ["route", "print", "-4"],
            capture_output=True,
            text=True,
            timeout=8,
            check=False,
        )
        return parse_windows_route_print((printed.stdout or "") + "\n" + (printed.stderr or ""))
    route = Path("/proc/net/route")
    if route.is_file():
        return parse_proc_net_route(route.read_text(encoding="utf-8", errors="replace"))
    raise ValueError("No private default gateway")


def resolved_gateway_host(settings: dict[str, Any]) -> str:
    host = str(settings.get("gateway_host") or "").strip()
    return host or default_gateway_ipv4()


def resolved_gateway_user(settings: dict[str, Any]) -> str:
    user = str(settings.get("gateway_user") or settings.get("gateway_username") or "").strip()
    if user:
        return user
    if str(settings.get("gateway_profile") or "openwrt_uci").strip() == "openwrt_uci":
        return "root"
    raise ValueError("Gateway SSH needs a username")


def gateway_ssh_configured(settings: dict[str, Any]) -> bool:
    has_key = bool(str(settings.get("gateway_identity_file") or "").strip())
    has_password = bool(str(settings.get("gateway_password") or "").strip())
    return has_key or has_password


def _identity_args(identity_file: str) -> list[str]:
    path = Path(identity_file or "").expanduser()
    if not str(path) or not path.is_file():
        raise ValueError("SSH identity file is required and must exist")
    return ["-i", str(path)]


_ASKPASS_SOURCE = """import os
import sys

path = os.environ.get("JARVIS_SSH_ASKPASS_FILE", "")
if not path:
    sys.exit(1)
try:
    with open(path, "r", encoding="utf-8") as handle:
        sys.stdout.write(handle.read())
finally:
    try:
        os.remove(path)
    except OSError:
        pass
"""


def ssh_askpass_executable() -> str:
    """Small OpenSSH askpass helper. Never receives the secret on argv."""
    from .store import root as mobile_root

    folder = mobile_root()
    folder.mkdir(parents=True, exist_ok=True)
    script = folder / "ssh-askpass.py"
    body = f"#!{os.path.abspath(sys.executable)}\n{_ASKPASS_SOURCE}"
    if not script.exists() or script.read_text(encoding="utf-8") != body:
        script.write_text(body, encoding="utf-8")
    script.chmod(0o700)
    if os.name == "nt":
        cmd = folder / "ssh-askpass.cmd"
        cmd.write_text(f'@echo off\r\n"{os.path.abspath(sys.executable)}" "{script}"\r\n', encoding="utf-8")
        return str(cmd)
    return str(script)


def prepare_ssh_password_env(password: str) -> tuple[dict[str, str], str]:
    secret = (password or "")
    if not secret:
        raise ValueError("Gateway password is empty")
    import tempfile

    handle, path = tempfile.mkstemp(prefix="jarvis-ssh-askpass-")
    try:
        os.write(handle, secret.encode("utf-8"))
    finally:
        os.close(handle)
    os.chmod(path, 0o600)
    env = os.environ.copy()
    env["DISPLAY"] = env.get("DISPLAY") or "jarvis:0"
    env["SSH_ASKPASS"] = ssh_askpass_executable()
    env["SSH_ASKPASS_REQUIRE"] = "force"
    env["JARVIS_SSH_ASKPASS_FILE"] = path
    env.pop("SSH_AUTH_SOCK", None)
    return env, path


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
    if not is_public_dial_host(host):
        raise ValueError("SSH reverse tunnel host must be a public hostname or global IPv4")
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
    identity_file: str = "",
    lan_ip: str,
    port: int = 22,
    profile: str = "openwrt_uci",
    password: str = "",
) -> list[str]:
    if (profile or "").strip() not in GATEWAY_PROFILES:
        raise ValueError("Unsupported gateway profile; only openwrt_uci is implemented")
    host = (host or "").strip()
    user = (user or "").strip()
    if not host or not user:
        raise ValueError("Gateway SSH needs host and user")
    auth = _identity_args(identity_file) if (identity_file or "").strip() else []
    if not auth and not (password or "").strip():
        raise ValueError("Gateway SSH needs an identity file or the owner router password")
    script = openwrt_redirect_script(lan_ip)
    options = ["-o", "StrictHostKeyChecking=accept-new"]
    if auth:
        options = ["-o", "BatchMode=yes", *options, *auth]
    else:
        options += [
            "-o",
            "BatchMode=no",
            "-o",
            "PreferredAuthentications=password,keyboard-interactive",
            "-o",
            "NumberOfPasswordPrompts=1",
        ]
    return [
        ssh_executable(),
        *options,
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
        "wan_public_host": str(config.get("wan_public_host") or "").strip(),
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


async def apply_gateway_ssh(settings: dict[str, Any], lan_ip: str, public_host: str = "") -> tuple[str | None, str]:
    password = str(settings.get("gateway_password") or "")
    argv = gateway_ssh_argv(
        host=resolved_gateway_host(settings),
        user=resolved_gateway_user(settings),
        identity_file=str(settings.get("gateway_identity_file") or ""),
        lan_ip=lan_ip,
        port=int(settings.get("gateway_port") or 22),
        profile=str(settings.get("gateway_profile") or "openwrt_uci"),
        password=password,
    )
    env: dict[str, str] | None = None
    secret_path = ""
    if not str(settings.get("gateway_identity_file") or "").strip() and password:
        env, secret_path = prepare_ssh_password_env(password)
    proc: asyncio.subprocess.Process | None = None
    stderr = b""
    try:
        proc = await asyncio.create_subprocess_exec(
            *argv[:-1],
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            env=env,
        )
        _stdout, stderr = await asyncio.wait_for(proc.communicate(argv[-1].encode("utf-8")), timeout=45)
    finally:
        if secret_path:
            try:
                os.remove(secret_path)
            except OSError:
                pass
    if proc is None or proc.returncode != 0:
        detail = (stderr or b"").decode("utf-8", errors="replace").strip()[:240]
        raise RuntimeError(detail or "Gateway SSH port-forward failed")
    host = (settings.get("wan_public_host") or public_host or "").strip()
    if not is_public_dial_host(host):
        return (
            None,
            "Gateway SSH mapped TCP 4781 on the router. Set a public hostname so the phone can dial it from outside this network.",
        )
    return companion_wan_origin(host), "Gateway SSH mapping applied; verify from outside this network"


async def apply_ssh_reverse(settings: dict[str, Any]) -> str:
    argv = reverse_tunnel_argv(
        host=settings["ssh_host"],
        user=settings["ssh_user"],
        identity_file=settings["ssh_identity_file"],
        port=int(settings["ssh_port"] or 22),
    )
    endpoint = companion_wan_origin(settings["ssh_host"])
    await REVERSE_TUNNEL.start(argv, endpoint)
    return endpoint
