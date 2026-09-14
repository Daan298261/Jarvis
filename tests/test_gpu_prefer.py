from __future__ import annotations

import pytest

from app.inference.gpu_prefer import llama_cpp_gpu_args, lmstudio_cli_load_args, ollama_gpu_options


def test_llama_cpp_keeps_fit_reserve_and_all_layers_path():
    fitted = llama_cpp_gpu_args(fit=True, fit_target_mib=2048, prefer_gpu=True)
    assert fitted == ["--fit", "on", "--fit-target", "2048"]
    full = llama_cpp_gpu_args(fit=False, fit_target_mib=1024, prefer_gpu=True)
    assert full == ["--n-gpu-layers", "99"]


def test_lmstudio_cli_requests_max_gpu(monkeypatch):
    monkeypatch.setattr("app.inference.gpu_prefer.shutil.which", lambda name: r"C:\lms.exe" if name == "lms" else None)
    args = lmstudio_cli_load_args("Qwen3.5-9B")
    assert args is not None
    assert args[1:4] == ["load", "Qwen3.5-9B", "--gpu"]
    assert "max" in args


def test_ollama_gpu_options_when_nvidia_present(monkeypatch):
    monkeypatch.setattr("app.inference.gpu_prefer.nvidia_gpu_present", lambda: True)
    assert ollama_gpu_options() == {"num_gpu": 99}
    monkeypatch.setattr("app.inference.gpu_prefer.nvidia_gpu_present", lambda: False)
    assert ollama_gpu_options() == {}


@pytest.mark.asyncio
async def test_ensure_lmstudio_gpu_uses_cli_when_present(monkeypatch):
    from types import SimpleNamespace

    from app.inference import gpu_prefer

    monkeypatch.setattr(gpu_prefer, "lmstudio_cli_load_args", lambda model: ["lms", "load", model, "--gpu", "max", "-y"])

    async def fake_cli(args, timeout):
        assert "--gpu" in args and "max" in args
        return SimpleNamespace(returncode=0, stdout="Loaded on GPU", stderr="")

    monkeypatch.setattr(gpu_prefer, "_run_cli", fake_cli)
    result = await gpu_prefer.ensure_lmstudio_gpu(host="127.0.0.1", port=1234, model="local-model")
    assert result["ok"] is True
    assert result["method"] == "lms-cli"


@pytest.mark.asyncio
async def test_ensure_ollama_gpu_posts_num_gpu(monkeypatch):
    from app.inference import gpu_prefer

    monkeypatch.setattr(gpu_prefer, "nvidia_gpu_present", lambda: True)

    class FakeResponse:
        status_code = 200

    class FakeClient:
        def __init__(self, *args, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return False

        async def post(self, url, json):
            assert url.endswith("/api/generate")
            assert json["options"]["num_gpu"] == 99
            return FakeResponse()

    monkeypatch.setattr(gpu_prefer.httpx, "AsyncClient", FakeClient)
    result = await gpu_prefer.ensure_ollama_gpu(host="127.0.0.1", port=11434, model="qwen")
    assert result["ok"] is True
    assert result["method"] == "ollama-generate"
