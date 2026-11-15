from pathlib import Path

from app.agent.tool_exposure import describe_exposure, grant_requested_tools, schemas_for, tool_names_for
from app.agent.tool_retrieval import suggest_tools_for_prompt
from app.tools.base import ToolResult
from app.tools.call_normalize import normalize_tool_call
from app.tools.mcp_runtime import MCP, mcp_tool_key, prepare_stdio_launch
from app.tools.registry import REGISTRY


def test_stdio_launch_rewrites_relative_mcp_prefix():
    launch = prepare_stdio_launch(
        {
            "command": "npm",
            "args": ["exec", "--prefix", "mcp", "--", "email-mcp", "stdio"],
            "env": {"FOO": "1"},
        }
    )
    assert launch["command"] == "npm"
    prefix = Path(launch["args"][launch["args"].index("--prefix") + 1])
    assert prefix.name == "mcp"
    assert prefix.is_absolute()
    assert launch["cwd"]
    assert launch["env"]["FOO"] == "1"


def test_stdio_launch_uses_extra_volume_cwd_and_path_args(tmp_path, monkeypatch):
    from app.config import repo_root

    extra = tmp_path / "USB" / "mcp-email"
    extra.mkdir(parents=True)
    script = extra / "run.py"
    script.write_text("print(1)\n", encoding="utf-8")
    monkeypatch.setattr(
        "app.config.live_allowed_directories",
        lambda existing=None: [str(tmp_path / "USB")],
    )
    launch = prepare_stdio_launch(
        {
            "command": str(script),
            "args": ["--root", str(extra)],
            "cwd": str(extra),
        }
    )
    assert Path(launch["cwd"]).resolve() == extra.resolve()
    assert Path(launch["command"]).resolve() == script.resolve()
    assert Path(launch["args"][1]).resolve() == extra.resolve()

    denied = prepare_stdio_launch(
        {
            "command": "npx",
            "args": ["-y", "@modelcontextprotocol/server-filesystem"],
            "cwd": str(tmp_path / "outside"),
        }
    )
    assert Path(denied["cwd"]).resolve() == repo_root().resolve()
    assert denied["args"][1].startswith("@")


def test_stdio_filesystem_mcp_defaults_to_documents(tmp_path, monkeypatch):
    docs = tmp_path / "Documents"
    docs.mkdir()
    monkeypatch.setattr(
        "app.config.live_allowed_directories",
        lambda existing=None: [str(tmp_path)],
    )
    monkeypatch.setattr("app.tools.owner_paths.default_workspace_dir", lambda allowed: docs)
    launch = prepare_stdio_launch(
        {
            "command": "npx",
            "args": ["-y", "@modelcontextprotocol/server-filesystem"],
        }
    )
    assert str(docs.resolve()) in [str(Path(item).resolve()) if not str(item).startswith(("@", "-")) else item for item in launch["args"]]
    assert launch["args"][1].startswith("@")


def test_stdio_filesystem_mcp_includes_extra_drive(tmp_path, monkeypatch):
    extra = tmp_path / "USB"
    extra.mkdir()
    docs = tmp_path / "Documents"
    docs.mkdir()
    monkeypatch.setattr(
        "app.config.live_allowed_directories",
        lambda existing=None: [str(tmp_path), str(extra)],
    )
    monkeypatch.setattr("app.config.extra_volume_roots", lambda: [extra])
    monkeypatch.setattr("app.tools.owner_paths.default_workspace_dir", lambda allowed: docs)
    launch = prepare_stdio_launch(
        {
            "command": "npx",
            "args": ["-y", "@modelcontextprotocol/server-filesystem"],
        }
    )
    resolved_args = [str(Path(item).resolve()) for item in launch["args"] if not str(item).startswith(("@", "-"))]
    assert str(extra.resolve()) in resolved_args
    assert str(docs.resolve()) in resolved_args
    assert launch["args"][1].startswith("@")


