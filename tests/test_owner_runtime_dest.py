"""Extra-drive install dest for runtime sidecars, TTS caches, and Laya pins."""
from __future__ import annotations

import os
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


def test_kokoro_model_dir_uses_extra_when_os_volume_is_full(tmp_path, monkeypatch):
    from app.tts.kokoro_adapter import KokoroAdapter, resolved_kokoro_model_dir

    models = tmp_path / "models"
    extra = tmp_path / "USB"
    models.mkdir()
    extra.mkdir()
    monkeypatch.setattr(config, "models_dir", lambda: models)
    monkeypatch.setattr(config, "extra_volume_roots", lambda: [extra])
    monkeypatch.setattr(
        "app.inference.lmstudio_catalog.shutil.disk_usage",
        lambda path: _full_local_usage(path, extra),
    )
    dest = resolved_kokoro_model_dir()
    assert dest == extra / "Jarvis" / "models" / "tts" / "kokoro-82m"
    assert KokoroAdapter().model_dir == dest


def test_kokoro_model_dir_discovers_existing_extra_weights(tmp_path, monkeypatch):
    from app.tts.kokoro_adapter import resolved_kokoro_model_dir

    models = tmp_path / "models"
    extra = tmp_path / "USB"
    found = extra / "Jarvis" / "models" / "tts" / "kokoro-82m"
    found.mkdir(parents=True)
    (found / "config.json").write_text("{}", encoding="utf-8")
    monkeypatch.setattr(config, "models_dir", lambda: models)
    monkeypatch.setattr(config, "extra_volume_roots", lambda: [extra])
    monkeypatch.setattr("app.inference.lmstudio_catalog.shutil.disk_usage", _plenty_usage)
    assert resolved_kokoro_model_dir() == found


def test_ensure_kokoro_weights_downloads_to_extra_when_os_volume_is_full(tmp_path, monkeypatch):
    from app.tts import pack_install

    models = tmp_path / "models"
    extra = tmp_path / "USB"
    models.mkdir()
    extra.mkdir()
    monkeypatch.setattr(config, "models_dir", lambda: models)
    monkeypatch.setattr(config, "extra_volume_roots", lambda: [extra])
    monkeypatch.setattr(
        "app.inference.lmstudio_catalog.shutil.disk_usage",
        lambda path: _full_local_usage(path, extra),
    )
    monkeypatch.setattr("app.tts.pack_install.kokoro_weights_ready", lambda *_a, **_k: False)

    def fake_snapshot(*, repo_id, local_dir, **_kwargs):
        dest = Path(local_dir)
        dest.mkdir(parents=True, exist_ok=True)
        (dest / "config.json").write_text("{}", encoding="utf-8")
        return str(dest)

    monkeypatch.setattr("app.tts.pack_install.snapshot_download", fake_snapshot)
    monkeypatch.setattr(
        "app.policy.network_http.require_http_url_allowed",
        lambda *args, **kwargs: None,
    )
    dest = pack_install.ensure_kokoro_weights(force=True)
    assert dest == extra / "Jarvis" / "models" / "tts" / "kokoro-82m"
    assert (dest / ".jarvis_staged_ok").is_file()


def _clear_playwright_env(monkeypatch) -> None:
    monkeypatch.delenv("PLAYWRIGHT_BROWSERS_PATH", raising=False)
    monkeypatch.delenv("JARVIS_PLAYWRIGHT_BROWSERS", raising=False)


def test_playwright_browsers_dir_uses_extra_when_os_volume_is_full(tmp_path, monkeypatch):
    extra = tmp_path / "USB"
    extra.mkdir()
    _clear_playwright_env(monkeypatch)
    monkeypatch.setattr(config, "extra_volume_roots", lambda: [extra])
    monkeypatch.setattr(config.shutil, "disk_usage", lambda path: _full_local_usage(path, extra))
    dest = config.playwright_browsers_dir()
    assert dest == extra / "Jarvis" / "runtime" / "ms-playwright"
    applied = config.apply_playwright_browsers_path()
    assert applied == dest
    assert dest.is_dir()
    assert os.environ.get("PLAYWRIGHT_BROWSERS_PATH") == str(dest)


