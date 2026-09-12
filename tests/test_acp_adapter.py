from app.agent.acp_adapter import ACPAgentAdapter, AcpProtocolError
from app.config import AcpAdapterSettings


async def test_acp_adapter_resumes_and_deduplicates_prompt_requests(jarvis_env):
    calls = []
    async def runner(prompt, profile, workspace):
        calls.append((prompt, profile, workspace)); return {"id": "task-123"}
    adapter = ACPAgentAdapter(AcpAdapterSettings(enabled=True), task_runner=runner)
    await adapter.handle({"jsonrpc": "2.0", "method": "initialize", "params": {}})
    created = await adapter.handle({"jsonrpc": "2.0", "method": "session/new", "params": {"sessionId": "session-1", "workspace": str(jarvis_env["tmp"]), "agentProfileId": "balanced", "capabilities": {"filesystem": True}}})
    assert created["sessionId"] == "session-1"
    message = {"jsonrpc": "2.0", "method": "session/prompt", "params": {"sessionId": "session-1", "prompt": "Write a test", "requestId": "req-1"}}
    first = await adapter.handle(message); second = await adapter.handle(message)
    assert first == second and len(calls) == 1
    resumed = await adapter.handle({"jsonrpc": "2.0", "method": "session/load", "params": {"sessionId": "session-1"}})
    assert resumed["taskId"] == "task-123" and resumed["capabilities"]["filesystem"] == "delegated-only"


async def test_acp_adapter_blocks_policy_escalation_and_invalid_workspace(jarvis_env):
    adapter = ACPAgentAdapter(AcpAdapterSettings(enabled=True), task_runner=lambda *_: None)
    try:
        await adapter.handle({"jsonrpc": "2.0", "method": "session/new", "params": {"workspace": "relative"}})
    except AcpProtocolError as exc:
        assert "absolute" in str(exc)
    else: raise AssertionError("relative workspace was accepted")
    await adapter.handle({"jsonrpc": "2.0", "method": "session/new", "params": {"sessionId": "session-2", "workspace": str(jarvis_env["tmp"])}})
    answer = await adapter.handle({"jsonrpc": "2.0", "method": "session/request_permission", "params": {"sessionId": "session-2", "mode": "unrestricted", "actionId": "approval-1"}})
    assert answer["approved"] is False and answer["action_id"] == "approval-1"


async def test_acp_adapter_hands_client_mcp_config_to_session_runtime(jarvis_env):
    adapter = ACPAgentAdapter(AcpAdapterSettings(enabled=True))
    await adapter.handle({"jsonrpc": "2.0", "method": "session/new", "params": {"sessionId": "session-3", "workspace": str(jarvis_env["tmp"])}})
    class FakeRuntime:
        async def refresh(self, servers):
            assert servers == [{"name": "editor", "enabled": True}]
            return {"editor": "2 tools"}
    adapter._mcp["session-3"] = FakeRuntime()
    result = await adapter.handle({"jsonrpc": "2.0", "method": "session/register_mcp", "params": {"sessionId": "session-3", "servers": [{"name": "editor", "enabled": True}]}})
    assert result["status"] == {"editor": "2 tools"}
