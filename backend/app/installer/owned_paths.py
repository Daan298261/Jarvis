"""RFC-0124: Jarvis-owned path registry (allowlist) for clean reinstall."""

from __future__ import annotations

import os
import sys
from pathlib import Path

from ..config import data_dir, repo_root

LICENSE_ISSUER_LEAF = "license-issuer"
OWNED_PATHS_REG_REL = Path("Software") / "Jarvis" / "OwnedPaths"


def default_install_dir() -> Path:
    local = os.environ.get("LOCALAPPDATA")
    if local:
        return Path(local) / "Jarvis"
    return repo_root()


def is_safe_jarvis_install_dir(path: Path) -> bool:
    candidate = path.resolve()
    default = default_install_dir().resolve()
    if candidate == default:
        return True
    return (
        (candidate / "start-jarvis.ps1").is_file()
        and (candidate / "unins000.exe").is_file()
        and (candidate / "installer" / "windows" / "Jarvis.iss").is_file()
    )


def is_under_jarvis_owned_root(child: Path, root: Path) -> bool:
    try:
        child.resolve().relative_to(root.resolve())
        return True
    except ValueError:
        return False


def blocked_owner_roots() -> list[Path]:
    home = Path.home()
    blocked: list[Path] = [home]
    for env_name in ("USERPROFILE", "LOCALAPPDATA"):
        value = os.environ.get(env_name)
        if value:
            blocked.append(Path(value))
    for getter in ("Desktop", "MyDocuments", "Downloads"):
        try:
            import ctypes
            from ctypes import wintypes

            if sys.platform != "win32":
                break
            buf = ctypes.create_unicode_buffer(260)
            # CSIDL constants
            csidl = {"Desktop": 0, "MyDocuments": 5, "Downloads": 0x10}.get(getter, -1)
            if csidl >= 0 and ctypes.windll.shell32.SHGetFolderPathW(None, csidl, None, 0, buf) == 0:
                blocked.append(Path(buf.value))
        except Exception:
            pass
    unique: list[Path] = []
    for item in blocked:
        try:
            resolved = item.resolve()
        except OSError:
            continue
        if resolved not in unique:
            unique.append(resolved)
    return unique


def path_is_blocked_owner_root(path: Path) -> bool:
    try:
        norm = path.resolve()
    except OSError:
        return True
    for blocked in blocked_owner_roots():
        if norm == blocked:
            return True
    return False


def resolve_install_root(explicit: str | None = None) -> Path:
    if explicit:
        candidate = Path(explicit)
        if candidate.exists():
            return candidate.resolve()
    root = repo_root()
    if is_safe_jarvis_install_dir(root):
        return root.resolve()
    default = default_install_dir()
    if default.exists():
        return default.resolve()
    return default


def license_issuer_preserve_path(install_root: Path) -> Path:
    return install_root / LICENSE_ISSUER_LEAF


def registered_owned_roots(
    *,
    install_root: Path | None = None,
    extra_data_dir: Path | None = None,
) -> list[Path]:
    """Return only allowlisted roots safe to wipe. Never includes allowed_directories."""
    install = install_root or resolve_install_root()
    roots: list[Path] = []
    if is_safe_jarvis_install_dir(install):
        roots.append(install.resolve())

    data_path = extra_data_dir or data_dir()
    if roots and is_under_jarvis_owned_root(data_path, roots[0]):
        if data_path.resolve() not in roots:
            roots.append(data_path.resolve())

    safe_roots: list[Path] = []
    for root in roots:
        if path_is_blocked_owner_root(root):
            continue
        if not is_safe_jarvis_install_dir(install) and root == install:
            continue
        safe_roots.append(root)
    return safe_roots


def owned_paths_preview() -> dict[str, object]:
    install = resolve_install_root()
    roots = registered_owned_roots(install_root=install)
    script = repo_root() / "installer" / "windows" / "clean-reinstall-jarvis.ps1"
    force_stop = repo_root() / "installer" / "windows" / "force-stop-jarvis.ps1"
    setup_candidates = [
        install / "installer" / "windows" / "dist" / "JarvisSetup.exe",
        repo_root() / "installer" / "windows" / "dist" / "JarvisSetup.exe",
    ]
    setup_path = next((p for p in setup_candidates if p.is_file()), None)
    return {
        "install_root": str(install),
        "owned_roots": [str(p) for p in roots],
        "license_issuer_preserved": str(license_issuer_preserve_path(install)),
        "setup_exe": str(setup_path) if setup_path else "",
        "helper_script": str(script),
        "force_stop_script": str(force_stop),
        "windows_only": sys.platform == "win32",
        "safe_install_dir": is_safe_jarvis_install_dir(install),
    }
