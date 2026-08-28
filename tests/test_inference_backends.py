import pytest

from app.config import AppSettings
from app.inference.backends import (
    LlamaCppBackend,
    LMStudioBackend,
    OllamaBackend,
    RemoteOpenAICompatibleBackend,
    normalize_chat_messages,
    parse_models_payload,
    resolve_backend,
    suggested_port,
)
from app.inference.profiles import resolve_profile
from app.providers.base import ChatMessage


def _settings(**inference) -> AppSettings:
    base = {"backend": "llama.cpp", "host": "127.0.0.1", "port": 8088}
    base.update(inference)
    return AppSettings(inference=base)


def test_llama_cpp_is_the_default_backend():
    assert isinstance(resolve_backend(_settings()), LlamaCppBackend)


def test_normalize_chat_messages_keeps_single_system_first():
    messages = [
        ChatMessage(role="system", content="rules"),
        ChatMessage(role="user", content="hello"),
        ChatMessage(role="system", content="extra context"),
        ChatMessage(role="assistant", content="hi"),
    ]
    normalized = normalize_chat_messages(messages)
    assert [message.role for message in normalized] == ["system", "user", "assistant"]
    assert "rules" in normalized[0].content
    assert "extra context" in normalized[0].content


async def test_manager_chat_normalizes_messages_before_provider(monkeypatch):
    from app.inference.manager import InferenceManager

    captured: dict[str, list] = {}

    class FakeProvider:
        model = "Qwen3.5-9B"

        async def chat(self, messages, **kwargs):
            captured["messages"] = messages
            from app.providers.base import ChatResult

            return ChatResult(content="ok")

    mgr = InferenceManager()
    mgr.provider = FakeProvider()
    messages = [
        ChatMessage(role="system", content="sys-a"),
        ChatMessage(role="user", content="task"),
        ChatMessage(role="system", content="sys-b"),
    ]
    result = await mgr.chat(messages)
    assert result.content == "ok"
    assert len(captured["messages"]) == 2
    assert captured["messages"][0].role == "system"
    assert "sys-a" in captured["messages"][0].content
    assert "sys-b" in captured["messages"][0].content


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


async def test_remote_backend_load_does_not_require_local_gguf(monkeypatch):
    from app.config import AppSettings
    from app.inference.manager import InferenceManager

    settings = AppSettings(inference={"backend": "remote", "host": "192.168.1.40", "port": 8088, "remote_model": "qwen"})
    mgr = InferenceManager()

    async def fake_probe(host, port, api_key="", timeout=8, retry=False):
        assert host == "192.168.1.40"
        return {"ok": True, "health_path": "/v1/models", "models": ["qwen"]}

    async def fake_health(self):
        return True

    monkeypatch.setattr("app.inference.manager.probe_remote_server", fake_probe)
    monkeypatch.setattr("app.providers.base.ModelProvider.health", fake_health)
    state = await mgr.load(settings, "balanced")
    assert state.loaded is True
    assert state.manages_process is False
    assert mgr.provider is not None
    assert mgr.provider.model == "qwen"
    assert not state.model_path


def test_llama_cpp_reports_missing_local_files():
    backend = LlamaCppBackend(_settings())
    missing = backend.missing_requirements(resolve_profile("balanced"))
    assert any("model file missing" in item for item in missing)


def test_expert_profile_is_the_27b_escalation_alias():
    from app.inference.profiles import PROFILES

    expert = PROFILES["expert"]
    assert expert.name == "expert"
    assert "27B" in expert.filename
    assert expert.thinking is True


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
        "app.inference.profiles.model_paths",
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


async def test_ensure_vision_attaches_then_release_detaches(jarvis_env):
    from app.inference.manager import MANAGER, resolve_vision

    settings = jarvis_env["settings"]
    settings.inference.vision_mode = "lazy"
    MANAGER.backend = None
    MANAGER.state.vision_loaded = False
    MANAGER.state.mmproj_path = ""
    MANAGER.state.vision = False

    assert resolve_vision(settings, None) is False
    attached = await MANAGER.ensure_vision(settings)
    assert attached.vision_loaded is True
    assert attached.vision is True
    released = await MANAGER.release_vision(settings)
    assert released.vision_loaded is False
    assert released.vision is False
    assert released.mmproj_path == ""

    settings.inference.vision_mode = "always"
    MANAGER.state.vision_loaded = True
    MANAGER.state.vision = True
    kept = await MANAGER.release_vision(settings)
    assert kept.vision_loaded is True


async def test_unloaded_snapshot_starts_at_16k_with_selective_thinking():
    from app.config import AppSettings
    from app.inference.manager import InferenceManager

    snap = await InferenceManager().snapshot(AppSettings())
    assert snap["context_size"] == 16384
    assert snap["context_cap"] == 32768
    assert snap["thinking_mode"] == "selective"
    assert snap["vision_mode"] == "lazy"
    assert snap["vision_loaded"] is False
