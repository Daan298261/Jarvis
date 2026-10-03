from app.tools.python_exec import PythonTool
from app.tools.terminal import (
    TerminalTool,
    _command_args,
    _child_env,
    _python_args,
    cifs_host_from_token,
    default_shell,
    container_direct_argv,
    dockerfile_from_images,
    docker_registry_host_from_image,
    expand_image_vars,
    git_direct_argv,
    lan_bound_cifs_argv,
    compose_service_depends,
    compose_service_dockerfiles,
    compose_service_images,
    compose_service_inline_dockerfiles,
    lan_bound_compose_build_argv,
    lan_bound_compose_pull_argv,
    lan_bound_compose_push_argv,
    lan_bound_compose_run_argv,
    lan_bound_compose_up_argv,
    lan_bound_dns_argv,
    lan_bound_docker_bake_argv,
    lan_bound_docker_build_argv,
    rewrite_dockerfile_lan_add,
    lan_bound_docker_login_argv,
    lan_bound_docker_pull_argv,
    lan_bound_docker_push_argv,
    lan_bound_http_argv,
    lan_bound_netcat_argv,
    lan_bound_nfs_argv,
    lan_bound_rclone_argv,
    lan_bound_rsync_argv,
    lan_bound_scan_argv,
    lan_bound_smb_argv,
    lan_bound_snmp_argv,
    lan_bound_ssh_argv,
    nfs_host_from_token,
    python_direct_argv,
    rclone_host_from_token,
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
        lambda name: f"/usr/bin/{name}"
        if name in {"nmap", "ping", "traceroute", "masscan", "nping", "arp-scan", "arping", "fping", "iperf3", "iperf"}
        else None,
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
    arp = lan_bound_scan_argv("arp-scan 192.168.1.0/24")
    assert arp is not None
    assert arp[1:5] == ["--arpspa", "192.168.1.12", "-I", "eth0"]
    arping = lan_bound_scan_argv("arping 192.168.1.1")
    assert arping is not None
    assert arping[1:5] == ["-s", "192.168.1.12", "-I", "eth0"]
    fping = lan_bound_scan_argv("fping -c 1 192.168.1.50")
    assert fping is not None
    assert fping[1:5] == ["-S", "192.168.1.12", "-I", "eth0"]
    iperf = lan_bound_scan_argv("iperf3 -c 192.168.1.50")
    assert iperf is not None
    assert iperf[1:3] == ["-B", "192.168.1.12"]
    assert lan_bound_scan_argv("iperf3 -B 10.8.0.2 -c 192.168.1.50") is None
    assert lan_bound_scan_argv("arp-scan -I eth0 192.168.1.0/24") is None
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


def test_lan_mtr_and_nmblookup_bind_home_nic_not_vpn(monkeypatch):
    monkeypatch.setattr("psutil.net_if_addrs", _home_vpn_nics)
    monkeypatch.setattr("app.mobile.wan_forward.default_gateway_ipv4", lambda: "192.168.1.1")
    monkeypatch.setattr(
        "app.tools.terminal.shutil.which",
        lambda name: f"/usr/bin/{name}" if name in {"mtr", "nmblookup"} else None,
    )
    mtr = lan_bound_scan_argv("mtr -c 3 192.168.1.1")
    assert mtr is not None
    assert mtr[0] == "/usr/bin/mtr"
    assert mtr[1:3] == ["-a", "192.168.1.12"]
    assert mtr[-1] == "192.168.1.1"
    assert lan_bound_scan_argv("mtr -a 10.8.0.2 192.168.1.1") is None
    assert lan_bound_scan_argv("mtr 8.8.8.8") is None
    nmb = lan_bound_scan_argv("nmblookup -A 192.168.1.50")
    assert nmb is not None
    assert nmb[0] == "/usr/bin/nmblookup"
    assert nmb[1:5] == ["-B", "192.168.1.255", "-i", "eth0"]
    assert nmb[-1] == "192.168.1.50"
    star = lan_bound_scan_argv("nmblookup '*'")
    assert star is not None
    assert star[1:5] == ["-B", "192.168.1.255", "-i", "eth0"]
    assert lan_bound_scan_argv("nmblookup -i eth0 -A 192.168.1.50") is None
    bash = _command_args("mtr 192.168.1.50", "bash")
    assert bash[0] == "/usr/bin/mtr"
    assert bash[1:3] == ["-a", "192.168.1.12"]


def test_lan_tcpdump_and_tshark_bind_home_nic_not_vpn(monkeypatch):
    monkeypatch.setattr("psutil.net_if_addrs", _home_vpn_nics)
    monkeypatch.setattr(
        "app.tools.terminal.shutil.which",
        lambda name: f"/usr/bin/{name}" if name in {"tcpdump", "tshark", "dumpcap"} else None,
    )
    dump = lan_bound_scan_argv("tcpdump -n host 192.168.1.50")
    assert dump is not None
    assert dump[0] == "/usr/bin/tcpdump"
    assert dump[1:3] == ["-i", "eth0"]
    assert dump[-1] == "192.168.1.50"
    tshark = lan_bound_scan_argv("tshark -Y ip.addr==192.168.1.1")
    assert tshark is not None
    assert tshark[1:3] == ["-i", "eth0"]
    cap = lan_bound_scan_argv("dumpcap net 192.168.1.0/24")
    assert cap is not None
    assert cap[1:3] == ["-i", "eth0"]
    assert lan_bound_scan_argv("tcpdump -i wg0 host 192.168.1.50") is None
    assert lan_bound_scan_argv("tcpdump host 8.8.8.8") is None
    assert lan_bound_scan_argv("tcpdump -n") is None
    bash = _command_args("tcpdump host 192.168.1.1", "bash")
    assert bash[0] == "/usr/bin/tcpdump"
    assert bash[1:3] == ["-i", "eth0"]
    monkeypatch.setattr(
        "app.tools.terminal.shutil.which",
        lambda name: f"/usr/bin/{name}" if name in {"tcpdump", "tshark", "dumpcap", "hping3", "hping"} else None,
    )
    hping = lan_bound_scan_argv("hping3 -S -p 80 192.168.1.50")
    assert hping is not None
    assert hping[0] == "/usr/bin/hping3"
    assert hping[1:3] == ["-I", "eth0"]
    assert hping[-1] == "192.168.1.50"
    assert lan_bound_scan_argv("hping3 -I wg0 192.168.1.50") is None
    assert lan_bound_scan_argv("hping3 8.8.8.8") is None


def test_cifs_host_from_token_unc():
    assert cifs_host_from_token("//192.168.1.50/share") == "192.168.1.50"
    assert cifs_host_from_token("//nas.local/media") == "nas.local"
    assert cifs_host_from_token(r"\\nas.lan\backup") == "nas.lan"
    assert cifs_host_from_token("/mnt/nas") == ""


def test_lan_cifs_mount_binds_home_nic_not_vpn(monkeypatch):
    import socket

    monkeypatch.setattr("psutil.net_if_addrs", _home_vpn_nics)
    monkeypatch.setattr(
        "app.tools.terminal.shutil.which",
        lambda name: f"/usr/sbin/{name}" if name in {"mount", "mount.cifs"} else None,
    )

    def fake_getaddrinfo(host, *args, **kwargs):
        if host == "nas.local":
            return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("192.168.1.40", 0))]
        raise socket.gaierror("no")

    monkeypatch.setattr("app.mobile.wan_forward.socket.getaddrinfo", fake_getaddrinfo)
    mount = lan_bound_cifs_argv("mount -t cifs //192.168.1.50/share /mnt/nas")
    assert mount is not None
    assert mount[0] == "/usr/sbin/mount"
    assert mount[1:3] == ["-o", "srcaddr=192.168.1.12"]
    assert mount[-2:] == ["//192.168.1.50/share", "/mnt/nas"]
    guest = lan_bound_cifs_argv("mount -t cifs //nas.local/media /mnt -o guest,uid=1000")
    assert guest is not None
    assert guest[guest.index("-o") + 1] == "guest,uid=1000,srcaddr=192.168.1.12"
    helper = lan_bound_cifs_argv("mount.cifs //192.168.1.1/backup /mnt/backup")
    assert helper is not None
    assert helper[0] == "/usr/sbin/mount.cifs"
    assert helper[1:3] == ["-o", "srcaddr=192.168.1.12"]
    assert lan_bound_cifs_argv("mount -t ext4 /dev/sdb1 /mnt") is None
    assert lan_bound_cifs_argv("mount -t cifs //8.8.8.8/share /mnt") is None
    assert lan_bound_cifs_argv("mount -t cifs //192.168.1.50/share /mnt -o srcaddr=10.8.0.2") is None
    assert lan_bound_cifs_argv("mount -t cifs //192.168.1.50/share /mnt | cat") is None
    bash = _command_args("mount -t cifs //192.168.1.50/share /mnt/nas", "bash")
    assert bash[0] == "/usr/sbin/mount"
    assert bash[1:3] == ["-o", "srcaddr=192.168.1.12"]


def test_nfs_host_from_token():
    assert nfs_host_from_token("192.168.1.50:/export") == "192.168.1.50"
    assert nfs_host_from_token("nas.local:/share") == "nas.local"
    assert nfs_host_from_token("/mnt/nas") == ""
    assert nfs_host_from_token("C:/Windows") == ""


def test_lan_nfs_mount_binds_home_nic_not_vpn(monkeypatch):
    import socket

    monkeypatch.setattr("psutil.net_if_addrs", _home_vpn_nics)
    monkeypatch.setattr(
        "app.tools.terminal.shutil.which",
        lambda name: f"/usr/sbin/{name}" if name in {"mount", "mount.nfs", "mount.nfs4"} else None,
    )

    def fake_getaddrinfo(host, *args, **kwargs):
        if host == "nas.local":
            return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("192.168.1.40", 0))]
        raise socket.gaierror("no")

    monkeypatch.setattr("app.mobile.wan_forward.socket.getaddrinfo", fake_getaddrinfo)
    mount = lan_bound_nfs_argv("mount -t nfs 192.168.1.50:/export /mnt/nas")
    assert mount is not None
    assert mount[0] == "/usr/sbin/mount"
    assert mount[1:3] == ["-o", "clientaddr=192.168.1.12"]
    assert mount[-2:] == ["192.168.1.50:/export", "/mnt/nas"]
    named = lan_bound_nfs_argv("mount -t nfs nas.local:/media /mnt -o rw,vers=4")
    assert named is not None
    assert named[named.index("-o") + 1] == "rw,vers=4,clientaddr=192.168.1.12"
    helper = lan_bound_nfs_argv("mount.nfs 192.168.1.1:/backup /mnt/backup")
    assert helper is not None
    assert helper[0] == "/usr/sbin/mount.nfs"
    assert helper[1:3] == ["-o", "clientaddr=192.168.1.12"]
    assert lan_bound_nfs_argv("mount -t ext4 /dev/sdb1 /mnt") is None
    assert lan_bound_nfs_argv("mount -t nfs 8.8.8.8:/export /mnt") is None
    assert lan_bound_nfs_argv("mount -t nfs 192.168.1.50:/export /mnt -o clientaddr=10.8.0.2") is None
    assert lan_bound_nfs_argv("mount -t nfs 192.168.1.50:/export /mnt | cat") is None
    bash = _command_args("mount -t nfs 192.168.1.50:/export /mnt/nas", "bash")
    assert bash[0] == "/usr/sbin/mount"
    assert bash[1:3] == ["-o", "clientaddr=192.168.1.12"]


def test_rclone_host_from_token():
    assert rclone_host_from_token("sftp://me@192.168.1.50/share") == "192.168.1.50"
    assert rclone_host_from_token(":sftp,host=192.168.1.50,user=me:/home") == "192.168.1.50"
    assert rclone_host_from_token(":smb,host=nas.local:media") == "nas.local"
    assert rclone_host_from_token("local/path") == ""


def test_lan_rclone_binds_home_nic_not_vpn(monkeypatch):
    import socket

    monkeypatch.setattr("psutil.net_if_addrs", _home_vpn_nics)
    monkeypatch.setattr(
        "app.tools.terminal.shutil.which",
        lambda name: f"/usr/bin/{name}" if name in {"rclone", "rclone.exe"} else None,
    )

    def fake_getaddrinfo(host, *args, **kwargs):
        if host == "nas.local":
            return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("192.168.1.40", 0))]
        raise socket.gaierror("no")

    monkeypatch.setattr("app.mobile.wan_forward.socket.getaddrinfo", fake_getaddrinfo)
    listed = lan_bound_rclone_argv("rclone ls sftp://me@192.168.1.50/share")
    assert listed is not None
    assert listed[0] == "/usr/bin/rclone"
    assert listed[1:3] == ["--bind", "192.168.1.12"]
    conn = lan_bound_rclone_argv("rclone copy :sftp,host=nas.local,user=me:/media /tmp/out")
    assert conn is not None
    assert conn[1:3] == ["--bind", "192.168.1.12"]
    flag = lan_bound_rclone_argv("rclone ls --sftp-host 192.168.1.1 remote:")
    assert flag is not None
    assert flag[1:3] == ["--bind", "192.168.1.12"]
    assert lan_bound_rclone_argv("rclone ls sftp://me@8.8.8.8/share") is None
    assert lan_bound_rclone_argv("rclone --bind 10.8.0.2 ls sftp://me@192.168.1.50/share") is None
    assert lan_bound_rclone_argv("rclone ls sftp://me@192.168.1.50/share | cat") is None
    bash = _command_args("rclone ls sftp://me@192.168.1.50/share", "bash")
    assert bash[0] == "/usr/bin/rclone"
    assert bash[1:3] == ["--bind", "192.168.1.12"]


