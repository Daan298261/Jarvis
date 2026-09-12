"""Companion APK generation via the owner UI/API — personalized + generic release paths."""
from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.config import AppSettings
from app.main import app
from app.mobile import provision, store

REPO = Path(__file__).resolve().parents[1]


def _load_build_android():
    source = REPO / "scripts" / "build_android.py"
    spec = importlib.util.spec_from_file_location("jarvis_build_android_test", source)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def owner_client(tmp_path, monkeypatch):
    monkeypatch.setattr("app.config.data_dir", lambda: tmp_path)
    monkeypatch.setattr(store, "data_dir", lambda: tmp_path)
    (tmp_path / "mobile" / "builds").mkdir(parents=True, exist_ok=True)

    settings = AppSettings(
        allowed_directories=[str(tmp_path)],
        auth_required=True,
        auth_token="jarvis_pk_apk_build_owner",
    )
    monkeypatch.setattr("app.main.load_settings", lambda: settings)
    monkeypatch.setattr("app.auth.load_settings", lambda: settings)
    return TestClient(app), {"X-Jarvis-Key": settings.auth_token}


@pytest.fixture
def mobile_env(tmp_path, monkeypatch):
    monkeypatch.setattr(store, "data_dir", lambda: tmp_path)
    return tmp_path


def test_ensure_feature_sources_passes_on_tree():
    module = _load_build_android()
    module.ensure_feature_sources()
    assert "apex_orb" in module.REQUIRED_COMPANION_FEATURES
    assert "whatsapp_contact" in module.REQUIRED_COMPANION_FEATURES
    assert "tasks" in module.REQUIRED_COMPANION_FEATURES


def test_generic_build_starts_without_endpoint(owner_client, monkeypatch):
    client, headers = owner_client
    started = {}

    async def fake_start(endpoint, endpoints=None, *, generic=False):
        started["endpoint"] = endpoint
        started["endpoints"] = endpoints
        started["generic"] = generic
        return {
            "id": "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa",
            "state": "queued",
            "activity": "Preparing generic companion APK",
            "mode": "generic",
            "started_at": 1,
            "updated_at": 1,
            "heartbeat_at": 1,
            "stale": False,
        }

    monkeypatch.setattr(provision, "start", fake_start)
    response = client.post(
        "/api/mobile/manage/builds",
        headers=headers,
        json={"mode": "generic", "prepare_connection": False},
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["mode"] == "generic"
    assert body["state"] == "queued"
    assert started["generic"] is True
    assert started["endpoint"] == ""


def test_personalized_build_auto_prepares_connection(owner_client, monkeypatch):
    client, headers = owner_client
    started = {}

    class FakeConnectivity:
        def snapshot(self):
            return {"endpoints": []}

        async def configure(self, enabled, remote):
            assert enabled is True
            assert remote is True
            return {
                "state": "ready",
                "endpoints": ["https://192.168.1.10:4781"],
                "activity": "ready",
            }

    async def fake_start(endpoint, endpoints=None, *, generic=False):
        started.update(endpoint=endpoint, endpoints=endpoints, generic=generic)
        return {
            "id": "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb",
            "state": "queued",
            "activity": "Preparing Android build",
            "mode": "personalized",
            "started_at": 1,
            "updated_at": 1,
            "heartbeat_at": 1,
            "stale": False,
        }

    monkeypatch.setattr("app.mobile.connectivity.CONNECTIVITY", FakeConnectivity())
    monkeypatch.setattr(provision, "start", fake_start)
    response = client.post(
        "/api/mobile/manage/builds",
        headers=headers,
        json={"mode": "personalized", "prepare_connection": True, "remote": True},
    )
    assert response.status_code == 200, response.text
    assert response.json()["mode"] == "personalized"
    assert started["generic"] is False
    assert started["endpoint"] == "https://192.168.1.10:4781"


def test_personalized_build_requires_endpoint_without_prepare(owner_client, monkeypatch):
    client, headers = owner_client

    class EmptyConnectivity:
        def snapshot(self):
            return {"endpoints": []}

    monkeypatch.setattr("app.mobile.connectivity.CONNECTIVITY", EmptyConnectivity())
    response = client.post(
        "/api/mobile/manage/builds",
        headers=headers,
        json={"mode": "personalized", "prepare_connection": False, "endpoint": ""},
    )
    assert response.status_code == 400
    assert "generic companion APK" in response.json()["detail"]


def test_execute_generic_records_features(mobile_env, monkeypatch):
    module = _load_build_android()
    features = list(module.REQUIRED_COMPANION_FEATURES)

    def fake_build(progress=None, generic=False, endpoint=None, endpoints=None, firebase=None):
        assert generic is True
        if progress:
            progress("Compiling")
        return {
            "filename": "JarvisCompanion-generic-1.apk",
            "path": "/tmp/JarvisCompanion-generic-1.apk",
            "sha256": "abc",
            "mode": "generic",
            "features": features,
        }

    class FakeLoader:
        def exec_module(self, mod):
            mod.build = fake_build

    class FakeSpec:
        loader = FakeLoader()

    monkeypatch.setattr(importlib.util, "spec_from_file_location", lambda *a, **k: FakeSpec())
    monkeypatch.setattr(importlib.util, "module_from_spec", lambda spec: type("M", (), {})())

    with store.database() as db:
        store.put(
            db,
            "build",
            "job-generic",
            {
                "id": "job-generic",
                "state": "queued",
                "activity": "Preparing",
                "mode": "generic",
                "started_at": 1,
                "updated_at": 1,
                "heartbeat_at": 1,
            },
        )

    assert provision.BUILD_LOCK.acquire(blocking=False)
    try:
        provision.execute("job-generic", "", [], generic=True)
    finally:
        if provision.BUILD_LOCK.locked():
            provision.BUILD_LOCK.release()

    job = provision.job("job-generic")
    assert job["state"] == "completed"
    assert job["mode"] == "generic"
    assert job["result"]["features"] == features
