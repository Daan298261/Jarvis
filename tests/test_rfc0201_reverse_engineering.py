from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.reverse_engineering import store
from app.reverse_engineering.runtime import Investigations, approval_target
from app.reverse_engineering.skill import prompt_block


@pytest.fixture
def investigation_env(tmp_path, monkeypatch):
    monkeypatch.setattr(store, "data_dir", lambda: tmp_path)
    from app.policy import approval_grant, store as policy_store
    monkeypatch.setattr(approval_grant, "data_dir", lambda: tmp_path)
    monkeypatch.setattr(policy_store, "data_dir", lambda: tmp_path)
    return tmp_path


def source_target(tmp_path):
    p = tmp_path / "App ü with spaces"
    p.mkdir()
    (p / "main.py").write_text("def storage_key():\n    return 'ANZU_STORE_V1'\n", encoding="utf-8")
    return p


def test_prepare_preserves_bytes_and_records_identity(investigation_env):
    p = source_target(investigation_env)
    row = store.prepare(str(p), "How does storage work?", [str(investigation_env)], "task-1")
    assert row["kind"] == "source"
    assert Path(row["snapshot"]).is_dir()
    assert row["sha256"] == store.fingerprint(Path(row["snapshot"]))[0]
    assert row["task_id"] == "task-1"
    assert len(row["manifest"]) == 1


def test_snapshot_modification_is_rejected(investigation_env):
    p = source_target(investigation_env)
    row = store.prepare(str(p), "Explain storage", [str(investigation_env)], None)
    (Path(row["snapshot"]) / "main.py").write_text("changed")
    with pytest.raises(ValueError, match="changed"):
        store.validate_snapshot(row)


def test_outside_directory_and_empty_questions_fail(investigation_env):
    p = source_target(investigation_env)
    with pytest.raises(PermissionError):
        store.prepare(str(p), "Explain", [str(investigation_env / "other")], None)
    with pytest.raises(ValueError, match="question"):
        store.prepare(str(p), "", [str(investigation_env)], None)


@pytest.mark.parametrize("ident", ["../escape", "a" * 31, "a" * 33, "A" * 32])
def test_store_ids_are_contained(investigation_env, ident):
    with pytest.raises(ValueError):
        store.directory(ident)


def test_report_requires_real_evidence_and_declares_unknowns(investigation_env):
    p = source_target(investigation_env)
    row = store.prepare(str(p), "Explain storage", [str(investigation_env)], None)
    service = Investigations()
    service.record(row, "source_read", {}, {"text": "ANZU_STORE_V1"})
    with pytest.raises(ValueError, match="evidence"):
        store.write_report(row, [{"claim": "Storage works", "kind": "observation", "evidence_ids": ["fabricated"]}], [])
    store.write_report(row, [{"claim": "Uses ANZU_STORE_V1", "kind": "observation", "evidence_ids": ["E00001"]}], ["Runtime not observed"])
    assert row["status"] == "partial"
    assert "Runtime not observed" in (store.directory(row["id"]) / "report.md").read_text()
    assert json.loads((store.directory(row["id"]) / "report.json").read_text())["sha256"] == row["sha256"]


def test_routing_and_both_harnesses_expose_skill():
    from app.agent.planning import route_request
    from app.agent.ingress_gate import heuristic_needs_tools
    from app.agent.local_harness import LocalHarnessPolicy, load_skill_blocks
    from app.agent.tool_exposure import tool_names_for
    prompt = r"Reverse engineer C:\Apps\notes.exe. How does it search?"
    route = route_request(prompt)
    assert route.kind == "managed_task"
    assert route.task_class == "reverse engineering"
    assert heuristic_needs_tools(prompt, route.task_class) is True
    assert "reverse_engineer" in tool_names_for(route.task_class, prompt=prompt)
    assert "reverse_engineer" in prompt_block(prompt)
    assert any("reverse_engineer" in block for block in load_skill_blocks(LocalHarnessPolicy(task_class=route.task_class), prompt))


