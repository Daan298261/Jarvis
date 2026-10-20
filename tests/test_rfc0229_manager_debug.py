"""RFC-0229 S1: Manager debug logger, redaction, verbose toggle and control progress."""
import asyncio
import json
import os
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.manager import debug_log, main, redact
from app.manager import supervisor as sup

BACKEND = Path(__file__).resolve().parents[1] / "backend"
MANAGER_ORIGIN = {"Origin": "http://127.0.0.1:4782"}


async def _async(value):
    return value


@pytest.fixture
def root(tmp_path, monkeypatch):
    monkeypatch.setenv("JARVIS_ROOT", str(tmp_path))
    monkeypatch.setattr(main, "_root", lambda: tmp_path)
    monkeypatch.setattr(debug_log, "_verbose", False)
    main.CONTROL_PROGRESS.clear()
    main.SUPERVISOR.state.control_in_flight = None
    main.SUPERVISOR.state.launch_pending_until = 0.0
    yield tmp_path
    main.CONTROL_PROGRESS.clear()


def _lines(root):
    path = root / "logs" / debug_log.LOG_NAME
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]


def _all_log_text(root):
    return "".join(p.read_text(encoding="utf-8") for p in sorted((root / "logs").glob("manager-debug.log*")))


def _token(client):
    session = client.get("/api/manager/v1/session").json()
    return {session["header"]: session["token"]}


def _ready_core(monkeypatch, calls=None):
    monkeypatch.setattr(main, "_launch", (calls.append if calls is not None else (lambda action: None)))
    monkeypatch.setattr(
        main,
        "_wait_for",
        lambda action: _async({"core": {"healthy": action != "stop", "state": "stopped" if action == "stop" else "ready"}}),
    )


# --- press / control_start / control_end -------------------------------------------------


def test_each_press_writes_press_start_end_with_same_request_id(root, monkeypatch):
    _ready_core(monkeypatch)
    client = TestClient(main.app)
    response = client.post(
        "/api/manager/v1/control/start",
        json={"confirm": True},
        headers={**_token(client), "X-Anzu-Request-Id": "ui-1234-abcd"},
    )
    assert response.status_code == 200 and response.json()["ok"] is True
    rows = [r for r in _lines(root) if r["request_id"] == "ui-1234-abcd"]
    assert [r["event"] for r in rows] == ["press", "control_start", "control_end"]
    end = rows[-1]
    assert end["ok"] is True and isinstance(end["duration_ms"], int) and end["duration_ms"] >= 0
    assert end["action"] == "start" and end["level"] == "INFO"
    assert set(end) == {"ts", "level", "event", "action", "request_id", "duration_ms", "ok", "detail"}


def test_rejected_or_failed_press_is_logged_with_ok_false(root, monkeypatch):
    _ready_core(monkeypatch)
    client = TestClient(main.app)
    assert client.post("/api/manager/v1/control/stop", json={"confirm": True}, headers={"X-Anzu-Request-Id": "ui-no-token"}).status_code == 403

    def broken(action):
        raise RuntimeError("Required ANZU script is missing")

    monkeypatch.setattr(main, "_launch", broken)
    response = client.post("/api/manager/v1/control/start", json={"confirm": True}, headers={**_token(client), "X-Anzu-Request-Id": "ui-broken"})
    assert response.status_code == 503
    rows = _lines(root)
    rejected = [r for r in rows if r["request_id"] == "ui-no-token"]
    assert [r["event"] for r in rejected] == ["press", "control_end"]
    assert rejected[-1]["ok"] is False and "403" in rejected[-1]["detail"]["error"]
    broken_rows = [r for r in rows if r["request_id"] == "ui-broken"]
    assert [r["event"] for r in broken_rows] == ["press", "control_start", "control_end"]
    assert broken_rows[-1]["ok"] is False and "script is missing" in broken_rows[-1]["detail"]["error"]


def test_missing_or_malformed_request_id_gets_a_server_id(root, monkeypatch):
    _ready_core(monkeypatch)
    client = TestClient(main.app)
    client.post("/api/manager/v1/control/start", json={"confirm": True}, headers={**_token(client), "X-Anzu-Request-Id": "bad id\nwith newline"})
    ids = {r["request_id"] for r in _lines(root) if r["event"] == "press"}
    assert len(ids) == 1 and next(iter(ids)).startswith("srv-")


# --- simulated 30 s restart: phases, elapsed, duration ---------------------------------


