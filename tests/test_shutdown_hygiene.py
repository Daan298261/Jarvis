from __future__ import annotations

import sys
from pathlib import Path

import pytest

from app.recovery.journal import journal_mutate
from app.recovery.store import configure_recovery_db, connect, reset_recovery_db
from app.recovery.types import JournalOperation, RESOURCE_POLICY_PROFILES


@pytest.fixture
def recovery_connect_env(jarvis_env, monkeypatch):
    tmp = jarvis_env["tmp"]
    monkeypatch.setattr("app.config.data_dir", lambda: tmp)
    monkeypatch.setattr("app.recovery.store.data_dir", lambda: tmp)
    configure_recovery_db(tmp / "recovery" / "journal.db")
    reset_recovery_db()
    yield tmp
    reset_recovery_db()


def test_recovery_connect_releases_handles_between_operations(recovery_connect_env):
    """Leaked SQLite handles block reset_recovery_db on Windows."""
    for _ in range(5):
        with connect() as conn:
            conn.execute("SELECT COUNT(*) FROM journal_entries").fetchone()
    reset_recovery_db()


def test_reset_recovery_db_after_journal_use(recovery_connect_env):
    journal_mutate(
        resource_class=RESOURCE_POLICY_PROFILES,
        resource_id="reset-test",
        operation=JournalOperation.UPDATE,
        actor="tester",
        before={"profiles": {}},
        after={"profiles": {}},
        apply_fn=lambda: None,
    )
    reset_recovery_db()
    with connect() as conn:
        count = conn.execute("SELECT COUNT(*) AS c FROM journal_entries").fetchone()["c"]
    assert int(count) == 0


@pytest.mark.asyncio
async def test_mcp_close_all_clears_live_sessions():
    from app.tools.mcp_runtime import MCP

    script = Path(__file__).resolve().parent / "fixtures" / "echo_mcp_stdio.py"
    server = {
        "id": "echo-hygiene",
        "name": "echo",
        "transport": "stdio",
        "command": sys.executable,
        "args": ["-u", str(script)],
        "enabled": True,
    }
    await MCP.refresh([server])
    assert MCP._sessions
    await MCP.close_all()
    assert not MCP._sessions
    MCP.reset_for_tests()


@pytest.mark.asyncio
async def test_app_shutdown_closes_mcp_sessions():
    from app.main import shutdown
    from app.tools.mcp_runtime import MCP

    script = Path(__file__).resolve().parent / "fixtures" / "echo_mcp_stdio.py"
    server = {
        "id": "echo-shutdown",
        "name": "echo",
        "transport": "stdio",
        "command": sys.executable,
        "args": ["-u", str(script)],
        "enabled": True,
    }
    await MCP.refresh([server])
    assert MCP._sessions
    await shutdown()
    assert not MCP._sessions
    MCP.reset_for_tests()
