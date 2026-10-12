"""Pairing-stability: AnzuManager watchdog, launch logs and degraded startup."""
import asyncio

from fastapi.testclient import TestClient

from app import startup_health
from app.manager import main, supervisor as sup


class Clock:
    def __init__(self):
        self.now = 1_000.0

    def __call__(self):
        return self.now


def _make(tmp_path, healthy, present, clock=None):
    calls = []

    async def _healthy():
        return healthy[0]

    s = sup.CoreSupervisor(
        root=lambda: tmp_path,
        healthy=_healthy,
        process_present=lambda: present[0],
        launch=calls.append,
        clock=clock or Clock(),
        enabled=True,
    )
    return s, calls


def run(coro):
    return asyncio.run(coro)


def test_backoff_grows_and_caps():
    assert [sup.backoff_seconds(n) for n in (1, 2, 3, 4)] == [15, 30, 60, 120]
    assert sup.backoff_seconds(20) == sup.BACKOFF_CAP_SECONDS


def test_dead_backend_is_restarted_with_reason_and_error_tail(tmp_path):
    logs = tmp_path / "logs"
    logs.mkdir()
    (logs / "backend.err.log").write_text("Traceback\nRuntimeError: db locked\n", encoding="utf-8")
    clock = Clock()
    s, calls = _make(tmp_path, [False], [False], clock)
    assert run(s.tick()) == "restarted"
    assert calls == ["start"]
    exit_info = s.snapshot()["last_exit"]
    assert "exited" in exit_info["reason"]
    assert exit_info["error_tail"][-1] == "RuntimeError: db locked"
    assert (logs / exit_info["crash_log"]).read_text(encoding="utf-8").startswith("Traceback")
    # the relaunched core gets its launch grace: no double launch
    clock.now += 5
    assert run(s.tick()) == "launch_pending"
    clock.now += sup.LAUNCH_PENDING_GRACE_SECONDS
    assert run(s.tick()) == "restarted"
    assert calls == ["start", "start"]
    assert s.snapshot()["restart_attempts"] == 2


def test_hung_backend_gets_grace_then_stop_and_start(tmp_path):
    clock = Clock()
    s, calls = _make(tmp_path, [False], [True], clock)
    assert run(s.tick()) == "starting"
    clock.now += sup.STARTUP_GRACE_SECONDS + 1
    assert run(s.tick()) == "restarted"
    assert calls == ["stop", "start"]
    assert "hung" in s.snapshot()["last_exit"]["reason"]


def test_owner_stop_is_respected_and_persisted(tmp_path):
    s, calls = _make(tmp_path, [False], [False])
    s.set_desired(False)
    assert run(s.tick()) == "idle"
    assert calls == []
    reloaded, _ = _make(tmp_path, [False], [False])
    assert reloaded.state.desired_running is False


def test_stable_health_resets_attempts(tmp_path):
    clock = Clock()
    healthy = [False]
    s, _ = _make(tmp_path, healthy, [False], clock)
    run(s.tick())
    healthy[0] = True
    run(s.tick())
    clock.now += sup.STABLE_RESET_SECONDS
    run(s.tick())
    assert s.snapshot()["restart_attempts"] == 0


def test_launch_failure_never_crashes_watchdog(tmp_path):
    async def _healthy():
        return False

    def _boom(action):
        raise RuntimeError("Required ANZU script is missing")

    s = sup.CoreSupervisor(root=lambda: tmp_path, healthy=_healthy, process_present=lambda: False, launch=_boom, clock=Clock(), enabled=True)
    assert run(s.tick()) == "restarted"
    assert "missing" in s.snapshot()["last_exit"]["launch_error"]
    assert s.state.restarting is False


def test_rotate_file_keeps_bounded_history(tmp_path):
    path = tmp_path / "anzu-launch.log"
    for index in range(4):
        path.write_text(f"run {index}", encoding="utf-8")
        sup.rotate_file(path, keep=2)
    assert not path.exists()
    assert (tmp_path / "anzu-launch.log.1").read_text(encoding="utf-8") == "run 3"
    assert (tmp_path / "anzu-launch.log.2").read_text(encoding="utf-8") == "run 2"
    assert not (tmp_path / "anzu-launch.log.3").exists()


def test_launch_writes_launcher_output_to_log(monkeypatch, tmp_path):
    (tmp_path / "start-jarvis.ps1").write_text("", encoding="utf-8")
    monkeypatch.setattr(main, "_root", lambda: tmp_path)
    seen = {}

    def fake_popen(args, **kwargs):
        seen.update(kwargs)
        kwargs["stdout"].write(b"launcher said hi\n")

    monkeypatch.setattr(main.subprocess, "Popen", fake_popen)
    main._launch("start")
    text = (tmp_path / "logs" / "anzu-launch.log").read_text(encoding="utf-8")
    assert "=== start" in text and "launcher said hi" in text
    assert seen["stderr"] is main.subprocess.STDOUT


def test_status_reports_supervisor_and_control_sets_desired(monkeypatch, tmp_path):
    monkeypatch.setattr(main, "_root", lambda: tmp_path)
    monkeypatch.setattr(main, "_core_healthy", lambda: _async(False))
    monkeypatch.setattr(main, "_managed_process_running", lambda: False)
    monkeypatch.setattr(main, "hardware_dict", lambda: {})
    monkeypatch.setattr(main, "_launch", lambda action: None)
    monkeypatch.setattr(main, "_wait_for", lambda action: _async({"core": {"healthy": False, "state": "stopped"}}))
    client = TestClient(main.app)
    headers = _token_headers(client)
    client.post("/api/manager/v1/control/stop", json={"confirm": True}, headers=headers)
    body = client.get("/api/manager/v1/status").json()
    assert body["supervisor"]["desired_running"] is False
    client.post("/api/manager/v1/control/start", json={"confirm": True}, headers=headers)
    assert client.get("/api/manager/v1/status").json()["supervisor"]["desired_running"] is True