def test_hexstrike_stdio_mcp_drops_proxy_email_keeps_it(monkeypatch):
    monkeypatch.setenv("HTTP_PROXY", "http://10.8.0.1:8080")
    monkeypatch.setenv("https_proxy", "http://10.8.0.1:8080")
    monkeypatch.setenv("ALL_PROXY", "socks5://10.8.0.1:1080")
    hex_launch = prepare_stdio_launch(
        {
            "name": "hexstrike-upstream",
            "command": "python",
            "args": ["/opt/hexstrike-ai/hexstrike_mcp.py", "--server", "http://127.0.0.1:8888", "--stdio"],
            "env": {"HEXSTRIKE_HOST": "127.0.0.1", "HEXSTRIKE_PORT": "8888"},
        }
    )
    assert "HTTP_PROXY" not in hex_launch["env"]
    assert "https_proxy" not in hex_launch["env"]
    assert "ALL_PROXY" not in hex_launch["env"]
    assert hex_launch["env"]["HEXSTRIKE_HOST"] == "127.0.0.1"
    assert hex_launch["env"]["HEXSTRIKE_PORT"] == "8888"
    assert "lan_python_site" in hex_launch["env"]["PYTHONPATH"]

    mail = prepare_stdio_launch(
        {
            "name": "email",
            "command": "npm",
            "args": ["exec", "--prefix", "mcp", "--", "email-mcp", "stdio"],
            "env": {"FOO": "1"},
        }
    )
    assert mail["env"]["HTTP_PROXY"] == "http://10.8.0.1:8080"
    assert mail["env"]["FOO"] == "1"


def test_loopback_mcp_http_bypasses_env_proxy():
    from app.tools.mcp_runtime import mcp_url_bypasses_env_proxy, streamable_http_proxy_bypass_param

    assert mcp_url_bypasses_env_proxy("http://127.0.0.1:8888/mcp")
    assert mcp_url_bypasses_env_proxy("http://192.168.1.40:8888/mcp")
    assert not mcp_url_bypasses_env_proxy("https://api.github.com/mcp")
    assert not mcp_url_bypasses_env_proxy("")

    def opener_with_client(url, *, http_client=None):
        return url, http_client

    hex_param = streamable_http_proxy_bypass_param(
        {"name": "hexstrike-upstream-http", "url": "http://127.0.0.1:8888/mcp"},
        opener_with_client,
    )
    assert hex_param == "http_client"
    remote = streamable_http_proxy_bypass_param(
        {"name": "email-http", "url": "https://mcp.gmail.example/mcp"},
        opener_with_client,
    )
    assert remote is None
    assert (
        streamable_http_proxy_bypass_param(
            {"name": "hexstrike-upstream-http", "url": "http://127.0.0.1:8888/mcp"}
        )
        == "http_client"
    )


def test_mcp_direct_http_client_ignores_trust_env():
    from app.tools.mcp_runtime import _mcp_direct_http_client

    client = _mcp_direct_http_client()
    assert client.trust_env is False


def test_mcp_tool_keys_are_openai_safe():
    key = mcp_tool_key("email", "send email!")
    assert key.startswith("mcp_email_")
    assert " " not in key
    assert "!" not in key


def test_connected_mcp_tools_are_attached_on_mixed():
    MCP._tools = {
        "mcp_email_send": {
            "server": {"name": "email"},
            "tool": {
                "name": "send",
                "description": "Send mail",
                "inputSchema": {"type": "object", "properties": {}},
            },
            "remote_name": "send",
        }
    }
    MCP._status = {"email": {"status": "1 tools", "tools": ["send"], "error": ""}}
    names = [item["function"]["name"] for item in schemas_for("mixed")]
    assert "mcp_email_send" in names
    assert "mcp_call" in names
    assert "mcp_call" in tool_names_for("mixed")
    assert "mcp_email_send" in describe_exposure("mixed")


def test_granting_mcp_adds_mcp_call_without_full_catalog():
    granted = grant_requested_tools({"capabilities": ["mcp"]})
    assert granted == ["mcp"]
    names = tool_names_for("filesystem", granted)
    assert "mcp_call" in names
    assert "docker" not in names


def test_gmail_prompt_retrieves_mcp_call():
    assert "mcp_call" in suggest_tools_for_prompt("Send this gmail to the owner")


def test_copy_scripts_still_prefer_filesystem():
    name, args = normalize_tool_call(
        "python",
        {"action": "run_code", "code": "import shutil\nsrc='C:/a'\ndst='C:/b'\nshutil.copytree(src, dst)"},
    )
    assert name == "filesystem"
    assert args["action"] == "copy"


async def test_mcp_call_proxy_is_not_swallowed_by_mcp_prefix(monkeypatch):
    seen: list[tuple[str, dict]] = []

    async def fake_call(tool_key: str, arguments: dict) -> ToolResult:
        seen.append((tool_key, arguments))
        return ToolResult(True, "sent")

    monkeypatch.setattr(MCP, "call", fake_call)
    proxy = await REGISTRY.execute("mcp_call", {"mcp_tool": "mcp_email_send", "arguments": {"to": "a@b.c"}})
    direct = await REGISTRY.execute("mcp_email_send", {"to": "a@b.c"})
    assert proxy.success
    assert direct.success
    assert seen[0][0] == "mcp_email_send"
    assert seen[1][0] == "mcp_email_send"