async def test_cross_task_access_is_denied(investigation_env):
    p = source_target(investigation_env)
    service = Investigations()
    row = await service.prepare(str(p), "Storage", [str(investigation_env)], "a")
    with pytest.raises(PermissionError):
        service.owned(row["id"], "b")


async def test_secondary_paths_cannot_escape(investigation_env, monkeypatch):
    p = source_target(investigation_env)
    row = store.prepare(str(p), "Storage", [str(investigation_env)], None)
    monkeypatch.setattr("app.reverse_engineering.provision.linux_path", lambda path: "/mapped/" + Path(path).name)
    service = Investigations()
    with pytest.raises(PermissionError):
        await service._map_arguments(row, {"path": str(investigation_env / "secret")})
    mapped = await service._map_arguments(row, {"path": row["target"]})
    assert mapped["path"].startswith("/mapped/")


def test_approval_binds_exact_operation_and_arguments():
    base = {"action": "call", "investigation_id": "a" * 32, "operation": "android_capture", "arguments": {"package": "org.example"}}
    assert approval_target(base) == approval_target({**base, "confirmed": True})
    assert approval_target(base) != approval_target({**base, "arguments": {"package": "org.other"}})
    from app.policy.reversibility import resolve_action_effect
    assert resolve_action_effect("reverse_engineer", arguments=base).high_consequence
    assert not resolve_action_effect("reverse_engineer", arguments={**base, "operation": "search_strings"}).side_effecting


async def test_runtime_approval_is_enforced_without_actor(investigation_env):
    p = investigation_env / "sample.apk"
    p.write_bytes(b"fixture")
    service = Investigations()
    row = await service.prepare(str(p), "Behavior", [str(investigation_env)], None)
    result = await service.call(row["id"], "android_capture", {"package": "org.example", "activity": ".MainActivity"}, None)
    assert result["status"] == "pending_approval"
    assert not service.sessions


async def test_unknown_operation_rejected_before_provider(investigation_env):
    p = source_target(investigation_env)
    service = Investigations()
    row = await service.prepare(str(p), "Storage", [str(investigation_env)], None)
    with pytest.raises(PermissionError):
        await service.call(row["id"], "execute_shell", {}, None)


async def test_raw_mcp_and_proxy_cannot_bypass_adapter(monkeypatch):
    from app.tools.mcp_runtime import MCPRuntime
    runtime = MCPRuntime()
    runtime._tools["mcp_custom_capture"] = {"server": {"name": "custom", "args": ["rea-agents@3.2.1", "mcp"]},
                                          "remote_name": "capture_process_scenario", "tool": {"name": "capture_process_scenario"}}
    result = await runtime.call("mcp_custom_capture", {})
    assert not result.success
    assert "blocked" in result.error


async def test_api_has_auth_and_report_download(investigation_env, allow_loopback_api):
    from fastapi.testclient import TestClient
    from app.main import app
    client = TestClient(app)
    row = store.prepare(str(source_target(investigation_env)), "Storage", [str(investigation_env)], None)
    assert client.get(f"/api/investigations/{row['id']}").status_code == 200
    assert client.get(f"/api/investigations/{row['id']}/report").status_code == 404
    assert client.get("/api/investigations/readiness").status_code == 200


def test_android_schema_rejects_shell_injection():
    from jsonschema import ValidationError, validate
    from app.reverse_engineering.android import capture_schema
    with pytest.raises(ValidationError):
        validate({"package": "org.example;id", "activity": ".MainActivity"}, capture_schema()["inputSchema"])


