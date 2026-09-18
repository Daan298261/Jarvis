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


def _label_for_owned_root(root: Path, install: Path) -> tuple[str, str]:
    root_s = str(root.resolve())
    install_s = str(install.resolve())
    if root_s.lower() == install_s.lower():
        return (
            "install_root",
            "Jarvis install folder — application, models, chats, logs, and other Jarvis-owned data",
        )
    data_default = install / "data"
    if root.resolve() == data_default.resolve():
        return (
            "data_directory",
            "Jarvis data directory (settings, chats DB, projects under install\\data)",
        )
    return (
        "additional_owned_root",
        "Additional Jarvis-owned directory recorded at install",
    )


def build_owned_root_entries(install: Path, roots: list[Path]) -> list[dict[str, str]]:
    entries: list[dict[str, str]] = []
    for root in roots:
        entry_id, label = _label_for_owned_root(root, install)
        entries.append({"id": entry_id, "path": str(root), "label": label})
    return entries


def log_paths_for_install(install: Path | None = None) -> dict[str, str]:
    root = install or resolve_install_root()
    temp = Path(os.environ.get("TEMP") or os.environ.get("TMP") or "/tmp")
    return {
        "durable": str(temp / "Jarvis-clean-reinstall.log"),
        "install": str(root / "logs" / "clean-reinstall.log"),
        "status": str(temp / "Jarvis-clean-reinstall.status.json"),
    }


def owned_paths_preview() -> dict[str, object]:
    from .confirm_token import issue_confirm_token

    install = resolve_install_root()
    roots = registered_owned_roots(install_root=install)
    entries = build_owned_root_entries(install, roots)
    paths = [entry["path"] for entry in entries]
    confirm_token, expires_at = issue_confirm_token(paths)
    script = repo_root() / "installer" / "windows" / "clean-reinstall-jarvis.ps1"
    force_stop = repo_root() / "installer" / "windows" / "force-stop-jarvis.ps1"
    setup_candidates = [
        install / "installer" / "windows" / "dist" / "JarvisSetup.exe",
        repo_root() / "installer" / "windows" / "dist" / "JarvisSetup.exe",
    ]
    setup_path = next((p for p in setup_candidates if p.is_file()), None)
    safe = is_safe_jarvis_install_dir(install)
    windows = sys.platform == "win32"
    return {
        "action_available": bool(windows and safe and entries),
        "install_root": str(install),
        "confirm_token": confirm_token,
        "confirm_token_expires_at": expires_at,
        "owned_root_entries": entries,
        "owned_roots": paths,
        "license_issuer_preserved": str(license_issuer_preserve_path(install)),
        "preserved_note": "Vendor license-issuer folder is not deleted.",
        "setup_exe": str(setup_path) if setup_path else "",
        "helper_script": str(script),
        "force_stop_script": str(force_stop),
        "log_paths": log_paths_for_install(install),
        "windows_only": windows,
        "safe_install_dir": safe,
        "ux": {
            "requires_two_step_confirm": True,
            "post_start_poll_path": "/api/installer/clean-reinstall/status",
            "never_show_success_on_http_400": True,
            "post_start_means_helper_spawned_not_wipe_complete": True,
        },
    }