async def test_mcp_list_includes_status(jarvis_env, monkeypatch):
    from fastapi.testclient import TestClient
    from app.main import app

    settings = jarvis_env["settings"]
    settings.mcp_servers = [
        {
            "id": "email-1",
            "name": "email",
            "transport": "stdio",
            "command": "npm",
            "args": ["exec", "--prefix", "mcp", "--", "email-mcp", "stdio"],
            "enabled": True,
        }
    ]
    MCP._status = {"email": {"status": "3 tools", "tools": ["send", "list"], "error": ""}}
    MCP._tools = {
        "mcp_email_send": {
            "server": settings.mcp_servers[0],
            "tool": {"name": "send", "description": "send", "inputSchema": {"type": "object"}},
            "remote_name": "send",
        }
    }
    monkeypatch.setattr("app.api.mcp.load_settings", lambda: settings)
    client = TestClient(app)
    listed = client.get("/api/mcp")
    assert listed.status_code == 200
    body = listed.json()
    assert body[0]["status"] == "3 tools"
    assert "send" in body[0]["tools"]
    hub = client.get("/api/mcp/usability")
    assert hub.status_code == 200
    assert "vault" in hub.json()
    assert "supermemory" in hub.json()


def _processes_with(marker: str) -> list[int]:
    import os
    found = []
    for pid in os.listdir("/proc") if os.path.isdir("/proc") else []:
        if not pid.isdigit():
            continue
        try:
            cmdline = Path(f"/proc/{pid}/cmdline").read_bytes().replace(b"\0", b" ").decode(errors="ignore")
        except OSError:
            continue
        if marker in cmdline and "echo_mcp_stdio.py" in cmdline:
            found.append(int(pid))
    return found


def _echo_server(server_id: str, marker: str = "") -> dict:
    import sys
    script = Path(__file__).resolve().parent / "fixtures" / "echo_mcp_stdio.py"
    return {"id": server_id, "name": "echo", "transport": "stdio", "command": sys.executable,
            "args": ["-u", str(script), *([marker] if marker else [])], "enabled": True}


async def test_live_stdio_mcp_refresh_expose_and_call():
    import asyncio

    from app.agent.tool_exposure import schemas_for
    from app.tools.mcp_runtime import MCP

    try:
        status = await asyncio.create_task(MCP.refresh([_echo_server("echo-live")]))
        assert status["echo"].startswith("1 tool"), status
        names = [item["function"]["name"] for item in schemas_for("mixed")]
        assert "mcp_echo_ping" in names
        assert "mcp_call" in names
        schema = next(item["function"]["parameters"] for item in MCP.openai_tools()
                      if item["function"]["name"] == "mcp_echo_ping")
        assert schema["required"] == ["text"]
        assert schema["properties"]["text"]["type"] == "string"
        result = await asyncio.create_task(MCP.call("mcp_echo_ping", {"text": "usable"}))
        assert result.success, result.error
        assert result.output == "pong:usable"
        proxy = await asyncio.create_task(
            REGISTRY.execute("mcp_call", {"mcp_tool": "mcp_echo_ping", "arguments": {"text": "proxy"}}))
        assert proxy.success
        assert proxy.output == "pong:proxy"
        await asyncio.create_task(MCP.refresh([]))
        assert not MCP.connected_keys()
    finally:
        await MCP.close_all()
        MCP.reset_for_tests()


async def test_stdio_session_closed_from_another_task_exits_cleanly(caplog):
    """The session is opened, used and closed from three different tasks, as API requests do. Closing
    must not hit AnyIO's "exit cancel scope in a different task" error, and the server process must exit."""
    import asyncio
    import logging
    import sys
    import uuid

    from app.tools.mcp_runtime import MCP

    caplog.set_level(logging.DEBUG)
    marker = f"stdio-{uuid.uuid4().hex[:8]}"
    try:
        await asyncio.create_task(MCP.refresh([_echo_server("echo-close", marker)]))
        result = await asyncio.create_task(MCP.call("mcp_echo_ping", {"text": "x"}))
        assert result.success, result.error
        if sys.platform.startswith("linux"):
            assert _processes_with(marker), "the stdio server should be running while connected"
        await asyncio.create_task(MCP.refresh([]))  # closed from a third task
        cross_task = [record for record in caplog.records
                      if "cancel scope in a different task" in (record.getMessage() + repr(record.exc_info))]
        assert not cross_task, cross_task[0].exc_info
        if sys.platform.startswith("linux"):
            for _ in range(50):
                if not _processes_with(marker):
                    break
                await asyncio.sleep(0.1)
            assert not _processes_with(marker), "the stdio server process must exit when its session closes"
        after = await asyncio.create_task(MCP.call("mcp_echo_ping", {"text": "y"}))
        assert not after.success
    finally:
        await MCP.close_all()
        MCP.reset_for_tests()


