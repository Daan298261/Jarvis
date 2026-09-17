from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.inference.hotswap import activate_runtime_profile
from app.inference.model_stack import MODEL_CATALOG
from app.inference.runtime_profiles import reset_runtime_profiles
from app.inference.runtime_router import AgentRoutingPreferences, route_runtime
from app.main import app
from app.security.hexstrike import (
    HEXSTRIKE_SUITE_NAME,
    gateway_allows,
    is_hexstrike_suite,
    is_suite_runtime,
)


def test_hexstrike_catalog_ships_enabled_suite_profile():
    entry = MODEL_CATALOG["hexstrike-suite"]
    assert entry.role == "cyber-suite"
    assert entry.provider == "hexstrike"
    assert "suite:hexstrike" in entry.capability_tags
    assert "llm_inference" not in entry.capability_tags
    runtime = entry.runtime_profile()
    assert runtime is not None
    assert runtime.enabled is True
    assert is_hexstrike_suite(runtime)
    assert is_suite_runtime(runtime)


def test_gateway_allowlist_is_deny_by_default():
    from app.security.hexstrike import operator_post_allowed

    assert gateway_allows("GET", "health")
    assert gateway_allows("GET", "/api/telemetry")
    assert gateway_allows("GET", "api/processes/list")
    assert gateway_allows("GET", "api/processes/status/12")
    assert gateway_allows("GET", "api/tools/nmap")
    assert operator_post_allowed("api/tools/nmap")
    assert operator_post_allowed("api/processes/terminate/12")
    assert gateway_allows("POST", "api/processes/terminate/12")
    assert not gateway_allows("POST", "api/command")
    assert not gateway_allows("POST", "api/intelligence/analyze-target")
    assert not gateway_allows("GET", "api/command")
    assert not gateway_allows("POST", "payload")
    assert not gateway_allows("GET", "../health")
    assert not gateway_allows("GET", "api/python")


def test_inference_router_ignores_hexstrike_suite(jarvis_env, monkeypatch):
    monkeypatch.setattr("app.inference.runtime_profiles.data_dir", lambda: jarvis_env["tmp"])
    reset_runtime_profiles()
    profiles = reset_runtime_profiles()
    decision = route_runtime(
        AgentRoutingPreferences(required_capabilities=("llm_inference", "text")),
        profiles=profiles,
    )
    assert decision.accepted
    assert decision.runtime_profile is not None
    assert not is_suite_runtime(decision.runtime_profile)

    forced = route_runtime(
        AgentRoutingPreferences(force_profile=HEXSTRIKE_SUITE_NAME),
        profiles=profiles,
    )
    assert forced.accepted is False
    assert forced.code == "suite_not_inference"


def test_hexstrike_status_endpoint_without_install(jarvis_env, monkeypatch):
    monkeypatch.setattr("app.security.hexstrike.data_dir", lambda: jarvis_env["tmp"])
    monkeypatch.setattr("app.security.hexstrike.load_settings", lambda: jarvis_env["settings"])
    monkeypatch.setattr("app.security.hexstrike.resolve_install", lambda explicit="": None)
    client = TestClient(app)
    response = client.get("/api/hexstrike")
    assert response.status_code == 200
    body = response.json()
    assert body["suite"] == "hexstrike-suite"
    assert body["shape_id"] == "hex_aegis"
    assert body["installed"] is False
    assert body["running"] is False


def test_hexstrike_upstream_denies_command(jarvis_env, monkeypatch):
    monkeypatch.setattr("app.security.hexstrike.load_settings", lambda: jarvis_env["settings"])
    client = TestClient(app)
    denied = client.post("/api/hexstrike/upstream/api/command", json={"cmd": "id"})
    assert denied.status_code == 403


@pytest.mark.asyncio
async def test_activate_suite_does_not_load_inference(jarvis_env, monkeypatch):
    monkeypatch.setattr("app.security.hexstrike.load_settings", lambda: jarvis_env["settings"])
    monkeypatch.setattr("app.security.hexstrike.save_settings", lambda settings: None)

    called = {"load": False}

    async def fake_start():
        from app.security.hexstrike import HEXSTRIKE

        return await HEXSTRIKE.status(enrich=False)

    async def boom(*args, **kwargs):
        called["load"] = True
        raise AssertionError("suite activate must not load an LLM")

    monkeypatch.setattr("app.security.hexstrike.HEXSTRIKE.ensure_started", fake_start)
    monkeypatch.setattr("app.inference.hotswap.MANAGER.load", boom)

    profile = MODEL_CATALOG["hexstrike-suite"].runtime_profile()
    assert profile is not None
    result = await activate_runtime_profile(profile)
    assert called["load"] is False
    assert result is not None


def test_compat_shim_stubs_mitmproxy_without_installing_it():
    from app.security.hexstrike_compat import DISABLED_MESSAGE, install_optional_stubs

    stubbed = install_optional_stubs(force=True)
    assert "mitmproxy" in stubbed
    import mitmproxy
    from mitmproxy.tools.dump import DumpMaster

    try:
        DumpMaster()
        raise AssertionError("proxy stub must fail closed")
    except RuntimeError as exc:
        assert DISABLED_MESSAGE in str(exc)
    assert mitmproxy.__name__ == "mitmproxy"


def test_bootstrap_script_excludes_vulnerable_proxy_stack():
    from pathlib import Path

    text = (Path(__file__).resolve().parents[1] / "scripts" / "bootstrap-hexstrike.ps1").read_text(encoding="utf-8")
    assert "mitmproxy" in text.lower()
    assert "uninstall" in text.lower()
    assert "pwntools" in text.lower()
    assert "hexstrike_compat" in text
    assert "d689933ff579d839c676c82b231f8e98326c5f04" in text
