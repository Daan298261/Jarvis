"""RFC-0124 owned-path allowlist tests (no Windows required)."""

from pathlib import Path

from app.installer.owned_paths import (
    is_safe_jarvis_install_dir,
    is_under_jarvis_owned_root,
    license_issuer_preserve_path,
    path_is_blocked_owner_root,
    registered_owned_roots,
)


def _fake_install(tmp_path: Path) -> Path:
    root = tmp_path / "Jarvis"
    root.mkdir()
    (root / "start-jarvis.ps1").write_text("", encoding="utf-8")
    (root / "unins000.exe").write_text("", encoding="utf-8")
    iss_dir = root / "installer" / "windows"
    iss_dir.mkdir(parents=True)
    (iss_dir / "Jarvis.iss").write_text("; stub", encoding="utf-8")
    return root


def test_safe_gate_rejects_random_directory(tmp_path):
    random_dir = tmp_path / "not-jarvis"
    random_dir.mkdir()
    assert not is_safe_jarvis_install_dir(random_dir)


def test_registered_roots_never_include_profile_root(tmp_path):
    install = _fake_install(tmp_path)
    home = Path.home()
    roots = registered_owned_roots(install_root=install)
    assert install.resolve() in roots
    assert home.resolve() not in roots
    assert path_is_blocked_owner_root(home)


def test_allowed_directories_outside_install_are_not_owned(tmp_path):
    install = _fake_install(tmp_path)
    external = tmp_path / "owner-git-project"
    external.mkdir()
    roots = registered_owned_roots(install_root=install)
    assert external.resolve() not in roots


def test_data_under_install_is_owned(tmp_path):
    install = _fake_install(tmp_path)
    data = install / "data"
    data.mkdir()
    roots = registered_owned_roots(install_root=install, extra_data_dir=data)
    assert data.resolve() in roots
    assert is_under_jarvis_owned_root(data / "projects" / "x", install)


def test_license_issuer_path_under_install(tmp_path):
    install = _fake_install(tmp_path)
    issuer = license_issuer_preserve_path(install)
    assert issuer.name == "license-issuer"
    assert is_under_jarvis_owned_root(issuer, install)