def test_explicit_multi_word_tool_requests_use_agent_path():
    from app.agent.ingress_gate import heuristic_needs_tools
    from app.agent.planning import classify_task, requests_agent_tools

    prompts = {
        "Use the native Obsidian vault_memory tool to search my vault.": "vault_memory",
        "Search my bound Obsidian vault for the launch checklist.": "vault_memory",
        "Call the connected Docker MCP get_current_time tool.": "mcp_call",
        "Use REA to inspect C:/samples/example.exe.": "reverse_engineer",
    }
    for prompt, expected in prompts.items():
        assert requests_agent_tools(prompt)
        task_class = classify_task(prompt)
        assert heuristic_needs_tools(prompt, task_class) is True
        extras = ["mcp"] if expected == "mcp_call" else []
        assert expected in tool_names_for(task_class, extras, prompt=prompt)
    assert not requests_agent_tools("What is an MCP server?")


def test_native_vault_lookup_is_observational():
    from app.policy.reversibility import resolve_action_effect
    for action in ("search", "read", "resolve", "neighborhood", "follow"):
        effect = resolve_action_effect("vault_memory", arguments={"action": action, "query": "project"})
        assert not effect.side_effecting
        assert not effect.high_consequence
    assert resolve_action_effect("vault_memory", arguments={"action": "edit"}).side_effecting


def test_small_model_keeps_requested_connected_function():
    from app.agent.turn_tools import select_turn_schemas
    names = ("request_tools", "request_capability", "filesystem", "python", "docker", "mcp_call", "mcp_docker_catalog_get_current_time")
    schemas = [{"type": "function", "function": {"name": name, "parameters": {"type": "object"}}} for name in names]
    for request in ("Use the Docker MCP get_current_time tool.", "Get the current time using Docker MCP."):
        chosen = select_turn_schemas(schemas, model_family="9b-abliterated", prompt=request)
        assert "mcp_docker_catalog_get_current_time" in {item["function"]["name"] for item in chosen}


def test_direct_mcp_read_has_proxy_policy_parity(connected_mcp_server):
    from app.policy.reversibility import resolve_action_effect
    key = connected_mcp_server(_pinned_time_server(), "get_current_time")
    direct = resolve_action_effect(key, arguments={"timezone": "UTC"})
    proxy = resolve_action_effect("mcp_call", arguments={"mcp_tool": key, "arguments": {"timezone": "UTC"}})
    assert not direct.side_effecting
    assert direct.reversibility == proxy.reversibility
    assert resolve_action_effect("mcp_service_delete_record", arguments={"id": "example"}).side_effecting


async def test_tool_event_stream_uses_one_sse_envelope():
    """api/tasks streams BUS.stream() through EventSourceResponse, which encodes every frame with
    ensure_bytes. The bytes on the wire must hold one `data:` envelope, never `data: data: {...}`."""
    import asyncio
    import json
    from sse_starlette.sse import EventSourceResponse, ensure_bytes
    from app.events import EventBus

    bus = EventBus()
    stream = bus.stream()
    waiting = asyncio.create_task(anext(stream))
    await asyncio.sleep(0)
    await bus.publish("example", "tool", "Running connected tool", persist=False)
    frame = await waiting
    try:
        wire = ensure_bytes(frame, EventSourceResponse(iter(())).sep).decode("utf-8")
        assert "data: data:" not in wire, wire
        assert wire.startswith("data: {"), wire
        payload = json.loads(wire.removeprefix("data: ").strip())
        assert payload["kind"] == "tool"
        assert payload["task_id"] == "example"
    finally:
        await stream.aclose()


async def test_rea_status_keeps_catalog_out_of_model_text(monkeypatch):
    import json
    from app.tools.reverse_engineer import ReverseEngineerTool
    data = {
        "status": "ready", "stage": "Static analysis engine installed",
        "versions": {"rea": {"version": "3.2.1"}},
        "capabilities": {"tools": [{"name": "operation", "description": "x" * 100000}]},
    }
    monkeypatch.setattr("app.reverse_engineering.provision.readiness", lambda: data)
    result = await ReverseEngineerTool(lambda: {}).execute(action="status")
    assert result.success
    assert result.data is data
    assert len(result.output) < 1000
    assert json.loads(result.output)["status"] == "ready"
    assert json.loads(result.output)["capabilities_available"]


