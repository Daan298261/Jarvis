from app.tools.python_exec import PythonTool
from app.tools.terminal import TerminalTool, _command_args, _python_args, default_shell


def test_python_shell_uses_dash_c_for_snippets():
    args = _python_args("import time; time.sleep(1)")
    assert args[1:] == ["-c", "import time; time.sleep(1)"]
    assert args[0]
    print_args = _python_args("print('hi')")
    assert print_args[1:] == ["-c", "print('hi')"]
    file_args = _python_args("script.py --flag")
    assert file_args[1:3] == ["script.py", "--flag"]


async def test_background_process_can_be_inspected_and_killed(tmp_path):
    tool = TerminalTool()
    started = await tool.execute(
        action="start",
        shell="python",
        command="import time; time.sleep(20)",
        working_directory=str(tmp_path),
    )
    assert started.success, started.error
    pid = started.data["pid"]
    assert pid

    inspected = await tool.execute(action="inspect", pid=pid)
    assert inspected.success
    assert inspected.data["alive"] is True
    assert inspected.data["pid"] == pid

    listed = await tool.execute(action="inspect")
    assert any(job["pid"] == pid for job in listed.data.get("jobs") or [])

    killed = await tool.execute(action="kill", pid=pid)
    assert killed.success
    inspected_after = await tool.execute(action="inspect", pid=pid)
    assert inspected_after.data["alive"] is False


def test_default_shell_is_bash_off_windows(monkeypatch):
    monkeypatch.setattr("app.tools.terminal.platform.system", lambda: "Linux")
    assert default_shell() == "bash"
    monkeypatch.setattr("app.tools.terminal.platform.system", lambda: "Windows")
    assert default_shell() == "powershell"


def test_unknown_shell_falls_back_to_bash_on_linux(monkeypatch):
    monkeypatch.setattr("app.tools.terminal.platform.system", lambda: "Linux")
    monkeypatch.setattr("app.tools.terminal.shutil.which", lambda name: "/bin/bash" if name == "bash" else None)
    args = _command_args("echo hi", "unknown")
    assert args[:3] == ["bash", "-lc", "echo hi"]


def test_python_tool_uses_sys_executable():
    import sys

    tool = PythonTool()
    assert tool._python_bin(None) == sys.executable


async def test_wait_collects_output_from_a_started_process(tmp_path):
    tool = TerminalTool()
    started = await tool.execute(
        action="start",
        shell="python",
        command="print('hello-from-bg')",
        working_directory=str(tmp_path),
    )
    assert started.success, started.error
    waited = await tool.execute(action="wait", pid=started.data["pid"], timeout_seconds=10)
    assert waited.success
    assert waited.data["alive"] is False
    assert "hello-from-bg" in (waited.data.get("stdout") or waited.output)


def test_linux_default_shell_is_not_powershell():
    import sys

    if sys.platform == "win32":
        assert default_shell() == "powershell"
    else:
        assert default_shell() in {"bash", "python"}


async def test_terminal_curl_honors_internet_deny(tmp_path, monkeypatch):
    from app.policy.computer_permissions import apply_grant, reset_computer_permission_state

    monkeypatch.setattr("app.policy.computer_permissions.data_dir", lambda: tmp_path)
    reset_computer_permission_state()
    apply_grant("network.internet", "deny")
    ran = {"n": 0}

    async def _boom(*_args, **_kwargs):
        ran["n"] += 1
        raise AssertionError("curl must not run when internet is denied")

    monkeypatch.setattr("app.tools.terminal.TerminalTool._run", _boom)
    tool = TerminalTool()
    result = await tool.execute(command="curl https://example.com", shell="bash")
    assert result.success is False
    assert ran["n"] == 0
    assert "internet" in (result.error or "").lower() or "permission" in (result.error or "").lower() or "don't allow" in (result.error or "").lower()


async def test_python_urllib_honors_internet_deny(tmp_path, monkeypatch):
    from app.policy.computer_permissions import apply_grant, reset_computer_permission_state

    monkeypatch.setattr("app.policy.computer_permissions.data_dir", lambda: tmp_path)
    reset_computer_permission_state()
    apply_grant("network.internet", "deny")
    tool = PythonTool()
    result = await tool.execute(
        action="run_code",
        code="import urllib.request; urllib.request.urlopen('https://example.com')",
    )
    assert result.success is False
    assert "internet" in (result.error or "").lower() or "permission" in (result.error or "").lower() or "don't allow" in (result.error or "").lower()
    local = await tool.execute(action="run_code", code="print(1)")
    assert local.success is True
    assert "1" in local.output
