from app.tools.python_exec import PythonTool
from app.tools.terminal import (
    TerminalTool,
    _command_args,
    _python_args,
    default_shell,
    lan_bound_dns_argv,
    lan_bound_http_argv,
    lan_bound_netcat_argv,
    lan_bound_rsync_argv,
    lan_bound_scan_argv,
    lan_bound_ssh_argv,
    python_direct_argv,
    rsync_host_from_token,
)


def test_python_shell_uses_dash_c_for_snippets():
    args = _python_args("import time; time.sleep(1)")
    assert args[1:] == ["-c", "import time; time.sleep(1)"]
    assert args[0]
    print_args = _python_args("print('hi')")
    assert print_args[1:] == ["-c", "print('hi')"]
    file_args = _python_args("script.py --flag")
    assert file_args[1:3] == ["script.py", "--flag"]
    bash_py = python_direct_argv("python3 -c \"import os; print(1)\"")
    assert bash_py is not None
    assert bash_py[1:3] == ["-c", "import os; print(1)"]
    bash_run = _command_args("python3 -c \"print('hi')\"", "bash")
    assert bash_run[0] == bash_py[0]
    assert bash_run[1] == "-c"
    assert python_direct_argv("python3 -c 'print(1)' | cat") is None


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
    wrapped = await tool.execute(
        action="run_code",
        code="import socket; print(socket.socket.connect.__name__)",
        working_directory=str(tmp_path),
    )
    assert wrapped.success, wrapped.error
    assert "_connect" in wrapped.output


async def test_bash_python_c_uses_lan_http_proxy_not_vpn(tmp_path, monkeypatch):
    monkeypatch.setenv("HTTP_PROXY", "http://10.8.0.1:8080")
    tool = TerminalTool(lambda: {"allowed_directories": [str(tmp_path)]})
    result = await tool.execute(
        command="python3 -c \"import os; print(os.environ.get('HTTP_PROXY') or '')\"",
        shell="bash",
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
    ftp = lan_bound_http_argv("curl -s ftp://192.168.1.50/backup.tar")
    assert ftp is not None
    assert ftp[1:3] == ["--interface", "192.168.1.12"]
    assert ftp[-1] == "ftp://192.168.1.50/backup.tar"
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


def test_lan_ssh_binds_home_nic_not_vpn(monkeypatch):
    monkeypatch.setattr("psutil.net_if_addrs", _home_vpn_nics)
    monkeypatch.setattr(
        "app.tools.terminal.shutil.which",
        lambda name: f"/usr/bin/{name}" if name in {"ssh", "scp", "sftp"} else None,
    )
    ssh = lan_bound_ssh_argv("ssh -p 22 taco@192.168.1.50")
    assert ssh is not None
    assert ssh[0] == "/usr/bin/ssh"
    assert ssh[1:3] == ["-o", "BindAddress=192.168.1.12"]
    assert ssh[-1] == "taco@192.168.1.50"
    scp = lan_bound_ssh_argv("scp a.txt user@192.168.1.1:/tmp/a.txt")
    assert scp is not None
    assert scp[1:3] == ["-o", "BindAddress=192.168.1.12"]
    assert lan_bound_ssh_argv("ssh git@github.com") is None
    assert lan_bound_ssh_argv("ssh taco@192.168.1.1 | cat") is None
    powershell = _command_args("ssh taco@192.168.1.50", "powershell")
    assert powershell[0] == "/usr/bin/ssh"
    assert "BindAddress=192.168.1.12" in powershell


def test_lan_scan_binds_home_nic_not_vpn(monkeypatch):
    import socket

    monkeypatch.setattr("psutil.net_if_addrs", _home_vpn_nics)
    monkeypatch.setattr(
        "app.tools.terminal.shutil.which",
        lambda name: f"/usr/bin/{name}" if name in {"nmap", "ping", "traceroute", "masscan", "nping"} else None,
    )

    def fake_getaddrinfo(host, *args, **kwargs):
        if host in {"nas.local", "router.lan"}:
            return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("192.168.1.40", 0))]
        raise socket.gaierror("no")

    monkeypatch.setattr("app.mobile.wan_forward.socket.getaddrinfo", fake_getaddrinfo)
    nmap = lan_bound_scan_argv("nmap -sn 192.168.1.0/24")
    assert nmap is not None
    assert nmap[0] == "/usr/bin/nmap"
    assert nmap[1:5] == ["-S", "192.168.1.12", "-e", "eth0"]
    assert nmap[-1] == "192.168.1.0/24"
    ported = lan_bound_scan_argv("nmap -p 80 192.168.1.50")
    assert ported is not None
    assert ported[1:5] == ["-S", "192.168.1.12", "-e", "eth0"]
    assert ported[-1] == "192.168.1.50"
    ping = lan_bound_scan_argv("ping -c 1 192.168.1.1")
    assert ping is not None
    assert ping[1:3] == ["-I", "192.168.1.12"]
    assert ping[-1] == "192.168.1.1"
    mdns = lan_bound_scan_argv("ping nas.local")
    assert mdns is not None
    assert mdns[1:3] == ["-I", "192.168.1.12"]
    trace = lan_bound_scan_argv("traceroute 192.168.1.1")
    assert trace is not None
    assert trace[1:3] == ["-s", "192.168.1.12"]
    masscan = lan_bound_scan_argv("masscan 192.168.1.0/24 -p80")
    assert masscan is not None
    assert masscan[1:5] == ["--source-ip", "192.168.1.12", "-e", "eth0"]
    vpn = lan_bound_scan_argv("nmap 10.8.0.2")
    assert vpn is not None
    assert vpn[1:5] == ["-S", "10.8.0.2", "-e", "wg0"]
    assert lan_bound_scan_argv("nmap 8.8.8.8") is None
    assert lan_bound_scan_argv("ping 1.1.1.1") is None
    assert lan_bound_scan_argv("nmap -S 192.168.1.12 192.168.1.50") is None
    assert lan_bound_scan_argv("ping -I eth0 192.168.1.1") is None
    assert lan_bound_scan_argv("nmap 192.168.1.1 | cat") is None
    bash = _command_args("nmap -sn 192.168.1.0/24", "bash")
    assert bash[0] == "/usr/bin/nmap"
    assert bash[1:5] == ["-S", "192.168.1.12", "-e", "eth0"]


