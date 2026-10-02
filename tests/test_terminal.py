from app.tools.python_exec import PythonTool
from app.tools.terminal import TerminalTool, _command_args, _python_args, default_shell, lan_bound_http_argv


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


async def test_terminal_git_pull_honors_internet_deny(tmp_path, monkeypatch):
    from app.policy.computer_permissions import apply_grant, reset_computer_permission_state

    monkeypatch.setattr("app.policy.computer_permissions.data_dir", lambda: tmp_path)
    reset_computer_permission_state()
    apply_grant("network.internet", "deny")
    ran = {"n": 0}

    async def _boom(*_args, **_kwargs):
        ran["n"] += 1
        raise AssertionError("git pull must not run when internet is denied")

    monkeypatch.setattr("app.tools.terminal.TerminalTool._run", _boom)
    tool = TerminalTool()
    result = await tool.execute(command="git pull origin main", shell="bash")
    assert result.success is False
    assert ran["n"] == 0


async def test_python_working_directory_on_extra_drive(tmp_path):
    extra = tmp_path / "E" / "code"
    extra.mkdir(parents=True)
    (extra / "marker.txt").write_text("usb", encoding="utf-8")
    tool = PythonTool(lambda: {"allowed_directories": [str(tmp_path)]})
    result = await tool.execute(
        action="run_code",
        code="from pathlib import Path; print(Path.cwd()); print((Path.cwd()/'marker.txt').read_text())",
        working_directory=str(extra),
    )
    assert result.success, result.error
    assert "usb" in result.output
    outside = await tool.execute(
        action="run_code",
        code="print(1)",
        working_directory="/etc",
    )
    assert outside.success is False
    assert "outside allowed directories" in (outside.error or "")


async def test_python_run_file_on_extra_drive(tmp_path):
    extra = tmp_path / "D" / "scripts"
    extra.mkdir(parents=True)
    script = extra / "hello.py"
    script.write_text("print('from-usb')\n", encoding="utf-8")
    tool = PythonTool(lambda: {"allowed_directories": [str(tmp_path)]})
    result = await tool.execute(action="run_file", path=str(script))
    assert result.success, result.error
    assert "from-usb" in result.output


async def test_terminal_working_directory_on_extra_drive(tmp_path):
    extra = tmp_path / "E" / "shell"
    extra.mkdir(parents=True)
    (extra / "here.txt").write_text("ok", encoding="utf-8")
    tool = TerminalTool(lambda: {"allowed_directories": [str(tmp_path)]})
    result = await tool.execute(
        command="cat here.txt",
        shell="bash",
        working_directory=str(extra),
    )
    assert result.success, result.error
    assert "ok" in result.output


async def test_python_omitted_cwd_uses_documents(tmp_path, monkeypatch):
    docs = tmp_path / "Documents"
    docs.mkdir()
    (docs / "here.txt").write_text("docs-cwd", encoding="utf-8")
    monkeypatch.setattr("app.tools.owner_paths.Path.home", classmethod(lambda cls: tmp_path))
    tool = PythonTool(lambda: {"allowed_directories": [str(tmp_path)]})
    result = await tool.execute(
        action="run_code",
        code="from pathlib import Path; print(Path.cwd()); print((Path.cwd()/'here.txt').read_text())",
    )
    assert result.success, result.error
    assert "docs-cwd" in result.output


async def test_terminal_omitted_cwd_uses_documents(tmp_path, monkeypatch):
    docs = tmp_path / "Documents"
    docs.mkdir()
    (docs / "here.txt").write_text("shell-docs", encoding="utf-8")
    monkeypatch.setattr("app.tools.owner_paths.Path.home", classmethod(lambda cls: tmp_path))
    tool = TerminalTool(lambda: {"allowed_directories": [str(tmp_path)]})
    result = await tool.execute(command="cat here.txt", shell="bash")
    assert result.success, result.error
    assert "shell-docs" in result.output


