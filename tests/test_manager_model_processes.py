"""Emergency process controls remain usable without a healthy model/core API."""
from unittest.mock import Mock

import httpx
import pytest
from fastapi.testclient import TestClient

from app.manager import main, model_processes as monitor


def process(name="llama-server.exe", command=None, pid=42, created=10.0):
    p = Mock()
    p.pid = pid
    p.name.return_value = name
    p.cmdline.return_value = command or [name, "--model", "C:/models/small.gguf"]
    p.create_time.return_value = created
    p.status.return_value = "running"
    p.memory_info.return_value.rss = 1024**3
    return p


@pytest.fixture
def worker(monkeypatch):
    p = process()
    monkeypatch.setattr(monitor.psutil, "process_iter", lambda: iter([p]))
    monkeypatch.setattr(monitor.psutil, "Process", lambda pid: p)
    return p


def test_monitor_includes_managed_workers_without_http_and_hides_raw_arguments(worker):
    worker.cmdline.return_value += ["--api-key", "private-value"]
    rows = monitor.snapshot()["processes"]
    assert len(rows) == 1
    assert rows[0]["model"] == "small.gguf"
    assert rows[0]["pid"] == 42 and rows[0]["can_kill"]
    assert "private-value" not in str(rows)
    assert "C:/models" not in str(rows)


@pytest.mark.parametrize("name,command,expected", [
    ("ollama.exe", ["ollama", "runner", "--model", "C:/blobs/sha256-abc"], True),
    ("ollama.exe", ["ollama", "serve"], True),
    ("ollama.exe", ["ollama", "list"], False),
    ("ollama.exe", ["ollama", "run", "runner"], False),
    ("ollama.exe", ["ollama", "show", "serve"], False),
    ("python.exe", ["python", "-m", "vllm.entrypoints.openai.api_server"], True),
    ("python.exe", ["python", "-u", "-m", "sglang.launch_server"], True),
    ("python.exe", ["python", "C:/runtime/koboldcpp.py"], True),
    ("python.exe", ["python", "C:/runtime/text-generation-webui/server.py"], True),
    ("python.exe", ["python", "-m", "unrelated.module"], False),
    ("python.exe", ["python"], False),
    ("python.exe", ["python", "my_script.py"], False),
    ("python.exe", ["python", "analyse.py", "--input", "C:/data/colibri.json"], False),
    ("python.exe", ["python", "analyse.py", "--input", "vllm.entrypoints"], False),
    ("Codex.exe", ["Codex", "--model", "small"], False),
])
def test_only_recognized_model_servers_and_workers_are_targets(monkeypatch, name, command, expected):
    monkeypatch.setattr(monitor.psutil, "process_iter", lambda: iter([process(name, command)]))
    assert bool(monitor.snapshot()["processes"]) is expected


def test_hard_kill_is_immediate_and_waits_for_exit(worker):
    row = monitor.snapshot()["processes"][0]
    monitor.hard_kill(row["id"])
    worker.kill.assert_called_once()
    worker.terminate.assert_not_called()
    worker.wait.assert_called_once_with(timeout=5)


def test_python_module_is_not_mistaken_for_model(monkeypatch):
    p = process("python.exe", ["python", "-m", "vllm.entrypoints.openai.api_server",
                              "--model", "owner/small-model"])
    monkeypatch.setattr(monitor.psutil, "process_iter", lambda: iter([p]))
    assert monitor.snapshot()["processes"][0]["model"] == "small-model"


def test_recycled_pid_is_never_killed(worker):
    row = monitor.snapshot()["processes"][0]
    worker.create_time.side_effect = [10.0, 11.0]
    with pytest.raises(ValueError, match="changed"):
        monitor.hard_kill(row["id"])
    worker.kill.assert_not_called()


def test_disappeared_process_is_stale(worker):
    row = monitor.snapshot()["processes"][0]
    worker.create_time.return_value = 11.0
    with pytest.raises(ValueError, match="changed|no longer"):
        monitor.hard_kill(row["id"])
    worker.kill.assert_not_called()


def test_permission_denied_is_visible_but_not_a_kill_target(worker):
    worker.cmdline.side_effect = monitor.psutil.AccessDenied(42)
    row = monitor.snapshot()["processes"][0]
    assert not row["can_kill"] and row["error"]