def test_lan_smbclient_binds_home_nic_not_vpn(monkeypatch):
    import socket

    monkeypatch.setattr("psutil.net_if_addrs", _home_vpn_nics)
    monkeypatch.setattr("app.mobile.wan_forward.default_gateway_ipv4", lambda: "192.168.1.1")
    monkeypatch.setattr(
        "app.tools.terminal.shutil.which",
        lambda name: f"/usr/bin/{name}" if name in {"smbclient", "smbget", "rpcclient", "smbtree"} else None,
    )

    def fake_getaddrinfo(host, *args, **kwargs):
        if host == "nas.local":
            return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("192.168.1.40", 0))]
        raise socket.gaierror("no")

    monkeypatch.setattr("app.mobile.wan_forward.socket.getaddrinfo", fake_getaddrinfo)
    listed = lan_bound_smb_argv("smbclient -L 192.168.1.50 -N")
    assert listed is not None
    assert listed[0] == "/usr/bin/smbclient"
    assert listed[1] == "--option=client addr=192.168.1.12"
    assert listed[2:] == ["-L", "192.168.1.50", "-N"]
    share = lan_bound_smb_argv("smbclient //nas.local/media -N")
    assert share is not None
    assert share[1] == "--option=client addr=192.168.1.12"
    assert share[-2:] == ["//nas.local/media", "-N"]
    get = lan_bound_smb_argv("smbget smb://192.168.1.1/backup/file.bin")
    assert get is not None
    assert get[1] == "--option=client addr=192.168.1.12"
    tree = lan_bound_smb_argv("smbtree -N")
    assert tree is not None
    assert tree[1] == "--option=client addr=192.168.1.12"
    assert lan_bound_smb_argv("smbclient -L 8.8.8.8") is None
    assert lan_bound_smb_argv("smbclient //192.168.1.50/share --option=client addr=10.8.0.2") is None
    assert lan_bound_smb_argv("smbclient //192.168.1.50/share | cat") is None
    bash = _command_args("smbclient -L 192.168.1.50 -N", "bash")
    assert bash[0] == "/usr/bin/smbclient"
    assert bash[1] == "--option=client addr=192.168.1.12"


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


def test_lan_snmpwalk_sets_clientaddr_not_vpn(monkeypatch):
    from pathlib import Path

    monkeypatch.setattr("psutil.net_if_addrs", _home_vpn_nics)
    monkeypatch.setattr(
        "app.tools.terminal.shutil.which",
        lambda name: f"/usr/bin/{name}" if name in {"snmpwalk", "snmpget"} else None,
    )
    argv = lan_bound_snmp_argv("snmpwalk -v2c -c public 192.168.1.1")
    assert argv is not None
    assert argv[0] == "/usr/bin/snmpwalk"
    assert argv[-1] == "192.168.1.1"
    env = _child_env(argv)
    conf = Path(env["SNMPCONFPATH"]) / "snmp.conf"
    assert "clientaddr 192.168.1.12" in conf.read_text(encoding="utf-8")
    assert lan_bound_snmp_argv("snmpwalk -v2c -c public 8.8.8.8") is None
    bash = _command_args("snmpget -v2c -c public 192.168.1.50 sysName.0", "bash")
    assert bash[0] == "/usr/bin/snmpget"
    assert "clientaddr 192.168.1.12" in (Path(_child_env(bash)["SNMPCONFPATH"]) / "snmp.conf").read_text(
        encoding="utf-8"
    )


def test_docker_registry_host_from_image():
    assert docker_registry_host_from_image("192.168.1.50:5000/app:latest") == "192.168.1.50"
    assert docker_registry_host_from_image("nas.local/org/img") == "nas.local"
    assert docker_registry_host_from_image("registry.lan:5000/app@sha256:abc") == "registry.lan"
    assert docker_registry_host_from_image("nginx") == ""
    assert docker_registry_host_from_image("library/nginx") == ""
    assert docker_registry_host_from_image("docker.io/library/nginx") == "docker.io"
    assert docker_registry_host_from_image("192.168.1.0/24") == ""


def test_lan_docker_pull_rewrites_to_skopeo_not_dockerd(monkeypatch):
    import socket

    monkeypatch.setattr("psutil.net_if_addrs", _home_vpn_nics)
    monkeypatch.setenv("HTTP_PROXY", "http://10.8.0.1:8080")
    monkeypatch.setattr(
        "app.tools.terminal.shutil.which",
        lambda name: f"/usr/bin/{name}"
        if name in {"skopeo", "skopeo.exe", "podman", "buildah", "trivy", "grype"}
        else None,
    )

    def fake_getaddrinfo(host, *args, **kwargs):
        if host in {"nas.local", "registry.lan"}:
            return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("192.168.1.40", 0))]
        raise socket.gaierror("no")

    monkeypatch.setattr("app.mobile.wan_forward.socket.getaddrinfo", fake_getaddrinfo)
    pulled = lan_bound_docker_pull_argv("docker pull 192.168.1.50:5000/app")
    assert pulled is not None
    assert pulled[0] == "/usr/bin/skopeo"
    assert pulled[1:3] == ["copy", "--src-tls-verify=false"]
    assert pulled[3] == "docker://192.168.1.50:5000/app:latest"
    assert pulled[4] == "docker-daemon:192.168.1.50:5000/app:latest"
    tagged = lan_bound_docker_pull_argv("docker image pull -q nas.local/org/img:v1")
    assert tagged is not None
    assert tagged[1:3] == ["copy", "--quiet"]
    assert "docker://nas.local/org/img:v1" in tagged
    assert lan_bound_docker_pull_argv("docker pull nginx") is None
    assert lan_bound_docker_pull_argv("docker pull docker.io/library/nginx") is None
    platform = lan_bound_docker_pull_argv("docker pull --platform linux/amd64 192.168.1.50:5000/app")
    assert platform is not None
    assert platform[1:5] == ["copy", "--override-os", "linux", "--override-arch"]
    assert platform[5] == "amd64"
    assert "--src-tls-verify=false" in platform
    equals = lan_bound_docker_pull_argv("docker pull --platform=linux/arm64/v8 192.168.1.50:5000/app:v1")
    assert equals is not None
    assert equals[1:7] == ["copy", "--override-os", "linux", "--override-arch", "arm64", "--override-variant"]
    assert equals[7] == "v8"
    assert lan_bound_docker_pull_argv("docker pull -a 192.168.1.50:5000/app") is not None
    all_tags = lan_bound_docker_pull_argv("docker pull --all-tags 192.168.1.50:5000/app:v1")
    assert all_tags is not None
    assert all_tags[1].endswith("lan_skopeo_load.py")
    assert "--all-tags" in all_tags
    assert "192.168.1.50:5000/app" in all_tags
    assert "192.168.1.50:5000/app:v1" not in all_tags
    plat_all = lan_bound_docker_pull_argv(
        "docker pull --all-tags --platform linux/arm64 192.168.1.50:5000/app"
    )
    assert plat_all is not None
    assert "--all-tags" in plat_all
    assert plat_all[plat_all.index("--override-os") : plat_all.index("--override-os") + 4] == [
        "--override-os",
        "linux",
        "--override-arch",
        "arm64",
    ]
    assert lan_bound_docker_pull_argv("docker pull 192.168.1.50:5000/app | cat") is None
    assert lan_bound_docker_pull_argv("docker pull 8.8.8.8:5000/app") is None
    bash = _command_args("docker pull 192.168.1.50:5000/app:stable", "bash")
    assert bash[0] == "/usr/bin/skopeo"
    env = _child_env(bash)
    assert env["HTTP_PROXY"].startswith("http://127.0.0.1:")
    assert "10.8.0.1" not in env["HTTP_PROXY"]
    podman = container_direct_argv("podman pull 192.168.1.50:5000/app")
    assert podman is not None
    assert podman[0] == "/usr/bin/podman"
    assert _child_env(podman)["HTTP_PROXY"].startswith("http://127.0.0.1:")
    buildah = _command_args("buildah pull registry.lan/base:latest", "bash")
    assert buildah[0] == "/usr/bin/buildah"
    assert _child_env(buildah)["HTTPS_PROXY"] == _child_env(buildah)["HTTP_PROXY"]
    scan = container_direct_argv("trivy image 192.168.1.50:5000/app")
    assert scan is not None
    assert scan[0] == "/usr/bin/trivy"
    assert _child_env(scan)["HTTP_PROXY"].startswith("http://127.0.0.1:")


def test_lan_docker_push_rewrites_to_skopeo_not_dockerd(monkeypatch):
    import socket

    monkeypatch.setattr("psutil.net_if_addrs", _home_vpn_nics)
    monkeypatch.setenv("HTTP_PROXY", "http://10.8.0.1:8080")
    monkeypatch.setattr(
        "app.tools.terminal.shutil.which",
        lambda name: f"/usr/bin/{name}" if name in {"skopeo", "skopeo.exe"} else None,
    )

    def fake_getaddrinfo(host, *args, **kwargs):
        if host == "nas.local":
            return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("192.168.1.40", 0))]
        raise socket.gaierror("no")

    monkeypatch.setattr("app.mobile.wan_forward.socket.getaddrinfo", fake_getaddrinfo)
    pushed = lan_bound_docker_push_argv("docker push 192.168.1.50:5000/app")
    assert pushed is not None
    assert pushed[0] == "/usr/bin/skopeo"
    assert pushed[1:3] == ["copy", "--dest-tls-verify=false"]
    assert pushed[3] == "docker-daemon:192.168.1.50:5000/app:latest"
    assert pushed[4] == "docker://192.168.1.50:5000/app:latest"
    quiet = lan_bound_docker_push_argv("docker image push -q nas.local/org/img:v1")
    assert quiet is not None
    assert "--quiet" in quiet
    assert "docker-daemon:nas.local/org/img:v1" in quiet
    assert lan_bound_docker_push_argv("docker push nginx") is None
    assert lan_bound_docker_push_argv("docker push docker.io/library/nginx") is None
    all_tags = lan_bound_docker_push_argv("docker push -a 192.168.1.50:5000/app")
    assert all_tags is not None
    assert all_tags[1].endswith("lan_skopeo_load.py")
    assert "--all-tags" in all_tags
    assert "--push" in all_tags
    assert "192.168.1.50:5000/app" in all_tags
    named = lan_bound_docker_push_argv("docker push --all-tags 192.168.1.50:5000/app:v1")
    assert named is not None
    assert "192.168.1.50:5000/app" in named
    assert lan_bound_docker_push_argv("docker push 192.168.1.50:5000/app | cat") is None
    bash = _command_args("docker push 192.168.1.50:5000/app:stable", "bash")
    assert bash[0] == "/usr/bin/skopeo"
    assert bash[1:3] == ["copy", "--dest-tls-verify=false"]
    env = _child_env(bash)
    assert env["HTTP_PROXY"].startswith("http://127.0.0.1:")
    assert "10.8.0.1" not in env["HTTP_PROXY"]


def test_lan_docker_login_rewrites_to_skopeo(tmp_path, monkeypatch):
    import socket

    monkeypatch.setattr("psutil.net_if_addrs", _home_vpn_nics)
    monkeypatch.setenv("HTTP_PROXY", "http://10.8.0.1:8080")
    monkeypatch.setattr(
        "app.tools.terminal.shutil.which",
        lambda name: f"/usr/bin/{name}" if name in {"skopeo", "skopeo.exe"} else None,
    )
    authfile = tmp_path / ".docker" / "config.json"
    monkeypatch.setattr("app.tools.terminal._docker_config_authfile", lambda: str(authfile))

    def fake_getaddrinfo(host, *args, **kwargs):
        if host == "nas.local":
            return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("192.168.1.40", 0))]
        raise socket.gaierror("no")

    monkeypatch.setattr("app.mobile.wan_forward.socket.getaddrinfo", fake_getaddrinfo)
    logged = lan_bound_docker_login_argv("docker login -u taco -p secret 192.168.1.50:5000")
    assert logged is not None
    assert logged[0] == "/usr/bin/skopeo"
    assert logged[1:4] == ["login", "--tls-verify=false", "--authfile"]
    assert logged[4] == str(authfile)
    assert logged[-5:] == ["-u", "taco", "-p", "secret", "192.168.1.50:5000"]
    assert authfile.parent.is_dir()
    named = lan_bound_docker_login_argv("docker login --username=taco --password-stdin nas.local:5000")
    assert named is not None
    assert "--username=taco" in named
    assert "--password-stdin" in named
    assert named[-1] == "nas.local:5000"
    https = lan_bound_docker_login_argv("docker login https://192.168.1.50:5000")
    assert https is not None
    assert https[-1] == "192.168.1.50:5000"
    assert lan_bound_docker_login_argv("docker login") is None
    assert lan_bound_docker_login_argv("docker login docker.io") is None
    assert lan_bound_docker_login_argv("docker login -u taco -p secret 192.168.1.50:5000 | cat") is None
    bash = _command_args("docker login -u taco 192.168.1.50:5000", "bash")
    assert bash[0] == "/usr/bin/skopeo"
    env = _child_env(bash)
    assert env["HTTP_PROXY"].startswith("http://127.0.0.1:")
    assert "10.8.0.1" not in env["HTTP_PROXY"]
    monkeypatch.setattr("psutil.net_if_addrs", _home_vpn_nics)
    monkeypatch.setattr("app.tools.terminal.shutil.which", lambda name: None)
    assert lan_bound_docker_pull_argv("docker pull 192.168.1.50:5000/app") is None
    assert container_direct_argv("podman pull 192.168.1.50:5000/app") is None


def test_terminal_git_and_pip_use_lan_http_proxy_not_vpn(monkeypatch):
    monkeypatch.setenv("HTTP_PROXY", "http://10.8.0.1:8080")
    monkeypatch.setenv("https_proxy", "http://10.8.0.1:8080")
    monkeypatch.setattr(
        "app.tools.terminal.shutil.which",
        lambda name: f"/usr/bin/{name}" if name in {"git", "git.exe", "pip", "pip3", "npm", "uv"} else None,
    )
    cloned = git_direct_argv("git clone http://192.168.1.50/repo.git")
    assert cloned is not None
    assert cloned[0] == "/usr/bin/git"
    assert cloned[1:] == ["clone", "http://192.168.1.50/repo.git"]
    bash = _command_args("git clone taco@192.168.1.50:media.git", "bash")
    assert bash[0] == "/usr/bin/git"
    env = _child_env(bash)
    assert env["HTTP_PROXY"].startswith("http://127.0.0.1:")
    assert "10.8.0.1" not in env["HTTP_PROXY"]
    assert "lan_ssh.py" in (env.get("GIT_SSH_COMMAND") or "")
    pip = container_direct_argv("pip install --index-url http://192.168.1.50:3141/simple pkg")
    assert pip is not None
    assert pip[0] == "/usr/bin/pip"
    assert _child_env(pip)["HTTP_PROXY"].startswith("http://127.0.0.1:")
    npm = _command_args("npm install --registry http://192.168.1.40:4873", "bash")
    assert npm[0] == "/usr/bin/npm"
    assert _child_env(npm)["HTTPS_PROXY"] == _child_env(npm)["HTTP_PROXY"]
    uv = container_direct_argv("uv pip install httpx")
    assert uv is not None
    assert _child_env(uv)["HTTP_PROXY"].startswith("http://127.0.0.1:")
    assert git_direct_argv("git clone http://192.168.1.50/repo.git | cat") is None
    assert container_direct_argv("pip install pkg && rm -rf /") is None


