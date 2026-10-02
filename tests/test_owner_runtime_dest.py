"""Extra-drive install dest for HexStrike / Crucix / Supermemory sidecars."""
from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from app import config
from app.modules import crucix_runtime, supermemory_runtime
from app.security.hexstrike import candidate_install_roots, resolve_install
from app.security.hexstrike_install import HexStrikeInstaller


def _full_local_usage(path, extra: Path):
    text = str(path)
    if str(extra) in text:
        return SimpleNamespace(free=200 * 1024**3, total=500 * 1024**3, used=0)
    return SimpleNamespace(free=100 * 1024**2, total=20 * 1024**3, used=19 * 1024**3)


def _plenty_usage(_path):
    return SimpleNamespace(free=200 * 1024**3, total=500 * 1024**3, used=0)


def test_preferred_runtime_install_dir_uses_extra_when_repo_volume_is_full(tmp_path, monkeypatch):
    repo = tmp_path / "repo"
    extra = tmp_path / "USB"
    repo.mkdir()
    extra.mkdir()
    monkeypatch.setattr(config, "repo_root", lambda: repo)
    monkeypatch.setattr(config, "extra_volume_roots", lambda: [extra])
    monkeypatch.setattr(config.shutil, "disk_usage", lambda path: _full_local_usage(path, extra))
    dest = config.preferred_runtime_install_dir("hexstrike-ai")
    assert dest == extra / "Jarvis" / "runtime" / "hexstrike-ai"
    local = config.preferred_runtime_install_dir("hexstrike-ai", need_bytes=512)
    assert local == repo / "runtime" / "hexstrike-ai"


def test_preferred_runtime_install_dir_stays_local_when_repo_volume_fits(tmp_path, monkeypatch):
    repo = tmp_path / "repo"
    extra = tmp_path / "USB"
    repo.mkdir()
    extra.mkdir()
    monkeypatch.setattr(config, "repo_root", lambda: repo)
    monkeypatch.setattr(config, "extra_volume_roots", lambda: [extra])
    monkeypatch.setattr(config.shutil, "disk_usage", _plenty_usage)
    dest = config.preferred_runtime_install_dir("crucix")
    assert dest == repo / "runtime" / "crucix"


def test_discover_named_runtime_dir_finds_extra_volume_checkout(tmp_path, monkeypatch):
    repo = tmp_path / "repo"
    extra = tmp_path / "USB"
    found = extra / "Jarvis" / "runtime" / "hexstrike-ai"
    found.mkdir(parents=True)
    (found / "hexstrike_server.py").write_text("# extra\n", encoding="utf-8")
    monkeypatch.setattr(config, "repo_root", lambda: repo)
    monkeypatch.setattr(config, "extra_volume_roots", lambda: [extra])
    assert config.discover_named_runtime_dir("hexstrike-ai", marker="hexstrike_server.py") == found


def test_hexstrike_default_path_uses_extra_when_os_volume_is_full(tmp_path, monkeypatch):
    repo = tmp_path / "repo"
    extra = tmp_path / "USB"
    repo.mkdir()
    extra.mkdir()
    monkeypatch.delenv("JARVIS_HEXSTRIKE_HOME", raising=False)
    monkeypatch.setattr(config, "repo_root", lambda: repo)
    monkeypatch.setattr(config, "extra_volume_roots", lambda: [extra])
    monkeypatch.setattr(config.shutil, "disk_usage", lambda path: _full_local_usage(path, extra))
    monkeypatch.setattr(
        "app.security.hexstrike_install.load_settings",
        lambda: SimpleNamespace(hexstrike=SimpleNamespace(install_path="")),
    )
    dest = HexStrikeInstaller().default_path()
    assert dest == extra / "Jarvis" / "runtime" / "hexstrike-ai"