def test_lan_ping_windows_uses_source_flag(monkeypatch):
    monkeypatch.setattr("psutil.net_if_addrs", _home_vpn_nics)
    monkeypatch.setattr("app.tools.terminal.platform.system", lambda: "Windows")
    monkeypatch.setattr(
        "app.tools.terminal.shutil.which",
        lambda name: f"/usr/bin/{name}" if name in {"ping", "ping.exe"} else None,
    )
    ping = lan_bound_scan_argv("ping -n 1 192.168.1.50")
    assert ping is not None
    assert ping[1:3] == ["-S", "192.168.1.12"]
    assert lan_bound_scan_argv("ping -S 192.168.1.12 192.168.1.50") is None


def test_rsync_host_from_token_ssh_and_daemon():
    assert rsync_host_from_token("taco@192.168.1.50:/share/") == "192.168.1.50"
    assert rsync_host_from_token("192.168.1.1:/volume1/media") == "192.168.1.1"
    assert rsync_host_from_token("rsync://nas.local/backup") == "nas.local"
    assert rsync_host_from_token("192.168.1.40::module") == "192.168.1.40"
    assert rsync_host_from_token("C:\\Users\\taco\\file") == ""
    assert rsync_host_from_token("./local") == ""


def test_lan_rsync_binds_home_nic_not_vpn(monkeypatch):
    monkeypatch.setattr("psutil.net_if_addrs", _home_vpn_nics)
    monkeypatch.setattr(
        "app.tools.terminal.shutil.which",
        lambda name: "/usr/bin/rsync" if name in {"rsync", "rsync.exe"} else None,
    )
    ssh = lan_bound_rsync_argv("rsync -a taco@192.168.1.50:/share/ ./")
    assert ssh is not None
    assert ssh[0] == "/usr/bin/rsync"
    assert ssh[1] == "-e"
    assert "lan_ssh.py" in ssh[2]
    daemon = lan_bound_rsync_argv("rsync rsync://192.168.1.50/backup ./")
    assert daemon is not None
    assert daemon[1] == "--address=192.168.1.12"
    colon = lan_bound_rsync_argv("rsync 192.168.1.1::media /tmp/media")
    assert colon is not None
    assert colon[1] == "--address=192.168.1.12"
    assert lan_bound_rsync_argv("rsync rsync://example.com/mod ./") is None
    assert lan_bound_rsync_argv("rsync --address=10.8.0.2 rsync://192.168.1.1/m ./") is None
    assert lan_bound_rsync_argv("rsync taco@192.168.1.1:/a ./ | cat") is None
    bash = _command_args("rsync rsync://192.168.1.50/backup ./", "bash")
    assert bash[0] == "/usr/bin/rsync"
    assert bash[1] == "--address=192.168.1.12"


