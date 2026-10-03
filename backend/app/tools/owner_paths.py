"""Owner Downloads/Pictures/Desktop paths inside the allowed workspace."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from ..config import data_dir, repo_root
from .safety import resolve_allowed_path

_PROXY_ENV_NAMES = frozenset({"HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "NO_PROXY", "FTP_PROXY"})


def direct_child_env(base: dict[str, str] | None = None) -> dict[str, str]:
    """Environment for owner tool children on the OS default route.

    Leftover HTTP_PROXY (VPN clients, installer leftovers) steals LAN curl and
    internet fetch away from this PC's default route. ``web_fetch`` and Chromium
    already ignore process proxies; terminal, python, git, and HexStrike must
    match. PATH and JARVIS_* are kept.
    """
    env = dict(os.environ if base is None else base)
    for key in list(env):
        if key.upper() in _PROXY_ENV_NAMES:
            env.pop(key, None)
    try:
        from .lan_ssh import git_ssh_command

        # rsync SSH of a NAS otherwise follows the VPN default route. lan_ssh.py
        # only inserts BindAddress for on-link RFC1918; public hosts are unchanged.
        env["RSYNC_RSH"] = git_ssh_command()
    except Exception:
        pass
    return env


def lan_http_child_env(base: dict[str, str] | None = None) -> dict[str, str]:
    """HTTP_PROXY to Jarvis's loopback proxy: LAN binds the home NIC.

    Git and Python ``requests`` honor HTTP_PROXY. After dropping a leftover VPN
    proxy, point them at the process-local proxy which sources RFC1918 from the
    on-link NIC and sends public internet on the OS default route.
    """
    env = direct_child_env(base)
    try:
        from ..security.lan_http_proxy import ensure_lan_http_proxy

        origin = ensure_lan_http_proxy()
    except Exception:
        return env
    if not origin:
        return env
    env["HTTP_PROXY"] = origin
    env["HTTPS_PROXY"] = origin
    env["http_proxy"] = origin
    env["https_proxy"] = origin
    env["FTP_PROXY"] = origin
    env["ftp_proxy"] = origin
    env["ALL_PROXY"] = origin
    env["all_proxy"] = origin
    return env


def with_lan_socket_pythonpath(env: dict[str, str]) -> dict[str, str]:
    """Prepend sitecustomize so child Python RFC1918 sockets bind the home NIC.

    Does not set HTTP_PROXY. HexStrike nuclei ``-source-ip`` plus a process-wide
    proxy would bind LAN then CONNECT loopback. smbmap / enum4linux-ng / netexec
    / impacket still need ``connect``/``sendto`` sourced from the on-link NIC.
    """
    site = Path(__file__).resolve().parent / "lan_python_site"
    backend = repo_root() / "backend"
    parts = [str(site), str(backend)]
    existing = env.get("PYTHONPATH") or ""
    if existing:
        parts.append(existing)
    env["PYTHONPATH"] = os.pathsep.join(parts)
    return env


def python_child_env(base: dict[str, str] | None = None) -> dict[str, str]:
    """Python HTTP proxy plus sitecustomize so raw sockets bind the home NIC."""
    return with_lan_socket_pythonpath(lan_http_child_env(base))


def git_child_env(base: dict[str, str] | None = None) -> dict[str, str]:
    """Git HTTP uses the LAN proxy; git SSH uses BindAddress on on-link RFC1918."""
    env = lan_http_child_env(base)
    try:
        from .lan_ssh import git_ssh_command

        env["GIT_SSH_COMMAND"] = git_ssh_command()
    except Exception:
        return env
    return env


def owner_media_dir(*names: str) -> Path:
    """Owner Downloads/Pictures/Desktop when present; otherwise a Jarvis data folder."""
    for name in names:
        candidate = Path.home() / name
        try:
            if candidate.is_dir():
                return candidate
        except OSError:
            continue
    fallback = data_dir() / (names[0].lower() if names else "downloads")
    fallback.mkdir(parents=True, exist_ok=True)
    return fallback


def owner_downloads_dir() -> Path:
    """Chromium / Browser Use download directory: the owner's Downloads folder."""
    dest = owner_media_dir("Downloads")
    dest.mkdir(parents=True, exist_ok=True)
    return dest