def test_playwright_browsers_dir_discovers_existing_extra_chromium(tmp_path, monkeypatch):
    extra = tmp_path / "USB"
    found = extra / "Jarvis" / "runtime" / "ms-playwright"
    (found / "chromium-1234").mkdir(parents=True)
    _clear_playwright_env(monkeypatch)
    monkeypatch.setattr(config, "extra_volume_roots", lambda: [extra])
    monkeypatch.setattr(config.shutil, "disk_usage", _plenty_usage)
    assert config.playwright_browsers_dir() == found


def test_playwright_browsers_dir_stays_default_when_os_volume_fits(tmp_path, monkeypatch):
    extra = tmp_path / "USB"
    extra.mkdir()
    _clear_playwright_env(monkeypatch)
    monkeypatch.setattr(config, "extra_volume_roots", lambda: [extra])
    monkeypatch.setattr(config.shutil, "disk_usage", _plenty_usage)
    dest = config.playwright_browsers_dir()
    assert dest == config.default_playwright_browsers_dir()
    config.apply_playwright_browsers_path()
    assert "PLAYWRIGHT_BROWSERS_PATH" not in os.environ


def test_playwright_install_reuses_extra_chromium(tmp_path, monkeypatch):
    from app import runtime_install

    extra = tmp_path / "USB"
    found = extra / "Jarvis" / "runtime" / "ms-playwright"
    (found / "chromium-1234").mkdir(parents=True)
    repo = tmp_path / "repo"
    repo.mkdir()
    _clear_playwright_env(monkeypatch)
    monkeypatch.setattr(config, "extra_volume_roots", lambda: [extra])
    monkeypatch.setattr(config.shutil, "disk_usage", _plenty_usage)
    monkeypatch.setattr(runtime_install, "repo_root", lambda: repo)

    def boom(*_args, **_kwargs):
        raise AssertionError("must not download Chromium when extra-drive browsers exist")

    monkeypatch.setattr("subprocess.run", boom)
    runtime_install._install_playwright()
    assert (repo / ".venv" / ".playwright-chromium-ready").is_file()


def _patch_model_disk(monkeypatch, extra: Path) -> None:
    monkeypatch.setattr(config, "extra_volume_roots", lambda: [extra])
    monkeypatch.setattr(
        "app.inference.lmstudio_catalog.shutil.disk_usage",
        lambda path: _full_local_usage(path, extra),
    )


def test_companion_pack_cache_uses_extra_when_data_volume_is_full(tmp_path, monkeypatch):
    from app.mobile import companion_offline

    data = tmp_path / "data"
    extra = tmp_path / "USB"
    data.mkdir()
    extra.mkdir()
    monkeypatch.setattr(companion_offline, "data_dir", lambda: data)
    _patch_model_disk(monkeypatch, extra)
    dest = companion_offline.pack_cache_dir()
    assert dest == extra / "Jarvis" / "models" / "companion-packs"
    assert dest.is_dir()


def test_companion_pack_cache_discovers_existing_extra_gguf(tmp_path, monkeypatch):
    from app.mobile import companion_offline

    data = tmp_path / "data"
    extra = tmp_path / "USB"
    found = extra / "Jarvis" / "models" / "companion-packs"
    found.mkdir(parents=True)
    (found / "Qwen2.5-1.5B-Instruct-Q4_K_M.gguf").write_bytes(b"gguf")
    monkeypatch.setattr(companion_offline, "data_dir", lambda: data)
    monkeypatch.setattr(config, "extra_volume_roots", lambda: [extra])
    monkeypatch.setattr("app.inference.lmstudio_catalog.shutil.disk_usage", _plenty_usage)
    assert companion_offline.pack_cache_dir() == found


def test_companion_voice_pack_cache_uses_extra_when_data_volume_is_full(tmp_path, monkeypatch):
    from app.mobile import companion_voice_packs

    data = tmp_path / "data"
    extra = tmp_path / "USB"
    data.mkdir()
    extra.mkdir()
    monkeypatch.setattr(companion_voice_packs, "data_dir", lambda: data)
    _patch_model_disk(monkeypatch, extra)
    dest = companion_voice_packs.voice_pack_cache_dir()
    assert dest == extra / "Jarvis" / "models" / "companion-voice-packs"


