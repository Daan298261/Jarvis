"""Owner extra-drive discovery for LE-gated clones (no username paths)."""
from __future__ import annotations

from pathlib import Path

from app.modules import catalog_download, cybersecurity


def test_le_gated_roots_cover_extra_volume_not_username(tmp_path, monkeypatch):
    extra = tmp_path / "USB"
    extra.mkdir()
    monkeypatch.setattr("app.config.extra_volume_roots", lambda: [extra])
    roots = catalog_download.le_gated_roots()
    blob = "\n".join(str(path) for path in roots).lower()
    assert "daanv" not in blob
    assert extra / "le-gated" in roots
    assert extra / "projects" / "le-gated" in roots
    assert extra / "jarvis-ig" / "le-gated" in roots


def test_discover_finds_extra_volume_le_gated(tmp_path, monkeypatch):
    extra = tmp_path / "USB"
    found_dir = extra / "le-gated" / "strix"
    found_dir.mkdir(parents=True)
    monkeypatch.setattr("app.config.extra_volume_roots", lambda: [extra])
    monkeypatch.setattr("app.modules.cybersecurity.data_dir", lambda: tmp_path)
    monkeypatch.setattr("app.modules.catalog_download.data_dir", lambda: tmp_path)
    monkeypatch.setattr("app.modules.catalog_download.repo_root", lambda: tmp_path / "repo")
    monkeypatch.setattr("app.modules.cybersecurity.repo_root", lambda: tmp_path / "repo")
    found = cybersecurity.discover_local_path("strix")
    assert found == found_dir.resolve()


def test_owner_project_roots_include_usb_projects(tmp_path, monkeypatch):
    extra = tmp_path / "E"
    (extra / "projects").mkdir(parents=True)
    monkeypatch.setattr("app.config.extra_volume_roots", lambda: [extra])
    roots = catalog_download.owner_project_roots()
    assert extra / "projects" in roots
    assert extra / "Jarvis" / "projects" in roots


def test_dest_auto_uses_extra_when_library_volume_is_full(tmp_path, monkeypatch):
    from types import SimpleNamespace

    extra = tmp_path / "USB"
    extra.mkdir()
    lib = tmp_path / "projects"
    lib.mkdir()
    monkeypatch.setattr("app.config.extra_volume_roots", lambda: [extra])
    monkeypatch.setattr("app.modules.catalog_download.catalog_library_root", lambda: lib)

    def fake_usage(path):
        text = str(path)
        if str(extra) in text:
            return SimpleNamespace(free=200 * 1024**3, total=500 * 1024**3, used=0)
        return SimpleNamespace(free=100 * 1024**2, total=20 * 1024**3, used=19 * 1024**3)

    monkeypatch.setattr("app.modules.catalog_download.shutil.disk_usage", fake_usage)
    assert catalog_download.preferred_catalog_dest() == "extra"
    root = catalog_download._dest_root("auto")
    assert root == extra / "Jarvis" / "projects"


def test_dest_auto_stays_library_when_repo_volume_fits(tmp_path, monkeypatch):
    from types import SimpleNamespace

    extra = tmp_path / "USB"
    extra.mkdir()
    lib = tmp_path / "projects"
    lib.mkdir()
    monkeypatch.setattr("app.config.extra_volume_roots", lambda: [extra])
    monkeypatch.setattr("app.modules.catalog_download.catalog_library_root", lambda: lib)
    monkeypatch.setattr(
        "app.modules.catalog_download.shutil.disk_usage",
        lambda path: SimpleNamespace(free=200 * 1024**3, total=500 * 1024**3, used=0),
    )
    assert catalog_download.preferred_catalog_dest() == "library"
    root = catalog_download._dest_root("auto")
    assert root == lib