async def _report_failure_after_a_tool_call(jarvis_env, monkeypatch, task_id, fail):
    """A read tool call succeeds, then the model fails while reporting. The stored answer keeps the result."""
    import asyncio
    import json
    from unittest.mock import AsyncMock
    from app.agent.loop import AgentRuntime
    from app.db.models import Task
    from app.db.session import SessionLocal
    from app.providers.base import ChatResult

    target = jarvis_env["tmp"] / f"{task_id}.txt"
    target.write_text("REPORT-MARKER-7731")
    async with SessionLocal() as session:
        session.add(Task(id=task_id, title="Report", prompt=f"Read {target} and report its contents.", status="running",
                         task_class="filesystem", profile="fast", autonomy="autonomous", response_route="managed_task"))
        await session.commit()
    monkeypatch.setattr("app.agent.loop.record_trajectory", AsyncMock())
    monkeypatch.setattr("app.agent.loop.publish_owner_text", AsyncMock(return_value={}))
    jarvis_env["settings"].front_responder.enabled = False

    class Provider:
        name = "scripted"
        model = "scripted-model"

        def __init__(self):
            self.calls = 0

        async def health(self):
            return True

        async def chat(self, messages, tools=None, **kwargs):
            self.calls += 1
            if self.calls == 1:
                return ChatResult(tool_calls=[{"id": "read-1", "type": "function", "function": {
                    "name": "filesystem", "arguments": json.dumps({"action": "read", "path": str(target)})}}])
            return await fail(self.calls)

    provider = Provider()
    jarvis_env["manager"].provider = provider
    await asyncio.wait_for(AgentRuntime()._run(task_id, continue_existing=False), 40)
    async with SessionLocal() as session:
        return await session.get(Task, task_id), provider


async def test_model_report_http_error_keeps_successful_tool_results(jarvis_env, monkeypatch):
    import httpx
    from openai import APIStatusError

    async def fail(_call):
        response = httpx.Response(500, request=httpx.Request("POST", "http://127.0.0.1/v1/chat/completions"))
        raise APIStatusError("server error", response=response, body=None)

    task, _ = await _report_failure_after_a_tool_call(jarvis_env, monkeypatch, "report-http-500", fail)
    assert task.status == "completed", (task.status, task.error)
    assert "REPORT-MARKER-7731" in task.result, task.result
    assert "The model could not finish the final report." in task.result


async def test_model_report_timeout_keeps_successful_tool_results(jarvis_env, monkeypatch):
    from app.providers.base import ChatResult

    async def fail(call):
        if call == 2:  # the first report moves the task into verification
            return ChatResult(content="The file was read.")
        raise TimeoutError("report timed out")

    task, provider = await _report_failure_after_a_tool_call(jarvis_env, monkeypatch, "report-timeout", fail)
    assert provider.calls >= 3, provider.calls
    assert task.status == "completed", (task.status, task.error)
    assert "REPORT-MARKER-7731" in task.result, task.result
    assert "The model timed out while writing the final report." in task.result


def test_rea_capability_requests_resolve_to_the_reverse_engineer_adapter():
    """RFC-0201: chat requests use reverse_engineer; asking for it by name must not hand out rea_investigate."""
    from app.agent.tool_exposure import normalize_capabilities
    for requested in ("reverse_engineer", "rea", "reverse-engineer"):
        assert normalize_capabilities([requested]) == ["reverse_engineer"], requested
    assert normalize_capabilities(["rea_investigate"]) == ["rea_investigate"]
    suggested = suggest_tools_for_prompt("Use REA to inspect C:/samples/example.exe")
    assert "reverse_engineer" in suggested
    assert "rea_investigate" not in suggested


# --- #692 review: MCP reads by annotation or exact allowlist only; vault credentials; chat routing ---

import pytest  # noqa: E402

from app.decision.types import Answer, DecisionResult  # noqa: E402
from app.policy.authorize import AuthorizationResult  # noqa: E402
from app.policy.levels import AutonomyLevel  # noqa: E402
from app.policy.reversibility import resolve_action_effect  # noqa: E402

# Real-world MCP writes whose key only contains a read word ("thread", "playlist", "budget_", "status_page").
MCP_WRITES = [
    ("mcp_slack_reply_to_thread", {"channel": "C1", "text": "hi"}),
    ("mcp_spotify_add_to_playlist", {"playlist_id": "p", "uri": "u"}),
    ("mcp_budget_tracker_delete_entry", {"id": "42"}),
    ("mcp_status_page_delete_incident", {"id": "7"}),
    ("mcp_gmail_archive_thread", {"id": "t"}),
]


