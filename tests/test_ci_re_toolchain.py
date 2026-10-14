"""The CI fetcher for the RFC-0207 real-toolchain tests verifies every artifact against engine-lock.json."""
import hashlib
import importlib.util
import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / ".github" / "scripts" / "fetch_re_toolchain.py"
LOCK = ROOT / "backend" / "app" / "reverse_engineering" / "engine-lock.json"
WORKFLOW = ROOT / ".github" / "workflows" / "pr-tests.yml"


def _load():
    spec = importlib.util.spec_from_file_location("fetch_re_toolchain", SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_fetch_accepts_matching_hash_and_reuses_cached_file(tmp_path):
    mod = _load()
    src = tmp_path / "apktool_9.9.jar"
    src.write_bytes(b"pinned bytes")
    spec = {"version": "9.9", "url": src.as_uri(), "sha256": hashlib.sha256(b"pinned bytes").hexdigest()}
    first = mod.fetch(tmp_path / "root", "apktool", spec)
    assert first.read_bytes() == b"pinned bytes"
    src.unlink()  # a cached, verified file is reused without downloading
    assert mod.fetch(tmp_path / "root", "apktool", spec) == first


def test_fetch_rejects_hash_mismatch_and_poisoned_cache(tmp_path):
    mod = _load()
    src = tmp_path / "jadx-9.9.zip"
    src.write_bytes(b"tampered")
    spec = {"version": "9.9", "url": src.as_uri(), "sha256": "0" * 64}
    with pytest.raises(SystemExit, match="does not match engine-lock.json"):
        mod.fetch(tmp_path / "root", "jadx", spec)
    assert not (tmp_path / "root" / "downloads" / "jadx-9.9.zip").exists()


def test_ci_uses_the_locked_toolchain_and_forbids_skips():
    lock = json.loads(LOCK.read_text(encoding="utf-8"))
    assert all(lock[k]["sha256"] for k in ("jdk", "apktool", "jadx"))
    assert lock["jdk"]["version"].startswith("21.")
    wf = WORKFLOW.read_text(encoding="utf-8")
    assert "fetch_re_toolchain.py" in wf and "hashFiles('backend/app/reverse_engineering/engine-lock.json')" in wf
    assert "grep -q SKIPPED" in wf