def test_lan_compose_pull_rewrites_to_skopeo(tmp_path, monkeypatch):
    monkeypatch.setattr("psutil.net_if_addrs", _home_vpn_nics)
    monkeypatch.setenv("HTTP_PROXY", "http://10.8.0.1:8080")
    monkeypatch.setattr(
        "app.tools.terminal.shutil.which",
        lambda name: f"/usr/bin/{name}" if name in {"skopeo", "skopeo.exe", "docker", "docker.exe"} else None,
    )
    stack = tmp_path / "compose.yaml"
    stack.write_text(
        "services:\n"
        "  app:\n"
        "    image: 192.168.1.50:5000/app:latest\n"
        "  cache:\n"
        "    image: 192.168.1.50:5000/redis:7\n"
        "  web:\n"
        "    image: nginx:alpine\n",
        encoding="utf-8",
    )
    one = tmp_path / "lan.yml"
    one.write_text("services:\n  app:\n    image: 192.168.1.50:5000/app\n", encoding="utf-8")
    single = lan_bound_compose_pull_argv(f"docker compose -f {one} pull")
    assert single is not None
    assert single[0] == "/usr/bin/skopeo"
    assert "docker://192.168.1.50:5000/app:latest" in single
    mixed = lan_bound_compose_pull_argv(f"docker compose -f {stack} pull")
    assert mixed is not None
    assert mixed[0] in {__import__("sys").executable, "python3"}
    assert mixed[1].endswith("lan_skopeo_load.py")
    assert "/usr/bin/skopeo" in mixed
    assert "192.168.1.50:5000/app:latest" in mixed
    assert "192.168.1.50:5000/redis:7" in mixed
    assert "--" in mixed
    follow = mixed[mixed.index("--") + 1 :]
    assert follow[:2] == ["/usr/bin/docker", "compose"]
    assert "-f" in follow and str(stack) in follow
    assert follow[-1] == "web"
    only_app = lan_bound_compose_pull_argv(f"docker compose -f {stack} pull app")
    assert only_app is not None
    assert only_app[0] == "/usr/bin/skopeo"
    assert lan_bound_compose_pull_argv(f"docker compose -f {stack} pull web") is None
    assert lan_bound_compose_pull_argv(f"docker compose -f {stack} pull | cat") is None
    nest = tmp_path / "only-lan"
    nest.mkdir()
    (nest / "compose.yml").write_text("services:\n  app:\n    image: 192.168.1.50:5000/app:v1\n", encoding="utf-8")
    from_cwd = lan_bound_compose_pull_argv("docker compose pull", cwd=str(nest))
    assert from_cwd is not None
    assert "docker://192.168.1.50:5000/app:v1" in from_cwd
    bash = _command_args(f"docker compose -f {one} pull", "bash", cwd=str(tmp_path))
    assert bash[0] == "/usr/bin/skopeo"
    env = _child_env(bash)
    assert env["HTTP_PROXY"].startswith("http://127.0.0.1:")
    assert "10.8.0.1" not in env["HTTP_PROXY"]
    interp = tmp_path / "interp.yaml"
    interp.write_text(
        "services:\n"
        "  app:\n"
        "    image: ${REGISTRY:-192.168.1.50:5000}/app:latest\n"
        "  skip:\n"
        "    image: ${MISSING}/app\n",
        encoding="utf-8",
    )
    defaulted = lan_bound_compose_pull_argv(f"docker compose -f {interp} pull")
    assert defaulted is not None
    assert "docker://192.168.1.50:5000/app:latest" in defaulted
    assert compose_service_images(interp) == {"app": "192.168.1.50:5000/app:latest"}


def test_lan_compose_push_rewrites_to_skopeo(tmp_path, monkeypatch):
    monkeypatch.setattr("psutil.net_if_addrs", _home_vpn_nics)
    monkeypatch.setenv("HTTP_PROXY", "http://10.8.0.1:8080")
    monkeypatch.setattr(
        "app.tools.terminal.shutil.which",
        lambda name: f"/usr/bin/{name}" if name in {"skopeo", "skopeo.exe", "docker", "docker.exe"} else None,
    )
    stack = tmp_path / "compose.yaml"
    stack.write_text(
        "services:\n"
        "  app:\n"
        "    image: 192.168.1.50:5000/app:latest\n"
        "    depends_on:\n"
        "      - cache\n"
        "  cache:\n"
        "    image: 192.168.1.50:5000/redis:7\n"
        "  web:\n"
        "    image: nginx:alpine\n",
        encoding="utf-8",
    )
    one = tmp_path / "lan.yml"
    one.write_text("services:\n  app:\n    image: 192.168.1.50:5000/app\n", encoding="utf-8")
    single = lan_bound_compose_push_argv(f"docker compose -f {one} push")
    assert single is not None
    assert single[0] == "/usr/bin/skopeo"
    assert "--dest-tls-verify=false" in single
    assert "docker-daemon:192.168.1.50:5000/app:latest" in single
    assert "docker://192.168.1.50:5000/app:latest" in single
    mixed = lan_bound_compose_push_argv(f"docker compose -f {stack} push")
    assert mixed is not None
    assert mixed[1].endswith("lan_skopeo_load.py")
    assert "--push" in mixed
    assert "192.168.1.50:5000/app:latest" in mixed
    assert "192.168.1.50:5000/redis:7" in mixed
    follow = mixed[mixed.index("--") + 1 :]
    assert follow[:2] == ["/usr/bin/docker", "compose"]
    assert follow[-1] == "web"
    assert "push" in follow
    only_app = lan_bound_compose_push_argv(f"docker compose -f {stack} push app")
    assert only_app is not None
    assert "docker://192.168.1.50:5000/app:latest" in only_app
    assert "192.168.1.50:5000/redis:7" not in " ".join(only_app)
    with_deps = lan_bound_compose_push_argv(f"docker compose -f {stack} push --include-deps app")
    assert with_deps is not None
    joined = " ".join(with_deps)
    assert "192.168.1.50:5000/app:latest" in joined
    assert "192.168.1.50:5000/redis:7" in joined
    assert lan_bound_compose_push_argv(f"docker compose -f {stack} push web") is None
    assert lan_bound_compose_push_argv(f"docker compose -f {stack} push | cat") is None
    bash = _command_args(f"docker compose -f {one} push", "bash", cwd=str(tmp_path))
    assert bash[0] == "/usr/bin/skopeo"
    assert "--dest-tls-verify=false" in bash
    env = _child_env(bash)
    assert env["HTTP_PROXY"].startswith("http://127.0.0.1:")
    assert "10.8.0.1" not in env["HTTP_PROXY"]


def test_lan_skopeo_load_runs_copies_then_follow(monkeypatch):
    from app.tools.lan_skopeo_load import main
    import json

    seen: list[list[str]] = []

    def fake_run(cmd, check=False, **kwargs):
        if kwargs.get("capture_output") and "list-tags" in cmd:
            return type("R", (), {"returncode": 0, "stdout": json.dumps({"Tags": ["latest", "v1"]})})()
        if kwargs.get("capture_output") and cmd[:3] == ["/usr/bin/docker", "image", "ls"]:
            return type(
                "R",
                (),
                {
                    "returncode": 0,
                    "stdout": "192.168.1.50:5000/app:latest\n192.168.1.50:5000/app:v1\n",
                },
            )()
        seen.append(list(cmd))
        return type("R", (), {"returncode": 0, "stdout": ""})()

    monkeypatch.setattr("app.tools.lan_skopeo_load.subprocess.run", fake_run)
    assert (
        main(["/usr/bin/skopeo", "192.168.1.50:5000/app:latest", "--", "/usr/bin/docker", "compose", "pull", "web"]) == 0
    )
    assert seen[0][:2] == ["/usr/bin/skopeo", "copy"]
    assert seen[0][-1] == "docker-daemon:192.168.1.50:5000/app:latest"
    assert seen[1] == ["/usr/bin/docker", "compose", "pull", "web"]
    seen.clear()
    assert main(["--push", "/usr/bin/skopeo", "192.168.1.50:5000/app:latest"]) == 0
    assert seen[0][:2] == ["/usr/bin/skopeo", "copy"]
    assert seen[0][-2:] == [
        "docker-daemon:192.168.1.50:5000/app:latest",
        "docker://192.168.1.50:5000/app:latest",
    ]
    assert "--dest-tls-verify=false" in seen[0]
    seen.clear()
    assert (
        main(
            [
                "--push-after",
                "192.168.1.50:5000/app:latest",
                "/usr/bin/skopeo",
                "192.168.1.50:5000/base:latest",
                "--",
                "/usr/bin/docker",
                "buildx",
                "build",
                "--load",
                ".",
            ]
        )
        == 0
    )
    assert seen[0][-1] == "docker-daemon:192.168.1.50:5000/base:latest"
    assert seen[1] == ["/usr/bin/docker", "buildx", "build", "--load", "."]
    assert seen[2][-2:] == [
        "docker-daemon:192.168.1.50:5000/app:latest",
        "docker://192.168.1.50:5000/app:latest",
    ]
    seen.clear()
    assert (
        main(
            [
                "--push-after",
                "192.168.1.50:5000/app:v1",
                "/usr/bin/skopeo",
                "--",
                "/usr/bin/docker",
                "buildx",
                "bake",
                "--load",
            ]
        )
        == 0
    )
    assert seen[0] == ["/usr/bin/docker", "buildx", "bake", "--load"]
    assert seen[1][-2:] == [
        "docker-daemon:192.168.1.50:5000/app:v1",
        "docker://192.168.1.50:5000/app:v1",
    ]
    seen.clear()
    monkeypatch.setattr("app.tools.lan_skopeo_load.shutil.which", lambda name: "/usr/bin/docker" if name in {"docker", "docker.exe"} else None)
    assert main(["--all-tags", "--push", "/usr/bin/skopeo", "192.168.1.50:5000/app"]) == 0
    assert [item[-1] for item in seen] == [
        "docker://192.168.1.50:5000/app:latest",
        "docker://192.168.1.50:5000/app:v1",
    ]
    seen.clear()
    assert main(["--all-tags", "/usr/bin/skopeo", "192.168.1.50:5000/app"]) == 0
    assert [item[-1] for item in seen] == [
        "docker-daemon:192.168.1.50:5000/app:latest",
        "docker-daemon:192.168.1.50:5000/app:v1",
    ]
    seen.clear()
    assert (
        main(
            [
                "--all-tags",
                "--override-os",
                "linux",
                "--override-arch",
                "arm64",
                "/usr/bin/skopeo",
                "192.168.1.50:5000/app",
            ]
        )
        == 0
    )
    assert seen[0][1:6] == ["copy", "--override-os", "linux", "--override-arch", "arm64"]
    seen.clear()
    assert (
        main(
            [
                "--push-after",
                "192.168.1.50:5000/app:latest",
                "/usr/bin/skopeo",
                "192.168.1.50:5000/base:latest",
                "--",
                "/usr/bin/docker",
                "compose",
                "build",
                "--",
                "/usr/bin/docker",
                "compose",
                "push",
                "web",
            ]
        )
        == 0
    )
    assert seen[0][-1] == "docker-daemon:192.168.1.50:5000/base:latest"
    assert seen[1] == ["/usr/bin/docker", "compose", "build"]
    assert seen[2][-2:] == [
        "docker-daemon:192.168.1.50:5000/app:latest",
        "docker://192.168.1.50:5000/app:latest",
    ]
    assert seen[3] == ["/usr/bin/docker", "compose", "push", "web"]


def test_dockerfile_from_images_skips_scratch_and_args(tmp_path):
    df = tmp_path / "Dockerfile"
    df.write_text(
        "FROM 192.168.1.50:5000/base:latest\n"
        "FROM --platform=linux/amd64 nas.local/org/runtime AS runtime\n"
        "# FROM ignored\n"
        "FROM scratch\n"
        "FROM ${BASE}\n"
        "FROM alpine:3.20\n",
        encoding="utf-8",
    )
    assert dockerfile_from_images(df) == [
        "192.168.1.50:5000/base:latest",
        "nas.local/org/runtime",
        "alpine:3.20",
    ]
    copied = tmp_path / "Copy.Dockerfile"
    copied.write_text(
        "FROM alpine:3.20\n"
        "COPY --from=192.168.1.50:5000/assets:1 /data /data\n"
        "COPY --chown=0:0 --from=nas.local/org/tools:2 /bin /opt/bin\n"
        "ADD --from=${ASSETS:-192.168.1.50:5000/extra:3} /x /x\n"
        "COPY --from=runtime /out /out\n"
        "COPY . /\n",
        encoding="utf-8",
    )
    assert dockerfile_from_images(copied) == [
        "alpine:3.20",
        "192.168.1.50:5000/assets:1",
        "nas.local/org/tools:2",
        "192.168.1.50:5000/extra:3",
        "runtime",
    ]
    assert dockerfile_from_images(copied, {"ASSETS": "192.168.1.50:5000/custom:9"}) == [
        "alpine:3.20",
        "192.168.1.50:5000/assets:1",
        "nas.local/org/tools:2",
        "192.168.1.50:5000/custom:9",
        "runtime",
    ]
    mounted = tmp_path / "Mount.Dockerfile"
    mounted.write_text(
        "FROM alpine:3.20\n"
        "RUN --mount=type=bind,from=192.168.1.50:5000/sdk:1,source=/opt,target=/sdk true\n"
        "RUN --mount=type=cache,id=go,from=${CACHE:-192.168.1.50:5000/gocache:1} go build\n"
        "RUN echo hi\n",
        encoding="utf-8",
    )
    assert dockerfile_from_images(mounted) == [
        "alpine:3.20",
        "192.168.1.50:5000/sdk:1",
        "192.168.1.50:5000/gocache:1",
    ]
    assert dockerfile_from_images(mounted, {"CACHE": "192.168.1.50:5000/other-cache:2"}) == [
        "alpine:3.20",
        "192.168.1.50:5000/sdk:1",
        "192.168.1.50:5000/other-cache:2",
    ]
    arged = tmp_path / "Arg.Dockerfile"
    arged.write_text(
        "ARG BASE=192.168.1.50:5000/base:latest\n"
        "FROM ${BASE}\n"
        "FROM ${OTHER:-nas.local/runtime}\n"
        "FROM ${MISSING}\n"
        "ARG EMPTY\n"
        "FROM $EMPTY\n",
        encoding="utf-8",
    )
    assert dockerfile_from_images(arged) == [
        "192.168.1.50:5000/base:latest",
        "nas.local/runtime",
    ]
    assert dockerfile_from_images(arged, {"BASE": "192.168.1.50:5000/custom:1"}) == [
        "192.168.1.50:5000/custom:1",
        "nas.local/runtime",
    ]
    assert expand_image_vars("${REGISTRY:-192.168.1.50:5000}/app:latest") == "192.168.1.50:5000/app:latest"
    assert expand_image_vars("${MISSING}/app") is None