CHROMIUM_NO_PROXY_ARGS = ("--no-proxy-server",)
PLAYWRIGHT_DIRECT_PROXY = {"server": "direct://"}


def chromium_download_launch_kwargs() -> dict[str, Any]:
    """Playwright persistent-context kwargs: Downloads folder, OS default route.

    Chromium otherwise honors HTTP_PROXY from the process environment, which
    steals internet (and can steal LAN) away from the owner's default route.
    ``web_fetch`` already uses trust_env=False; Chromium must match.
    """
    return {
        "accept_downloads": True,
        "downloads_path": str(owner_downloads_dir()),
        "proxy": dict(PLAYWRIGHT_DIRECT_PROXY),
        "args": list(CHROMIUM_NO_PROXY_ARGS),
    }


def resolve_owner_file_path(
    raw: str | None,
    *,
    suggested_name: str,
    allowed: list[str],
    fallback_dirs: tuple[str, ...] = ("Downloads",),
) -> Path:
    """Save/open path under the allowed workspace. Default is the owner's Downloads folder."""
    name = Path(str(suggested_name or "download").strip() or "download").name
    if raw and str(raw).strip():
        target = Path(str(raw).strip()).expanduser()
        try:
            is_dir = target.is_dir()
        except OSError:
            is_dir = False
        if is_dir or str(raw).endswith(("/", "\\")):
            target = target / name
        return resolve_allowed_path(str(target), allowed)
    dest = owner_media_dir(*fallback_dirs) / name
    try:
        return resolve_allowed_path(str(dest), allowed)
    except PermissionError:
        alt = data_dir() / (fallback_dirs[0].lower() if fallback_dirs else "downloads") / name
        alt.parent.mkdir(parents=True, exist_ok=True)
        if not allowed:
            return alt
        return resolve_allowed_path(str(alt), allowed)


def resolve_workspace_dir(raw: str | None, allowed: list[str]) -> str | None:
    """Expand ~ and, when the workspace is bound, keep the path on an allowed drive."""
    text = str(raw or "").strip()
    if not text:
        return None
    expanded = str(Path(text).expanduser())
    if not allowed:
        return expanded
    return str(resolve_allowed_path(expanded, allowed))


def default_workspace_dir(allowed: list[str], *, media_only: bool = False) -> Path:
    """Documents (then Desktop/Downloads) when that folder is in the workspace."""
    for name in ("Documents", "Desktop", "Downloads"):
        candidate = Path.home() / name
        try:
            if not candidate.is_dir():
                continue
        except OSError:
            continue
        try:
            return resolve_allowed_path(str(candidate), allowed)
        except PermissionError:
            continue
    if media_only:
        raise PermissionError("Documents is not in the allowed workspace")
    if allowed:
        return resolve_allowed_path(allowed[0], allowed)
    return Path.cwd()


def resolve_project_dir(raw: str | None, allowed: list[str]) -> Path:
    """Explicit extra-drive/USB folder, or Documents when path is omitted."""
    text = str(raw or "").strip()
    if text:
        resolved = resolve_workspace_dir(text, allowed)
        return Path(resolved) if resolved else resolve_allowed_path(text, allowed)
    return default_workspace_dir(allowed)


def workspace_cwd(raw: str | None, allowed: list[str]) -> str | None:
    """Working directory for python/terminal. Omit path → Documents when the workspace is bound."""
    text = str(raw or "").strip()
    if text:
        return resolve_workspace_dir(text, allowed)
    if not allowed:
        return None
    return str(default_workspace_dir(allowed))