def test_lan_netcat_binds_home_nic_not_vpn(monkeypatch):
    import socket

    monkeypatch.setattr("psutil.net_if_addrs", _home_vpn_nics)
    monkeypatch.setattr(
        "app.tools.terminal.shutil.which",
        lambda name: f"/usr/bin/{name}" if name in {"nc", "ncat", "netcat"} else None,
    )

    def fake_getaddrinfo(host, *args, **kwargs):
        if host == "nas.local":
            return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("192.168.1.40", 0))]
        raise socket.gaierror("no")

    monkeypatch.setattr("app.mobile.wan_forward.socket.getaddrinfo", fake_getaddrinfo)
    nc = lan_bound_netcat_argv("nc -zv 192.168.1.1 22")
    assert nc is not None
    assert nc[0] == "/usr/bin/nc"
    assert nc[1:3] == ["-s", "192.168.1.12"]
    assert nc[-2:] == ["192.168.1.1", "22"]
    mdns = lan_bound_netcat_argv("ncat nas.local 80")
    assert mdns is not None
    assert mdns[1:3] == ["-s", "192.168.1.12"]
    assert lan_bound_netcat_argv("nc 8.8.8.8 53") is None
    assert lan_bound_netcat_argv("nc -s 192.168.1.12 192.168.1.1 22") is None
    assert lan_bound_netcat_argv("nc 192.168.1.1 22 | cat") is None
    bash = _command_args("nc -zv 192.168.1.50 80", "bash")
    assert bash[0] == "/usr/bin/nc"
    assert bash[1:3] == ["-s", "192.168.1.12"]


def test_lan_dig_binds_home_nic_not_vpn(monkeypatch):
    monkeypatch.setattr("psutil.net_if_addrs", _home_vpn_nics)
    monkeypatch.setattr(
        "app.tools.terminal.shutil.which",
        lambda name: f"/usr/bin/{name}" if name in {"dig", "drill"} else None,
    )
    dig = lan_bound_dns_argv("dig @192.168.1.1 taco.lan")
    assert dig is not None
    assert dig[0] == "/usr/bin/dig"
    assert dig[1:3] == ["-b", "192.168.1.12"]
    assert dig[-2:] == ["@192.168.1.1", "taco.lan"]
    drill = lan_bound_dns_argv("drill @192.168.1.1 nas.local")
    assert drill is not None
    assert drill[1:3] == ["-b", "192.168.1.12"]
    assert lan_bound_dns_argv("dig @8.8.8.8 example.com") is None
    assert lan_bound_dns_argv("dig example.com") is None
    assert lan_bound_dns_argv("dig -b 192.168.1.12 @192.168.1.1 taco.lan") is None
    bash = _command_args("dig @192.168.1.50 MX taco.lan", "bash")
    assert bash[0] == "/usr/bin/dig"
    assert bash[1:3] == ["-b", "192.168.1.12"]