def test_whisper_models_dir_uses_extra_when_os_volume_is_full(tmp_path, monkeypatch):
    from app.tts.voice_runtime_config import whisper_models_dir
    from app.workers.voice import whisper_model_candidates

    models = tmp_path / "models"
    extra = tmp_path / "USB"
    models.mkdir()
    extra.mkdir()
    monkeypatch.setattr(config, "models_dir", lambda: models)
    _patch_model_disk(monkeypatch, extra)
    dest = whisper_models_dir()
    assert dest == extra / "Jarvis" / "models" / "whisper"
    roots = whisper_model_candidates()
    assert any(str(dest) in str(path) for path in roots)


def test_whisper_models_dir_discovers_existing_extra_base(tmp_path, monkeypatch):
    from app.config import AppSettings, VoiceSettings
    from app.tts.voice_runtime_config import resolved_faster_whisper_model, whisper_models_dir

    models = tmp_path / "models"
    extra = tmp_path / "USB"
    found = extra / "Jarvis" / "models" / "whisper"
    (found / "base").mkdir(parents=True)
    (found / "base" / "model.bin").write_bytes(b"w")
    monkeypatch.delenv("JARVIS_WHISPER_MODEL", raising=False)
    monkeypatch.setattr(
        "app.tts.voice_runtime_config.load_settings",
        lambda: AppSettings(voice=VoiceSettings(whisper_model="")),
    )
    monkeypatch.setattr(config, "models_dir", lambda: models)
    monkeypatch.setattr(config, "extra_volume_roots", lambda: [extra])
    monkeypatch.setattr("app.inference.lmstudio_catalog.shutil.disk_usage", _plenty_usage)
    assert whisper_models_dir() == found
    assert resolved_faster_whisper_model() == str(found / "base")


def test_laya_install_root_uses_extra_when_data_volume_is_full(tmp_path, monkeypatch):
    from app.decision.laya import pins as laya_pins

    data = tmp_path / "data"
    extra = tmp_path / "USB"
    data.mkdir()
    extra.mkdir()
    monkeypatch.setattr(laya_pins, "data_dir", lambda: data)
    _patch_model_disk(monkeypatch, extra)
    dest = laya_pins.install_root()
    assert dest == extra / "Jarvis" / "models" / "laya"
    assert dest.is_dir()


def test_laya_install_root_discovers_existing_extra_manifest(tmp_path, monkeypatch):
    from app.decision.laya import pins as laya_pins

    data = tmp_path / "data"
    extra = tmp_path / "USB"
    found = extra / "Jarvis" / "models" / "laya"
    found.mkdir(parents=True)
    (found / "install_manifest.json").write_text("{}", encoding="utf-8")
    monkeypatch.setattr(laya_pins, "data_dir", lambda: data)
    monkeypatch.setattr(config, "extra_volume_roots", lambda: [extra])
    monkeypatch.setattr("app.inference.lmstudio_catalog.shutil.disk_usage", _plenty_usage)
    assert laya_pins.install_root() == found


def test_huggingface_home_uses_extra_when_os_volume_is_full(tmp_path, monkeypatch):
    from app.inference.lmstudio_catalog import apply_huggingface_home, resolved_huggingface_home

    extra = tmp_path / "USB"
    extra.mkdir()
    monkeypatch.delenv("HF_HOME", raising=False)
    monkeypatch.delenv("HF_HUB_CACHE", raising=False)
    _patch_model_disk(monkeypatch, extra)
    dest = resolved_huggingface_home()
    assert dest == extra / "Jarvis" / "models" / "huggingface"
    applied = apply_huggingface_home()
    assert applied == dest
    assert os.environ.get("HF_HOME") == str(dest)
    assert os.environ.get("HF_HUB_CACHE") == str(dest / "hub")


def test_huggingface_home_discovers_existing_extra_hub(tmp_path, monkeypatch):
    from app.inference.lmstudio_catalog import resolved_huggingface_home

    extra = tmp_path / "USB"
    found = extra / "Jarvis" / "models" / "huggingface"
    (found / "hub").mkdir(parents=True)
    monkeypatch.delenv("HF_HOME", raising=False)
    monkeypatch.delenv("HF_HUB_CACHE", raising=False)
    monkeypatch.setattr(config, "extra_volume_roots", lambda: [extra])
    monkeypatch.setattr("app.inference.lmstudio_catalog.shutil.disk_usage", _plenty_usage)
    assert resolved_huggingface_home() == found