def test_permission_denied_target_cannot_be_killed(worker):
    worker.cmdline.side_effect = monitor.psutil.AccessDenied(42)
    row = monitor.snapshot()["processes"][0]
    with pytest.raises(ValueError, match="Permission"):
        monitor.hard_kill(row["id"])
    worker.kill.assert_not_called()


@pytest.mark.parametrize("error,expected", [
    (monitor.psutil.NoSuchProcess(42), "no longer"),
    (monitor.psutil.AccessDenied(42), "Permission"),
    (monitor.psutil.TimeoutExpired(5), "not confirmed"),
])
def test_kill_failure_never_reports_success(worker, error, expected):
    row = monitor.snapshot()["processes"][0]
    worker.wait.side_effect = error
    with pytest.raises(ValueError, match=expected):
        monitor.hard_kill(row["id"])


def test_exit_between_enumeration_and_final_check(worker, monkeypatch):
    row = monitor.snapshot()["processes"][0]
    monkeypatch.setattr(monitor.psutil, "Process", Mock(side_effect=monitor.psutil.NoSuchProcess(42)))
    with pytest.raises(ValueError, match="no longer"):
        monitor.hard_kill(row["id"])
    worker.kill.assert_not_called()


def test_process_enumeration_handles_disappearance_and_inaccessible_processes(monkeypatch):
    gone, denied, alive = process(pid=1), process(pid=2), process(pid=3)
    gone.name.side_effect = monitor.psutil.NoSuchProcess(1)
    denied.name.side_effect = monitor.psutil.AccessDenied(2)
    alive.memory_info.side_effect = monitor.psutil.AccessDenied(3)
    monkeypatch.setattr(monitor.psutil, "process_iter", lambda: iter([gone, denied, alive]))
    result = monitor.snapshot()
    assert [row["pid"] for row in result["processes"]] == [3]
    assert result["processes"][0]["rss_bytes"] is None
    assert "1 processes could not be inspected" in result["warning"]


def test_equals_model_option_and_non_model_process_exclusion(worker, monkeypatch):
    worker.cmdline.return_value = ["llama-server.exe", "--model=C:/models/small.gguf"]
    assert monitor.snapshot()["processes"][0]["model"] == "small.gguf"
    worker.name.return_value = "notepad.exe"
    assert monitor.snapshot()["processes"] == []


def test_manager_requires_token_confirmation_and_own_origin(worker, monkeypatch, tmp_path):
    monkeypatch.setenv("JARVIS_ROOT", str(tmp_path))
    client = TestClient(main.app)
    rows = client.get("/api/manager/v1/model-processes").json()["processes"]
    url = f"/api/manager/v1/model-processes/{rows[0]['id']}/kill"
    headers = {main.TOKEN_HEADER: main.SESSION_TOKEN, "Origin": "http://127.0.0.1:4782"}
    assert client.post(url, json={"confirm": True}).status_code == 403
    assert client.post(url, headers=headers, json={"confirm": False}).status_code == 400
    assert client.post(url, headers={**headers, "Origin": "http://evil.example"}, json={"confirm": True}).status_code == 403
    assert client.post("/api/manager/v1/model-processes/invalid/kill", headers=headers,
                       json={"confirm": True}).status_code == 400
    response = client.post(url, headers=headers, json={"confirm": True})
    assert response.status_code == 200 and response.json()["ok"]
    worker.kill.assert_called_once()


async def test_remote_clients_cannot_read_or_kill(worker):
    transport = httpx.ASGITransport(app=main.app, client=("192.0.2.1", 1))
    async with httpx.AsyncClient(transport=transport, base_url="http://manager") as client:
        assert (await client.get("/api/manager/v1/model-processes")).status_code == 403
        assert (await client.post("/api/manager/v1/model-processes/anything/kill",
                                  json={"confirm": True})).status_code == 403


def test_failed_kill_is_reported(worker, monkeypatch, tmp_path):
    monkeypatch.setenv("JARVIS_ROOT", str(tmp_path))
    client = TestClient(main.app)
    row = monitor.snapshot()["processes"][0]
    worker.kill.side_effect = monitor.psutil.AccessDenied(42)
    response = client.post(f"/api/manager/v1/model-processes/{row['id']}/kill",
                           json={"confirm": True}, headers={main.TOKEN_HEADER: main.SESSION_TOKEN,
                           "Origin": "http://127.0.0.1:4782"})
    assert response.status_code == 409
    assert "permission" in response.json()["detail"].lower()