def test_simulated_30s_restart_reports_phases_elapsed_and_duration(root, monkeypatch):
    now = [100.0]
    monkeypatch.setattr(main, "_clock", lambda: now[0])
    seen = []
    probe = TestClient(main.app)

    def progress():
        seen.append(probe.get("/api/manager/v1/control/progress").json())

    def launch(action):
        progress()
        now[0] += 10.0 if action == "stop" else 5.0

    async def wait_for(action):
        progress()
        now[0] += 5.0 if action == "stop" else 10.0
        return {"core": {"healthy": action != "stop", "state": "stopped" if action == "stop" else "ready"}}

    monkeypatch.setattr(main, "_launch", launch)
    monkeypatch.setattr(main, "_wait_for", wait_for)
    client = TestClient(main.app)
    response = client.post("/api/manager/v1/control/restart", json={"confirm": True}, headers={**_token(client), "X-Anzu-Request-Id": "ui-restart-30"})
    assert response.status_code == 200 and response.json()["ok"] is True
    assert [p["phase_text"] for p in seen] == ["Stopping…", "Waiting for ANZU to stop…", "Starting…", "Waiting for health…"]
    assert [p["elapsed_ms"] for p in seen] == [0, 10_000, 15_000, 20_000]
    assert all(p["active"] and p["request_id"] == "ui-restart-30" and p["action"] == "restart" for p in seen)
    end = [r for r in _lines(root) if r["event"] == "control_end"][-1]
    assert end["duration_ms"] == 30_000 and end["ok"] is True
    assert probe.get("/api/manager/v1/control/progress").json() == {"active": False}


# --- redaction (UX #2) -------------------------------------------------------------------


def test_redaction_in_log_and_endpoint(root, monkeypatch):
    _ready_core(monkeypatch)
    debug_log.set_verbose(True)  # DEBUG lines carry the request headers and spawn argv
    monkeypatch.setenv("ANZU_TEST_ENV_SECRET", "env-value-q7")
    case_path = redact.investigations_dir() / "case-42" / "evidence.bin"
    client = TestClient(main.app)
    client.post(
        "/api/manager/v1/control/start",
        json={"confirm": True},
        headers={**_token(client), "Authorization": "Bearer bearer-x-secret", "X-API-Key": "hdr-key-9", "Cookie": "sid=cookie-5"},
    )
    debug_log.spawn(
        "start",
        ["llama-server", "--api-key", "sk-1-secret", "--token=t-secret", "HF_TOKEN=h-secret", "--port", "8088", str(case_path)],
        {"HF_TOKEN": "env-h-secret", "PATH": "/usr/bin"},
    )
    debug_log.write(
        "INFO",
        "supervisor",
        action="restart",
        detail={"message": "owner said hello there", "prompt": "summarise", "path": str(case_path), "env": {"OPENAI_API_KEY": "env-k-secret"}},
    )
    body = client.get("/api/manager/v1/debug-log?tail=200").json()
    endpoint = json.dumps(body)
    disk = _all_log_text(root)
    for secret in (
        "bearer-x-secret", "hdr-key-9", "cookie-5", "sk-1-secret", "t-secret", "h-secret", "env-h-secret",
        "env-k-secret", "env-value-q7", "owner said hello", "summarise", "case-42", "evidence.bin", main.SESSION_TOKEN,
    ):
        assert secret not in disk, secret
        assert secret not in endpoint, secret
    spawn = next(r for r in body["lines"] if r["detail"] and r["detail"].get("argv_redacted"))
    assert spawn["detail"]["argv_redacted"] == ["llama-server", "--api-key", "***", "--token=***", "HF_TOKEN=***", "--port", "8088", "<case-file>"]
    assert spawn["detail"]["env_names"] == ["HF_TOKEN", "PATH"]
    note = next(r for r in body["lines"] if r["event"] == "supervisor" and r["action"] == "restart")
    assert note["detail"]["message"] == "<22 chars>" and note["detail"]["prompt"] == "<9 chars>"
    assert note["detail"]["path"] == "<case-file>"
    assert note["detail"]["env_names"] == ["OPENAI_API_KEY"]
    headers = next(r for r in body["lines"] if r["level"] == "DEBUG" and r["event"] == "press")["detail"]["headers"]
    assert headers["authorization"] == "***" and headers["x-anzu-manager-token"] == "***" and headers["cookie"] == "***"


