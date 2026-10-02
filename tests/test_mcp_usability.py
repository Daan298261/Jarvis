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


async def test_live_stdio_mcp_refresh_expose_and_call():
    import sys
    from pathlib import Path

    from app.agent.tool_exposure import schemas_for
    from app.tools.mcp_runtime import MCP

    script = Path(__file__).resolve().parent / "fixtures" / "echo_mcp_stdio.py"
    server = {
        "id": "echo-live",
        "name": "echo",
        "transport": "stdio",
        "command": sys.executable,
        "args": ["-u", str(script)],
        "enabled": True,
    }
    try:
        status = await MCP.refresh([server])
        assert status["echo"].startswith("1 tool"), status
        names = [item["function"]["name"] for item in schemas_for("mixed")]
        assert "mcp_echo_ping" in names
        assert "mcp_call" in names
        result = await MCP.call("mcp_echo_ping", {"text": "usable"})
        assert result.success, result.error
        assert "pong:usable" in result.output
        proxy = await REGISTRY.execute("mcp_call", {"mcp_tool": "mcp_echo_ping", "arguments": {"text": "proxy"}})
        assert proxy.success
        assert "pong:proxy" in proxy.output
    finally:
        await MCP.close_all()
        MCP.reset_for_tests()