def test_lan_docker_build_skopeo_loads_from_before_build(tmp_path, monkeypatch):
    import socket

    monkeypatch.setattr("psutil.net_if_addrs", _home_vpn_nics)
    monkeypatch.setenv("HTTP_PROXY", "http://10.8.0.1:8080")
    monkeypatch.setattr(
        "app.tools.terminal.shutil.which",
        lambda name: f"/usr/bin/{name}" if name in {"skopeo", "skopeo.exe", "docker", "docker.exe"} else None,
    )

    def fake_getaddrinfo(host, *args, **kwargs):
        if host == "nas.local":
            return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("192.168.1.40", 0))]
        raise socket.gaierror("no")

    monkeypatch.setattr("app.mobile.wan_forward.socket.getaddrinfo", fake_getaddrinfo)
    ctx = tmp_path / "app"
    ctx.mkdir()
    (ctx / "Dockerfile").write_text("FROM 192.168.1.50:5000/base:latest\nCOPY . .\n", encoding="utf-8")
    built = lan_bound_docker_build_argv(f"docker build -t mine {ctx}")
    assert built is not None
    assert built[1].endswith("lan_skopeo_load.py")
    assert "192.168.1.50:5000/base:latest" in built
    assert "--" in built
    follow = built[built.index("--") + 1 :]
    assert follow[0] == "/usr/bin/docker"
    assert "build" in follow
    assert "--pull=false" in follow
    assert str(ctx) in follow
    alt = tmp_path / "Dockerfile.lan"
    alt.write_text("FROM nas.local:5000/app\n", encoding="utf-8")
    custom = lan_bound_docker_build_argv(f"docker build -f {alt} -t x {ctx}", cwd=str(tmp_path))
    assert custom is not None
    assert "nas.local:5000/app:latest" in custom
    (ctx / "Dockerfile").write_text("FROM alpine:3.20\n", encoding="utf-8")
    assert lan_bound_docker_build_argv(f"docker build {ctx}") is None
    (ctx / "Dockerfile").write_text("FROM scratch\n", encoding="utf-8")
    assert lan_bound_docker_build_argv(f"docker build {ctx}") is None
    (ctx / "Dockerfile").write_text("FROM 192.168.1.50:5000/base\n", encoding="utf-8")
    bash = _command_args(f"docker build --pull {ctx}", "bash", cwd=str(tmp_path))
    assert bash[1].endswith("lan_skopeo_load.py")
    follow = bash[bash.index("--") + 1 :]
    assert "--pull=false" in follow
    assert "--pull" not in follow
    env = _child_env(bash)
    assert env["HTTP_PROXY"].startswith("http://127.0.0.1:")
    assert "10.8.0.1" not in env["HTTP_PROXY"]
    (ctx / "Dockerfile").write_text(
        "ARG BASE=192.168.1.50:5000/base:latest\nFROM ${BASE}\nCOPY . .\n",
        encoding="utf-8",
    )
    arged = lan_bound_docker_build_argv(f"docker build {ctx}")
    assert arged is not None
    assert "192.168.1.50:5000/base:latest" in arged
    override = lan_bound_docker_build_argv(
        f"docker build --build-arg BASE=192.168.1.50:5000/other:1 {ctx}"
    )
    assert override is not None
    assert "192.168.1.50:5000/other:1" in override
    assert "192.168.1.50:5000/base:latest" not in override
    (ctx / "Dockerfile").write_text("ARG BASE\nFROM ${BASE}\nCOPY . .\n", encoding="utf-8")
    monkeypatch.setenv("BASE", "192.168.1.50:5000/from-env:1")
    from_env = lan_bound_docker_build_argv(f"docker build --build-arg BASE {ctx}")
    assert from_env is not None
    assert "192.168.1.50:5000/from-env:1" in from_env
    assert lan_bound_docker_build_argv(f"docker build {ctx}") is None
    (ctx / "Dockerfile").write_text(
        "FROM alpine:3.20\nCOPY --from=192.168.1.50:5000/assets:1 /data /data\n",
        encoding="utf-8",
    )
    copied = lan_bound_docker_build_argv(f"docker build {ctx}")
    assert copied is not None
    assert "192.168.1.50:5000/assets:1" in copied
    follow = copied[copied.index("--") + 1 :]
    assert "--pull=false" in follow
    (ctx / "Dockerfile").write_text("FROM alpine:3.20\nCOPY --from=assets /data /data\n", encoding="utf-8")
    named = lan_bound_docker_build_argv(
        f"docker build --build-context assets=docker-image://192.168.1.50:5000/assets:1 {ctx}"
    )
    assert named is not None
    assert "192.168.1.50:5000/assets:1" in named
    assert lan_bound_docker_build_argv(
        f"docker build --build-context assets=docker-image://nginx:alpine {ctx}"
    ) is None
    (ctx / "Dockerfile").write_text(
        "FROM alpine:3.20\n"
        "RUN --mount=type=bind,from=192.168.1.50:5000/sdk:1,target=/sdk true\n",
        encoding="utf-8",
    )
    mounted = lan_bound_docker_build_argv(f"docker build {ctx}")
    assert mounted is not None
    assert "192.168.1.50:5000/sdk:1" in mounted
    (ctx / "Dockerfile").write_text("FROM alpine:3.20\n", encoding="utf-8")
    cached = lan_bound_docker_build_argv(
        f"docker build --cache-from 192.168.1.50:5000/app:cache {ctx}"
    )
    assert cached is not None
    assert "192.168.1.50:5000/app:cache" in cached
    typed = lan_bound_docker_build_argv(
        f"docker build --cache-from type=registry,ref=192.168.1.50:5000/app:typed {ctx}"
    )
    assert typed is not None
    assert "192.168.1.50:5000/app:typed" in typed
    assert lan_bound_docker_build_argv(
        f"docker build --cache-from type=local,src=/tmp/cache {ctx}"
    ) is None


def test_lan_docker_buildx_skopeo_loads_from_before_build(tmp_path, monkeypatch):
    monkeypatch.setattr("psutil.net_if_addrs", _home_vpn_nics)
    monkeypatch.setenv("HTTP_PROXY", "http://10.8.0.1:8080")
    monkeypatch.setattr(
        "app.tools.terminal.shutil.which",
        lambda name: f"/usr/bin/{name}" if name in {"skopeo", "skopeo.exe", "docker", "docker.exe"} else None,
    )
    ctx = tmp_path / "app"
    ctx.mkdir()
    (ctx / "Dockerfile").write_text("FROM 192.168.1.50:5000/base:latest\nCOPY . .\n", encoding="utf-8")
    built = lan_bound_docker_build_argv(f"docker buildx build --pull --builder default -t mine {ctx}")
    assert built is not None
    assert built[1].endswith("lan_skopeo_load.py")
    assert "192.168.1.50:5000/base:latest" in built
    follow = built[built.index("--") + 1 :]
    assert follow[:2] == ["/usr/bin/docker", "buildx"]
    assert "build" in follow
    assert "--pull=false" in follow
    assert "--pull" not in follow
    assert "--builder" in follow and "default" in follow
    assert str(ctx) in follow
    (ctx / "Dockerfile").write_text("FROM alpine:3.20\n", encoding="utf-8")
    assert lan_bound_docker_build_argv(f"docker buildx build {ctx}") is None
    (ctx / "Dockerfile").write_text("FROM 192.168.1.50:5000/base\n", encoding="utf-8")
    bash = _command_args(f"docker buildx build --load {ctx}", "bash", cwd=str(tmp_path))
    assert bash[1].endswith("lan_skopeo_load.py")
    follow = bash[bash.index("--") + 1 :]
    assert "--load" in follow
    env = _child_env(bash)
    assert env["HTTP_PROXY"].startswith("http://127.0.0.1:")
    assert "10.8.0.1" not in env["HTTP_PROXY"]


def test_lan_docker_buildx_push_skopeo_uploads_tag(tmp_path, monkeypatch):
    monkeypatch.setattr("psutil.net_if_addrs", _home_vpn_nics)
    monkeypatch.setenv("HTTP_PROXY", "http://10.8.0.1:8080")
    monkeypatch.setattr(
        "app.tools.terminal.shutil.which",
        lambda name: f"/usr/bin/{name}" if name in {"skopeo", "skopeo.exe", "docker", "docker.exe"} else None,
    )
    ctx = tmp_path / "app"
    ctx.mkdir()
    (ctx / "Dockerfile").write_text("FROM alpine:3.20\nCOPY . .\n", encoding="utf-8")
    pushed = lan_bound_docker_build_argv(
        f"docker buildx build --push -t 192.168.1.50:5000/app:latest {ctx}"
    )
    assert pushed is not None
    assert pushed[1].endswith("lan_skopeo_load.py")
    assert "--push-after" in pushed
    assert "192.168.1.50:5000/app:latest" in pushed
    follow = pushed[pushed.index("--") + 1 :]
    assert "buildx" in follow
    assert "--load" in follow
    assert "--push" not in follow
    assert "--pull=false" in follow
    (ctx / "Dockerfile").write_text("FROM 192.168.1.50:5000/base:latest\nCOPY . .\n", encoding="utf-8")
    both = lan_bound_docker_build_argv(
        f"docker buildx build --push -t 192.168.1.50:5000/app:v1 {ctx}"
    )
    assert both is not None
    assert "192.168.1.50:5000/base:latest" in both
    assert "--push-after" in both
    assert "192.168.1.50:5000/app:v1" in both
    hub = lan_bound_docker_build_argv(f"docker buildx build --push -t docker.io/library/app:1 {ctx}")
    assert hub is not None
    follow = hub[hub.index("--") + 1 :]
    assert "--push" in follow
    assert "--push-after" not in hub
    output = lan_bound_docker_build_argv(
        f"docker buildx build -o type=registry,name=192.168.1.50:5000/app:out {ctx}"
    )
    assert output is not None
    assert "--push-after" in output
    assert "192.168.1.50:5000/app:out" in output
    follow = output[output.index("--") + 1 :]
    assert "--load" in follow
    assert "-o" not in follow
    assert "--output" not in follow
    assert not any(item.startswith("--output=") or item.startswith("-o=") for item in follow)
    assert "type=registry" not in follow


def test_lan_docker_cache_to_skopeo_uploads_inline(tmp_path, monkeypatch):
    monkeypatch.setattr("psutil.net_if_addrs", _home_vpn_nics)
    monkeypatch.setenv("HTTP_PROXY", "http://10.8.0.1:8080")
    monkeypatch.setattr(
        "app.tools.terminal.shutil.which",
        lambda name: f"/usr/bin/{name}" if name in {"skopeo", "skopeo.exe", "docker", "docker.exe"} else None,
    )
    ctx = tmp_path / "app"
    ctx.mkdir()
    (ctx / "Dockerfile").write_text("FROM alpine:3.20\nCOPY . .\n", encoding="utf-8")
    exported = lan_bound_docker_build_argv(
        f"docker buildx build --cache-to type=registry,ref=192.168.1.50:5000/app:cache {ctx}"
    )
    assert exported is not None
    assert exported[1].endswith("lan_skopeo_load.py")
    assert "--push-after" in exported
    assert "192.168.1.50:5000/app:cache" in exported
    follow = exported[exported.index("--") + 1 :]
    assert "--load" in follow
    assert "--cache-to" in follow
    assert "type=inline" in follow
    assert "-t" in follow
    assert "192.168.1.50:5000/app:cache" in follow
    joined = " ".join(follow)
    assert "type=registry" not in joined
    equals = lan_bound_docker_build_argv(
        f"docker build --cache-to=type=registry,ref=192.168.1.50:5000/app:eq,mode=max {ctx}"
    )
    assert equals is not None
    assert "192.168.1.50:5000/app:eq" in equals
    follow = equals[equals.index("--") + 1 :]
    assert "type=inline" in follow
    assert "type=registry" not in " ".join(follow)
    mixed = lan_bound_docker_build_argv(
        "docker buildx build --push "
        "-t 192.168.1.50:5000/app:latest "
        "--cache-to type=registry,ref=192.168.1.50:5000/app:cache "
        "--cache-to type=local,dest=/tmp/jarvis-cache "
        f"{ctx}"
    )
    assert mixed is not None
    after = mixed.index("--push-after")
    dests = mixed[after + 1 : mixed.index("--")]
    assert "192.168.1.50:5000/app:latest" in dests
    assert "192.168.1.50:5000/app:cache" in dests
    follow = mixed[mixed.index("--") + 1 :]
    assert "--push" not in follow
    assert "--load" in follow
    assert "type=inline" in follow
    assert "type=local,dest=/tmp/jarvis-cache" in follow
    assert "type=registry" not in " ".join(follow)
    assert lan_bound_docker_build_argv(
        f"docker buildx build --cache-to type=registry,ref=docker.io/library/app:cache {ctx}"
    ) is None
    assert lan_bound_docker_build_argv(
        f"docker build --cache-to type=local,dest=/tmp/cache {ctx}"
    ) is None