def test_launcher_spawn_logs_redacted_argv_and_env_names_only(root, monkeypatch):
    (root / "start-jarvis.ps1").write_text("", encoding="utf-8")
    monkeypatch.setattr(main.subprocess, "Popen", lambda args, **kwargs: None)
    monkeypatch.setenv("ANZU_TEST_ENV_SECRET", "env-value-launch")
    debug_log.set_verbose(True)
    token = debug_log.bind_control("start", "ui-launch")
    try:
        main._launch("start")
    finally:
        debug_log.unbind_control(token)
    rows = [r for r in _lines(root) if r["detail"] and "argv_redacted" in r["detail"]]
    assert rows and rows[-1]["event"] == "control_start" and rows[-1]["request_id"] == "ui-launch"
    assert rows[-1]["detail"]["argv_redacted"][0] == "powershell.exe"
    assert "ANZU_TEST_ENV_SECRET" in rows[-1]["detail"]["env_names"]
    assert "env-value-launch" not in _all_log_text(root)
    debug_log.set_verbose(False)
    main._launch("start")  # spawn detail is DEBUG only
    assert len([r for r in _lines(root) if r["detail"] and "argv_redacted" in r["detail"]]) == 1


def test_redact_rules_unit(root):
    assert redact.redact_argv(["--key", "k", "--SECRET=s", "--auth", "a", "--bearer", "b", "--password", "p", "--hf-token", "h"]) == [
        "--key", "***", "--SECRET=***", "--auth", "***", "--bearer", "***", "--password", "***", "--hf-token", "***",
    ]
    assert redact.redact_argv(["db_pass=x", "MyCredential=y", "auth_mode=z", "PORT=8088"]) == ["db_pass=***", "MyCredential=***", "auth_mode=***", "PORT=8088"]
    assert redact.redact_headers({"Set-Cookie": "a", "Api-Key": "b", "X-Jarvis-Key": "c", "Accept": "json"}) == {
        "Set-Cookie": "***", "Api-Key": "***", "X-Jarvis-Key": "***", "Accept": "json",
    }
    assert redact.redact_env({"A": "1"}, debug=False) is None
    assert redact.redact({"transcript": "abc", "content": "<3 chars>", "text": "hello"}) == {"transcript": "<3 chars>", "content": "<3 chars>", "text": "<5 chars>"}
    case = str(redact.investigations_dir()).replace("/", "\\") + "\\c1\\f.txt"
    assert redact.redact_text(f"could not open {case} now") == "could not open <case-file> now"
    assert redact.redact({"env": {"X": "1"}}, debug=False) == {}


# --- disk cap (UX #2) --------------------------------------------------------------------


def test_disk_cap_30_mib_of_events(root):
    chunk = "x" * 8000
    written = 0
    while written < 30 * 1024 * 1024:
        debug_log.write("INFO", "supervisor", action="tick", detail={"pad": chunk})
        written += len(chunk) + 120
    files = sorted((root / "logs").glob("manager-debug.log*"))
    sizes = [p.stat().st_size for p in files]
    assert len(files) <= 6
    assert {p.name for p in files} == {"manager-debug.log"} | {f"manager-debug.log.{i}" for i in range(1, 6)}
    assert all(size <= 2 * 1024 * 1024 for size in sizes), sizes
    assert sum(sizes) <= 12 * 1024 * 1024
    assert debug_log.MAX_BYTES == sup.LAUNCH_LOG_MAX_BYTES == 2 * 1024 * 1024 and debug_log.KEPT == sup.LAUNCH_LOGS_KEPT == 5


def test_oversized_record_is_truncated_to_one_bounded_line(root):
    record = debug_log.write("INFO", "supervisor", detail={"pad": "y" * (debug_log.MAX_LINE_BYTES * 2)})
    assert record["detail"]["truncated"] is True
    assert (root / "logs" / debug_log.LOG_NAME).stat().st_size < debug_log.MAX_LINE_BYTES


# --- verbose (UX #4) ---------------------------------------------------------------------


