from app.agent.acp import (
    CursorACPWorker,
    InMemoryAcpTransport,
    auto_answer_ask_question,
    auto_answer_create_plan,
    handle_blocking_request,
)


def test_routine_isolated_question_is_auto_answered():
    result = auto_answer_ask_question(
        "Should I add a migration or modify the existing schema?",
        ["Modify the existing schema", "Add a migration"],
        isolated=True,
        autonomy="autonomous",
    )
    assert result["auto"] is True
    assert "Modify the existing schema" in result["answer"]


def test_consequential_question_is_not_auto_answered():
    result = auto_answer_ask_question(
        "Should I merge to main and deploy to production?",
        ["Yes", "No"],
        isolated=True,
        autonomy="autonomous",
    )
    assert result["auto"] is False
    assert "consequential" in result["reason"]


def test_plan_approval_for_isolated_work():
    ok = auto_answer_create_plan("Add a unit test for EscalationContext.", isolated=True)
    assert ok["auto"] is True and ok["approved"] is True
    blocked = auto_answer_create_plan("Overwrite the trusted installation and deploy.", isolated=True)
    assert blocked["auto"] is False
    not_isolated = auto_answer_create_plan("Add a helper.", isolated=False)
    assert not_isolated["auto"] is False


def test_handle_blocking_request_methods():
    asked = handle_blocking_request(
        "cursor/ask_question",
        {"question": "Use library or CLI?", "options": ["library", "CLI"]},
        isolated=True,
        autonomy="trusted",
    )
    assert asked["auto"] is True
    plan = handle_blocking_request("cursor/create_plan", {"plan": "Write tests first."}, isolated=True)
    assert plan["approved"] is True


async def test_acp_session_persists_without_live_cli(jarvis_env):
    transport = InMemoryAcpTransport()
    transport.on("initialize", lambda params: {"protocolVersion": "0.1.0"})
    transport.on("session/new", lambda params: {"sessionId": "sess-123"})
    worker = CursorACPWorker(transport=transport)
    status = worker.verify_connection()
    assert "status" in status
    await worker.initialize(cwd="/tmp/work", model="composer-2.5")
    session = await worker.create_or_load_session()
    assert session["session_id"]
    sent = await worker.send_task("Implement EscalationContext")
    assert sent["ok"] is True
    answer = await worker.handle_cursor_request(
        "cursor/ask_question",
        {"question": "Add a test file?", "options": ["yes", "no"]},
        isolated=True,
        autonomy="autonomous",
    )
    assert answer["auto"] is True
    await worker.cancel()
    from app.agent.acp import list_acp_sessions

    rows = await list_acp_sessions()
    assert any(row["id"] == worker.session_id for row in rows)
    assert any(item["method"] == "initialize" for item in transport.sent)