def test_lan_compose_and_bake_cache_to_skopeo_uploads(tmp_path, monkeypatch):
    from pathlib import Path

    monkeypatch.setattr("psutil.net_if_addrs", _home_vpn_nics)
    monkeypatch.setenv("HTTP_PROXY", "http://10.8.0.1:8080")
    monkeypatch.setattr(
        "app.tools.terminal.shutil.which",
        lambda name: f"/usr/bin/{name}" if name in {"skopeo", "skopeo.exe", "docker", "docker.exe"} else None,
    )

    def fake_mkdtemp(prefix=""):
        root = tmp_path / f"{prefix or 'jarvis-lan-add-'}cache"
        root.mkdir(exist_ok=True)
        return str(root)

    monkeypatch.setattr("app.tools.terminal.tempfile.mkdtemp", fake_mkdtemp)
    app = tmp_path / "app"
    app.mkdir()
    (app / "Dockerfile").write_text("FROM alpine:3.20\nCOPY . .\n", encoding="utf-8")
    stack = tmp_path / "compose.yaml"
    stack.write_text(
        "services:\n"
        "  app:\n"
        "    build:\n"
        "      context: ./app\n"
        "      cache_to:\n"
        "        - type=registry,ref=192.168.1.50:5000/app:cache\n",
        encoding="utf-8",
    )
    built = lan_bound_compose_build_argv(f"docker compose -f {stack} build")
    assert built is not None
    assert "--push-after" in built
    assert "192.168.1.50:5000/app:cache" in built
    follow = built[built.index("--") + 1 :]
    overlays = [
        follow[i + 1]
        for i, item in enumerate(follow)
        if item in {"-f", "--file"} and i + 1 < len(follow) and "compose.jarvis-lan.yaml" in follow[i + 1]
    ]
    assert overlays
    overlay = Path(overlays[0]).read_text(encoding="utf-8")
    assert "cache_to: !override" in overlay
    assert "type=inline" in overlay
    assert "192.168.1.50:5000/app:cache" in overlay
    cli = lan_bound_compose_build_argv(
        f"docker compose -f {stack} build --cache-to type=registry,ref=192.168.1.50:5000/app:cli"
    )
    assert cli is not None
    assert "192.168.1.50:5000/app:cli" in cli
    follow = cli[cli.index("--") + 1 :]
    assert "type=inline" in follow
    assert "type=registry" not in " ".join(follow)
    up = lan_bound_compose_up_argv(f"docker compose -f {stack} up --build")
    assert up is not None
    assert "--push-after" in up
    assert "192.168.1.50:5000/app:cache" in up
    ran = lan_bound_compose_run_argv(f"docker compose -f {stack} run --build app")
    assert ran is not None
    assert "--push-after" in ran
    hcl = tmp_path / "docker-bake.hcl"
    hcl.write_text(
        "target \"app\" {\n"
        "  context = \"./app\"\n"
        "  dockerfile = \"Dockerfile\"\n"
        "  tags = [\"docker.io/library/app:1\"]\n"
        "  cache-to = [\"type=registry,ref=192.168.1.50:5000/from-bake-cache:1\"]\n"
        "}\n",
        encoding="utf-8",
    )
    baked = lan_bound_docker_bake_argv(f"docker buildx bake -f {hcl}")
    assert baked is not None
    assert "--push-after" in baked
    assert "192.168.1.50:5000/from-bake-cache:1" in baked
    follow = baked[baked.index("--") + 1 :]
    assert "--load" in follow
    assert "--set" in follow
    assert "app.cache-to=type=inline" in follow
    assert any(
        item.startswith("app.tags=") and "192.168.1.50:5000/from-bake-cache:1" in item for item in follow
    )
    payload = tmp_path / "bake.json"
    payload.write_text(
        '{"target":{"web":{"context":"./app","dockerfile":"Dockerfile",'
        '"cache-to":[{"type":"registry","ref":"192.168.1.50:5000/from-json-cache:1"}]}}}',
        encoding="utf-8",
    )
    json_bake = lan_bound_docker_bake_argv(f"docker buildx bake -f {payload}")
    assert json_bake is not None
    assert "192.168.1.50:5000/from-json-cache:1" in json_bake
    follow = json_bake[json_bake.index("--") + 1 :]
    assert "web.cache-to=type=inline" in follow
    assert any(item.startswith("web.tags=") and "from-json-cache:1" in item for item in follow)


def test_lan_compose_and_bake_inline_dockerfile(tmp_path, monkeypatch):
    from pathlib import Path

    monkeypatch.setattr("psutil.net_if_addrs", _home_vpn_nics)
    monkeypatch.setenv("HTTP_PROXY", "http://10.8.0.1:8080")

    def fake_mkdtemp(prefix=""):
        root = tmp_path / f"{prefix or 'jarvis-lan-add-'}inline"
        root.mkdir(exist_ok=True)
        return str(root)

    monkeypatch.setattr("app.tools.terminal.tempfile.mkdtemp", fake_mkdtemp)
    monkeypatch.setattr(
        "app.tools.terminal.shutil.which",
        lambda name: f"/usr/bin/{name}"
        if name in {"skopeo", "skopeo.exe", "docker", "docker.exe"}
        else None,
    )
    stack = tmp_path / "compose.yaml"
    stack.write_text(
        "services:\n"
        "  app:\n"
        "    build:\n"
        "      dockerfile_inline: |\n"
        "        FROM 192.168.1.50:5000/base:latest\n"
        "        COPY . .\n",
        encoding="utf-8",
    )
    assert compose_service_inline_dockerfiles(stack)["app"].startswith("FROM 192.168.1.50")
    built = lan_bound_compose_build_argv(f"docker compose -f {stack} build")
    assert built is not None
    assert "192.168.1.50:5000/base:latest" in built
    follow = built[built.index("--") + 1 :]
    assert "build" in follow
    add_stack = tmp_path / "add.yaml"
    add_stack.write_text(
        "services:\n"
        "  pkg:\n"
        "    build:\n"
        "      dockerfile_inline: |\n"
        "        FROM alpine:3.20\n"
        "        ADD http://192.168.1.50:8000/pkg.tgz /opt/pkg.tgz\n",
        encoding="utf-8",
    )
    added = lan_bound_compose_build_argv(f"docker compose -f {add_stack} build")
    assert added is not None
    assert "--fetch" in added
    assert any(item.startswith("http://192.168.1.50:8000/pkg.tgz=") for item in added)
    follow = added[added.index("--") + 1 :]
    overlays = [
        follow[i + 1]
        for i, item in enumerate(follow)
        if item in {"-f", "--file"} and i + 1 < len(follow) and "compose.jarvis-lan.yaml" in follow[i + 1]
    ]
    assert overlays
    overlay = Path(overlays[0]).read_text(encoding="utf-8")
    assert "dockerfile_inline: !reset" in overlay
    import json

    df_line = next(line for line in overlay.splitlines() if line.strip().startswith("dockerfile:"))
    rewritten = Path(json.loads(df_line.split(":", 1)[1].strip()))
    assert "COPY --from=jarvisadd0 pkg.tgz /opt/pkg.tgz" in rewritten.read_text(encoding="utf-8")
    up = lan_bound_compose_up_argv(f"docker compose -f {stack} up --build")
    assert up is not None
    assert "192.168.1.50:5000/base:latest" in up
    hub = tmp_path / "hub.yaml"
    hub.write_text(
        "services:\n"
        "  web:\n"
        "    build:\n"
        "      dockerfile_inline: FROM scratch\n",
        encoding="utf-8",
    )
    assert lan_bound_compose_build_argv(f"docker compose -f {hub} build") is None
    payload = tmp_path / "bake.json"
    payload.write_text(
        '{"target":{"web":{"dockerfile-inline":'
        '"FROM 192.168.1.50:5000/base:latest\\nADD http://192.168.1.50:8000/pkg.tgz /opt/pkg.tgz\\n"}}}',
        encoding="utf-8",
    )
    baked = lan_bound_docker_bake_argv(f"docker buildx bake -f {payload}")
    assert baked is not None
    assert "192.168.1.50:5000/base:latest" in baked
    assert "--fetch" in baked
    follow = baked[baked.index("--") + 1 :]
    assert "web.dockerfile-inline=" in follow
    assert any(item.startswith("web.dockerfile=") for item in follow)
    hcl = tmp_path / "docker-bake.hcl"
    hcl.write_text(
        'target "app" {\n'
        '  dockerfile-inline = "FROM 192.168.1.50:5000/from-hcl:1\\nCOPY . .\\n"\n'
        "}\n",
        encoding="utf-8",
    )
    hcl_bake = lan_bound_docker_bake_argv(f"docker buildx bake -f {hcl}")
    assert hcl_bake is not None
    assert "192.168.1.50:5000/from-hcl:1" in hcl_bake


def test_lan_run_wget_curl_and_hcl_heredoc(tmp_path, monkeypatch):
    from pathlib import Path

    monkeypatch.setattr("psutil.net_if_addrs", _home_vpn_nics)
    monkeypatch.setenv("HTTP_PROXY", "http://10.8.0.1:8080")

    def fake_mkdtemp(prefix=""):
        root = tmp_path / f"{prefix or 'jarvis-lan-add-'}run"
        root.mkdir(exist_ok=True)
        return str(root)

    monkeypatch.setattr("app.tools.terminal.tempfile.mkdtemp", fake_mkdtemp)
    monkeypatch.setattr(
        "app.tools.terminal.shutil.which",
        lambda name: f"/usr/bin/{name}" if name in {"docker", "docker.exe"} else None,
    )
    ctx = tmp_path / "app"
    ctx.mkdir()
    (ctx / "Dockerfile").write_text(
        "FROM alpine:3.20\n"
        "RUN wget -q -O /opt/pkg.tgz http://192.168.1.50:8000/pkg.tgz\n",
        encoding="utf-8",
    )
    wget = lan_bound_docker_build_argv(f"docker build {ctx}")
    assert wget is not None
    assert "--fetch" in wget
    assert any(item.startswith("http://192.168.1.50:8000/pkg.tgz=") for item in wget)
    follow = wget[wget.index("--") + 1 :]
    rewritten = Path(follow[follow.index("-f") + 1])
    text = rewritten.read_text(encoding="utf-8")
    assert "COPY --from=jarvisadd0 pkg.tgz /opt/pkg.tgz" in text
    assert "RUN wget" not in text
    (ctx / "Dockerfile").write_text(
        "FROM alpine:3.20\n"
        "RUN curl -fsSL -o /usr/local/bin/tool http://192.168.1.50:8000/tool\n",
        encoding="utf-8",
    )
    curled = lan_bound_docker_build_argv(f"docker build {ctx}")
    assert curled is not None
    follow = curled[curled.index("--") + 1 :]
    text = Path(follow[follow.index("-f") + 1]).read_text(encoding="utf-8")
    assert "COPY --from=jarvisadd0 tool /usr/local/bin/tool" in text
    (ctx / "Dockerfile").write_text(
        "FROM alpine:3.20\n"
        "RUN curl -fsSL http://192.168.1.50:8000/install.sh | sh\n",
        encoding="utf-8",
    )
    piped = lan_bound_docker_build_argv(f"docker build {ctx}")
    assert piped is not None
    follow = piped[piped.index("--") + 1 :]
    text = Path(follow[follow.index("-f") + 1]).read_text(encoding="utf-8")
    assert "COPY --from=jarvisadd0 install.sh /tmp/jarvisadd0-install.sh" in text
    assert "RUN sh /tmp/jarvisadd0-install.sh" in text
    (ctx / "Dockerfile").write_text(
        'FROM alpine:3.20\nRUN ["wget", "-O", "/opt/a.bin", "http://192.168.1.50:8000/a.bin"]\n',
        encoding="utf-8",
    )
    exec_form = lan_bound_docker_build_argv(f"docker build {ctx}")
    assert exec_form is not None
    follow = exec_form[exec_form.index("--") + 1 :]
    text = Path(follow[follow.index("-f") + 1]).read_text(encoding="utf-8")
    assert "COPY --from=jarvisadd0 a.bin /opt/a.bin" in text
    (ctx / "Dockerfile").write_text(
        "FROM alpine:3.20\n"
        "RUN apk add curl && wget -O /x http://192.168.1.50:8000/x && chmod 755 /x\n",
        encoding="utf-8",
    )
    chained = lan_bound_docker_build_argv(f"docker build {ctx}")
    assert chained is not None
    follow = chained[chained.index("--") + 1 :]
    text = Path(follow[follow.index("-f") + 1]).read_text(encoding="utf-8")
    assert "RUN apk add curl" in text
    assert "COPY --from=jarvisadd0 x /x" in text
    assert "RUN chmod 755 /x" in text
    assert "wget" not in text
    (ctx / "Dockerfile").write_text(
        "FROM alpine:3.20\n"
        "RUN wget -O /opt/pkg.tgz http://192.168.1.50:8000/pkg.tgz && tar -tzf /opt/pkg.tgz\n",
        encoding="utf-8",
    )
    leading = lan_bound_docker_build_argv(f"docker build {ctx}")
    assert leading is not None
    follow = leading[leading.index("--") + 1 :]
    text = Path(follow[follow.index("-f") + 1]).read_text(encoding="utf-8")
    assert text.index("COPY --from=jarvisadd0") < text.index("RUN tar")
    assert "wget" not in text
    (ctx / "Dockerfile").write_text(
        "FROM alpine:3.20\n"
        "RUN apk add curl && curl -fsSL http://192.168.1.50:8000/install.sh | sh\n",
        encoding="utf-8",
    )
    piped_chain = lan_bound_docker_build_argv(f"docker build {ctx}")
    assert piped_chain is not None
    follow = piped_chain[piped_chain.index("--") + 1 :]
    text = Path(follow[follow.index("-f") + 1]).read_text(encoding="utf-8")
    assert "RUN apk add curl" in text
    assert "COPY --from=jarvisadd0 install.sh" in text
    assert "RUN sh /tmp/jarvisadd0-install.sh" in text
    (ctx / "Dockerfile").write_text(
        "FROM alpine:3.20\n"
        "RUN apk add curl; echo ready && wget -O /x http://192.168.1.50:8000/x\n",
        encoding="utf-8",
    )
    semi = lan_bound_docker_build_argv(f"docker build {ctx}")
    assert semi is not None
    follow = semi[semi.index("--") + 1 :]
    text = Path(follow[follow.index("-f") + 1]).read_text(encoding="utf-8")
    assert "RUN apk add curl ; echo ready" in text
    assert "COPY --from=jarvisadd0 x /x" in text
    assert "wget" not in text
    (ctx / "Dockerfile").write_text(
        "FROM alpine:3.20\nRUN wget -O /x http://192.168.1.50:8000/x || true\n",
        encoding="utf-8",
    )
    assert lan_bound_docker_build_argv(f"docker build {ctx}") is None
    (ctx / "Dockerfile").write_text(
        "FROM alpine:3.20\nRUN curl -fsSL https://example.com/install.sh | sh\n",
        encoding="utf-8",
    )
    assert lan_bound_docker_build_argv(f"docker build {ctx}") is None
    monkeypatch.setattr(
        "app.tools.terminal.shutil.which",
        lambda name: f"/usr/bin/{name}"
        if name in {"skopeo", "skopeo.exe", "docker", "docker.exe"}
        else None,
    )
    hcl = tmp_path / "docker-bake.hcl"
    hcl.write_text(
        "target \"app\" {\n"
        "  dockerfile-inline = <<EOF\n"
        "FROM 192.168.1.50:5000/from-heredoc:1\n"
        "ADD http://192.168.1.50:8000/pkg.tgz /opt/pkg.tgz\n"
        "EOF\n"
        "}\n",
        encoding="utf-8",
    )
    baked = lan_bound_docker_bake_argv(f"docker buildx bake -f {hcl}")
    assert baked is not None
    assert "192.168.1.50:5000/from-heredoc:1" in baked
    assert "--fetch" in baked
    follow = baked[baked.index("--") + 1 :]
    assert "app.dockerfile-inline=" in follow
    assert any(item.startswith("app.dockerfile=") for item in follow)