def test_verbose_off_at_start_and_only_manager_page_with_token_can_enable(root, monkeypatch):
    _ready_core(monkeypatch)
    client = TestClient(main.app)
    assert client.get("/api/manager/v1/debug-log").json()["verbose"] is False
    url = "/api/manager/v1/debug-log/verbose"
    # refused: no token, foreign origin (the :4780 portal can read /session), no origin, non-loopback client
    assert client.post(url, json={"enabled": True}, headers=MANAGER_ORIGIN).status_code == 403
    assert client.post(url, json={"enabled": True}, headers={**_token(client), "Origin": "http://127.0.0.1:4780"}).status_code == 403
    assert client.post(url, json={"enabled": True}, headers={**_token(client), "Origin": "https://evil.example"}).status_code == 403
    assert client.post(url, json={"enabled": True}, headers=_token(client)).status_code == 403
    remote = TestClient(main.app, client=("192.168.1.20", 50000))
    assert remote.post(url, json={"enabled": True}, headers={**_token(client), **MANAGER_ORIGIN}).status_code == 403
    assert debug_log.is_verbose() is False
    client.post("/api/manager/v1/control/start", json={"confirm": True}, headers=_token(client))
    assert not [r for r in _lines(root) if r["level"] == "DEBUG"]
    # accepted: token + Manager origin
    for origin in ("http://127.0.0.1:4782", "http://localhost:4782"):
        ok = client.post(url, json={"enabled": True}, headers={**_token(client), "Origin": origin})
        assert ok.status_code == 200 and ok.json() == {"verbose": True}
    client.post("/api/manager/v1/control/start", json={"confirm": True}, headers=_token(client))
    assert [r for r in _lines(root) if r["level"] == "DEBUG"]
    assert client.get("/api/manager/v1/debug-log").json()["verbose"] is True
    # no file anywhere under the install root holds the verbose state
    for path in root.rglob("*"):
        if path.is_file():
            assert "verbose" not in path.read_text(encoding="utf-8", errors="replace").lower(), path
    off = client.post(url, json={"enabled": False}, headers={**_token(client), **MANAGER_ORIGIN})
    assert off.json() == {"verbose": False}


def test_verbose_resets_to_off_on_manager_restart(tmp_path):
    script = textwrap.dedent(
        """
        import sys
        from fastapi.testclient import TestClient
        from app.manager import debug_log, main
        client = TestClient(main.app)
        print("START", client.get("/api/manager/v1/debug-log").json()["verbose"])
        if sys.argv[1] == "enable":
            s = client.get("/api/manager/v1/session").json()
            r = client.post("/api/manager/v1/debug-log/verbose", json={"enabled": True},
                            headers={s["header"]: s["token"], "Origin": "http://127.0.0.1:4782"})
            print("SET", r.json()["verbose"])
        """
    )
    env = {**os.environ, "PYTHONPATH": str(BACKEND), "JARVIS_ROOT": str(tmp_path)}
    env.pop("JARVIS_MANAGER_WATCHDOG", None)
    first = subprocess.run([sys.executable, "-c", script, "enable"], env=env, capture_output=True, text=True, timeout=120)
    assert "START False" in first.stdout and "SET True" in first.stdout, first.stdout + first.stderr
    second = subprocess.run([sys.executable, "-c", script, "check"], env=env, capture_output=True, text=True, timeout=120)
    assert "START False" in second.stdout, second.stdout + second.stderr


# --- debug-log endpoint ------------------------------------------------------------------


def test_debug_log_endpoint_returns_last_n_lines_across_rotation(root):
    for index in range(150):
        debug_log.write("INFO", "supervisor", action="tick", detail={"n": index})
    sup.rotate_file(root / "logs" / debug_log.LOG_NAME, debug_log.KEPT)
    for index in range(150, 300):
        debug_log.write("INFO", "supervisor", action="tick", detail={"n": index})
    client = TestClient(main.app)
    body = client.get("/api/manager/v1/debug-log?tail=200").json()
    assert [row["detail"]["n"] for row in body["lines"]] == list(range(100, 300))
    assert [row["detail"]["n"] for row in client.get("/api/manager/v1/debug-log?tail=5").json()["lines"]] == [295, 296, 297, 298, 299]
    assert len(client.get("/api/manager/v1/debug-log").json()["lines"]) == 200
    assert client.get("/api/manager/v1/debug-log?tail=0").status_code == 422


def test_debug_log_endpoint_rejects_non_loopback(root):
    debug_log.write("INFO", "supervisor", action="tick")
    remote = TestClient(main.app, client=("203.0.113.10", 40000))
    response = remote.get("/api/manager/v1/debug-log")
    assert response.status_code == 403
    assert response.json() == {"detail": "ANZU Manager is available only on this computer"}
    assert remote.get("/api/manager/v1/control/progress").status_code == 403
    assert TestClient(main.app, client=("127.0.0.1", 40000)).get("/api/manager/v1/debug-log").status_code == 200


# --- supervisor events and status errors -------------------------------------------------


