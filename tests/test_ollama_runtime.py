"""Ollama runtime ensure (Umi brain)."""

from __future__ import annotations

import pytest

from app.inference import ollama_runtime
from app.persona.persona_brain import UMI_OLLAMA_MODEL, reflex_verify_brain_runtime


@pytest.mark.asyncio
async def test_ensure_local_ollama_already_up(monkeypatch):
    async def fake_probe(host, port, timeout=8.0, retry=False, api_key=""):
        return {"ok": True, "models": [UMI_OLLAMA_MODEL]}

    async def fake_gpu(**kwargs):
        return {"ok": True, "detail": "warm"}

    monkeypatch.setattr(ollama_runtime, "probe_remote_server", fake_probe)
    monkeypatch.setattr(ollama_runtime, "ensure_ollama_gpu", fake_gpu)

    result = await ollama_runtime.ensure_local_ollama(
        host="127.0.0.1",
        port=11434,
        model=UMI_OLLAMA_MODEL,
        pull_if_missing=False,
    )
    assert result["ok"] is True
    assert result["method"] == "ollama-ready"


def test_reflex_verify_brain_accepts_umi_runtime():
    assert reflex_verify_brain_runtime(persona_id="umi", runtime_name="umi-opus-9b") is True


def test_reflex_verify_brain_skips_unbound_persona():
    assert reflex_verify_brain_runtime(persona_id="anzu", runtime_name="umi-opus-9b") is True


@pytest.mark.asyncio
async def test_starts_missing_local_service_without_downloading(monkeypatch):
    from unittest.mock import AsyncMock, Mock
    probe = AsyncMock(return_value={"ok": False})
    wait = AsyncMock(return_value={"ok": True, "models": ["saved:latest"]})
    start = Mock()
    monkeypatch.setattr(ollama_runtime, "probe_remote_server", probe)
    monkeypatch.setattr(ollama_runtime, "_wait_until_up", wait)
    monkeypatch.setattr(ollama_runtime, "_start_server", start)
    monkeypatch.setattr(ollama_runtime, "ollama_cli", lambda: "ollama.exe")
    monkeypatch.setattr(ollama_runtime, "ensure_ollama_gpu", AsyncMock(return_value={"ok": True}))
    result = await ollama_runtime.ensure_local_ollama(host="localhost", port=11434, model="saved", pull_if_missing=False)
    assert result["ok"] and result["model"] == "saved:latest"
    start.assert_called_once_with("localhost", 11434)


@pytest.mark.asyncio
@pytest.mark.parametrize("advertised", [[], ["different:latest"], ["saved-other:latest"]])
async def test_missing_selection_never_attaches_another_model_or_pulls(monkeypatch, advertised):
    from unittest.mock import AsyncMock, Mock
    monkeypatch.setattr(ollama_runtime, "probe_remote_server", AsyncMock(return_value={"ok": True, "models": advertised}))
    pull = Mock(side_effect=AssertionError("unsolicited download"))
    monkeypatch.setattr(ollama_runtime, "_run_ollama", pull)
    result = await ollama_runtime.ensure_local_ollama(host="localhost", port=11434, model="saved", pull_if_missing=False)
    assert not result["ok"] and result["method"] == "model-missing"
    pull.assert_not_called()


@pytest.mark.asyncio
async def test_failed_warmup_is_not_ready(monkeypatch):
    from unittest.mock import AsyncMock
    monkeypatch.setattr(ollama_runtime, "probe_remote_server", AsyncMock(return_value={"ok": True, "models": ["saved"]}))
    monkeypatch.setattr(ollama_runtime, "ensure_ollama_gpu", AsyncMock(return_value={"ok": False, "detail": "out of memory"}))
    result = await ollama_runtime.ensure_local_ollama(host="localhost", port=11434, model="saved", pull_if_missing=False)
    assert not result["ok"] and result["detail"] == "out of memory"


@pytest.mark.asyncio
async def test_remote_host_is_never_managed(monkeypatch):
    from unittest.mock import AsyncMock
    probe = AsyncMock(side_effect=AssertionError("must not probe"))
    monkeypatch.setattr(ollama_runtime, "probe_remote_server", probe)
    result = await ollama_runtime.ensure_local_ollama(host="192.0.2.1", port=11434)
    assert not result["ok"] and result["method"] == "skipped"
    probe.assert_not_called()


@pytest.mark.asyncio
async def test_cpu_only_model_is_warmed(monkeypatch):
    import httpx
    from unittest.mock import AsyncMock
    monkeypatch.setattr(ollama_runtime, "probe_remote_server", AsyncMock(return_value={"ok": True, "models": ["saved"]}))
    monkeypatch.setattr(ollama_runtime, "ensure_ollama_gpu", AsyncMock(return_value={"ok": False, "method": "skipped"}))
    requests = []
    def respond(request):
        requests.append(request)
        return httpx.Response(200, json={"done": True})
    original = httpx.AsyncClient
    monkeypatch.setattr(ollama_runtime.httpx, "AsyncClient", lambda **kwargs: original(transport=httpx.MockTransport(respond)))
    result = await ollama_runtime.ensure_local_ollama(host="localhost", port=11434, model="saved", pull_if_missing=False)
    assert result["ok"] and requests[0].url.path == "/api/generate"


@pytest.mark.asyncio
async def test_saved_ollama_autoload_waits_for_runtime(monkeypatch):
    from unittest.mock import AsyncMock
    from app import main
    from app.config import AppSettings
    ensure = AsyncMock(return_value={"ok": True})
    load = AsyncMock()
    monkeypatch.setattr(ollama_runtime, "ensure_local_ollama", ensure)
    monkeypatch.setattr(main.MANAGER, "load", load)
    settings = AppSettings(inference={"backend": "ollama", "host": "127.0.0.1", "port": 11434, "remote_model": "saved:latest"})
    await main._autoload_model(settings)
    assert ensure.await_args.kwargs["model"] == "saved:latest"
    assert ensure.await_args.kwargs["pull_if_missing"] is False
    load.assert_awaited_once_with(settings, context_size=settings.inference.context_size)


@pytest.mark.asyncio
async def test_manual_load_recovers_local_service_without_pulling(monkeypatch):
    from unittest.mock import AsyncMock
    from app.api import model as api
    from app.config import AppSettings
    settings = AppSettings(inference={"backend": "ollama", "port": 11434, "remote_model": "saved:latest"})
    ensure = AsyncMock(return_value={"ok": True})
    monkeypatch.setattr(ollama_runtime, "ensure_local_ollama", ensure)
    monkeypatch.setattr(api, "load_settings", lambda: settings)
    monkeypatch.setattr(api.MANAGER, "load", AsyncMock())
    monkeypatch.setattr(api, "rebind_owner_conversations_after_hotswap", lambda *args, **kwargs: None)
    from app.inference.status_monitor import STATUS_MONITOR
    monkeypatch.setattr(STATUS_MONITOR, "get_snapshot", AsyncMock(return_value={"loaded": True}))
    assert (await api.load_model())["loaded"]
    assert ensure.await_args.kwargs["pull_if_missing"] is False
    assert ensure.await_args.kwargs["model"] == "saved:latest"
