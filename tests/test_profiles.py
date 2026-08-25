from pathlib import Path

from app.inference.backends import LlamaCppBackend
from app.inference.profiles import (
    PRIMARY_GGUF_REPO,
    PROFILES,
    declared_profiles,
    profile_gguf,
    resolve_profile,
)


def test_default_profiles_are_nine_b_abliterated():
    names = {p.name for p in declared_profiles()}
    assert names == {"fast", "balanced", "quality", "expert"}
    for name in ("fast", "balanced", "quality"):
        profile = PROFILES[name]
        assert profile.family == "9b-abliterated"
        assert profile.alias == "Qwen3.5-9B"
        assert profile.repo == PRIMARY_GGUF_REPO
        assert "9B-abliterated" in profile.filename


def test_expert_keeps_twenty_seven_b():
    expert = PROFILES["expert"]
    assert expert.family == "27b"
    assert expert.alias == "Qwen3.5-27B"
    assert expert.filename == "Qwen3.5-27B-Q4_K_M.gguf"
    assert expert.thinking_mode == "on"


def test_balanced_is_selective_thinking_32k_cap():
    balanced = resolve_profile("balanced")
    assert balanced.thinking_mode == "selective"
    assert balanced.thinking is True
    assert balanced.context_size == 32768
    assert resolve_profile("fast").thinking_mode == "off"
    assert resolve_profile("fast").context_size == 8192
    assert resolve_profile("reliable").name == "quality"


def test_resolve_falls_back_to_installed_weights(tmp_path, monkeypatch):
    from app.inference import profiles as profiles_mod

    root = tmp_path / "models"
    monkeypatch.setattr(profiles_mod, "models_dir", lambda: root)
    expert_file = root / "Qwen3.5-27B-GGUF" / "Qwen3.5-27B-Q4_K_M.gguf"
    expert_file.parent.mkdir(parents=True)
    expert_file.write_bytes(b"gguf")
    resolved = profiles_mod.resolve_profile("balanced")
    assert resolved.name == "balanced"
    assert resolved.family == "27b"
    assert resolved.filename.endswith("Q4_K_M.gguf")
    assert profile_gguf(resolved) == expert_file


def test_llama_cpp_omits_mmproj_unless_vision_enabled():
    from app.config import AppSettings

    profile = resolve_profile("balanced")
    backend = LlamaCppBackend(AppSettings(inference={"vision": False, "fit": False}))
    args = backend.build_args(profile)
    assert "--mmproj" not in args
    assert args[args.index("--alias") + 1] == profile.alias
    assert args[args.index("--ctx-size") + 1] == str(profile.context_size)

    with_vision = LlamaCppBackend(AppSettings(inference={"vision": True, "fit": False})).build_args(profile)
    # Projector file is not present in this environment, so it still must not be attached.
    assert "--mmproj" not in with_vision


def test_profile_gguf_lives_under_family_directory():
    balanced = PROFILES["balanced"]
    path = profile_gguf(balanced)
    assert isinstance(path, Path)
    assert path.name == "Qwen3.5-9B-abliterated-Q8_0.gguf"
    assert "Qwen3.5-9B-abliterated-GGUF" in str(path)


def test_unloaded_snapshot_uses_profile_context():
    import asyncio

    from app.config import AppSettings
    from app.inference.manager import InferenceManager

    mgr = InferenceManager()
    settings = AppSettings()

    async def _run():
        snap = await mgr.snapshot(settings)
        assert snap["loaded"] is False
        assert snap["family"] == "9b-abliterated"
        assert snap["thinking_mode"] == "selective"
        assert snap["context_size"] == 16384
        assert snap["vision"] is False
        assert {p["name"] for p in snap["profiles"]} == {"fast", "balanced", "quality", "expert"}

    asyncio.run(_run())
