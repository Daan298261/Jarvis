import pytest

from app.config import AppSettings
from app.inference.backends import (
    LlamaCppBackend,
    LMStudioBackend,
    OllamaBackend,
    RemoteOpenAICompatibleBackend,
    parse_models_payload,
    resolve_backend,
    suggested_port,
)
from app.inference.profiles import resolve_profile


def _settings(**inference) -> AppSettings:
    base = {"backend": "llama.cpp", "host": "127.0.0.1", "port": 8088}
    base.update(inference)
    return AppSettings(inference=base)


def test_llama_cpp_is_the_default_backend():
    assert isinstance(resolve_backend(_settings()), LlamaCppBackend)


@pytest.mark.parametrize("name", ["remote", "lmstudio", "ollama", "vllm", "openai-compatible"])
def test_other_servers_resolve_to_the_remote_backend(name):
    backend = resolve_backend(_settings(backend=name))
    assert isinstance(backend, RemoteOpenAICompatibleBackend)
    assert backend.manages_process is False
    assert backend.requires_local_files is False


def test_unknown_backend_on_another_host_is_treated_as_remote():
    backend = resolve_backend(_settings(backend="mystery", host="192.168.1.50"))
    assert isinstance(backend, RemoteOpenAICompatibleBackend)


def test_remote_backend_needs_no_local_model_files():
    backend = RemoteOpenAICompatibleBackend(_settings(backend="remote"))
    assert backend.missing_requirements(resolve_profile("balanced")) == []
    assert backend.health_url().endswith("/v1/models")


def test_named_lan_backends_keep_family_health_urls():
    ollama = resolve_backend(_settings(backend="ollama", port=11434))
    assert isinstance(ollama, OllamaBackend)
    assert ollama.health_url().endswith("/api/tags")
    assert ollama.requires_local_files is False
    studio = resolve_backend(_settings(backend="lmstudio", port=1234))
    assert isinstance(studio, LMStudioBackend)


def test_suggested_port_only_replaces_stock_ports():
    assert suggested_port("ollama", 8088) == 11434
    assert suggested_port("lmstudio", 8088) == 1234
    assert suggested_port("llama.cpp", 11434) == 8088
    assert suggested_port("ollama", 9999) == 9999


def test_parse_models_payload_from_openai_and_ollama():
    openai = parse_models_payload("/v1/models", {"data": [{"id": "qwen"}, {"id": "qwen"}]})
    assert openai == ["qwen"]
    tags = parse_models_payload("/api/tags", {"models": [{"name": "qwen3.5:9b"}, {"name": "llama3"}]})
    assert tags == ["qwen3.5:9b", "llama3"]


async def test_snapshot_includes_lan_fields():
    from app.config import AppSettings
    from app.inference.manager import MANAGER

    settings = AppSettings(inference={"backend": "remote", "host": "192.168.1.50", "port": 11434})
    snap = await MANAGER.snapshot(settings)
    assert snap["base_url"] == "http://192.168.1.50:11434/v1"
    assert snap["host"] == "192.168.1.50"
    assert "advertised_models" in snap
    assert "api_key_configured" in snap


def test_llama_cpp_reports_missing_local_files():
    backend = LlamaCppBackend(_settings())
    missing = backend.missing_requirements(resolve_profile("balanced"))
    assert any("model file missing" in item for item in missing)


def test_llama_cpp_command_reflects_profile_and_settings():
    profile = resolve_profile("balanced")
    args = LlamaCppBackend(_settings(port=9099, fit=True, fit_target_mib=2048)).build_args(profile)
    assert "--ctx-size" in args
    assert args[args.index("--ctx-size") + 1] == str(profile.context_size)
    assert args[args.index("--port") + 1] == "9099"
    assert args[args.index("--reasoning") + 1] == "on"
    assert args[args.index("--fit-target") + 1] == "2048"
    assert "--jinja" in args
    assert args[args.index("--alias") + 1] == "Qwen3.5-9B"
    assert "--mmproj" not in args

    fast = LlamaCppBackend(_settings(fit=False)).build_args(resolve_profile("fast"))
    assert fast[fast.index("--reasoning") + 1] == "off"
    assert fast[fast.index("--n-gpu-layers") + 1] == "99"


def test_llama_cpp_attaches_mmproj_only_when_vision_requested(tmp_path, monkeypatch):
    mmproj = tmp_path / "mmproj-F16.gguf"
    mmproj.write_bytes(b"fake")
    monkeypatch.setattr(
        "app.inference.backends.model_paths",
        lambda: {"root": tmp_path, "mmproj": mmproj, "q4": tmp_path / "q4.gguf", "q5": tmp_path / "q5.gguf"},
    )
    backend = LlamaCppBackend(_settings())
    lazy = backend.build_args(resolve_profile("balanced"), context_size=8192, vision=False)
    assert lazy[lazy.index("--ctx-size") + 1] == "8192"
    assert "--mmproj" not in lazy
    with_vision = backend.build_args(resolve_profile("balanced"), context_size=16384, vision=True)
    assert "--mmproj" in with_vision
    assert with_vision[with_vision.index("--mmproj") + 1] == str(mmproj)
    assert "--image-min-tokens" in with_vision


async def test_unloaded_snapshot_starts_at_16k_with_selective_thinking():
    from app.config import AppSettings
    from app.inference.manager import InferenceManager

    snap = await InferenceManager().snapshot(AppSettings())
    assert snap["context_size"] == 16384
    assert snap["context_cap"] == 32768
    assert snap["thinking_mode"] == "selective"
    assert snap["vision_mode"] == "lazy"
    assert snap["vision_loaded"] is False
