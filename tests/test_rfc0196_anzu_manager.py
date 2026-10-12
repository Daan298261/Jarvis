from fastapi.testclient import TestClient

from app.manager import main


def test_manager_status_is_local_aggregate(monkeypatch, tmp_path):
    monkeypatch.setattr(main, "_root", lambda: tmp_path)
    monkeypatch.setattr(main, "_core_healthy", lambda: _async(False))
    monkeypatch.setattr(main, "_managed_process_running", lambda: False)
    monkeypatch.setattr(main, "hardware_dict", lambda: {"ram_available_gb": 12, "gpu_name": None})
    response = TestClient(main.app).get("/api/manager/v1/status")
    assert response.status_code == 200
    assert response.json()["core"]["state"] == "stopped"
    assert response.json()["manager"]["bind"] == "127.0.0.1:4782"
    assert response.json()["agents"]["tasks"] == {"active": 0, "total": 0}


def test_manager_control_requires_confirmation():
    client = TestClient(main.app)
    session = client.get("/api/manager/v1/session").json()
    response = client.post("/api/manager/v1/control/start", json={}, headers={session["header"]: session["token"]})
    assert response.status_code == 400


def test_manager_control_runs_only_confirmed_action(monkeypatch):
    calls = []
    monkeypatch.setattr(main, "_launch", calls.append)
    monkeypatch.setattr(main, "_wait_for", lambda action: _async({"core": {"healthy": True, "state": "ready"}}))
    response = _client_post("/api/manager/v1/control/start")
    assert response.status_code == 200
    assert response.json()["ok"] is True
    assert calls == ["start"]


def test_manager_restart_stops_before_start(monkeypatch):
    calls = []
    monkeypatch.setattr(main, "_launch", calls.append)
    monkeypatch.setattr(main, "_wait_for", lambda action: _async({"core": {"healthy": action != "stop", "state": "stopped" if action == "stop" else "ready"}}))
    response = _client_post("/api/manager/v1/control/restart")
    assert response.status_code == 200
    assert calls == ["stop", "start"]


async def _async(value):
    return value


def _client_post(path):
    client = TestClient(main.app)
    session = client.get("/api/manager/v1/session").json()
    return client.post(path, json={"confirm": True}, headers={session["header"]: session["token"]})
