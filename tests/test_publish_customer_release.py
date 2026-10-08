"""Customer deliverables land in the gitignored repo release/ folder."""
from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]


def _load():
    source = REPO / "scripts" / "publish_customer_release.py"
    spec = importlib.util.spec_from_file_location("publish_customer_release", source)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_publish_file_copies_customer_set_and_refuses_archives(tmp_path):
    module = _load()
    src = tmp_path / "in"
    dest = tmp_path / "release"
    src.mkdir()
    apk = src / "JarvisCompanion-generic-9.apk"
    lic = src / "Jarvis-unrestricted.jarvis-license"
    setup = src / "JarvisSetup.exe"
    apk.write_bytes(b"apk")
    lic.write_bytes(b"lic")
    setup.write_bytes(b"exe")

    published = [
        module.publish_file(apk, release_dir=dest),
        module.publish_file(lic, release_dir=dest),
        module.publish_file(setup, release_dir=dest),
    ]
    assert [path.name for path in published] == [
        "JarvisCompanion-generic-9.apk",
        "Jarvis-unrestricted.jarvis-license",
        "JarvisSetup.exe",
    ]
    assert (dest / "JarvisSetup.exe").read_bytes() == b"exe"
    assert apk.read_bytes() == b"apk"

    renamed = module.publish_file(apk, name="JarvisCompanion.apk", release_dir=dest)
    assert renamed.name == "JarvisCompanion.apk"
    assert renamed.read_bytes() == b"apk"

    archive = src / "jarvis-source.tar.gz"
    archive.write_bytes(b"src")
    with pytest.raises(ValueError, match="non-customer"):
        module.publish_file(archive, release_dir=dest)
    zipped = src / "portal.zip"
    zipped.write_bytes(b"zip")
    with pytest.raises(ValueError, match="non-customer"):
        module.publish_file(zipped, name="JarvisCompanion.apk", release_dir=dest)
    assert not (dest / "jarvis-source.tar.gz").exists()
    assert not (dest / "portal.zip").exists()


def test_cli_publishes_one_apk(tmp_path, monkeypatch):
    module = _load()
    apk = tmp_path / "app-release.apk"
    apk.write_bytes(b"apk-bytes")
    release = tmp_path / "out"
    monkeypatch.setattr(module, "RELEASE_DIR", release)
    assert module.main(["--source", str(apk), "--as", "JarvisCompanion.apk"]) == 0
    assert (release / "JarvisCompanion.apk").read_bytes() == b"apk-bytes"
