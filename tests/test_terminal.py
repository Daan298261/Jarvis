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
    git_direct_argv,
    lan_bound_cifs_argv,
    compose_service_dockerfiles,
    lan_bound_compose_build_argv,
    lan_bound_compose_pull_argv,
    lan_bound_dns_argv,
    lan_bound_docker_build_argv,
    lan_bound_docker_pull_argv,
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
    assert lan_bound_docker_pull_argv("docker pull -a 192.168.1.50:5000/app") is None
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


def test_lan_docker_pull_skips_when_skopeo_missing(monkeypatch):
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


def test_lan_skopeo_load_runs_copies_then_follow(monkeypatch):
    from app.tools.lan_skopeo_load import main

    seen: list[list[str]] = []

    def fake_run(cmd, check=False):
        seen.append(list(cmd))
        return type("R", (), {"returncode": 0})()

    monkeypatch.setattr("app.tools.lan_skopeo_load.subprocess.run", fake_run)
    assert (
        main(["/usr/bin/skopeo", "192.168.1.50:5000/app:latest", "--", "/usr/bin/docker", "compose", "pull", "web"]) == 0
    )
    assert seen[0][:2] == ["/usr/bin/skopeo", "copy"]
    assert seen[0][-1] == "docker-daemon:192.168.1.50:5000/app:latest"
    assert seen[1] == ["/usr/bin/docker", "compose", "pull", "web"]


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
    (app / "Dockerfile").write_text("FROM alpine:3.20\n", encoding="utf-8")
    assert lan_bound_compose_build_argv(f"docker compose -f {stack} build") is None
