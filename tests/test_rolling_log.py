from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

from app.observability import rolling_log as rl


def test_record_and_list_recent_event(monkeypatch, tmp_path):
    path = tmp_path / "rolling-log.jsonl"
    monkeypatch.setattr(rl, "log_path", lambda: path)
    monkeypatch.setattr(rl, "_PRUNE_EVERY_WRITES", 100)

    event = rl.record_event("tool_call", message="filesystem", tool="filesystem", success=True)
    assert path.is_file()
    rows = rl.list_events(limit=10)
    assert len(rows) == 1
    assert rows[0]["id"] == event["id"]
    assert rows[0]["kind"] == "tool_call"


def test_prunes_entries_older_than_one_day(monkeypatch, tmp_path):
    path = tmp_path / "rolling-log.jsonl"
    monkeypatch.setattr(rl, "log_path", lambda: path)
    monkeypatch.setattr(rl, "_PRUNE_EVERY_WRITES", 1)

    old_ts = (datetime.now(timezone.utc) - timedelta(hours=30)).isoformat()
    fresh_ts = datetime.now(timezone.utc).isoformat()
    path.write_text(
        "\n".join(
            [
                json.dumps({"id": "old", "ts": old_ts, "kind": "log", "message": "stale"}),
                json.dumps({"id": "new", "ts": fresh_ts, "kind": "log", "message": "keep"}),
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    rl.record_event("startup", message="trigger prune")
    kept = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
    ids = {row["id"] for row in kept}
    assert "old" not in ids
    assert "new" in ids


def test_redacts_secrets_in_tool_arguments(monkeypatch, tmp_path):
    path = tmp_path / "rolling-log.jsonl"
    monkeypatch.setattr(rl, "log_path", lambda: path)
    monkeypatch.setattr(rl, "_PRUNE_EVERY_WRITES", 100)

    rl.record_tool_call(
        name="example",
        arguments={"api_key": "secret-value", "path": "/tmp/x"},
        success=True,
    )
    row = json.loads(path.read_text(encoding="utf-8").strip())
    assert row["arguments"]["api_key"] == "[redacted]"
    assert row["arguments"]["path"] == "/tmp/x"