@pytest.mark.parametrize("name,args", MCP_WRITES)
def test_direct_mcp_write_with_a_read_word_in_its_name_stays_side_effecting(name, args):
    effect = resolve_action_effect(name, arguments=args)
    assert effect.side_effecting, f"{name} classified observational: {effect.recovery_summary}"


@pytest.mark.parametrize("server,tool", [("slack", "reply_to_thread"), ("budget_tracker", "delete_entry"),
                                         ("status_page", "delete_incident"), ("evil", "get_and_delete_all")])
def test_connected_unannotated_mcp_tools_fail_closed_direct_and_proxy(connected_mcp, server, tool):
    key = connected_mcp(server, tool)
    for name, args in ((key, {}), ("mcp_call", {"mcp_tool": key, "arguments": {}})):
        effect = resolve_action_effect(name, arguments=args)
        assert effect.side_effecting and effect.external_side_effect, (name, effect.recovery_summary)


def test_mcp_read_only_needs_an_identity_pinned_allowlist_entry(connected_mcp, connected_mcp_server):
    """Server annotations never make a tool a read (CoS R3); only the pinned (server, image, tool) entry does."""
    hinted = connected_mcp("notes", "lookup_page", {"readOnlyHint": True})
    flagged = connected_mcp("notes", "purge_pages", {"readOnlyHint": True, "destructiveHint": True})
    explicit_write = connected_mcp("notes", "list_and_archive", {"readOnlyHint": False})
    named_like_the_old_entry = connected_mcp("docker_catalog", "get_current_time")
    pinned = connected_mcp_server(_pinned_time_server(), "get_current_time")
    for key, side_effecting in ((hinted, True), (flagged, True), (explicit_write, True),
                                (named_like_the_old_entry, True), (pinned, False)):
        assert resolve_action_effect(key, arguments={}).side_effecting is side_effecting, key
        proxied = resolve_action_effect("mcp_call", arguments={"mcp_tool": key, "arguments": {}})
        assert proxied.side_effecting is side_effecting, key
    assert resolve_action_effect("mcp_call", arguments={"mcp_tool": "mcp_not_connected_get_x"}).side_effecting


def _gate_allows_and_laya_cancels(monkeypatch):
    monkeypatch.setattr("app.policy.reversibility_gate.authorize", lambda *a, **k: AuthorizationResult(
        True, False, "ok", AutonomyLevel.L3_EXECUTE_WITH_GATES, "mcp"))
    monkeypatch.setattr("app.policy.action_gate.decide", lambda *a, **k: DecisionResult(
        answers={"cancel": Answer("cancel", "choice", "cancel", 0.99)},
        source="laya", decision_class="harm_veto", provider="laya"))


@pytest.mark.parametrize("name,args", MCP_WRITES[2:4])
def test_misclassified_mcp_write_is_not_auto_allowed_past_the_veto(monkeypatch, name, args):
    from app.policy.action_gate import gate_side_effect
    _gate_allows_and_laya_cancels(monkeypatch)
    decision = gate_side_effect(name, arguments=args, park_if_needed=False)
    assert not decision.allowed, decision.reason
    proxied = gate_side_effect("mcp_call", arguments={"mcp_tool": name, "arguments": args}, park_if_needed=False)
    assert not proxied.allowed, proxied.reason


def test_laya_veto_still_skips_pinned_mcp_reads(monkeypatch, connected_mcp, connected_mcp_server):
    from app.policy.action_gate import gate_side_effect
    _gate_allows_and_laya_cancels(monkeypatch)
    read = connected_mcp_server(_pinned_time_server(), "get_current_time")
    write = connected_mcp("notes", "reply_to_thread")
    assert gate_side_effect(read, arguments={}, park_if_needed=False).allowed
    assert not gate_side_effect(write, arguments={}, park_if_needed=False).allowed


@pytest.mark.parametrize("args", [
    {"action": "read", "rel_path": "secrets/api_token.md"},
    {"action": "search", "query": "password for the router"},
    {"action": "resolve", "query": "github token"},
])
def test_vault_credential_lookup_keeps_the_credential_gate(args):
    effect = resolve_action_effect("vault_memory", arguments=args)
    assert effect.credential_effect and effect.side_effecting, effect.recovery_summary


@pytest.mark.parametrize("prompt", [
    "How do people use AI as a learning tool?",
    "Should I use MCP or a plain REST API for my app?",
    "Should I read Obsidian's docs before switching from Notion?",
])
def test_conversation_about_tools_is_not_routed_to_agent_tools(prompt):
    from app.agent.ingress_gate import heuristic_needs_tools
    from app.agent.planning import classify_task, requests_agent_tools
    assert not requests_agent_tools(prompt)
    # The tool-request check no longer forces tools; the topic classifier decides as it did before #692.
    assert heuristic_needs_tools(prompt, classify_task(prompt)) is not True


