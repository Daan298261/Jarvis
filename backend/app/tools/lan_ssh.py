"""Bind OpenSSH of on-link RFC1918 hosts to this PC's home NIC.

``ssh user@192.168.1.1`` and ``git@nas:repo.git`` follow the OS default route.
A VPN default route would steal the hop to the NAS or gateway. OpenSSH
``-o BindAddress=`` (not scp's ``-b`` batch flag) pins the source IP.
"""
from __future__ import annotations

import os
import shlex
import shutil
import sys
from pathlib import Path

_SSH_NAMES = frozenset({"ssh", "scp", "sftp"})
_VALUE_FLAGS = frozenset(
    {
        "-b",
        "-c",
        "-D",
        "-E",
        "-F",
        "-i",
        "-I",
        "-J",
        "-L",
        "-l",
        "-m",
        "-o",
        "-P",
        "-p",
        "-Q",
        "-R",
        "-S",
        "-W",
    }
)


def _tool_name(argv0: str) -> str:
    text = Path(argv0 or "").name.lower()
    if text.endswith(".exe"):
        text = text[:-4]
    return text


def ssh_host_from_token(token: str) -> str:
    text = str(token or "").strip().strip("'\"")
    if not text or text.startswith("-"):
        return ""
    if "@" in text:
        text = text.rsplit("@", 1)[-1]
    if text.startswith("[") and "]" in text:
        text = text[1 : text.index("]")]
    if ":" in text:
        host, _, rest = text.partition(":")
        if rest.isdigit() or "/" in rest or "\\" in rest or rest.endswith(".git"):
            text = host
        else:
            text = host
    return text.split("/")[0].strip()


def looks_ssh_destination(token: str) -> bool:
    text = str(token or "").strip().strip("'\"")
    if not text or text.startswith("-"):
        return False
    if "@" not in text and ("/" in text or "\\" in text):
        return False
    if "@" in text:
        return True
    host = ssh_host_from_token(text)
    if not host:
        return False
    try:
        import ipaddress

        ipaddress.ip_address(host)
        return True
    except ValueError:
        pass
    lowered = host.lower().rstrip(".")
    return lowered.endswith((".local", ".lan", ".home.arpa"))


def ssh_destination_host(argv: list[str]) -> str:
    """First destination host in an ssh/scp/sftp argv (after options)."""
    parts = list(argv or [])
    if parts and _tool_name(parts[0]) in _SSH_NAMES:
        parts = parts[1:]
    index = 0
    while index < len(parts):
        token = str(parts[index])
        if token == "--":
            index += 1
            break
        if token.startswith("-") and token != "-":
            key = token.split("=", 1)[0]
            if key in _VALUE_FLAGS and "=" not in token:
                index += 2
                continue
            index += 1
            continue
        if looks_ssh_destination(token):
            return ssh_host_from_token(token)
        index += 1
    if index < len(parts) and looks_ssh_destination(parts[index]):
        return ssh_host_from_token(parts[index])
    return ""


def lan_ssh_bind_ip(host: str) -> str:
    from ..mobile.wan_forward import lan_http_bind_for_url, lan_source_ipv4_for_peer

    text = (host or "").strip()
    if not text:
        return ""
    bind = lan_source_ipv4_for_peer(text)
    if bind:
        return bind
    return lan_http_bind_for_url(f"http://{text}")


def with_lan_ssh_bind(argv: list[str]) -> list[str]:
    """Insert ``-o BindAddress=<lan-ip>`` when the destination is on-link RFC1918."""
    parts = [str(item) for item in (argv or [])]
    if not parts:
        return parts
    joined = " ".join(parts)
    if "-b" in parts or "BindAddress=" in joined:
        return parts
    if "-J" in parts or "ProxyJump" in joined or "ProxyCommand" in joined:
        return parts
    host = ssh_destination_host(parts)
    bind = lan_ssh_bind_ip(host)
    if not bind:
        return parts
    return [parts[0], "-o", f"BindAddress={bind}", *parts[1:]]


def git_ssh_command() -> str:
    """GIT_SSH_COMMAND that runs this module so git SSH of a NAS binds the home NIC."""
    script = str(Path(__file__).resolve())
    exe = sys.executable or "python3"
    if os.name == "nt":
        return f'"{exe}" "{script}"'
    return f"{shlex.quote(exe)} {shlex.quote(script)}"


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    ssh = shutil.which("ssh") or shutil.which("ssh.exe") or "ssh"
    bound = with_lan_ssh_bind([ssh, *args])
    os.execvp(bound[0], bound)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