def test_lan_skopeo_load_fetches_add_http_before_follow(tmp_path, monkeypatch):
    from pathlib import Path
    from app.tools.lan_skopeo_load import main

    seen: list[list[str]] = []
    fetched: list[tuple[str, str]] = []

    def fake_run(cmd, check=False, **kwargs):
        seen.append(list(cmd))
        return type("R", (), {"returncode": 0, "stdout": ""})()

    def fake_retrieve(url, filename, **kwargs):
        fetched.append((url, filename))
        dest = Path(filename)
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(b"pkg")
        return filename, None

    monkeypatch.setattr("app.tools.lan_skopeo_load.subprocess.run", fake_run)
    monkeypatch.setattr("app.tools.lan_skopeo_load.urllib.request.urlretrieve", fake_retrieve)
    dest = tmp_path / "jarvisadd0" / "pkg.tgz"
    assert (
        main(
            [
                "--fetch",
                f"http://192.168.1.50:8000/pkg.tgz={dest}",
                "--",
                "/usr/bin/docker",
                "build",
                "--pull=false",
                ".",
            ]
        )
        == 0
    )
    assert fetched == [("http://192.168.1.50:8000/pkg.tgz", str(dest))]
    assert dest.read_bytes() == b"pkg"
    assert seen == [["/usr/bin/docker", "build", "--pull=false", "."]]
    seen.clear()
    fetched.clear()

    def boom(url, filename, **kwargs):
        raise OSError("offline")

    monkeypatch.setattr("app.tools.lan_skopeo_load.urllib.request.urlretrieve", boom)
    assert (
        main(
            [
                "--fetch",
                f"http://192.168.1.50:8000/pkg.tgz={tmp_path / 'missing.tgz'}",
                "--",
                "/usr/bin/docker",
                "build",
                ".",
            ]
        )
        == 1
    )
    assert seen == []
    monkeypatch.setattr("app.tools.lan_skopeo_load.urllib.request.urlretrieve", fake_retrieve)
    root = tmp_path / "jarvis-lan-add-xyz"
    root.mkdir()
    nested = root / "jarvisadd0" / "pkg.tgz"
    assert (
        main(
            [
                "--cleanup",
                str(root),
                "--fetch",
                f"http://192.168.1.50:8000/pkg.tgz={nested}",
                "--",
                "/usr/bin/docker",
                "build",
                ".",
            ]
        )
        == 0
    )
    assert not root.exists()
    assert main(["--fetch", "not-a-spec", "--", "/usr/bin/docker", "build", "."]) == 2


def test_lan_docker_build_prefetches_add_http(tmp_path, monkeypatch):
    from pathlib import Path

    monkeypatch.setattr("psutil.net_if_addrs", _home_vpn_nics)
    monkeypatch.setenv("HTTP_PROXY", "http://10.8.0.1:8080")

    def fake_mkdtemp(prefix=""):
        root = tmp_path / f"{prefix or 'jarvis-lan-add-'}work"
        root.mkdir(exist_ok=True)
        return str(root)

    monkeypatch.setattr("app.tools.terminal.tempfile.mkdtemp", fake_mkdtemp)
    monkeypatch.setattr(
        "app.tools.terminal.shutil.which",
        lambda name: f"/usr/bin/{name}" if name in {"docker", "docker.exe"} else None,
    )
    ctx = tmp_path / "app"
    ctx.mkdir()
    df = ctx / "Dockerfile"
    df.write_text(
        "FROM alpine:3.20\n"
        "ADD --chown=1000:1000 --checksum=sha256:abc "
        "http://192.168.1.50:8000/pkg.tgz /opt/pkg.tgz\n",
        encoding="utf-8",
    )
    built = lan_bound_docker_build_argv(f"docker build -t mine {ctx}")
    assert built is not None
    assert built[1].endswith("lan_skopeo_load.py")
    assert "/usr/bin/skopeo" not in built
    assert "--fetch" in built
    spec = built[built.index("--fetch") + 1]
    assert spec.startswith("http://192.168.1.50:8000/pkg.tgz=")
    assert spec.endswith("pkg.tgz")
    assert "--cleanup" in built
    follow = built[built.index("--") + 1 :]
    assert follow[0] == "/usr/bin/docker"
    assert "build" in follow
    assert "--pull=false" in follow
    assert "-f" in follow
    rewritten = Path(follow[follow.index("-f") + 1])
    text = rewritten.read_text(encoding="utf-8")
    assert "COPY --from=jarvisadd0 --chown=1000:1000 pkg.tgz /opt/pkg.tgz" in text
    assert "ADD " not in text
    assert "--checksum" not in text
    assert "--build-context" in follow
    ctx_flag = follow[follow.index("--build-context") + 1]
    assert ctx_flag.startswith("jarvisadd0=")
    env = _child_env(built)
    assert env["HTTP_PROXY"].startswith("http://127.0.0.1:")
    assert "10.8.0.1" not in env["HTTP_PROXY"]
    json_df = tmp_path / "Json.Dockerfile"
    json_df.write_text(
        'FROM alpine:3.20\nADD ["http://192.168.1.50:8000/a.bin", "/a.bin"]\n',
        encoding="utf-8",
    )
    json_built = lan_bound_docker_build_argv(f"docker build -f {json_df} {ctx}")
    assert json_built is not None
    json_follow = json_built[json_built.index("--") + 1 :]
    json_text = Path(json_follow[json_follow.index("-f") + 1]).read_text(encoding="utf-8")
    assert "COPY --from=jarvisadd0 a.bin /a.bin" in json_text
    assert str(json_df) not in json_follow
    continued = tmp_path / "Cont.Dockerfile"
    continued.write_text(
        "FROM alpine:3.20\n"
        "ADD ftp://192.168.1.50/backup.tar \\\n"
        "    /backup.tar\n",
        encoding="utf-8",
    )
    ftp_built = lan_bound_docker_build_argv(f"docker build -f {continued} {ctx}")
    assert ftp_built is not None
    assert any(
        item.startswith("ftp://192.168.1.50/backup.tar=")
        for item in ftp_built
        if isinstance(item, str)
    )
    arged = tmp_path / "Arg.Dockerfile"
    arged.write_text(
        "ARG HOST=192.168.1.50:8000\n"
        "FROM alpine:3.20\n"
        "ADD http://${HOST}/pkg.tgz /opt/\n",
        encoding="utf-8",
    )
    arg_built = lan_bound_docker_build_argv(f"docker build -f {arged} {ctx}")
    assert arg_built is not None
    assert any("http://192.168.1.50:8000/pkg.tgz=" in item for item in arg_built)
    override = lan_bound_docker_build_argv(
        f"docker build -f {arged} --build-arg HOST=192.168.1.40:8000 {ctx}"
    )
    assert override is not None
    assert any("http://192.168.1.40:8000/pkg.tgz=" in item for item in override)
    df.write_text("FROM alpine:3.20\nADD https://example.com/pkg.tgz /opt/pkg.tgz\n", encoding="utf-8")
    assert lan_bound_docker_build_argv(f"docker build {ctx}") is None
    df.write_text("FROM alpine:3.20\nADD pkg.tgz /opt/\n", encoding="utf-8")
    assert lan_bound_docker_build_argv(f"docker build {ctx}") is None
    monkeypatch.setattr(
        "app.tools.terminal.shutil.which",
        lambda name: f"/usr/bin/{name}"
        if name in {"skopeo", "skopeo.exe", "docker", "docker.exe"}
        else None,
    )
    df.write_text(
        "FROM 192.168.1.50:5000/base:latest\n"
        "ADD http://192.168.1.50:8000/pkg.tgz /opt/pkg.tgz\n",
        encoding="utf-8",
    )
    both = lan_bound_docker_build_argv(f"docker buildx build --push -t 192.168.1.50:5000/app:1 {ctx}")
    assert both is not None
    assert "192.168.1.50:5000/base:latest" in both
    assert "--fetch" in both
    assert "--push-after" in both
    follow = both[both.index("--") + 1 :]
    assert "buildx" in follow
    assert "--load" in follow
    assert "--push" not in follow
    assert "-f" in follow
    assert "COPY --from=jarvisadd0" in Path(follow[follow.index("-f") + 1]).read_text(encoding="utf-8")
    df.write_text(
        "FROM alpine:3.20\n"
        "ADD http://192.168.1.50:8000/a.bin https://example.com/b.bin /data/\n",
        encoding="utf-8",
    )
    mixed_text, mixed_plan = rewrite_dockerfile_lan_add(df)
    assert mixed_plan == [("http://192.168.1.50:8000/a.bin", "jarvisadd0", "a.bin")]
    assert "COPY --from=jarvisadd0 a.bin /data/" in mixed_text
    assert "ADD https://example.com/b.bin /data/" in mixed_text


def test_lan_compose_and_bake_prefetches_add_http(tmp_path, monkeypatch):
    from pathlib import Path

    monkeypatch.setattr("psutil.net_if_addrs", _home_vpn_nics)
    monkeypatch.setenv("HTTP_PROXY", "http://10.8.0.1:8080")

    def fake_mkdtemp(prefix=""):
        root = tmp_path / f"{prefix or 'jarvis-lan-add-'}work"
        root.mkdir(exist_ok=True)
        return str(root)

    monkeypatch.setattr("app.tools.terminal.tempfile.mkdtemp", fake_mkdtemp)
    monkeypatch.setattr(
        "app.tools.terminal.shutil.which",
        lambda name: f"/usr/bin/{name}" if name in {"docker", "docker.exe"} else None,
    )
    app = tmp_path / "app"
    app.mkdir()
    (app / "Dockerfile").write_text(
        "FROM alpine:3.20\nADD http://192.168.1.50:8000/pkg.tgz /opt/pkg.tgz\n",
        encoding="utf-8",
    )
    stack = tmp_path / "compose.yaml"
    stack.write_text("services:\n  app:\n    build: ./app\n", encoding="utf-8")
    built = lan_bound_compose_build_argv(f"docker compose -f {stack} build")
    assert built is not None
    assert built[1].endswith("lan_skopeo_load.py")
    assert "/usr/bin/skopeo" not in built
    assert "--fetch" in built
    assert any(item.startswith("http://192.168.1.50:8000/pkg.tgz=") for item in built)
    follow = built[built.index("--") + 1 :]
    overlays = [
        follow[i + 1]
        for i, item in enumerate(follow)
        if item in {"-f", "--file"} and i + 1 < len(follow) and "compose.jarvis-lan.yaml" in follow[i + 1]
    ]
    assert overlays
    import yaml

    payload = yaml.safe_load(Path(overlays[0]).read_text(encoding="utf-8"))
    rewritten = Path(payload["services"]["app"]["build"]["dockerfile"])
    assert "COPY --from=jarvisadd0 pkg.tgz /opt/pkg.tgz" in rewritten.read_text(encoding="utf-8")
    assert "jarvisadd0" in payload["services"]["app"]["build"]["additional_contexts"]
    up = lan_bound_compose_up_argv(f"docker compose -f {stack} up --build")
    assert up is not None
    assert "--fetch" in up
    ran = lan_bound_compose_run_argv(f"docker compose -f {stack} run --build app")
    assert ran is not None
    assert "--fetch" in ran
    hcl = tmp_path / "docker-bake.hcl"
    hcl.write_text(
        'target "app" {\n  context = "./app"\n  dockerfile = "Dockerfile"\n}\n',
        encoding="utf-8",
    )
    baked = lan_bound_docker_bake_argv(f"docker buildx bake -f {hcl}", cwd=str(tmp_path))
    assert baked is not None
    assert "--fetch" in baked
    bake_follow = baked[baked.index("--") + 1 :]
    assert "--set" in bake_follow
    sets = [bake_follow[i + 1] for i, item in enumerate(bake_follow) if item == "--set" and i + 1 < len(bake_follow)]
    assert any(item.startswith("app.dockerfile=") for item in sets)
    assert any(item.startswith("app.contexts.jarvisadd0=") for item in sets)
    (app / "Dockerfile").write_text(
        "FROM alpine:3.20\nADD https://example.com/pkg.tgz /opt/pkg.tgz\n",
        encoding="utf-8",
    )
    assert lan_bound_compose_build_argv(f"docker compose -f {stack} build") is None
    assert lan_bound_docker_bake_argv(f"docker buildx bake -f {hcl}", cwd=str(tmp_path)) is None
    monkeypatch.setattr(
        "app.tools.terminal.shutil.which",
        lambda name: f"/usr/bin/{name}"
        if name in {"skopeo", "skopeo.exe", "docker", "docker.exe"}
        else None,
    )
    (app / "Dockerfile").write_text(
        "FROM 192.168.1.50:5000/base:latest\n"
        "ADD http://192.168.1.50:8000/pkg.tgz /opt/pkg.tgz\n",
        encoding="utf-8",
    )
    both = lan_bound_compose_build_argv(f"docker compose -f {stack} build")
    assert both is not None
    assert "192.168.1.50:5000/base:latest" in both
    assert "--fetch" in both