def test_huggingface_home_honors_existing_hf_home(tmp_path, monkeypatch):
    from app.inference.lmstudio_catalog import apply_huggingface_home, resolved_huggingface_home

    extra = tmp_path / "USB"
    extra.mkdir()
    custom = tmp_path / "custom-hf"
    custom.mkdir()
    monkeypatch.setenv("HF_HOME", str(custom))
    _patch_model_disk(monkeypatch, extra)
    assert resolved_huggingface_home() == custom
    assert apply_huggingface_home() == custom
    assert os.environ.get("HF_HOME") == str(custom)


def test_ensure_chatterbox_weights_use_extra_hf_cache(tmp_path, monkeypatch):
    from app.tts import pack_install

    extra = tmp_path / "USB"
    extra.mkdir()
    monkeypatch.delenv("HF_HOME", raising=False)
    monkeypatch.delenv("HF_HUB_CACHE", raising=False)
    _patch_model_disk(monkeypatch, extra)
    seen: dict[str, str] = {}

    def download(*, repo_id, filename, local_files_only=False, cache_dir=None, **_kwargs):
        del repo_id, local_files_only
        seen["cache_dir"] = str(cache_dir or "")
        seen["hf_home"] = os.environ.get("HF_HOME") or ""
        return filename

    monkeypatch.setattr(pack_install, "hf_hub_download", download)
    monkeypatch.setattr(
        "app.policy.network_http.require_http_url_allowed",
        lambda *args, **kwargs: None,
    )
    pack_install.ensure_chatterbox_weights(force=True)
    dest = extra / "Jarvis" / "models" / "huggingface"
    assert seen["cache_dir"] == str(dest / "hub")
    assert seen["hf_home"] == str(dest)


def test_pocket_tts_model_dir_uses_extra_when_os_volume_is_full(tmp_path, monkeypatch):
    from app.tts.pocket_tts_adapter import PocketTtsAdapter, resolved_pocket_tts_model_dir

    models = tmp_path / "models"
    extra = tmp_path / "USB"
    models.mkdir()
    extra.mkdir()
    monkeypatch.setattr(config, "models_dir", lambda: models)
    _patch_model_disk(monkeypatch, extra)
    dest = resolved_pocket_tts_model_dir()
    assert dest == extra / "Jarvis" / "models" / "tts" / "pocket-tts"
    assert PocketTtsAdapter().model_dir == dest


def test_pocket_tts_model_dir_discovers_existing_extra_weights(tmp_path, monkeypatch):
    from app.tts.pocket_tts_adapter import resolved_pocket_tts_model_dir

    models = tmp_path / "models"
    extra = tmp_path / "USB"
    found = extra / "Jarvis" / "models" / "tts" / "pocket-tts"
    found.mkdir(parents=True)
    (found / "model.safetensors").write_bytes(b"w")
    monkeypatch.setattr(config, "models_dir", lambda: models)
    monkeypatch.setattr(config, "extra_volume_roots", lambda: [extra])
    monkeypatch.setattr("app.inference.lmstudio_catalog.shutil.disk_usage", _plenty_usage)
    assert resolved_pocket_tts_model_dir() == found


def test_piper_voices_dir_uses_extra_when_os_volume_is_full(tmp_path, monkeypatch):
    from app.tts.engines import resolved_piper_voices_dir
    from app.tts.synthesize import _resolve_piper_onnx

    models = tmp_path / "models"
    extra = tmp_path / "USB"
    models.mkdir()
    extra.mkdir()
    monkeypatch.setattr(config, "models_dir", lambda: models)
    _patch_model_disk(monkeypatch, extra)
    dest = resolved_piper_voices_dir()
    assert dest == extra / "Jarvis" / "models" / "tts" / "piper"
    voice = dest / "en_US-lessac-medium.onnx"
    voice.write_bytes(b"onnx")
    assert _resolve_piper_onnx("lessac", None) == voice


def test_piper_voices_dir_discovers_existing_extra_onnx(tmp_path, monkeypatch):
    from app.tts.engines import resolved_piper_voices_dir

    models = tmp_path / "models"
    extra = tmp_path / "USB"
    found = extra / "Jarvis" / "models" / "tts" / "piper"
    found.mkdir(parents=True)
    (found / "en_US-lessac-medium.onnx").write_bytes(b"onnx")
    monkeypatch.setattr(config, "models_dir", lambda: models)
    monkeypatch.setattr(config, "extra_volume_roots", lambda: [extra])
    monkeypatch.setattr("app.inference.lmstudio_catalog.shutil.disk_usage", _plenty_usage)
    assert resolved_piper_voices_dir() == found


