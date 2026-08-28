from __future__ import annotations

import json
from pathlib import Path

import pytest
from httpx import ASGITransport, AsyncClient

from app.agent.planning import WorkingState
from app.agent.trajectory import record_trajectory
from app.db.models import Task, ToolCallRecord
from app.db.session import SessionLocal
from app.trajectories.adapters.cursor import TrajectoryAdapterError, parse_cursor_transcript
from app.trajectories.consumer import drain_pending_trajectories, enqueue_trajectory, reset_consumer_state
from app.trajectories.native import from_native_trajectory
from app.trajectories.redaction import redact_string, redact_trajectory_payload
from app.trajectories.store import get_trajectory, reset_trajectories_store, save_trajectory

FIXTURES = Path(__file__).resolve().parent / "fixtures" / "trajectories"


@pytest.fixture(autouse=True)
def trajectory_store(tmp_path, monkeypatch):
    monkeypatch.setattr("app.trajectories.store.data_dir", lambda: tmp_path)
    reset_trajectories_store()
    reset_consumer_state()
    yield tmp_path
    reset_consumer_state()


async def _seed_task(task_class: str, title: str) -> str:
    task = Task(id=f"ingest-{title}", title=title, prompt=title, task_class=task_class, verification="checked")
    async with SessionLocal() as session:
        session.add(task)
        session.add(ToolCallRecord(task_id=task.id, tool_name="python", success=True, output="ok"))
        await session.commit()
    return task.id


def test_cursor_adapter_parses_fixture_with_order_and_provenance():
    text = (FIXTURES / "cursor-sample.jsonl").read_text(encoding="utf-8")
    trajectory = parse_cursor_transcript(
        text,
        source_uri="cursor://agent/run-123",
        model="claude-sonnet-4",
    )

    assert trajectory.schema_version == "JarvisTrajectoryV1"
    assert trajectory.provenance.harness == "cursor"
    assert trajectory.provenance.source_format == "cursor-jsonl"
    assert trajectory.provenance.source_uri == "cursor://agent/run-123"
    assert trajectory.provenance.trusted is False
    assert trajectory.workspace.repository == "Daan298261/Jarvis"
    assert trajectory.workspace.branch == "cursor/rfc-0010-trajectories-99ea"
    assert len(trajectory.events) >= 5
    assert trajectory.events[0].sequence < trajectory.events[-1].sequence
    assert trajectory.events[0].timestamp <= trajectory.events[-1].timestamp
    assert trajectory.outcome.verified is True
    assert trajectory.verification is not None and trajectory.verification.passed is True


def test_cursor_adapter_rejects_malformed_jsonl():
    with pytest.raises(TrajectoryAdapterError, match="invalid JSON"):
        parse_cursor_transcript('{"role":"user"}\nnot-json\n')


def test_redaction_strips_secret_material():
    raw = {
        "events": [
            {
                "tool_args": {"api_key": "sk-test-secret-token-abcdef1234567890", "path": "x.py"},
                "content": "Authorization: Bearer abc.def.ghi",
            }
        ]
    }
    cleaned = redact_trajectory_payload(raw)
    dumped = json.dumps(cleaned)
    assert "sk-test-secret" not in dumped
    assert "abc.def.ghi" not in dumped
    assert cleaned["events"][0]["tool_args"]["api_key"] == "[REDACTED]"
    assert redact_string("token ghp_abcdefghijklmnopqrstuvwxyz123456") == "token [REDACTED]"


def test_store_persists_redacted_trajectory():
    text = (FIXTURES / "cursor-sample.jsonl").read_text(encoding="utf-8")
    trajectory = parse_cursor_transcript(text)
    saved = save_trajectory(trajectory)
    loaded = get_trajectory(saved.trajectory_id)
    assert loaded is not None
    payload = json.dumps(loaded.model_dump(mode="json"))
    assert "sk-test-secret" not in payload


async def test_native_converter_emits_same_schema(jarvis_env):
    task_id = await _seed_task("coding", "add trajectory ingest tests")
    row = await record_trajectory(task_id, WorkingState(goal="add trajectory ingest tests", task_class="coding"), "completed")
    assert row is not None

    normalized = from_native_trajectory(row)
    assert normalized.schema_version == "JarvisTrajectoryV1"
    assert normalized.provenance.harness == "jarvis"
    assert normalized.provenance.trusted is True
    assert normalized.outcome.status == "completed"
    assert normalized.outcome.verified is True
    assert normalized.events


async def test_consumer_processes_enqueued_trajectory():
    text = (FIXTURES / "cursor-sample.jsonl").read_text(encoding="utf-8")
    trajectory = save_trajectory(parse_cursor_transcript(text))
    enqueue_trajectory(trajectory)

    from app.agent.skills import note_imported_trajectory_evidence

    result = await note_imported_trajectory_evidence(trajectory)
    assert result["accepted"] is True
    assert result["policy_modified"] is False

    pending = drain_pending_trajectories()
    assert len(pending) == 1


async def test_api_import_list_inspect(jarvis_env, monkeypatch):
    monkeypatch.setattr("app.trajectories.store.data_dir", lambda: jarvis_env["tmp"])
    reset_trajectories_store()

    from app.main import app

    text = (FIXTURES / "cursor-sample.jsonl").read_text(encoding="utf-8")
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        imported = await client.post(
            "/api/trajectories/import/cursor",
            json={"transcript": text, "source_uri": "fixture://cursor-sample"},
        )
        assert imported.status_code == 200
        trajectory_id = imported.json()["trajectory_id"]

        listed = await client.get("/api/trajectories")
        assert listed.status_code == 200
        assert any(row["trajectory_id"] == trajectory_id for row in listed.json())

        detail = await client.get(f"/api/trajectories/{trajectory_id}")
        assert detail.status_code == 200
        body = detail.json()
        assert body["provenance"]["harness"] == "cursor"
        assert body["events"]

        bad = await client.post("/api/trajectories/import/cursor", json={"transcript": "{"})
        assert bad.status_code == 400