def test_lan_docker_bake_skopeo_loads_from_and_push(tmp_path, monkeypatch):
    monkeypatch.setattr("psutil.net_if_addrs", _home_vpn_nics)
    monkeypatch.setenv("HTTP_PROXY", "http://10.8.0.1:8080")
    monkeypatch.setattr(
        "app.tools.terminal.shutil.which",
        lambda name: f"/usr/bin/{name}" if name in {"skopeo", "skopeo.exe", "docker", "docker.exe"} else None,
    )
    ctx = tmp_path / "app"
    ctx.mkdir()
    (ctx / "Dockerfile").write_text("FROM 192.168.1.50:5000/base:latest\nCOPY . .\n", encoding="utf-8")
    hcl = tmp_path / "docker-bake.hcl"
    hcl.write_text(
        'target "app" {\n'
        '  context = "./app"\n'
        '  dockerfile = "Dockerfile"\n'
        '  tags = ["192.168.1.50:5000/app:latest"]\n'
        "}\n",
        encoding="utf-8",
    )
    baked = lan_bound_docker_bake_argv(f"docker buildx bake -f {hcl}")
    assert baked is not None
    assert "192.168.1.50:5000/base:latest" in baked
    follow = baked[baked.index("--") + 1 :]
    assert follow[:2] == ["/usr/bin/docker", "buildx"]
    assert "bake" in follow
    json_bake = tmp_path / "bake.json"
    json_bake.write_text(
        '{"target":{"app":{"context":"./app","dockerfile":"Dockerfile",'
        '"tags":["192.168.1.50:5000/app:v1"]}}}',
        encoding="utf-8",
    )
    (ctx / "Dockerfile").write_text("FROM alpine:3.20\n", encoding="utf-8")
    pushed = lan_bound_docker_bake_argv(f"docker buildx bake --push -f {json_bake}", cwd=str(tmp_path))
    assert pushed is not None
    assert "--push-after" in pushed
    assert "192.168.1.50:5000/app:v1" in pushed
    follow = pushed[pushed.index("--") + 1 :]
    assert "--load" in follow
    assert "--push" not in follow
    assert lan_bound_docker_bake_argv(f"docker buildx bake --print -f {hcl}") is None
    (ctx / "Dockerfile").write_text("FROM 192.168.1.50:5000/base:latest\n", encoding="utf-8")
    bash = _command_args(f"docker buildx bake -f {hcl}", "bash", cwd=str(tmp_path))
    assert bash[1].endswith("lan_skopeo_load.py")
    env = _child_env(bash)
    assert env["HTTP_PROXY"].startswith("http://127.0.0.1:")
    assert "10.8.0.1" not in env["HTTP_PROXY"]
    (ctx / "Dockerfile").write_text("FROM 192.168.1.50:5000/base:latest\nCOPY . .\n", encoding="utf-8")
    both = lan_bound_docker_bake_argv(f"docker buildx bake --push --pull -f {hcl}", cwd=str(tmp_path))
    assert both is not None
    assert "192.168.1.50:5000/base:latest" in both
    assert "--push-after" in both
    assert "192.168.1.50:5000/app:latest" in both
    follow = both[both.index("--") + 1 :]
    assert "--load" in follow
    assert "--push" not in follow
    assert "--pull" not in follow
    default_hcl = tmp_path / "docker-bake.hcl"
    default_hcl.write_text(hcl.read_text(encoding="utf-8"), encoding="utf-8")
    defaulted = lan_bound_docker_bake_argv("docker buildx bake", cwd=str(tmp_path))
    assert defaulted is not None
    assert "192.168.1.50:5000/base:latest" in defaulted
    set_tags = lan_bound_docker_bake_argv(
        f"docker buildx bake --push -f {json_bake} --set app.tags=192.168.1.50:5000/app:set",
        cwd=str(tmp_path),
    )
    assert set_tags is not None
    assert "--push-after" in set_tags
    assert "192.168.1.50:5000/app:set" in set_tags
    (ctx / "Dockerfile").write_text("ARG BASE\nFROM ${BASE}\nCOPY . .\n", encoding="utf-8")
    hcl.write_text(
        'target "app" {\n'
        '  context = "./app"\n'
        '  dockerfile = "Dockerfile"\n'
        "  args = {\n"
        '    BASE = "192.168.1.50:5000/from-bake:1"\n'
        "  }\n"
        '  tags = ["192.168.1.50:5000/app:latest"]\n'
        "}\n",
        encoding="utf-8",
    )
    from_hcl = lan_bound_docker_bake_argv(f"docker buildx bake -f {hcl}")
    assert from_hcl is not None
    assert "192.168.1.50:5000/from-bake:1" in from_hcl
    json_bake.write_text(
        '{"target":{"app":{"context":"./app","dockerfile":"Dockerfile",'
        '"args":{"BASE":"192.168.1.50:5000/from-json:1"},'
        '"tags":["192.168.1.50:5000/app:v1"]}}}',
        encoding="utf-8",
    )
    from_json = lan_bound_docker_bake_argv(f"docker buildx bake -f {json_bake}", cwd=str(tmp_path))
    assert from_json is not None
    assert "192.168.1.50:5000/from-json:1" in from_json
    set_args = lan_bound_docker_bake_argv(
        f"docker buildx bake -f {hcl} --set app.args.BASE=192.168.1.50:5000/from-set:1",
        cwd=str(tmp_path),
    )
    assert set_args is not None
    assert "192.168.1.50:5000/from-set:1" in set_args
    assert "192.168.1.50:5000/from-bake:1" not in set_args
    assert lan_bound_docker_bake_argv(f"docker buildx bake -f {hcl} --set app.args.BASE=alpine:3.20") is None
    (ctx / "Dockerfile").write_text("FROM alpine:3.20\nCOPY --from=assets /data /data\n", encoding="utf-8")
    hcl.write_text(
        'target "app" {\n'
        '  context = "./app"\n'
        '  dockerfile = "Dockerfile"\n'
        "  contexts = {\n"
        '    assets = "docker-image://192.168.1.50:5000/from-ctx:1"\n'
        "  }\n"
        "}\n",
        encoding="utf-8",
    )
    from_ctx = lan_bound_docker_bake_argv(f"docker buildx bake -f {hcl}")
    assert from_ctx is not None
    assert "192.168.1.50:5000/from-ctx:1" in from_ctx
    json_bake.write_text(
        '{"target":{"app":{"context":"./app","dockerfile":"Dockerfile",'
        '"contexts":{"assets":"docker-image://192.168.1.50:5000/from-json-ctx:1"}}}}',
        encoding="utf-8",
    )
    from_json_ctx = lan_bound_docker_bake_argv(f"docker buildx bake -f {json_bake}", cwd=str(tmp_path))
    assert from_json_ctx is not None
    assert "192.168.1.50:5000/from-json-ctx:1" in from_json_ctx
    set_ctx = lan_bound_docker_bake_argv(
        f"docker buildx bake -f {hcl} --set app.contexts.assets=docker-image://192.168.1.50:5000/from-set-ctx:1",
        cwd=str(tmp_path),
    )
    assert set_ctx is not None
    assert "192.168.1.50:5000/from-set-ctx:1" in set_ctx
    (ctx / "Dockerfile").write_text("FROM alpine:3.20\n", encoding="utf-8")
    hcl.write_text(
        'target "app" {\n'
        '  context = "./app"\n'
        '  dockerfile = "Dockerfile"\n'
        '  cache-from = ["type=registry,ref=192.168.1.50:5000/from-bake-cache:1"]\n'
        "}\n",
        encoding="utf-8",
    )
    from_bake_cache = lan_bound_docker_bake_argv(f"docker buildx bake -f {hcl}")
    assert from_bake_cache is not None
    assert "192.168.1.50:5000/from-bake-cache:1" in from_bake_cache
    json_bake.write_text(
        '{"target":{"app":{"context":"./app","dockerfile":"Dockerfile",'
        '"cache-from":[{"type":"registry","ref":"192.168.1.50:5000/from-json-cache:1"}]}}}',
        encoding="utf-8",
    )
    from_json_cache = lan_bound_docker_bake_argv(f"docker buildx bake -f {json_bake}", cwd=str(tmp_path))
    assert from_json_cache is not None
    assert "192.168.1.50:5000/from-json-cache:1" in from_json_cache


def test_compose_service_dockerfiles_resolves_context(tmp_path):
    app = tmp_path / "app"
    app.mkdir()
    (app / "Dockerfile").write_text("FROM alpine:3.20\n", encoding="utf-8")
    alt = tmp_path / "svc"
    alt.mkdir()
    (alt / "Dockerfile.lan").write_text("FROM 192.168.1.50:5000/base\n", encoding="utf-8")
    stack = tmp_path / "compose.yaml"
    stack.write_text(
        "services:\n"
        "  app:\n"
        "    build: ./app\n"
        "  lan:\n"
        "    build:\n"
        "      context: ./svc\n"
        "      dockerfile: Dockerfile.lan\n"
        "  web:\n"
        "    image: nginx:alpine\n"
        "  inline:\n"
        "    build:\n"
        "      dockerfile_inline: FROM scratch\n"
        "  interp:\n"
        "    build: ${CTX}\n",
        encoding="utf-8",
    )
    files = compose_service_dockerfiles(stack)
    assert files["app"] == app / "Dockerfile"
    assert files["lan"] == alt / "Dockerfile.lan"
    assert "web" not in files
    assert "inline" not in files
    assert "interp" not in files
    shared = tmp_path / "lib"
    shared.mkdir()
    base = shared / "base"
    base.mkdir()
    (base / "Dockerfile").write_text("FROM 192.168.1.50:5000/base:latest\n", encoding="utf-8")
    common = shared / "common.yaml"
    common.write_text(
        "services:\n"
        "  origin:\n"
        "    build: ./base\n"
        "    image: 192.168.1.50:5000/from-extends:1\n",
        encoding="utf-8",
    )
    stack.write_text(
        "services:\n"
        "  app:\n"
        "    extends:\n"
        "      file: ./lib/common.yaml\n"
        "      service: origin\n"
        "  local:\n"
        "    extends: app\n",
        encoding="utf-8",
    )
    extended = compose_service_dockerfiles(stack)
    assert extended["app"] == base / "Dockerfile"
    assert extended["local"] == base / "Dockerfile"
    assert compose_service_images(stack)["app"] == "192.168.1.50:5000/from-extends:1"
    assert compose_service_images(stack)["local"] == "192.168.1.50:5000/from-extends:1"


def test_compose_service_depends_maps_list_and_mapping(tmp_path):
    stack = tmp_path / "compose.yaml"
    stack.write_text(
        "services:\n"
        "  app:\n"
        "    image: nginx\n"
        "    depends_on:\n"
        "      - cache\n"
        "      - db\n"
        "  api:\n"
        "    image: nginx\n"
        "    depends_on:\n"
        "      cache:\n"
        "        condition: service_healthy\n"
        "  skip:\n"
        "    depends_on: ${DEPS}\n"
        "  cache:\n"
        "    image: redis\n"
        "  db:\n"
        "    image: postgres\n",
        encoding="utf-8",
    )
    deps = compose_service_depends(stack)
    assert deps["app"] == ["cache", "db"]
    assert deps["api"] == ["cache"]
    assert "skip" not in deps
    assert "cache" not in deps


