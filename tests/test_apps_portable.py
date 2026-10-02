from __future__ import annotations

import os
from pathlib import Path

import pytest

from app.tools.apps import find_apps, launch_app, resolve_app


def _isolate_catalog(monkeypatch, roots: list[tuple[Path, int]]) -> None:
    monkeypatch.setattr("app.tools.apps._shortcuts", lambda: [])
    monkeypatch.setattr("app.tools.apps._uwp_apps", lambda: [])
    monkeypatch.setattr("app.tools.apps._app_paths", lambda _query: None)
    monkeypatch.setattr("app.tools.apps.shutil.which", lambda _name: None)
    monkeypatch.setattr("app.tools.apps._portable_search_roots", lambda: list(roots))


def test_resolve_portable_exe_on_extra_drive(tmp_path, monkeypatch):
    extra = tmp_path / "E" / "PortableApps" / "CoolTool"
    extra.mkdir(parents=True)
    exe = extra / "cooltool.exe"
    exe.write_bytes(b"MZ")
    _isolate_catalog(monkeypatch, [(tmp_path / "E" / "PortableApps", 3)])
    target = resolve_app("cooltool")
    assert target is not None
    assert target.kind == "exe"
    assert Path(target.target) == exe


def test_resolve_desktop_shortcut(tmp_path, monkeypatch):
    desktop = tmp_path / "Desktop"
    desktop.mkdir()
    link = desktop / "JarvisPortableEditor.lnk"
    link.write_text("stub", encoding="utf-8")
    _isolate_catalog(monkeypatch, [(desktop, 2)])
    target = resolve_app("jarvisportableeditor")
    assert target is not None
    assert target.kind == "shortcut"
    assert Path(target.target) == link


def test_resolve_steam_on_extra_program_files(tmp_path, monkeypatch):
    steam = tmp_path / "D" / "Program Files (x86)" / "Steam"
    steam.mkdir(parents=True)
    exe = steam / "steam.exe"
    exe.write_bytes(b"MZ")
    _isolate_catalog(monkeypatch, [(tmp_path / "D" / "Program Files (x86)", 3)])
    target = resolve_app("steam")
    assert target is not None
    assert target.kind == "exe"
    assert Path(target.target) == exe


def test_skips_windowsapps_tree(tmp_path, monkeypatch):
    drive = tmp_path / "F"
    hidden = drive / "WindowsApps" / "CoolTool"
    hidden.mkdir(parents=True)
    (hidden / "cooltool.exe").write_bytes(b"MZ")
    _isolate_catalog(monkeypatch, [(drive, 2)])
    assert resolve_app("cooltool") is None


def test_find_apps_includes_portable(tmp_path, monkeypatch):
    extra = tmp_path / "E" / "PortableApps" / "CoolTool"
    extra.mkdir(parents=True)
    (extra / "cooltool.exe").write_bytes(b"MZ")
    _isolate_catalog(monkeypatch, [(tmp_path / "E" / "PortableApps", 3)])
    result = find_apps("cooltool")
    assert result.success
    assert any("cooltool" in name.lower() for name in result.data["apps"])


@pytest.mark.skipif(os.name == "nt", reason="POSIX extra-mount roots")
def test_portable_search_roots_skips_posix_slash(tmp_path, monkeypatch):
    usb = tmp_path / "usb"
    usb.mkdir()
    monkeypatch.setattr("app.config._posix_owner_roots", lambda: [Path("/"), usb])
    from app.tools.apps import _portable_search_roots

    roots = [path for path, _depth in _portable_search_roots()]
    assert usb in roots
    assert Path("/") not in roots


@pytest.mark.asyncio
async def test_launch_error_mentions_extra_drives(monkeypatch):
    monkeypatch.setattr("app.tools.apps.resolve_app", lambda _name: None)
    result = await launch_app("no-such-app-xyz")
    assert not result.success
    assert "PortableApps" in result.error
    assert "Desktop" in result.error
