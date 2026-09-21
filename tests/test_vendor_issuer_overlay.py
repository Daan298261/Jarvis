from pathlib import Path

from app.licensing.vendor_issuer import issuer_data_dir, load_or_create_vendor_keys, vendor_private_path


def test_issuer_dir_uses_gitignored_repo_overlay(tmp_path, monkeypatch):
    monkeypatch.delenv("JARVIS_LICENSE_ISSUER_DIR", raising=False)
    monkeypatch.delenv("LOCALAPPDATA", raising=False)
    monkeypatch.setattr("app.config.repo_root", lambda: tmp_path)
    target = issuer_data_dir()
    assert target == tmp_path / ".vendor" / "license-issuer"
    assert target.is_dir()
    load_or_create_vendor_keys()
    assert vendor_private_path().is_file()
    assert (target / "issuer.pub").is_file()


def test_issuer_dir_env_override_wins(tmp_path, monkeypatch):
    override = tmp_path / "custom-issuer"
    monkeypatch.setenv("JARVIS_LICENSE_ISSUER_DIR", str(override))
    assert issuer_data_dir() == override
