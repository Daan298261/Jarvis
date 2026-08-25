from app.mcp_server import FORBIDDEN_TOOLS, JarvisMcpServer, jarvis_mcp_manifest


async def test_mcp_lists_read_and_report_tools():
    server = JarvisMcpServer()
    listed = await server.handle({"jsonrpc": "2.0", "id": 1, "method": "tools/list"})
    assert listed is not None
    names = {tool["name"] for tool in listed["result"]["tools"]}
    assert "get_master_plan" in names
    assert "get_current_task" in names
    assert "request_verification" in names
    assert "report_worker_result" in names
    assert "start_cursor" not in names
    for forbidden in FORBIDDEN_TOOLS:
        assert forbidden not in names


async def test_initialize_and_ping():
    server = JarvisMcpServer()
    init = await server.handle({"jsonrpc": "2.0", "id": "a", "method": "initialize", "params": {}})
    assert init["result"]["serverInfo"]["name"] == "jarvis"
    assert init["result"]["capabilities"]["tools"]
    ping = await server.handle({"jsonrpc": "2.0", "id": 2, "method": "ping"})
    assert ping["result"] == {}
    note = await server.handle({"jsonrpc": "2.0", "method": "notifications/initialized"})
    assert note is None


async def test_master_plan_and_architecture_tools():
    server = JarvisMcpServer()
    plan = await server.call_tool("get_master_plan", {"section": "queue"})
    assert not plan["isError"]
    text = plan["content"][0]["text"]
    assert "DEVELOPMENT QUEUE" in text or "P0" in text
    architecture = await server.call_tool("get_known_architecture", {})
    assert "supervisor" in architecture["content"][0]["text"].lower() or "Jarvis" in architecture["content"][0]["text"]


async def test_refuses_recursive_dispatch():
    server = JarvisMcpServer()
    result = await server.call_tool("start_cursor", {})
    assert result["isError"] is True
    assert "Refused" in result["content"][0]["text"]


async def test_verification_and_worker_report_do_not_complete_task(jarvis_env):
    from app.db.models import Task, WorkerReport
    from app.db.session import SessionLocal
    from sqlalchemy import select

    async with SessionLocal() as session:
        session.add(
            Task(
                id="task-mcp-1",
                title="demo",
                prompt="demo",
                status="running",
                stage="act",
            )
        )
        await session.commit()

    server = JarvisMcpServer()
    verify = await server.call_tool("request_verification", {"task_id": "task-mcp-1", "note": "please verify"})
    assert not verify["isError"]
    assert "does not start Cursor" in verify["content"][0]["text"]
    report = await server.call_tool(
        "report_worker_result",
        {"task_id": "task-mcp-1", "worker": "cursor", "success": True, "summary": "looks done"},
    )
    assert "NOT completion" in report["content"][0]["text"]

    async with SessionLocal() as session:
        task = await session.get(Task, "task-mcp-1")
        rows = (await session.execute(select(WorkerReport).where(WorkerReport.task_id == "task-mcp-1"))).scalars().all()
    assert task.status == "running"
    assert len(rows) == 2

    manifest = jarvis_mcp_manifest()
    assert manifest["recursive_dispatch"] is False
    assert "python3 -m app.mcp_stdio" in manifest["command"]


async def test_coding_mcp_http_endpoint(jarvis_env):
    from fastapi.testclient import TestClient
    from app.main import app

    client = TestClient(app)
    listed = client.get("/api/coding/mcp")
    assert listed.status_code == 200
    body = listed.json()
    assert body["name"] == "jarvis"
    assert "get_master_plan" in body["read_tools"]
    called = client.post("/api/coding/mcp/call", json={"name": "get_master_plan", "arguments": {"section": "queue"}})
    assert called.status_code == 200
    assert called.json()["isError"] is False
    builtin = client.get("/api/mcp/jarvis")
    assert builtin.status_code == 200
    assert builtin.json()["supervisor"] == "jarvis"


async def test_unknown_method_is_jsonrpc_error():
    server = JarvisMcpServer()
    result = await server.handle({"jsonrpc": "2.0", "id": 9, "method": "session/new"})
    assert result["error"]["code"] == -32601