@pytest.mark.parametrize("prompt", [
    "Please use the Docker MCP to get the current time.",
    "Can you call the docker get_current_time tool?",
])
def test_explicit_instruction_to_use_a_named_tool_or_mcp_uses_agent_tools(prompt):
    from app.agent.planning import requests_agent_tools
    assert requests_agent_tools(prompt)


# --- #692 re-review (e474a2d1): vault containment, pinned allowlist, server hints, question routing ---

import os  # noqa: E402

PINNED_TIME_IMAGE = "mcp/time@sha256:9c46a918633fb474bf8035e3ee90ebac6bcf2b18ccb00679ac4c179cba0ebfcf"


def _pinned_time_server(**overrides):
    return {"id": "0b9f3c52-6a1e-4d55-9c1f-1d2f8f3e7a10", "name": "time", "transport": "stdio", "command": "docker",
            "args": ["run", "-i", "--rm", PINNED_TIME_IMAGE], "enabled": True, **overrides}


@pytest.fixture
def vault(tmp_path, monkeypatch):
    from app.memory.obsidian_vault import bind_vault, reset_vault_store, stop_watch, unbind_vault
    meta, root, outside = tmp_path / "meta", tmp_path / "vault", tmp_path / "outside"
    for folder in (meta, root, outside):
        folder.mkdir()
    monkeypatch.setattr("app.memory.obsidian_vault.data_dir", lambda: meta)
    reset_vault_store()
    bind_vault(str(root), init_layout=True)
    stop_watch()
    (outside / "id_ed25519").write_text("-----BEGIN OPENSSH PRIVATE KEY----- OUTSIDE-SECRET-91\n")
    (root / "Daily").mkdir(exist_ok=True)
    (root / "Daily" / "plan.md").write_text("# Plan\nOrdinary note body.\n")
    os.symlink(outside / "id_ed25519", root / "Daily" / "today.md")
    yield root, outside
    unbind_vault()
    reset_vault_store()


def _gated(effect):
    return effect.side_effecting or effect.credential_effect or effect.high_consequence


@pytest.mark.parametrize("rel", [
    "Secrets/API_TOKEN.md", "notes/Private/secrets/bank.md", "keys/api-key.md", "../outside/id_ed25519",
    "Daily/today.md", "ssh/id_ed25519", "ssh/id_rsa.md", "certs/server.pem", ".env", "Projects/.env.local",
    "Daily/plan.txt",
])
def test_vault_reads_outside_ordinary_notes_are_gated(vault, rel):
    effect = resolve_action_effect("vault_memory", arguments={"action": "read", "rel_path": rel})
    assert _gated(effect), (rel, effect.recovery_summary)


def test_vault_absolute_path_is_gated(vault):
    _, outside = vault
    effect = resolve_action_effect("vault_memory", arguments={"action": "read", "rel_path": str(outside / "id_ed25519")})
    assert _gated(effect), effect.recovery_summary


def test_an_ordinary_vault_note_read_stays_ungated(vault):
    effect = resolve_action_effect("vault_memory", arguments={"action": "read", "rel_path": "Daily/plan.md"})
    assert not _gated(effect), effect.recovery_summary


@pytest.mark.parametrize("which", ["dotdot", "symlink", "absolute"])
async def test_a_vault_read_never_returns_a_file_outside_the_vault(vault, which):
    from app.tools.vault_memory import VaultMemoryTool
    _, outside = vault
    rel = {"dotdot": "../outside/id_ed25519", "symlink": "Daily/today.md", "absolute": str(outside / "id_ed25519")}[which]
    effect = resolve_action_effect("vault_memory", arguments={"action": "read", "rel_path": rel})
    result = await VaultMemoryTool().execute(action="read", rel_path=rel)
    assert _gated(effect), which
    assert "OUTSIDE-SECRET-91" not in (result.output or ""), (which, result.output[:80])
    assert not result.success


def test_the_vault_index_skips_notes_that_link_outside_the_vault(vault):
    from app.memory.obsidian_vault import index_all_vault, index_file, search_vault
    index_all_vault()
    assert index_file("Daily/today.md") is None
    assert all("OUTSIDE-SECRET-91" not in hit.excerpt for hit in search_vault("OPENSSH PRIVATE KEY"))