class _Clock:
    def __init__(self):
        self.now = 1_000.0

    def __call__(self):
        return self.now


def test_supervisor_restart_backoff_and_crash_log_reach_debug_log(root, monkeypatch):
    logs = root / "logs"
    logs.mkdir()
    (logs / "backend.err.log").write_text("Traceback\nRuntimeError: db locked\n", encoding="utf-8")
    s = main.SUPERVISOR
    clock = _Clock()
    monkeypatch.setattr(s, "enabled", True)
    monkeypatch.setattr(s, "state", sup.SupervisorState())
    monkeypatch.setattr(s, "_clock", clock)
    monkeypatch.setattr(s, "_last_tick", None)
    monkeypatch.setattr(main, "_core_healthy", lambda: _async(False))
    monkeypatch.setattr(main, "_managed_process_running", lambda: False)
    launches = []
    monkeypatch.setattr(main, "_launch", launches.append)
    assert asyncio.run(s.tick()) == "restarted"
    s.state.launch_pending_until = 0.0
    s.state.next_restart_at = clock.now + 500
    assert asyncio.run(s.tick()) == "backoff"
    assert asyncio.run(s.tick()) == "backoff"  # unchanged decision: no second line

    def broken(action):
        raise RuntimeError("Required ANZU script is missing")

    monkeypatch.setattr(main, "_launch", broken)
    s.state.next_restart_at = 0.0
    assert asyncio.run(s.tick()) == "restarted"
    rows = [r for r in _lines(root) if r["event"] == "supervisor"]
    restart = next(r for r in rows if r["action"] == "restart")
    assert restart["level"] == "WARNING" and "exited" in restart["detail"]["reason"]
    assert restart["detail"]["crash_log"].startswith("backend-crash-") and restart["detail"]["attempt"] == 1
    assert (logs / restart["detail"]["crash_log"]).is_file()
    backoffs = [r for r in rows if r["action"] == "backoff"]
    assert len(backoffs) == 1 and backoffs[0]["level"] == "INFO" and backoffs[0]["detail"]["next_restart_in_seconds"] == 500
    failed = next(r for r in rows if r["action"] == "restart_failed")
    assert failed["level"] == "ERROR" and "script is missing" in failed["detail"]["error"]


def test_supervisor_tick_changes_are_debug_lines(root, monkeypatch):
    s = main.SUPERVISOR
    monkeypatch.setattr(s, "_last_tick", None)
    monkeypatch.setattr(s, "enabled", False)
    asyncio.run(s.tick())
    assert not (root / "logs" / debug_log.LOG_NAME).exists()  # DEBUG is filtered when verbose is off
    debug_log.set_verbose(True)
    monkeypatch.setattr(s, "_last_tick", None)
    asyncio.run(s.tick())
    asyncio.run(s.tick())
    ticks = [r for r in _lines(root) if r["action"] == "tick"]
    assert len(ticks) == 1 and ticks[0]["level"] == "DEBUG" and ticks[0]["detail"] == {"result": "idle"}


def test_core_details_failure_writes_status_error(root, monkeypatch):
    class Client:
        def __init__(self, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return False

        async def get(self, url):
            raise OSError("connection reset")

    monkeypatch.setattr(main, "_core_healthy", lambda: _async(True))
    monkeypatch.setattr(main.httpx, "AsyncClient", Client)
    assert asyncio.run(main._core_details())["tasks"] == {"active": 0, "total": 0}
    row = _lines(root)[-1]
    assert row["event"] == "status_error" and row["level"] == "WARNING" and "connection reset" in row["detail"]["error"]


def test_unknown_event_or_level_is_a_programming_error(root):
    with pytest.raises(ValueError):
        debug_log.write("INFO", "made_up")
    with pytest.raises(ValueError):
        debug_log.write("LOUD", "press")


def test_event_enum_matches_spec_including_process_view(root):
    # RFC-0229 "Debug logger": event is one of press, control_start, control_end,
    # supervisor, status_error, process_view (process_view is emitted by S2).
    assert debug_log.EVENTS == {"press", "control_start", "control_end", "supervisor", "status_error", "process_view"}
    debug_log.write("WARNING", "process_view", detail={"error": "registry fallback", "argv": ["llama-server", "--api-key", "sekrit"]})
    row = _lines(root)[-1]
    assert row["event"] == "process_view" and row["level"] == "WARNING"
    assert "sekrit" not in json.dumps(row)
    with pytest.raises(ValueError):
        debug_log.write("INFO", "not_an_event")
