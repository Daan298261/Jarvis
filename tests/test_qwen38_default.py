from pathlib import Path

from app.inference.qwen38_local import (
    discover_qwen38_27b_heretic,
    discover_qwen38_9b_uncensored,
    is_qwen38_27b_heretic_path,
    is_qwen38_9b_filename,
    is_uncensored_filename,
    should_prefer_qwen38_default,
)


def test_filename_matches_qwen38_9b_and_3m8_alias():
    assert is_qwen38_9b_filename("Qwen3.8-9B-Uncensored-Q4_K_M.gguf")
    assert is_qwen38_9b_filename("qwen 3m8 9b uncensored.gguf")
    assert is_qwen38_9b_filename("Qwen3_8_9B-abliterated-Q8_0.gguf")
    assert not is_qwen38_9b_filename("Qwen3.8-27B-TurboFCFusion-Q4.gguf")
    assert not is_qwen38_9b_filename("mmproj-Qwen3.8-9B.gguf")
    assert not is_qwen38_9b_filename("Qwen3.5-9B-abliterated-Q8_0.gguf")


def test_uncensored_tags():
    assert is_uncensored_filename("Qwen3.8-9B-Uncensored-Q4.gguf")
    assert is_uncensored_filename("Qwen3.8-9B-abliterated-Q6_K.gguf")
    assert is_uncensored_filename("Qwen3.8-9B-Defiant-Q4.gguf")
    assert not is_uncensored_filename("Qwen3.8-9B-Instruct-Q4.gguf")


def test_discover_prefers_uncensored(tmp_path, monkeypatch):
    from app.inference import qwen38_local as mod

    models = tmp_path / "models"
    lm = tmp_path / "lmstudio"
    models.mkdir()
    lm.mkdir()
    (models / "Qwen3.8-9B-Instruct-Q4_K_M.gguf").write_bytes(b"gguf")
    (lm / "Qwen3.8-9B-Uncensored-Q8_0.gguf").write_bytes(b"gguf")
    monkeypatch.setattr(mod, "models_dir", lambda: models)
    monkeypatch.setattr(mod, "_lmstudio_root", lambda: lm)

    found = discover_qwen38_9b_uncensored()
    assert found is not None
    assert found.uncensored is True
    assert found.filename.startswith("Qwen3.8-9B-Uncensored")


def test_prefer_default_skips_expert_pin():
    assert should_prefer_qwen38_default("balanced") is True
    assert should_prefer_qwen38_default("fast") is True
    assert should_prefer_qwen38_default("expert") is False
    assert should_prefer_qwen38_default("ornith_9b") is False
    assert should_prefer_qwen38_default("lm-best-overall") is False


def test_preferred_startup_profile_uses_discovered(tmp_path, monkeypatch):
    from app.inference import profiles as profiles_mod
    from app.inference import qwen38_local as local_mod

    models = tmp_path / "models"
    models.mkdir()
    gguf = models / "Qwen3.8-9B-Uncensored-Q4_K_M.gguf"
    gguf.write_bytes(b"gguf")
    monkeypatch.setattr(local_mod, "models_dir", lambda: models)
    monkeypatch.setattr(local_mod, "_lmstudio_root", lambda: tmp_path / "missing-lm")
    monkeypatch.setattr(profiles_mod, "models_dir", lambda: models)

    assert profiles_mod.preferred_startup_profile("balanced") == "qwen38_9b"
    resolved = profiles_mod.resolve_profile("qwen38_9b")
    assert resolved.name == "qwen38_9b"
    assert Path(resolved.absolute_path) == gguf
    assert profiles_mod.preferred_startup_profile("expert") == "expert"


def test_discovers_rvn_27b_from_parent_folder_and_resolves_internal_profile(tmp_path, monkeypatch):
    from app.inference import profiles as profiles_mod
    from app.inference import qwen38_local as local_mod

    models = tmp_path / "models"
    folder = models / "Qwen3.8-27B-Heretic-Abliterated-Uncensored-GGUF"
    folder.mkdir(parents=True)
    gguf = folder / "RVN-Q3_K_S-multilingual.gguf"
    gguf.write_bytes(b"gguf")
    monkeypatch.setattr(local_mod, "models_dir", lambda: models)
    monkeypatch.setattr(local_mod, "_lmstudio_root", lambda: tmp_path / "missing-lm")
    monkeypatch.setattr(profiles_mod, "models_dir", lambda: models)

    assert is_qwen38_27b_heretic_path(gguf)
    found = discover_qwen38_27b_heretic()
    assert found is not None
    assert found.path == gguf
    resolved = profiles_mod.resolve_profile("qwen38_27b_heretic")
    assert resolved.name == "qwen38_27b_heretic"
    assert resolved.context_size == 8192
    assert resolved.thinking is True
