from __future__ import annotations

from pathlib import Path

from app.inference import model_discovery as md


def test_scan_finds_gguf_in_models_dir(tmp_path, monkeypatch):
    monkeypatch.setattr(md, "models_dir", lambda: tmp_path / "models")
    root = tmp_path / "models" / "custom"
    root.mkdir(parents=True)
    gguf = root / "Test-9B-Q4_K_M.gguf"
    gguf.write_bytes(b"x" * 1024)
    monkeypatch.setattr(md, "standard_scan_roots", lambda **_: [root])
    payload = md.scan_local_ggufs(deep=False)
    paths = {row["path"] for row in payload["models"]}
    assert str(gguf.resolve()) in paths


def test_register_discovered_paths(tmp_path, monkeypatch):
    registry = tmp_path / "discovered.json"
    monkeypatch.setattr(md, "_registry_path", lambda: registry)
    gguf = tmp_path / "MiMo-V2.6-Distill-Qwen-9B-Q4_K_M.gguf"
    gguf.write_bytes(b"gguf")
    monkeypatch.setattr(
        "app.inference.model_discovery.create_runtime_profile",
        lambda **kwargs: None,
    )
    result = md.register_discovered_paths([str(gguf)])
    assert len(result["added"]) == 1
    assert md.list_registered_ggufs()[0].path == str(gguf.resolve())