async def test_terminal_python_uses_lan_http_proxy_not_vpn(tmp_path, monkeypatch):
    monkeypatch.setenv("HTTP_PROXY", "http://10.8.0.1:8080")
    monkeypatch.setenv("https_proxy", "http://10.8.0.1:8080")
    tool = TerminalTool(lambda: {"allowed_directories": [str(tmp_path)]})
    result = await tool.execute(
        command="import os; print(os.environ.get('HTTP_PROXY') or '')",
        shell="python",
        working_directory=str(tmp_path),
    )
    assert result.success, result.error
    assert "10.8.0.1" not in result.output
    assert "http://127.0.0.1:" in result.output


async def test_python_child_uses_lan_http_proxy_not_vpn(tmp_path, monkeypatch):
    monkeypatch.setenv("HTTP_PROXY", "http://10.8.0.1:8080")
    monkeypatch.setenv("https_proxy", "http://10.8.0.1:8080")
    tool = PythonTool(lambda: {"allowed_directories": [str(tmp_path)]})
    result = await tool.execute(
        action="run_code",
        code="import os; print(os.environ.get('HTTP_PROXY') or '')",
        working_directory=str(tmp_path),
    )
    assert result.success, result.error
    assert "10.8.0.1" not in result.output
    assert "http://127.0.0.1:" in result.output


def _home_vpn_nics():
    import socket
    from types import SimpleNamespace

    return {
        "eth0": [
            SimpleNamespace(family=socket.AF_INET, address="192.168.1.12", netmask="255.255.255.0"),
        ],
        "wg0": [
            SimpleNamespace(family=socket.AF_INET, address="10.8.0.2", netmask="255.255.255.0"),
        ],
    }


def test_lan_curl_binds_home_nic_not_vpn(monkeypatch):
    monkeypatch.setattr("psutil.net_if_addrs", _home_vpn_nics)
    monkeypatch.setattr(
        "app.tools.terminal.shutil.which",
        lambda name: f"/usr/bin/{name}" if name in {"curl", "wget"} else None,
    )
    curl = lan_bound_http_argv("curl -s http://192.168.1.50/status")
    assert curl is not None
    assert curl[0] == "/usr/bin/curl"
    assert curl[1:3] == ["--interface", "192.168.1.12"]
    assert curl[-1] == "http://192.168.1.50/status"
    wget = lan_bound_http_argv("wget http://192.168.1.50/status")
    assert wget is not None
    assert wget[1] == "--bind-address=192.168.1.12"
    header = lan_bound_http_argv("curl -H User-Agent:jarvis http://192.168.1.1/")
    assert header is not None
    assert header[1:3] == ["--interface", "192.168.1.12"]
    assert lan_bound_http_argv("curl https://example.com/") is None
    assert lan_bound_http_argv("curl --interface eth0 http://192.168.1.50/") is None
    assert lan_bound_http_argv("curl http://192.168.1.50/ | cat") is None
    powershell = _command_args("curl -s http://192.168.1.50/", "powershell")
    assert powershell[0] == "/usr/bin/curl"
    assert "--interface" in powershell
    iwr = lan_bound_http_argv("Invoke-WebRequest -Uri http://192.168.1.1/ -UseBasicParsing")
    assert iwr is not None
    assert iwr[0] == "/usr/bin/curl"
    assert iwr[1:3] == ["--interface", "192.168.1.12"]
    assert iwr[-1] == "http://192.168.1.1/"
    irm = lan_bound_http_argv('iwr -Uri "http://192.168.1.50/status" -OutFile page.html')
    assert irm is not None
    assert "-o" in irm and "page.html" in irm
    assert lan_bound_http_argv("iwr https://example.com/") is None
    assert lan_bound_http_argv("Invoke-WebRequest -Uri http://192.168.1.1/ -Headers @{a=1}") is None


def test_wget_without_binary_falls_back_to_curl_on_lan(monkeypatch):
    monkeypatch.setattr("psutil.net_if_addrs", _home_vpn_nics)
    monkeypatch.setattr(
        "app.tools.terminal.shutil.which",
        lambda name: "/usr/bin/curl" if name in {"curl", "curl.exe"} else None,
    )
    argv = lan_bound_http_argv("wget http://192.168.1.50/status")
    assert argv is not None
    assert argv[0] == "/usr/bin/curl"
    assert argv[1:3] == ["--interface", "192.168.1.12"]
    assert argv[-1] == "http://192.168.1.50/status"