async def test_cancel_stops_active_work_and_persists_cancelled(investigation_env, monkeypatch):
    import asyncio
    from app.reverse_engineering import artifacts
    started, cleaned = asyncio.Event(), asyncio.Event()
    async def slow_materialize(row):
        started.set()
        try:
            await asyncio.sleep(60)
        finally:
            cleaned.set()
    monkeypatch.setattr(artifacts, "materialize", slow_materialize)
    service = Investigations()
    row = await service.prepare(str(source_target(investigation_env)), "Storage", [str(investigation_env)], "a")
    work = asyncio.create_task(service.call(row["id"], "materialize_artifact", {}, "a"))
    await asyncio.wait_for(started.wait(), 5)
    await service.close(row["id"], "a", cancelled=True)
    assert work.cancelled() and cleaned.is_set()
    assert store.load(row["id"])["status"] == "cancelled"
    with pytest.raises(ValueError, match="closed"):
        await service.call(row["id"], "materialize_artifact", {}, "a")


async def test_runtime_grant_cannot_be_changed_or_reused(investigation_env, monkeypatch):
    from app.reverse_engineering import android
    from app.policy.approval_grant import decide_approval_request
    calls = []
    async def capture(row, args):
        calls.append(args)
        return {"observations": [{"text": "observed"}]}
    monkeypatch.setattr(android, "capture", capture)
    target = investigation_env / "fixture.apk"
    target.write_bytes(b"fixture")
    service = Investigations()
    row = await service.prepare(str(target), "Behavior", [str(investigation_env)], "a")
    args = {"package": "org.example", "activity": ".MainActivity"}
    pending = await service.call(row["id"], "android_capture", args, "a")
    grant = decide_approval_request(pending["pending_id"], decision="allow_once", origin_channel="api", actor="owner")["grant"]["id"]
    changed = await service.call(row["id"], "android_capture", {**args, "activity": ".Other"}, "a", grant)
    assert changed["status"] in {"pending_approval", "denied"} and not calls
    assert (await service.call(row["id"], "android_capture", args, "a", grant))["success"]
    repeated = await service.call(row["id"], "android_capture", args, "a", grant)
    assert repeated["status"] in {"pending_approval", "denied"} and len(calls) == 1


async def test_single_source_file_and_changed_snapshot(investigation_env):
    from app.tools.reverse_engineer import ReverseEngineerTool
    target = investigation_env / "single.py"
    target.write_text("answer = 42\n")
    tool = ReverseEngineerTool(lambda: {"allowed_directories": [str(investigation_env)]})
    prepared = await tool.execute(action="prepare", target=str(target), question="Value?", _task_id="a")
    ident = prepared.data["id"]
    result = await tool.execute(action="record_source", investigation_id=ident, arguments={"path": "single.py"}, _task_id="a")
    assert result.success and "42" in result.output
    Path(prepared.data["snapshot"]).write_text("changed")
    result = await tool.execute(action="record_source", investigation_id=ident, arguments={"path": "single.py"}, _task_id="a")
    assert not result.success and "changed" in result.error


def test_archive_traversal_is_rejected(investigation_env):
    import zipfile
    from app.reverse_engineering.artifacts import _extract_zip
    target = investigation_env / "unsafe.zip"
    with zipfile.ZipFile(target, "w") as z:
        z.writestr("../escaped.txt", "unsafe")
    with pytest.raises(ValueError, match="Unsafe"):
        _extract_zip(target, investigation_env / "derived")
    assert not (investigation_env / "escaped.txt").exists()


async def test_completion_requires_task_owned_report(investigation_env, jarvis_env):
    from app.agent.loop import AGENT
    from app.providers.base import ChatMessage
    messages = [ChatMessage(role="user", content="reverse engineer a file")]
    assert not await AGENT._complete("nonexistent", messages, "reverse engineer completed", "verified")
    assert "saved investigation report" in messages[-1].content


def test_investigation_api_requires_owner_auth(investigation_env, monkeypatch):
    from fastapi.testclient import TestClient
    from app.main import app
    monkeypatch.setattr("app.main.authenticate_request", lambda request, settings=None: False)
    client = TestClient(app)
    for method, url in [("GET", "/api/investigations"), ("GET", "/api/investigations/readiness"), ("POST", "/api/investigations/setup")]:
        assert client.request(method, url).status_code == 401