def test_hexstrike_default_path_keeps_existing_saved_install(tmp_path, monkeypatch):
    saved = tmp_path / "custom" / "hexstrike-ai"
    saved.mkdir(parents=True)
    extra = tmp_path / "USB"
    extra.mkdir()
    monkeypatch.delenv("JARVIS_HEXSTRIKE_HOME", raising=False)
    monkeypatch.setattr(config, "extra_volume_roots", lambda: [extra])
    monkeypatch.setattr(
        "app.security.hexstrike_install.load_settings",
        lambda: SimpleNamespace(hexstrike=SimpleNamespace(install_path=str(saved))),
    )
    dest = HexStrikeInstaller().default_path()
    assert dest == saved


def test_hexstrike_resolve_finds_extra_volume_checkout(tmp_path, monkeypatch):
    repo = tmp_path / "repo"
    extra = tmp_path / "E"
    repo.mkdir()
    found = extra / "Jarvis" / "runtime" / "hexstrike-ai"
    found.mkdir(parents=True)
    (found / "hexstrike_server.py").write_text("# extra\n", encoding="utf-8")
    monkeypatch.delenv("JARVIS_HEXSTRIKE_HOME", raising=False)
    monkeypatch.setattr("app.security.hexstrike.repo_root", lambda: repo)
    monkeypatch.setattr(config, "extra_volume_roots", lambda: [extra])
    roots = candidate_install_roots()
    assert found.resolve() in roots
    assert resolve_install() == found.resolve()


def test_crucix_install_dir_uses_extra_when_os_volume_is_full(tmp_path, monkeypatch):
    repo = tmp_path / "repo"
    extra = tmp_path / "USB"
    repo.mkdir()
    extra.mkdir()
    monkeypatch.setattr(config, "repo_root", lambda: repo)
    monkeypatch.setattr(config, "extra_volume_roots", lambda: [extra])
    monkeypatch.setattr(config.shutil, "disk_usage", lambda path: _full_local_usage(path, extra))
    assert crucix_runtime.install_dir() == extra / "Jarvis" / "runtime" / "crucix"


def test_crucix_install_dir_discovers_existing_extra_checkout(tmp_path, monkeypatch):
    repo = tmp_path / "repo"
    extra = tmp_path / "USB"
    found = extra / "Jarvis" / "runtime" / "crucix"
    found.mkdir(parents=True)
    (found / "package.json").write_text("{}", encoding="utf-8")
    monkeypatch.setattr(config, "repo_root", lambda: repo)
    monkeypatch.setattr(config, "extra_volume_roots", lambda: [extra])
    monkeypatch.setattr(config.shutil, "disk_usage", _plenty_usage)
    assert crucix_runtime.install_dir() == found


def test_supermemory_install_dir_uses_extra_when_os_volume_is_full(tmp_path, monkeypatch):
    repo = tmp_path / "repo"
    extra = tmp_path / "USB"
    repo.mkdir()
    extra.mkdir()
    monkeypatch.setattr(config, "repo_root", lambda: repo)
    monkeypatch.setattr(config, "extra_volume_roots", lambda: [extra])
    monkeypatch.setattr(config.shutil, "disk_usage", lambda path: _full_local_usage(path, extra))
    assert supermemory_runtime.install_dir() == extra / "Jarvis" / "runtime" / "supermemory"


def test_supermemory_install_dir_discovers_existing_extra_binary(tmp_path, monkeypatch):
    repo = tmp_path / "repo"
    extra = tmp_path / "USB"
    found = extra / "runtime" / "supermemory"
    found.mkdir(parents=True)
    (found / "supermemory-server.exe").write_bytes(b"")
    monkeypatch.setattr(config, "repo_root", lambda: repo)
    monkeypatch.setattr(config, "extra_volume_roots", lambda: [extra])
    monkeypatch.setattr(config.shutil, "disk_usage", _plenty_usage)
    assert supermemory_runtime.install_dir() == found
    assert supermemory_runtime.binary_path() == found / "supermemory-server.exe"