def test_allowlist_is_bound_to_the_pinned_server_not_its_display_name(connected_mcp_server):
    impostor = connected_mcp_server({"id": "a1", "name": "docker_catalog", "transport": "stdio", "command": "node",
                                     "args": ["./some-community-server.js"], "enabled": True}, "get_current_time")
    gateway = connected_mcp_server({"id": "a2", "name": "docker_gateway", "transport": "stdio", "command": "docker",
                                    "args": ["mcp", "gateway", "run", "--profile", "anzu-catalog"], "enabled": True},
                                   "get_current_time")
    unpinned = connected_mcp_server(_pinned_time_server(id="a3", name="time_latest", args=["run", "-i", "--rm", "mcp/time"]),
                                    "get_current_time")
    no_backend_id = connected_mcp_server(_pinned_time_server(id="", name="time_noid"), "get_current_time")
    for key in (impostor, gateway, unpinned, no_backend_id):
        for name, args in ((key, {}), ("mcp_call", {"mcp_tool": key, "arguments": {}})):
            assert resolve_action_effect(name, arguments=args).side_effecting, key
    pinned = connected_mcp_server(_pinned_time_server(), "get_current_time")
    other_tool = connected_mcp_server(_pinned_time_server(id="0b9f3c52-6a1e-4d55-9c1f-1d2f8f3e7a11", name="time2"), "convert_time_and_reset")
    assert not resolve_action_effect(pinned, arguments={}).side_effecting
    assert not resolve_action_effect("mcp_call", arguments={"mcp_tool": pinned, "arguments": {}}).side_effecting
    assert resolve_action_effect(other_tool, arguments={}).side_effecting


def test_add_mcp_rejects_a_duplicate_server_name(monkeypatch):
    from fastapi.testclient import TestClient
    from app.config import AppSettings
    from app.main import app
    settings = AppSettings()
    settings.mcp_servers = [_pinned_time_server(name="docker_catalog")]
    monkeypatch.setattr("app.api.mcp.load_settings", lambda: settings)
    saved = []
    monkeypatch.setattr("app.api.mcp.save_settings", lambda value: saved.append(value))

    async def no_refresh(_servers):
        return {}

    monkeypatch.setattr("app.api.mcp.MCP.refresh", no_refresh)
    client = TestClient(app)
    for name in ("docker_catalog", " Docker_Catalog "):
        response = client.post("/api/mcp", json={"name": name, "command": "node", "args": ["evil.js"]})
        assert response.status_code == 409, response.text
        assert "already" in response.json()["detail"].lower()
    assert not saved and len(settings.mcp_servers) == 1


@pytest.mark.parametrize("annotations", [{"readOnlyHint": True}, {"readOnlyHint": True, "destructiveHint": False}])
def test_a_servers_own_read_only_hint_does_not_skip_approval_or_the_veto(monkeypatch, connected_mcp, annotations):
    """CoS (R3): readOnlyHint is the server's unverified claim; only identity-pinned allowlist entries skip."""
    from app.policy.action_gate import gate_side_effect
    _gate_allows_and_laya_cancels(monkeypatch)
    key = connected_mcp("community_notes", "delete_all_pages", annotations)
    assert resolve_action_effect(key, arguments={}).side_effecting
    assert not gate_side_effect(key, arguments={}, park_if_needed=False).allowed
    assert not gate_side_effect("mcp_call", arguments={"mcp_tool": key, "arguments": {}}, park_if_needed=False).allowed


def test_a_destructive_hint_gates_even_a_pinned_allowlisted_tool(connected_mcp_server):
    key = connected_mcp_server(_pinned_time_server(), "get_current_time", {"destructiveHint": True})
    assert resolve_action_effect(key, arguments={}).side_effecting


@pytest.mark.parametrize("prompt", [
    "Would you use MCP for a hobby project?",
    "Can you use a hammer as a tool?",
    "Use the right tool for the job: is that good advice?",
    "Could you call that a tool, or is it more of a framework?",
    "Would you read the Obsidian docs first, or just start?",
])
def test_yes_no_questions_about_tools_do_not_force_tools(prompt):
    from app.agent.planning import requests_agent_tools
    assert not requests_agent_tools(prompt)


@pytest.mark.parametrize("prompt", [
    "Use the native Obsidian vault_memory tool to search my vault.",
    "Please call the connected Docker MCP get_current_time tool.",
    "Search my bound Obsidian vault for the launch checklist.",
    "Jarvis, use Docker MCP to get the current time.",
    "Run the nmap tool against my router.",
    "Can you use the Docker MCP get_current_time tool?",
    "Use REA to inspect C:/samples/example.exe.",
])
def test_legitimate_tool_requests_still_route_to_tools(prompt):
    from app.agent.planning import requests_agent_tools
    assert requests_agent_tools(prompt)
