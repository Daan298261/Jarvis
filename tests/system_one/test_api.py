from __future__ import annotations

from fastapi.testclient import TestClient

from app.decision.audit import reset_audit
from app.decision.jev_client import reset_http_post
from app.decision.laya import pins as laya_pins
from app.decision.laya import runtime as laya_runtime
from app.decision import cache, metrics
from app.main import app
from app.licensing.store import reset_licensing_store


def test_reflex_metrics_and_laya_api(jarvis_env, monkeypatch):
    tmp = jarvis_env["tmp"]
    monkeypatch.setattr("app.config.data_dir", lambda: tmp)
    monkeypatch.setattr("app.decision.laya.pins.data_dir", lambda: tmp)
    reset_licensing_store()
    reset_audit()
    reset_http_post()
    cache.clear()
    metrics.reset_metrics()
    laya_runtime.reset_runtime()
    laya_pins.clear_install()

    client = TestClient(app)
    status = client.get("/api/decision/jev")
    assert status.status_code == 200
    body = status.json()
    assert body["public_availability"] is True
    assert body["requires_probe"] is True
    assert body["requires_cloud_opt_in"] is True
    assert "early access" not in (body.get("owner_error") or "").lower()

    metrics_resp = client.get("/api/decision/reflex/metrics")
    assert metrics_resp.status_code == 200
    assert "decision_classes" in metrics_resp.json()
    assert "quartermaster" in metrics_resp.json()

    laya = client.get("/api/decision/laya")
    assert laya.status_code == 200
    assert laya.json()["license"] == "Apache-2.0"
    assert laya.json()["loopback_only"] is True

    bad = client.post("/api/decision/laya/enable", json={"warm": True})
    assert bad.status_code == 400

    laya_pins.write_test_install()
    ok = client.post("/api/decision/laya/enable", json={"warm": True})
    assert ok.status_code == 200
    assert ok.json()["warm"] is True

    disabled = client.post("/api/decision/laya/disable")
    assert disabled.status_code == 200
    assert disabled.json()["enabled"] is False