def test_runtime_dir_uses_extra_when_os_volume_is_full(tmp_path, monkeypatch):
    repo = tmp_path / "repo"
    extra = tmp_path / "USB"
    repo.mkdir()
    extra.mkdir()
    monkeypatch.setattr(config, "repo_root", lambda: repo)
    monkeypatch.setattr(config, "extra_volume_roots", lambda: [extra])
    monkeypatch.setattr(config.shutil, "disk_usage", lambda path: _full_local_usage(path, extra))
    dest = config.runtime_dir()
    assert dest == extra / "Jarvis" / "runtime" / "llama.cpp"
    from app.runtime_install import _llama_exe

    assert _llama_exe() == dest / "llama-server.exe"


def test_runtime_dir_discovers_existing_extra_llama_server(tmp_path, monkeypatch):
    repo = tmp_path / "repo"
    extra = tmp_path / "USB"
    found = extra / "Jarvis" / "runtime" / "llama.cpp"
    found.mkdir(parents=True)
    (found / "llama-server.exe").write_bytes(b"")
    monkeypatch.setattr(config, "repo_root", lambda: repo)
    monkeypatch.setattr(config, "extra_volume_roots", lambda: [extra])
    monkeypatch.setattr(config.shutil, "disk_usage", _plenty_usage)
    assert config.runtime_dir() == found


def test_runtime_dir_stays_local_when_repo_volume_fits(tmp_path, monkeypatch):
    repo = tmp_path / "repo"
    extra = tmp_path / "USB"
    repo.mkdir()
    extra.mkdir()
    monkeypatch.setattr(config, "repo_root", lambda: repo)
    monkeypatch.setattr(config, "extra_volume_roots", lambda: [extra])
    monkeypatch.setattr(config.shutil, "disk_usage", _plenty_usage)
    assert config.runtime_dir() == repo / "runtime" / "llama.cpp"


def test_optional_worker_root_uses_extra_when_os_volume_is_full(tmp_path, monkeypatch):
    from app.workers import install as install_mod

    repo = tmp_path / "repo"
    extra = tmp_path / "USB"
    repo.mkdir()
    extra.mkdir()
    monkeypatch.setattr(config, "repo_root", lambda: repo)
    monkeypatch.setattr(config, "extra_volume_roots", lambda: [extra])
    monkeypatch.setattr(config.shutil, "disk_usage", lambda path: _full_local_usage(path, extra))
    root = install_mod._optional_worker_root()
    assert root == extra / "Jarvis" / "runtime" / "optional-workers"
    assert root.is_dir()


def test_optional_worker_root_discovers_existing_extra_ufo_clone(tmp_path, monkeypatch):
    from app.workers import install as install_mod

    repo = tmp_path / "repo"
    extra = tmp_path / "USB"
    found = extra / "Jarvis" / "runtime" / "optional-workers"
    head = found / "microsoft-ufo" / ".git"
    head.mkdir(parents=True)
    (head / "HEAD").write_text("ref: refs/heads/main\n", encoding="utf-8")
    monkeypatch.setattr(config, "repo_root", lambda: repo)
    monkeypatch.setattr(config, "extra_volume_roots", lambda: [extra])
    monkeypatch.setattr(config.shutil, "disk_usage", _plenty_usage)
    assert install_mod._optional_worker_root() == found


def test_discover_named_runtime_dir_joins_nested_marker(tmp_path, monkeypatch):
    repo = tmp_path / "repo"
    extra = tmp_path / "USB"
    found = extra / "runtime" / "optional-workers"
    head = found / "microsoft-ufo" / ".git"
    head.mkdir(parents=True)
    (head / "HEAD").write_text("ref: refs/heads/main\n", encoding="utf-8")
    monkeypatch.setattr(config, "repo_root", lambda: repo)
    monkeypatch.setattr(config, "extra_volume_roots", lambda: [extra])
    assert config.discover_named_runtime_dir("optional-workers", marker="microsoft-ufo/.git/HEAD") == found