def test_manager_cors_allows_only_loopback_portal(monkeypatch):
    client = TestClient(main.app)
    pre = {"Access-Control-Request-Method": "POST", "Access-Control-Request-Headers": "content-type"}
    ok = client.options("/api/manager/v1/control/restart", headers={"Origin": "http://127.0.0.1:4780", **pre})
    assert ok.headers.get("access-control-allow-origin") == "http://127.0.0.1:4780"
    bad = client.options("/api/manager/v1/control/restart", headers={"Origin": "https://evil.example", **pre})
    assert "access-control-allow-origin" not in bad.headers


def test_startup_step_failure_degrades_instead_of_crashing():
    startup_health.reset()

    def broken():
        raise RuntimeError("node registry corrupt")

    async def fine():
        return 7

    assert run(startup_health.run_step("localhost_node", broken)) is None
    assert run(startup_health.run_step("database", fine)) == 7
    report = startup_health.report()
    assert report["degraded"] is True
    assert report["failed_steps"][0]["step"] == "localhost_node"
    assert "node registry corrupt" in report["failed_steps"][0]["error"]
    assert report["completed_steps"] == ["database"]
    startup_health.reset()


def test_critical_step_failure_makes_health_not_ready():
    import app.main as core_main

    startup_health.reset()

    async def broken_db():
        raise RuntimeError("database is locked")

    run(startup_health.run_step("database", broken_db, critical=True))
    body = run(core_main.health())
    assert body["ok"] is False
    assert body["startup"]["ready"] is False
    assert body["startup"]["failed_steps"][0] == {**body["startup"]["failed_steps"][0], "step": "database", "critical": True}
    startup_health.reset()
    assert run(core_main.health())["ok"] is True


def test_watchdog_treats_not_ready_core_as_unhealthy(monkeypatch):
    class Resp:
        is_success = True

        def json(self):
            return {"ok": False, "startup": {"ready": False}}

    class Client:
        def __init__(self, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return False

        async def get(self, url):
            return Resp()

    monkeypatch.setattr(main.httpx, "AsyncClient", Client)
    assert run(main._core_healthy()) is False


def test_watchdog_stands_down_during_owner_control(tmp_path):
    clock = Clock()
    s, calls = _make(tmp_path, [False], [False], clock)

    async def scenario():
        async with s.control_action("restart"):
            assert await s.tick() == "control_in_flight"
        # the owner's start gets the launch grace before the watchdog may act
        assert await s.tick() == "launch_pending"

    run(scenario())
    assert calls == []
    clock.now += sup.LAUNCH_PENDING_GRACE_SECONDS + 1
    assert run(s.tick()) == "restarted"


def test_control_requires_session_token_and_rejects_concurrent_action(monkeypatch):
    monkeypatch.setattr(main, "_launch", lambda action: None)
    monkeypatch.setattr(main, "_wait_for", lambda action: _async({"core": {"healthy": True, "state": "ready"}}))
    client = TestClient(main.app)
    assert client.post("/api/manager/v1/control/restart", json={"confirm": True}).status_code == 403
    bad = {"X-Anzu-Manager-Token": "nope"}
    assert client.post("/api/manager/v1/control/restart", json={"confirm": True}, headers=bad).status_code == 403
    headers = _token_headers(client)
    main.SUPERVISOR.state.control_in_flight = "stop"
    try:
        assert client.post("/api/manager/v1/control/start", json={"confirm": True}, headers=headers).status_code == 409
    finally:
        main.SUPERVISOR.state.control_in_flight = None
    assert client.post("/api/manager/v1/control/start", json={"confirm": True}, headers=headers).status_code == 200


def _token_headers(client):
    session = client.get("/api/manager/v1/session").json()
    return {session["header"]: session["token"]}


def test_health_endpoint_exposes_startup_report():
    import app.main as core_main

    startup_health.reset()
    run(startup_health.run_step("hardware_snapshot", lambda: (_ for _ in ()).throw(OSError("disk full"))))
    body = run(core_main.health())
    assert body["ok"] is True  # non-critical failure: degraded but still ready
    assert body["startup"]["ready"] is True
    assert body["startup"]["degraded"] is True
    assert body["startup"]["failed_steps"][0]["step"] == "hardware_snapshot"
    startup_health.reset()


async def _async(value):
    return value


def test_watchdog_is_opt_in_via_env(monkeypatch, tmp_path):
    async def _healthy():
        return False

    monkeypatch.delenv("JARVIS_MANAGER_WATCHDOG", raising=False)
    off = sup.CoreSupervisor(root=lambda: tmp_path, healthy=_healthy, process_present=lambda: False, launch=lambda a: None)
    assert off.enabled is False
    assert run(off.tick()) == "idle"
    monkeypatch.setenv("JARVIS_MANAGER_WATCHDOG", "1")
    on = sup.CoreSupervisor(root=lambda: tmp_path, healthy=_healthy, process_present=lambda: False, launch=lambda a: None)
    assert on.enabled is True
    assert main.SUPERVISOR.enabled is False  # test/import context never supervises