def test_lan_compose_build_skopeo_loads_from_before_build(tmp_path, monkeypatch):
    monkeypatch.setattr("psutil.net_if_addrs", _home_vpn_nics)
    monkeypatch.setenv("HTTP_PROXY", "http://10.8.0.1:8080")
    monkeypatch.setattr(
        "app.tools.terminal.shutil.which",
        lambda name: (
            f"/usr/bin/{name}"
            if name in {"skopeo", "skopeo.exe", "docker", "docker.exe", "docker-compose", "docker-compose.exe"}
            else None
        ),
    )
    app = tmp_path / "app"
    app.mkdir()
    (app / "Dockerfile").write_text("FROM 192.168.1.50:5000/base:latest\nCOPY . .\n", encoding="utf-8")
    web = tmp_path / "web"
    web.mkdir()
    (web / "Dockerfile").write_text("FROM alpine:3.20\n", encoding="utf-8")
    stack = tmp_path / "compose.yaml"
    stack.write_text(
        "services:\n"
        "  app:\n"
        "    build: ./app\n"
        "  web:\n"
        "    build: ./web\n",
        encoding="utf-8",
    )
    built = lan_bound_compose_build_argv(f"docker compose -f {stack} build --pull")
    assert built is not None
    assert built[1].endswith("lan_skopeo_load.py")
    assert "192.168.1.50:5000/base:latest" in built
    assert "--" in built
    follow = built[built.index("--") + 1 :]
    assert follow[:2] == ["/usr/bin/docker", "compose"]
    assert "-f" in follow and str(stack) in follow
    assert "build" in follow
    assert "--pull" not in follow
    assert "--pull=false" not in follow
    only_app = lan_bound_compose_build_argv(f"docker compose -f {stack} build app")
    assert only_app is not None
    assert "192.168.1.50:5000/base:latest" in only_app
    assert lan_bound_compose_build_argv(f"docker compose -f {stack} build web") is None
    assert lan_bound_compose_build_argv(f"docker compose -f {stack} build | cat") is None
    with_deps = lan_bound_compose_build_argv(f"docker compose -f {stack} build --with-dependencies web")
    assert with_deps is not None
    assert "192.168.1.50:5000/base:latest" in with_deps
    cached = lan_bound_compose_build_argv(f"docker compose -f {stack} build --no-cache app")
    assert cached is not None
    follow = cached[cached.index("--") + 1 :]
    assert "--no-cache" in follow
    nest = tmp_path / "only-lan"
    nest.mkdir()
    (nest / "Dockerfile").write_text("FROM 192.168.1.50:5000/app:v1\n", encoding="utf-8")
    (nest / "compose.yml").write_text("services:\n  app:\n    build: .\n", encoding="utf-8")
    from_cwd = lan_bound_compose_build_argv("docker compose build", cwd=str(nest))
    assert from_cwd is not None
    assert "192.168.1.50:5000/app:v1" in from_cwd
    hyphen = lan_bound_compose_build_argv(f"docker-compose -f {stack} build app")
    assert hyphen is not None
    assert hyphen[hyphen.index("--") + 1 :][0] == "/usr/bin/docker-compose"
    bash = _command_args(f"docker compose -f {stack} build -q app", "bash", cwd=str(tmp_path))
    assert bash[1].endswith("lan_skopeo_load.py")
    assert "--quiet" in bash or "-q" in bash
    env = _child_env(bash)
    assert env["HTTP_PROXY"].startswith("http://127.0.0.1:")
    assert "10.8.0.1" not in env["HTTP_PROXY"]
    stack.write_text(
        "services:\n"
        "  app:\n"
        "    image: 192.168.1.50:5000/app:latest\n"
        "    build: ./app\n"
        "  web:\n"
        "    image: nginx:alpine\n"
        "    build: ./web\n",
        encoding="utf-8",
    )
    pushed = lan_bound_compose_build_argv(f"docker compose -f {stack} build --push")
    assert pushed is not None
    assert "--push-after" in pushed
    assert "192.168.1.50:5000/base:latest" in pushed
    assert "192.168.1.50:5000/app:latest" in pushed
    rest = pushed[pushed.index("--") + 1 :]
    cut = rest.index("--")
    follow = rest[:cut]
    then = rest[cut + 1 :]
    assert "build" in follow
    assert "--push" not in follow
    assert then[:2] == ["/usr/bin/docker", "compose"]
    assert "push" in then
    assert then[-1] == "web"
    (app / "Dockerfile").write_text("FROM alpine:3.20\n", encoding="utf-8")
    alpine_push = lan_bound_compose_build_argv(f"docker compose -f {stack} build --push app")
    assert alpine_push is not None
    assert "--push-after" in alpine_push
    assert "192.168.1.50:5000/app:latest" in alpine_push
    assert "192.168.1.50:5000/base:latest" not in alpine_push
    assert lan_bound_compose_build_argv(f"docker compose -f {stack} build --push web") is None
    assert lan_bound_compose_build_argv(f"docker compose -f {stack} build") is None
    (app / "Dockerfile").write_text("ARG BASE\nFROM ${BASE}\nCOPY . .\n", encoding="utf-8")
    stack.write_text(
        "services:\n"
        "  app:\n"
        "    build:\n"
        "      context: ./app\n"
        "      args:\n"
        "        BASE: 192.168.1.50:5000/from-compose:1\n"
        "  listed:\n"
        "    build:\n"
        "      context: ./app\n"
        "      args:\n"
        "        - BASE=192.168.1.50:5000/from-list:1\n",
        encoding="utf-8",
    )
    from_compose = lan_bound_compose_build_argv(f"docker compose -f {stack} build app")
    assert from_compose is not None
    assert "192.168.1.50:5000/from-compose:1" in from_compose
    from_list = lan_bound_compose_build_argv(f"docker compose -f {stack} build listed")
    assert from_list is not None
    assert "192.168.1.50:5000/from-list:1" in from_list
    from_cli = lan_bound_compose_build_argv(
        f"docker compose -f {stack} build --build-arg BASE=192.168.1.50:5000/from-cli:2 app"
    )
    assert from_cli is not None
    assert "192.168.1.50:5000/from-cli:2" in from_cli
    assert "192.168.1.50:5000/from-compose:1" not in from_cli
    assert lan_bound_compose_build_argv(
        f"docker compose -f {stack} build --build-arg BASE=alpine:3.20 app"
    ) is None
    stack.write_text(
        "services:\n"
        "  app:\n"
        "    build:\n"
        "      context: ./app\n"
        "      args:\n"
        "        - BASE\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("BASE", "192.168.1.50:5000/from-env:1")
    from_env = lan_bound_compose_build_argv(f"docker compose -f {stack} build app")
    assert from_env is not None
    assert "192.168.1.50:5000/from-env:1" in from_env
    cli_env = lan_bound_compose_build_argv(f"docker compose -f {stack} build --build-arg BASE app")
    assert cli_env is not None
    assert "192.168.1.50:5000/from-env:1" in cli_env
    (app / "Dockerfile").write_text("FROM alpine:3.20\nCOPY --from=assets /data /data\n", encoding="utf-8")
    stack.write_text(
        "services:\n"
        "  app:\n"
        "    build:\n"
        "      context: ./app\n"
        "      additional_contexts:\n"
        "        assets: docker-image://192.168.1.50:5000/from-compose-ctx:1\n"
        "  listed:\n"
        "    build:\n"
        "      context: ./app\n"
        "      additional_contexts:\n"
        "        - assets=docker-image://192.168.1.50:5000/from-list-ctx:1\n",
        encoding="utf-8",
    )
    from_ctx = lan_bound_compose_build_argv(f"docker compose -f {stack} build app")
    assert from_ctx is not None
    assert "192.168.1.50:5000/from-compose-ctx:1" in from_ctx
    from_list_ctx = lan_bound_compose_build_argv(f"docker compose -f {stack} build listed")
    assert from_list_ctx is not None
    assert "192.168.1.50:5000/from-list-ctx:1" in from_list_ctx
    cli_ctx = lan_bound_compose_build_argv(
        f"docker compose -f {stack} build --build-context extra=docker-image://192.168.1.50:5000/from-cli-ctx:1 app"
    )
    assert cli_ctx is not None
    assert "192.168.1.50:5000/from-cli-ctx:1" in cli_ctx
    assert "192.168.1.50:5000/from-compose-ctx:1" in cli_ctx
    (app / "Dockerfile").write_text("FROM alpine:3.20\n", encoding="utf-8")
    stack.write_text(
        "services:\n"
        "  app:\n"
        "    build:\n"
        "      context: ./app\n"
        "      cache_from:\n"
        "        - 192.168.1.50:5000/from-compose-cache:1\n"
        "  typed:\n"
        "    build:\n"
        "      context: ./app\n"
        "      cache_from:\n"
        "        - type=registry,ref=192.168.1.50:5000/from-typed-cache:1\n",
        encoding="utf-8",
    )
    from_cache = lan_bound_compose_build_argv(f"docker compose -f {stack} build app")
    assert from_cache is not None
    assert "192.168.1.50:5000/from-compose-cache:1" in from_cache
    from_typed = lan_bound_compose_build_argv(f"docker compose -f {stack} build typed")
    assert from_typed is not None
    assert "192.168.1.50:5000/from-typed-cache:1" in from_typed
    cli_cache = lan_bound_compose_build_argv(
        f"docker compose -f {stack} build --cache-from 192.168.1.50:5000/from-cli-cache:1 app"
    )
    assert cli_cache is not None
    assert "192.168.1.50:5000/from-cli-cache:1" in cli_cache
    assert "192.168.1.50:5000/from-compose-cache:1" in cli_cache


def test_lan_compose_up_skopeo_loads_images_and_from(tmp_path, monkeypatch):
    monkeypatch.setattr("psutil.net_if_addrs", _home_vpn_nics)
    monkeypatch.setenv("HTTP_PROXY", "http://10.8.0.1:8080")
    monkeypatch.setattr(
        "app.tools.terminal.shutil.which",
        lambda name: f"/usr/bin/{name}" if name in {"skopeo", "skopeo.exe", "docker", "docker.exe"} else None,
    )
    app = tmp_path / "app"
    app.mkdir()
    (app / "Dockerfile").write_text("FROM 192.168.1.50:5000/base:latest\nCOPY . .\n", encoding="utf-8")
    stack = tmp_path / "compose.yaml"
    stack.write_text(
        "services:\n"
        "  app:\n"
        "    build: ./app\n"
        "    image: 192.168.1.50:5000/app:latest\n"
        "  web:\n"
        "    image: nginx:alpine\n"
        "  cache:\n"
        "    image: 192.168.1.50:5000/redis:7\n",
        encoding="utf-8",
    )
    started = lan_bound_compose_up_argv(f"docker compose -f {stack} up -d --pull always")
    assert started is not None
    assert started[1].endswith("lan_skopeo_load.py")
    assert "192.168.1.50:5000/app:latest" in started
    assert "192.168.1.50:5000/redis:7" in started
    assert "192.168.1.50:5000/base:latest" not in started
    follow = started[started.index("--") + 1 :]
    assert follow[:2] == ["/usr/bin/docker", "compose"]
    assert "up" in follow and "-d" in follow
    assert "--pull" in follow
    pull_at = follow.index("--pull")
    assert follow[pull_at + 1] == "missing"
    assert "always" not in follow
    rebuilt = lan_bound_compose_up_argv(f"docker compose -f {stack} up --build app")
    assert rebuilt is not None
    assert "192.168.1.50:5000/base:latest" in rebuilt
    assert "192.168.1.50:5000/app:latest" in rebuilt
    assert "192.168.1.50:5000/redis:7" not in rebuilt
    only_web = lan_bound_compose_up_argv(f"docker compose -f {stack} up web")
    assert only_web is None
    assert lan_bound_compose_up_argv(f"docker compose -f {stack} up | cat") is None
    no_build = lan_bound_compose_up_argv(f"docker compose -f {stack} up --no-build --build app")
    assert no_build is not None
    assert "192.168.1.50:5000/base:latest" not in no_build
    bash = _command_args(f"docker compose -f {stack} up -d cache", "bash", cwd=str(tmp_path))
    assert bash[1].endswith("lan_skopeo_load.py")
    assert "192.168.1.50:5000/redis:7" in bash
    env = _child_env(bash)
    assert env["HTTP_PROXY"].startswith("http://127.0.0.1:")
    assert "10.8.0.1" not in env["HTTP_PROXY"]
    hub = tmp_path / "hub.yml"
    hub.write_text("services:\n  web:\n    image: nginx:alpine\n", encoding="utf-8")
    assert lan_bound_compose_up_argv(f"docker compose -f {hub} up -d") is None
    deps_stack = tmp_path / "deps.yaml"
    deps_stack.write_text(
        "services:\n"
        "  app:\n"
        "    image: nginx:alpine\n"
        "    depends_on:\n"
        "      - cache\n"
        "  cache:\n"
        "    image: 192.168.1.50:5000/redis:7\n",
        encoding="utf-8",
    )
    with_dep = lan_bound_compose_up_argv(f"docker compose -f {deps_stack} up app")
    assert with_dep is not None
    assert "192.168.1.50:5000/redis:7" in with_dep
    assert lan_bound_compose_up_argv(f"docker compose -f {deps_stack} up --no-deps app") is None
    created = lan_bound_compose_up_argv(f"docker compose -f {deps_stack} create cache")
    assert created is not None
    assert "192.168.1.50:5000/redis:7" in created
    assert "create" in created[created.index("--") + 1 :]
    (app / "Dockerfile").write_text("ARG BASE\nFROM ${BASE}\nCOPY . .\n", encoding="utf-8")
    stack.write_text(
        "services:\n"
        "  app:\n"
        "    build:\n"
        "      context: ./app\n"
        "      args:\n"
        "        BASE: 192.168.1.50:5000/from-up:1\n",
        encoding="utf-8",
    )
    rebuilt_args = lan_bound_compose_up_argv(f"docker compose -f {stack} up --build app")
    assert rebuilt_args is not None
    assert "192.168.1.50:5000/from-up:1" in rebuilt_args
    assert lan_bound_compose_up_argv(f"docker compose -f {stack} up app") is None
    (app / "Dockerfile").write_text("FROM alpine:3.20\nCOPY --from=assets /data /data\n", encoding="utf-8")
    stack.write_text(
        "services:\n"
        "  app:\n"
        "    build:\n"
        "      context: ./app\n"
        "      additional_contexts:\n"
        "        assets: docker-image://192.168.1.50:5000/from-up-ctx:1\n",
        encoding="utf-8",
    )
    rebuilt_ctx = lan_bound_compose_up_argv(f"docker compose -f {stack} up --build app")
    assert rebuilt_ctx is not None
    assert "192.168.1.50:5000/from-up-ctx:1" in rebuilt_ctx
    assert lan_bound_compose_up_argv(f"docker compose -f {stack} up app") is None
    (app / "Dockerfile").write_text("FROM alpine:3.20\n", encoding="utf-8")
    stack.write_text(
        "services:\n"
        "  app:\n"
        "    build:\n"
        "      context: ./app\n"
        "      cache_from:\n"
        "        - 192.168.1.50:5000/from-up-cache:1\n",
        encoding="utf-8",
    )
    rebuilt_cache = lan_bound_compose_up_argv(f"docker compose -f {stack} up --build app")
    assert rebuilt_cache is not None
    assert "192.168.1.50:5000/from-up-cache:1" in rebuilt_cache
    assert lan_bound_compose_up_argv(f"docker compose -f {stack} up app") is None
    lib = tmp_path / "lib"
    lib.mkdir()
    (lib / "cache.yaml").write_text(
        "services:\n"
        "  cache:\n"
        "    image: 192.168.1.50:5000/from-include:1\n",
        encoding="utf-8",
    )
    stack.write_text(
        "include:\n"
        "  - path: ./lib/cache.yaml\n"
        "services:\n"
        "  web:\n"
        "    image: nginx:alpine\n",
        encoding="utf-8",
    )
    included = lan_bound_compose_up_argv(f"docker compose -f {stack} up -d")
    assert included is not None
    assert "192.168.1.50:5000/from-include:1" in included
    (lib / "common.yaml").write_text(
        "services:\n"
        "  origin:\n"
        "    image: 192.168.1.50:5000/from-extends-up:1\n",
        encoding="utf-8",
    )
    stack.write_text(
        "services:\n"
        "  cache:\n"
        "    extends:\n"
        "      file: ./lib/common.yaml\n"
        "      service: origin\n"
        "  web:\n"
        "    image: nginx:alpine\n",
        encoding="utf-8",
    )
    extended = lan_bound_compose_up_argv(f"docker compose -f {stack} up cache")
    assert extended is not None
    assert "192.168.1.50:5000/from-extends-up:1" in extended
    assert lan_bound_compose_up_argv(f"docker compose -f {stack} up web") is None


def test_lan_compose_run_skopeo_loads_image_and_from(tmp_path, monkeypatch):
    monkeypatch.setattr("psutil.net_if_addrs", _home_vpn_nics)
    monkeypatch.setenv("HTTP_PROXY", "http://10.8.0.1:8080")
    monkeypatch.setattr(
        "app.tools.terminal.shutil.which",
        lambda name: f"/usr/bin/{name}" if name in {"skopeo", "skopeo.exe", "docker", "docker.exe"} else None,
    )
    app = tmp_path / "app"
    app.mkdir()
    (app / "Dockerfile").write_text("FROM 192.168.1.50:5000/base:latest\nCOPY . .\n", encoding="utf-8")
    stack = tmp_path / "compose.yaml"
    stack.write_text(
        "services:\n"
        "  app:\n"
        "    build: ./app\n"
        "    image: 192.168.1.50:5000/app:latest\n"
        "    depends_on:\n"
        "      - cache\n"
        "  web:\n"
        "    image: nginx:alpine\n"
        "  cache:\n"
        "    image: 192.168.1.50:5000/redis:7\n",
        encoding="utf-8",
    )
    ran = lan_bound_compose_run_argv(f"docker compose -f {stack} run --rm --pull always app sh")
    assert ran is not None
    assert ran[1].endswith("lan_skopeo_load.py")
    assert "192.168.1.50:5000/app:latest" in ran
    assert "192.168.1.50:5000/redis:7" in ran
    assert "192.168.1.50:5000/base:latest" not in ran
    follow = ran[ran.index("--") + 1 :]
    assert follow[:2] == ["/usr/bin/docker", "compose"]
    assert "run" in follow and "--rm" in follow
    assert follow[-2:] == ["app", "sh"]
    pull_at = follow.index("--pull")
    assert follow[pull_at + 1] == "missing"
    rebuilt = lan_bound_compose_run_argv(f"docker compose -f {stack} run --build -it app python -c print(1)")
    assert rebuilt is not None
    assert "192.168.1.50:5000/base:latest" in rebuilt
    assert "192.168.1.50:5000/app:latest" in rebuilt
    assert "192.168.1.50:5000/redis:7" in rebuilt
    isolated = lan_bound_compose_run_argv(f"docker compose -f {stack} run --no-deps --build web")
    assert isolated is None
    with_cache = lan_bound_compose_run_argv(f"docker compose -f {stack} run --no-deps cache")
    assert with_cache is not None
    assert "192.168.1.50:5000/redis:7" in with_cache
    assert "192.168.1.50:5000/app:latest" not in with_cache
    assert lan_bound_compose_run_argv(f"docker compose -f {stack} run web") is None
    assert lan_bound_compose_run_argv(f"docker compose -f {stack} run app | cat") is None
    bash = _command_args(f"docker compose -f {stack} run --rm cache redis-cli ping", "bash", cwd=str(tmp_path))
    assert bash[1].endswith("lan_skopeo_load.py")
    assert "192.168.1.50:5000/redis:7" in bash
    env = _child_env(bash)
    assert env["HTTP_PROXY"].startswith("http://127.0.0.1:")
    assert "10.8.0.1" not in env["HTTP_PROXY"]
