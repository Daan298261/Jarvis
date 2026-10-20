"""UI status/catalog probes must not occupy the API event-loop thread."""
import asyncio
import threading
from types import SimpleNamespace

from fastapi import FastAPI
import httpx
import pytest

from app.api import custom_presence, diagnostics, named_personas, system, voice_profiles
from app.config import AppSettings


def _read(router, path, monkeypatch, module, attribute, value):
    main_thread = threading.get_ident()
    calls = []

    def probe(*args, **kwargs):
        calls.append(threading.get_ident())
        assert threading.get_ident() != main_thread
        return value

    monkeypatch.setattr(module, attribute, probe)
    app = FastAPI()
    app.include_router(router)

    async def run():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app), base_url="http://test") as client:
            response = await client.get(path)
            assert response.status_code == 200, response.text
    asyncio.run(run())
    assert calls


@pytest.mark.parametrize("module,path,attribute", [
    (named_personas, "/api/named-personas", "public_state"),
    (custom_presence, "/api/custom-presence", "public_custom_presence_state"),
    (system, "/api/system/elevation", "elevation_snapshot"),
])
def test_catalog_reads_use_worker_thread(monkeypatch, module, path, attribute):
    _read(module.router, path, monkeypatch, module, attribute, {"ok": True})


def test_voice_picker_checks_use_worker_thread(monkeypatch):
    monkeypatch.setattr(voice_profiles, "get_active_voice_profile_id", lambda: "butler_original_v1")
    _read(voice_profiles.router, "/api/voice-profiles", monkeypatch, voice_profiles, "get_catalog",
          SimpleNamespace(list_profiles=lambda active: []))


@pytest.mark.parametrize("path", ["/api/diagnostics", "/api/diagnostics/text"])
def test_diagnostics_probes_use_worker_thread(monkeypatch, path):
    async def snapshot(settings):
        return {"loaded": True}
    monkeypatch.setattr(diagnostics.MANAGER, "snapshot", snapshot)
    _read(diagnostics.router, path, monkeypatch, diagnostics, "build_diagnostics", {"ok": True})


def test_system_capability_probes_use_worker_thread(monkeypatch):
    async def snapshot(settings):
        return {"loaded": True}
    async def swarm():
        return {}
    monkeypatch.setattr(system, "load_settings", AppSettings)
    monkeypatch.setattr(system.MANAGER, "snapshot", snapshot)
    monkeypatch.setattr(system, "swarm_snapshot", swarm)
    _read(system.router, "/api/system", monkeypatch, system, "_system_details", {"capabilities": {}})


def test_front_startup_planning_uses_worker_thread(monkeypatch):
    from app.inference.front_runtime import FrontDecision, FrontRuntime
    main = threading.get_ident()
    runtime = FrontRuntime()
    def decide(settings, **kwargs):
        assert threading.get_ident() != main
        return FrontDecision(mode="fallback", reason="test")
    monkeypatch.setattr(runtime, "decide", decide)
    decision = asyncio.run(runtime.ensure_started(AppSettings()))
    assert decision.reason == "test"