def _patch_runtime_disk(monkeypatch, extra: Path) -> None:
    monkeypatch.setattr(config, "extra_volume_roots", lambda: [extra])
    monkeypatch.setattr(config.shutil, "disk_usage", lambda path: _full_local_usage(path, extra))


def test_playwright_user_data_dir_uses_extra_when_os_volume_is_full(tmp_path, monkeypatch):
    data = tmp_path / "data"
    extra = tmp_path / "USB"
    data.mkdir()
    extra.mkdir()
    monkeypatch.setattr(config, "data_dir", lambda: data)
    _patch_runtime_disk(monkeypatch, extra)
    dest = config.playwright_user_data_dir()
    assert dest == extra / "Jarvis" / "runtime" / "browser-profile"
    assert dest.is_dir()


def test_playwright_user_data_dir_discovers_existing_extra_profile(tmp_path, monkeypatch):
    data = tmp_path / "data"
    extra = tmp_path / "USB"
    found = extra / "Jarvis" / "runtime" / "browser-profile"
    (found / "Default").mkdir(parents=True)
    (found / "Local State").write_text("{}", encoding="utf-8")
    monkeypatch.setattr(config, "data_dir", lambda: data)
    monkeypatch.setattr(config, "extra_volume_roots", lambda: [extra])
    monkeypatch.setattr(config.shutil, "disk_usage", _plenty_usage)
    assert config.playwright_user_data_dir() == found


def test_browser_use_user_data_dir_uses_extra_when_os_volume_is_full(tmp_path, monkeypatch):
    data = tmp_path / "data"
    extra = tmp_path / "USB"
    data.mkdir()
    extra.mkdir()
    monkeypatch.setattr(config, "data_dir", lambda: data)
    _patch_runtime_disk(monkeypatch, extra)
    dest = config.browser_use_user_data_dir()
    assert dest == extra / "Jarvis" / "runtime" / "browser-use-profile"
    assert dest.is_dir()


def test_browser_use_user_data_dir_discovers_existing_extra_profile(tmp_path, monkeypatch):
    data = tmp_path / "data"
    extra = tmp_path / "USB"
    found = extra / "Jarvis" / "browser-use-profile"
    (found / "Default").mkdir(parents=True)
    monkeypatch.setattr(config, "data_dir", lambda: data)
    monkeypatch.setattr(config, "extra_volume_roots", lambda: [extra])
    monkeypatch.setattr(config.shutil, "disk_usage", _plenty_usage)
    assert config.browser_use_user_data_dir() == found


def test_default_vault_path_uses_extra_when_data_volume_is_full(tmp_path, monkeypatch):
    from app.memory.obsidian_vault import default_vault_path

    data = tmp_path / "data"
    extra = tmp_path / "USB"
    data.mkdir()
    extra.mkdir()
    monkeypatch.setattr("app.memory.obsidian_vault.data_dir", lambda: data)
    _patch_runtime_disk(monkeypatch, extra)
    dest = default_vault_path()
    assert dest == extra / "Jarvis" / "runtime" / "vault"


def test_default_vault_path_discovers_existing_extra_vault(tmp_path, monkeypatch):
    from app.memory.obsidian_vault import default_vault_path

    data = tmp_path / "data"
    extra = tmp_path / "USB"
    found = extra / "Jarvis" / "vault"
    (found / "Home").mkdir(parents=True)
    (found / "Home" / "Jarvis.md").write_text("# Jarvis\n", encoding="utf-8")
    monkeypatch.setattr("app.memory.obsidian_vault.data_dir", lambda: data)
    monkeypatch.setattr(config, "extra_volume_roots", lambda: [extra])
    monkeypatch.setattr(config.shutil, "disk_usage", _plenty_usage)
    assert default_vault_path() == found


def test_worktrees_root_uses_extra_when_data_volume_is_full(tmp_path, monkeypatch):
    from app.agent.worktrees import worktrees_root

    data = tmp_path / "data"
    extra = tmp_path / "USB"
    data.mkdir()
    extra.mkdir()
    monkeypatch.setattr("app.agent.worktrees.data_dir", lambda: data)
    _patch_runtime_disk(monkeypatch, extra)
    dest = worktrees_root()
    assert dest == extra / "Jarvis" / "runtime" / "worktrees"
    assert dest.is_dir()


def test_worktrees_root_discovers_existing_extra_registry(tmp_path, monkeypatch):
    from app.agent.worktrees import worktrees_root

    data = tmp_path / "data"
    extra = tmp_path / "USB"
    found = extra / "Jarvis" / "runtime" / "worktrees"
    found.mkdir(parents=True)
    (found / "worktrees.json").write_text("[]", encoding="utf-8")
    monkeypatch.setattr("app.agent.worktrees.data_dir", lambda: data)
    monkeypatch.setattr(config, "extra_volume_roots", lambda: [extra])
    monkeypatch.setattr(config.shutil, "disk_usage", _plenty_usage)
    assert worktrees_root() == found


def test_environments_root_uses_extra_when_data_volume_is_full(tmp_path, monkeypatch):
    from app.workers.credentials import credentials_root
    from app.workers.environments import environments_root

    data = tmp_path / "data"
    extra = tmp_path / "USB"
    data.mkdir()
    extra.mkdir()
    monkeypatch.setattr("app.workers.environments.data_dir", lambda: data)
    monkeypatch.setattr("app.workers.credentials.data_dir", lambda: data)
    _patch_runtime_disk(monkeypatch, extra)
    dest = environments_root()
    assert dest == extra / "Jarvis" / "runtime" / "worker-environments"
    assert credentials_root() == dest / ".credentials"


def test_environments_root_discovers_existing_extra_registry(tmp_path, monkeypatch):
    from app.workers.environments import environments_root

    data = tmp_path / "data"
    extra = tmp_path / "USB"
    found = extra / "Jarvis" / "runtime" / "worker-environments"
    found.mkdir(parents=True)
    (found / "registry.json").write_text("[]", encoding="utf-8")
    monkeypatch.setattr("app.workers.environments.data_dir", lambda: data)
    monkeypatch.setattr(config, "extra_volume_roots", lambda: [extra])
    monkeypatch.setattr(config.shutil, "disk_usage", _plenty_usage)
    assert environments_root() == found


def test_projects_root_uses_extra_when_data_volume_is_full(tmp_path, monkeypatch):
    from app.media.store import blob_path, media_store_root
    from app.projects.paths import media_relative_path, project_media_dir, projects_root

    data = tmp_path / "data"
    extra = tmp_path / "USB"
    data.mkdir()
    extra.mkdir()
    monkeypatch.setattr(config, "data_dir", lambda: data)
    monkeypatch.setattr("app.media.store.data_dir", lambda: data)
    _patch_runtime_disk(monkeypatch, extra)
    dest = projects_root()
    assert dest == extra / "Jarvis" / "runtime" / "projects"
    assert media_store_root() == extra / "Jarvis" / "runtime" / "media"
    media_dir = project_media_dir("alpha")
    upload = media_dir / "file-1"
    upload.write_bytes(b"pic")
    assert blob_path("file-1", record={"relative_path": media_relative_path("alpha", "file-1")}) == upload


def test_projects_root_discovers_existing_extra_project(tmp_path, monkeypatch):
    from app.projects.paths import projects_root

    data = tmp_path / "data"
    extra = tmp_path / "USB"
    found = extra / "Jarvis" / "runtime" / "projects"
    (found / "alpha").mkdir(parents=True)
    monkeypatch.setattr(config, "data_dir", lambda: data)
    monkeypatch.setattr(config, "extra_volume_roots", lambda: [extra])
    monkeypatch.setattr(config.shutil, "disk_usage", _plenty_usage)
    assert projects_root() == found


def test_backup_root_uses_extra_when_data_volume_is_full(tmp_path, monkeypatch):
    from app.tools.snapshots import backup_root

    data = tmp_path / "data"
    extra = tmp_path / "USB"
    data.mkdir()
    extra.mkdir()
    monkeypatch.setattr("app.tools.snapshots.data_dir", lambda: data)
    _patch_runtime_disk(monkeypatch, extra)
    dest = backup_root()
    assert dest == extra / "Jarvis" / "runtime" / "backups"
    assert dest.is_dir()
