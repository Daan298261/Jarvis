"""Owner-machine workspace, LAN cyberdefense, WAN companion, and internet browse."""
from __future__ import annotations

import os
from pathlib import Path

import pytest

from app.config import LOCAL_NETWORK_SCOPE, default_allowed_directories
from app.mobile.wan_forward import (
    companion_wan_origin,
    gateway_ssh_argv,
    gateway_ssh_configured,
    is_public_dial_host,
    is_rfc1918_ipv4,
    mapping_lan_ipv4,
    openwrt_redirect_script,
    parse_proc_net_route,
    parse_windows_route_print,
    redact_wan_config,
    resolved_gateway_host,
    resolved_gateway_user,
    reverse_tunnel_argv,
)
from app.tools.safety import resolve_allowed_path


@pytest.fixture(autouse=True)
def _egress_lookup_offline_in_owner_tests(monkeypatch):
    monkeypatch.setattr(
        "app.mobile.wan_forward.lookup_egress_ipv4",
        lambda: (_ for _ in ()).throw(ValueError("offline")),
    )


def test_defaults_cover_machine_roots_and_lan_scope():
    allowed = default_allowed_directories()
    assert LOCAL_NETWORK_SCOPE in allowed
    home = str(Path.home())
    assert home in allowed
    if os.name != "nt":
        assert "/" in allowed or str(Path("/")) in allowed
        assert resolve_allowed_path("/etc", allowed) == Path("/etc").resolve()
    else:
        assert Path.home().anchor in allowed or any(item.endswith(":\\") or item.endswith(":") for item in allowed)


def test_private_lan_unc_allowed_public_denied():
    allowed = [LOCAL_NETWORK_SCOPE]
    resolved = resolve_allowed_path(r"\\nas.local\media\clip.mp4", allowed)
    assert "nas.local" in str(resolved).replace("/", "\\").lower()
    with pytest.raises(PermissionError):
        resolve_allowed_path(r"\\8.8.8.8\share\x", allowed)
    with pytest.raises(PermissionError):
        resolve_allowed_path(r"\\nas.local\media\clip.mp4", [str(Path.home())])


def test_posix_slash_share_is_treated_as_lan_unc():
    allowed = [LOCAL_NETWORK_SCOPE]
    resolved = resolve_allowed_path("//nas/games/steam.exe", allowed)
    text = str(resolved).replace("\\", "/").lower()
    assert "nas" in text and "games" in text
    lan = resolve_allowed_path("//nas.lan/media/clip.mp4", allowed)
    assert "nas.lan" in str(lan).replace("\\", "/").lower()


def test_empty_allowlist_still_denies():
    with pytest.raises(PermissionError, match="No workspace directories"):
        resolve_allowed_path(str(Path.home()), [])


def test_reverse_tunnel_argv_is_batch_mode_and_4781_only(tmp_path, monkeypatch):
    key = tmp_path / "id_ed25519"
    key.write_text("dummy", encoding="utf-8")
    monkeypatch.setattr("app.mobile.wan_forward.shutil.which", lambda name: "/usr/bin/ssh" if "ssh" in name else None)
    argv = reverse_tunnel_argv(host="vpn.example.test", user="taco", identity_file=str(key))
    joined = " ".join(argv)
    assert argv[0].endswith("ssh")
    assert "-N" in argv
    assert "BatchMode=yes" in argv
    assert "-R" in argv
    assert f"0.0.0.0:4781:127.0.0.1:4781" in argv
    assert "taco@vpn.example.test" in argv
    assert "-i" in argv
    assert str(key) in argv
    assert "password" not in joined.lower()
    assert "4780" not in joined
    with pytest.raises(ValueError):
        reverse_tunnel_argv(host="bad/host", user="taco", identity_file=str(key))
    with pytest.raises(ValueError, match="identity file or the owner SSH password"):
        reverse_tunnel_argv(host="vpn.example.test", user="taco")


def test_reverse_tunnel_accepts_owner_password_without_identity(monkeypatch):
    monkeypatch.setattr("app.mobile.wan_forward.shutil.which", lambda name: "/usr/bin/ssh" if "ssh" in name else None)
    argv = reverse_tunnel_argv(host="vpn.example.test", user="taco", password="owner-secret")
    joined = " ".join(argv)
    assert "-N" in argv
    assert "-i" not in argv
    assert "owner-secret" not in joined
    assert "BatchMode=no" in argv
    assert "PreferredAuthentications=password,keyboard-interactive" in argv
    assert "0.0.0.0:4781:127.0.0.1:4781" in argv
    public = redact_wan_config({"ssh_password": "owner-secret", "ssh_host": "vpn.example.test"})
    assert "owner-secret" not in str(public)
    assert public["ssh_password_set"] is True
    assert "ssh_password" not in public


def test_openwrt_script_maps_only_companion_port_on_private_lan():
    script = openwrt_redirect_script("192.168.1.12")
    assert "src_dport='4781'" in script
    assert "dest_port='4781'" in script
    assert "dest_ip='192.168.1.12'" in script
    assert "4780" not in script
    assert "22" not in script.split("src_dport")[0]  # no ssh dport
    with pytest.raises(ValueError):
        openwrt_redirect_script("8.8.8.8")
    with pytest.raises(ValueError):
        openwrt_redirect_script("127.0.0.1")
    with pytest.raises(ValueError):
        openwrt_redirect_script("100.64.1.8")


def test_gateway_ssh_argv_uses_identity_and_openwrt_profile(tmp_path, monkeypatch):
    key = tmp_path / "router_key"
    key.write_text("dummy", encoding="utf-8")
    monkeypatch.setattr("app.mobile.wan_forward.shutil.which", lambda name: "/usr/bin/ssh" if "ssh" in name else None)
    argv = gateway_ssh_argv(
        host="192.168.1.1",
        user="root",
        identity_file=str(key),
        lan_ip="192.168.1.12",
    )
    assert argv[-2] == "-s"
    assert "src_dport='4781'" in argv[-1]
    assert "BatchMode=yes" in argv
    assert argv[1:3] == ["-b", "192.168.1.12"]
    with pytest.raises(ValueError):
        gateway_ssh_argv(
            host="192.168.1.1",
            user="root",
            identity_file=str(key),
            lan_ip="192.168.1.12",
            profile="exploit-kit",
        )


def test_gateway_ssh_accepts_owner_password_without_identity(monkeypatch):
    monkeypatch.setattr("app.mobile.wan_forward.shutil.which", lambda name: "/usr/bin/ssh" if "ssh" in name else None)
    argv = gateway_ssh_argv(
        host="192.168.1.1",
        user="root",
        lan_ip="192.168.1.12",
        password="owner-secret",
    )
    joined = " ".join(argv)
    assert "-i" not in argv
    assert "owner-secret" not in joined
    assert "BatchMode=no" in argv
    assert argv[1:3] == ["-b", "192.168.1.12"]
    assert "src_dport='4781'" in argv[-1]
    assert gateway_ssh_configured({"gateway_password": "owner-secret"})
    assert not gateway_ssh_configured({"gateway_host": "192.168.1.1"})
    with pytest.raises(ValueError, match="identity file or the owner router password"):
        gateway_ssh_argv(host="192.168.1.1", user="root", lan_ip="192.168.1.12")


def test_default_gateway_parsers_and_openwrt_user_fallback():
    proc = (
        "Iface\tDestination\tGateway\tFlags\tRefCnt\tUse\tMetric\tMask\tMTU\tWindow\tIRTT\n"
        "eth0\t00000000\t0101A8C0\t0003\t0\t0\t100\t00000000\t0\t0\t0\n"
    )
    assert parse_proc_net_route(proc) == "192.168.1.1"
    cgnat_then_lan = (
        "Iface\tDestination\tGateway\tFlags\tRefCnt\tUse\tMetric\tMask\tMTU\tWindow\tIRTT\n"
        "wwan0\t00000000\t01004064\t0003\t0\t0\t50\t00000000\t0\t0\t0\n"
        "eth0\t00000000\t0101A8C0\t0003\t0\t0\t100\t00000000\t0\t0\t0\n"
    )
    assert parse_proc_net_route(cgnat_then_lan) == "192.168.1.1"
    vpn_then_lan = (
        "Iface\tDestination\tGateway\tFlags\tRefCnt\tUse\tMetric\tMask\tMTU\tWindow\tIRTT\n"
        "wg0\t00000000\t0100080A\t0003\t0\t0\t0\t00000000\t0\t0\t0\n"
        "eth0\t00000000\t0101A8C0\t0003\t0\t0\t100\t00000000\t0\t0\t0\n"
    )
    assert parse_proc_net_route(vpn_then_lan) == "192.168.1.1"
    cgnat_only = (
        "Iface\tDestination\tGateway\tFlags\tRefCnt\tUse\tMetric\tMask\tMTU\tWindow\tIRTT\n"
        "wwan0\t00000000\t01004064\t0003\t0\t0\t50\t00000000\t0\t0\t0\n"
    )
    with pytest.raises(ValueError):
        parse_proc_net_route(cgnat_only)
    printed = "Network Destination        Netmask          Gateway       Interface  Metric\n          0.0.0.0          0.0.0.0      192.168.0.1     192.168.0.12     25\n"
    assert parse_windows_route_print(printed) == "192.168.0.1"
    dual = (
        "Network Destination        Netmask          Gateway       Interface  Metric\n"
        "          0.0.0.0          0.0.0.0      100.64.0.1      100.64.1.8      25\n"
        "          0.0.0.0          0.0.0.0      192.168.1.1     192.168.1.12    35\n"
    )
    assert parse_windows_route_print(dual) == "192.168.1.1"
    vpn_win = (
        "Network Destination        Netmask          Gateway       Interface  Metric\n"
        "          0.0.0.0          0.0.0.0         10.8.0.1         10.8.0.2      1\n"
        "          0.0.0.0          0.0.0.0      192.168.1.1     192.168.1.12    35\n"
    )
    assert parse_windows_route_print(vpn_win) == "192.168.1.1"
    from app.mobile.wan_forward import parse_proc_net_route_gateways, parse_windows_route_print_gateways

    assert parse_proc_net_route_gateways(vpn_then_lan) == ["192.168.1.1", "10.8.0.1"]
    assert parse_windows_route_print_gateways(vpn_win) == ["192.168.1.1", "10.8.0.1"]
    with pytest.raises(ValueError):
        parse_windows_route_print(
            "Network Destination        Netmask          Gateway       Interface  Metric\n"
            "          0.0.0.0          0.0.0.0      100.64.0.1      100.64.1.8      25\n"
        )
    assert resolved_gateway_user({"gateway_profile": "openwrt_uci"}) == "root"
    assert resolved_gateway_user({"gateway_username": "admin"}) == "admin"
    assert resolved_gateway_host({"gateway_host": "192.168.1.1"}) == "192.168.1.1"
    from app.mobile.wan_forward import gateway_ssh_hosts

    assert gateway_ssh_hosts({"gateway_host": "10.0.0.1"}) == ["10.0.0.1"]
    assert gateway_ssh_hosts({"gateway_host": " 192.168.1.1 "}) == ["192.168.1.1"]


def test_wan_origin_rejects_lan_and_accepts_public_hosts():
    assert is_public_dial_host("vpn.example.test")
    assert is_public_dial_host("8.8.8.8")
    assert is_public_dial_host("203.0.113.9")
    assert not is_public_dial_host("192.168.1.1")
    assert not is_public_dial_host("100.64.1.8")
    assert not is_public_dial_host("router.local")
    with pytest.raises(ValueError):
        companion_wan_origin("192.168.1.1")
    assert companion_wan_origin("home.example.test") == "https://home.example.test:4781"
    assert companion_wan_origin("203.0.113.9") == "https://203.0.113.9:4781"
    public = redact_wan_config({"gateway_password": "secret", "ssh_host": "vpn.example.test"})
    assert "secret" not in str(public)
    assert public["gateway_password_set"] is True
    assert public["ssh_host"] == "vpn.example.test"


@pytest.mark.asyncio
async def test_apply_gateway_ssh_prefers_live_egress_over_stale_literal(tmp_path, monkeypatch):
    from app.mobile.wan_forward import apply_gateway_ssh

    class FakeProc:
        returncode = 0

        async def communicate(self, _data):
            return b"", b""

    async def fake_exec(*_argv, **_kwargs):
        return FakeProc()

    monkeypatch.setattr("app.mobile.wan_forward.asyncio.create_subprocess_exec", fake_exec)
    monkeypatch.setattr("app.mobile.wan_forward.ssh_executable", lambda: "ssh")
    key = tmp_path / "id_ed25519"
    key.write_text("dummy", encoding="utf-8")
    settings = {
        "gateway_host": "192.168.1.1",
        "gateway_user": "root",
        "gateway_identity_file": str(key),
        "wan_public_host": "203.0.113.8",
    }
    mapped, _detail = await apply_gateway_ssh(settings, "192.168.1.12", public_host="203.0.113.9")
    assert mapped == "https://203.0.113.9:4781"
    settings["wan_public_host"] = "home.example.test"
    mapped, _detail = await apply_gateway_ssh(settings, "192.168.1.12", public_host="203.0.113.9")
    assert mapped == "https://home.example.test:4781"
    settings["wan_public_host"] = ""
    mapped, _detail = await apply_gateway_ssh(settings, "192.168.1.12", public_host="203.0.113.9")
    assert mapped == "https://203.0.113.9:4781"


def test_public_dial_host_for_gateway_keeps_ddns_and_prefers_live_ipv4():
    from app.mobile.wan_forward import public_dial_host_for_gateway

    assert public_dial_host_for_gateway("home.example.test", "203.0.113.9") == "home.example.test"
    assert public_dial_host_for_gateway("203.0.113.8", "203.0.113.9") == "203.0.113.9"
    assert public_dial_host_for_gateway("", "203.0.113.9") == "203.0.113.9"
    assert public_dial_host_for_gateway("", "", "203.0.113.8") == "203.0.113.8"


def test_mapping_lan_ipv4_skips_cgnat_and_prefers_gateway_subnet():
    assert is_rfc1918_ipv4("192.168.1.12")
    assert is_rfc1918_ipv4("10.0.0.5")
    assert not is_rfc1918_ipv4("100.64.1.8")
    assert not is_rfc1918_ipv4("8.8.8.8")
    assert mapping_lan_ipv4(["100.64.1.8", "192.168.1.12"], "192.168.1.1") == "192.168.1.12"
    assert mapping_lan_ipv4(["10.0.0.5", "192.168.1.12"], "192.168.1.1") == "192.168.1.12"
    assert mapping_lan_ipv4(["10.0.0.5", "192.168.0.9"], "192.168.1.1") == ""
    assert mapping_lan_ipv4(["10.8.0.2"], "192.168.1.1") == ""
    assert mapping_lan_ipv4(["100.64.1.8"], "192.168.1.1") == ""
    assert mapping_lan_ipv4([], "192.168.1.1") == ""
    assert mapping_lan_ipv4(["192.168.1.12", "10.0.0.5"], "") == "192.168.1.12"


def test_lan_hosts_drops_cgnat(monkeypatch):
    from app.mobile import connectivity

    monkeypatch.setattr("app.api.mobile._lan_hosts", lambda: ["100.64.1.8", "8.8.8.8", "192.168.1.12"])
    assert connectivity.lan_hosts() == ["192.168.1.12"]


def test_interface_ipv4_addresses_lists_every_nic(monkeypatch):
    from types import SimpleNamespace

    from app.mobile.wan_forward import interface_ipv4_addresses

    class _Addr(SimpleNamespace):
        pass

    def fake_addrs():
        return {
            "eth0": [_Addr(family=__import__("socket").AF_INET, address="192.168.1.12")],
            "wg0": [_Addr(family=__import__("socket").AF_INET, address="10.8.0.2")],
            "lo": [_Addr(family=__import__("socket").AF_INET, address="127.0.0.1")],
        }

    monkeypatch.setattr("psutil.net_if_addrs", fake_addrs)
    assert interface_ipv4_addresses() == ["192.168.1.12", "10.8.0.2"]


def test_lan_hosts_unions_every_nic_when_default_route_is_vpn(monkeypatch):
    from app.api import mobile

    monkeypatch.setattr("app.mobile.wan_forward.interface_ipv4_addresses", lambda: ["10.8.0.2", "192.168.1.12"])
    monkeypatch.setattr(mobile.socket, "gethostname", lambda: (_ for _ in ()).throw(OSError("no hostname")))

    class _Boom:
        def __init__(self, *a, **k):
            raise OSError("no udp")

    monkeypatch.setattr(mobile.socket, "socket", _Boom)
    assert mobile._lan_hosts() == ["10.8.0.2", "192.168.1.12"]


def test_preferred_lan_ipv4_picks_home_lan_over_vpn(monkeypatch):
    from app.mobile import connectivity

    monkeypatch.setattr(connectivity, "lan_hosts", lambda: ["10.8.0.2", "192.168.1.12"])
    monkeypatch.setattr("app.mobile.wan_forward.default_gateway_ipv4", lambda: "192.168.1.1")
    assert connectivity.preferred_lan_ipv4() == "192.168.1.12"
    assert connectivity.preferred_lan_ipv4("10.8.0.1") == "10.8.0.2"


def test_lan_inventory_nmap_binds_home_nic_not_vpn(monkeypatch):
    from types import SimpleNamespace

    import socket

    from app.security.hexstrike_defensive import lan_scan_bind, nmap_lan_bind_args

    def fake_addrs():
        return {
            "eth0": [
                SimpleNamespace(family=socket.AF_INET, address="192.168.1.12", netmask="255.255.255.0"),
            ],
            "wg0": [
                SimpleNamespace(family=socket.AF_INET, address="10.8.0.2", netmask="255.255.255.0"),
            ],
        }

    monkeypatch.setattr("psutil.net_if_addrs", fake_addrs)
    assert lan_scan_bind("192.168.1.0/24") == ("eth0", "192.168.1.12")
    assert nmap_lan_bind_args("192.168.1.0/24") == ["-S", "192.168.1.12", "-e", "eth0"]
    assert nmap_lan_bind_args("10.8.0.0/24") == ["-S", "10.8.0.2", "-e", "wg0"]


def test_web_fetch_lan_http_binds_home_nic_not_vpn(monkeypatch):
    from types import SimpleNamespace

    import socket

    from app.mobile.wan_forward import lan_http_bind_for_url, lan_source_ipv4_for_peer

    def fake_addrs():
        return {
            "eth0": [
                SimpleNamespace(family=socket.AF_INET, address="192.168.1.12", netmask="255.255.255.0"),
            ],
            "wg0": [
                SimpleNamespace(family=socket.AF_INET, address="10.8.0.2", netmask="255.255.255.0"),
            ],
        }

    monkeypatch.setattr("psutil.net_if_addrs", fake_addrs)
    assert lan_source_ipv4_for_peer("192.168.1.50") == "192.168.1.12"
    assert lan_source_ipv4_for_peer("10.8.0.9") == "10.8.0.2"
    assert lan_http_bind_for_url("http://192.168.1.50/status") == "192.168.1.12"
    assert lan_http_bind_for_url("https://example.com/") == ""
    monkeypatch.setattr(
        "app.mobile.wan_forward.socket.getaddrinfo",
        lambda *a, **k: [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("192.168.1.50", 80))],
    )
    assert lan_http_bind_for_url("http://nas.local/media") == "192.168.1.12"


@pytest.mark.asyncio
async def test_browser_lan_route_fetches_from_home_nic_not_vpn(monkeypatch):
    from types import SimpleNamespace

    import httpx

    from app.tools.browser import (
        browser_lan_bind_for_url,
        fetch_browser_lan_url,
        handle_browser_lan_route,
        install_browser_lan_route,
    )

    monkeypatch.setattr(
        "psutil.net_if_addrs",
        lambda: {
            "eth0": [
                SimpleNamespace(family=__import__("socket").AF_INET, address="192.168.1.12", netmask="255.255.255.0"),
            ],
            "wg0": [
                SimpleNamespace(family=__import__("socket").AF_INET, address="10.8.0.2", netmask="255.255.255.0"),
            ],
        },
    )
    assert browser_lan_bind_for_url("http://192.168.1.50/status") == "192.168.1.12"
    assert browser_lan_bind_for_url("https://example.com/") == ""
    assert browser_lan_bind_for_url("file:///home/owner/notes.html") == ""

    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text="nas-ok")

    class Client(httpx.AsyncClient):
        def __init__(self, **kwargs):
            seen["local_address"] = getattr(getattr(kwargs.get("transport"), "_pool", None), "_local_address", None)
            kwargs["transport"] = httpx.MockTransport(handler)
            super().__init__(**kwargs)

    monkeypatch.setattr("httpx.AsyncClient", Client)
    payload = await fetch_browser_lan_url("http://192.168.1.50/status")
    assert payload["status"] == 200
    assert payload["body"] == b"nas-ok"
    assert seen["local_address"] == "192.168.1.12"

    continued = {"n": 0}
    fulfilled = {}

    class FakeRoute:
        def __init__(self, url, method="GET"):
            self.request = SimpleNamespace(url=url, method=method, post_data=None, all_headers=lambda: {})

        async def continue_(self):
            continued["n"] += 1

        async def fulfill(self, **kwargs):
            fulfilled.update(kwargs)

        async def abort(self, reason=""):
            fulfilled["aborted"] = reason

    await handle_browser_lan_route(FakeRoute("https://example.com/"))
    assert continued["n"] == 1
    await handle_browser_lan_route(FakeRoute("http://192.168.1.50/status"))
    assert fulfilled.get("status") == 200
    assert fulfilled.get("body") == b"nas-ok"

    class FakeContext:
        def __init__(self):
            self.routes = []

        async def route(self, pattern, handler):
            self.routes.append((pattern, handler))

    ctx = FakeContext()
    await install_browser_lan_route(ctx)
    assert ctx.routes == [("**/*", handle_browser_lan_route)]


async def test_browser_use_lan_intercept_playwright_and_cdp(monkeypatch):
    import asyncio
    import base64
    from types import SimpleNamespace

    import httpx

    from app.tools.browser import (
        handle_browser_lan_route,
        handle_cdp_lan_paused,
        install_browser_use_lan_intercept,
    )

    monkeypatch.setattr(
        "psutil.net_if_addrs",
        lambda: {
            "eth0": [
                SimpleNamespace(family=__import__("socket").AF_INET, address="192.168.1.12", netmask="255.255.255.0"),
            ],
            "wg0": [
                SimpleNamespace(family=__import__("socket").AF_INET, address="10.8.0.2", netmask="255.255.255.0"),
            ],
        },
    )

    class FakeContext:
        def __init__(self):
            self.routes = []

        async def route(self, pattern, handler):
            self.routes.append((pattern, handler))

    class PlaywrightSession:
        def __init__(self):
            self.browser_context = FakeContext()

    pw = PlaywrightSession()
    await install_browser_use_lan_intercept(pw)
    assert pw.browser_context.routes == [("**/*", handle_browser_lan_route)]

    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text="nas-ok")

    class Client(httpx.AsyncClient):
        def __init__(self, **kwargs):
            seen["local_address"] = getattr(getattr(kwargs.get("transport"), "_pool", None), "_local_address", None)
            kwargs["transport"] = httpx.MockTransport(handler)
            super().__init__(**kwargs)

    monkeypatch.setattr("httpx.AsyncClient", Client)

    class FetchOps:
        def __init__(self):
            self.calls = []

        async def enable(self, params=None, session_id=None):
            self.calls.append(("enable", params, session_id))

        async def continueRequest(self, params=None, session_id=None):
            self.calls.append(("continueRequest", params, session_id))

        async def fulfillRequest(self, params=None, session_id=None):
            self.calls.append(("fulfillRequest", params, session_id))

        async def failRequest(self, params=None, session_id=None):
            self.calls.append(("failRequest", params, session_id))

    class FetchReg:
        def __init__(self):
            self.paused = None

        def requestPaused(self, callback):
            self.paused = callback

    class FakeCDP:
        def __init__(self):
            self.send = SimpleNamespace(Fetch=FetchOps())
            self.register = SimpleNamespace(Fetch=FetchReg())

    class CdpSession:
        def __init__(self):
            self._cdp_client_root = FakeCDP()

        @property
        def cdp_client(self):
            return self._cdp_client_root

    cdp_session = CdpSession()
    await install_browser_use_lan_intercept(cdp_session)
    fetch = cdp_session.cdp_client.send.Fetch
    assert fetch.calls[0][0] == "enable"
    assert fetch.calls[0][1]["patterns"][0]["urlPattern"] == "http://*"
    assert callable(cdp_session.cdp_client.register.Fetch.paused)

    await handle_cdp_lan_paused(
        cdp_session.cdp_client,
        {"requestId": "wan", "request": {"url": "https://example.com/", "method": "GET", "headers": {}}},
    )
    assert fetch.calls[-1][0] == "continueRequest"
    await handle_cdp_lan_paused(
        cdp_session.cdp_client,
        {"requestId": "lan", "request": {"url": "http://192.168.1.50/status", "method": "GET", "headers": {}}},
    )
    assert fetch.calls[-1][0] == "fulfillRequest"
    fulfilled = fetch.calls[-1][1]
    assert fulfilled["responseCode"] == 200
    assert base64.b64decode(fulfilled["body"]) == b"nas-ok"
    assert seen["local_address"] == "192.168.1.12"

    cdp_session.cdp_client.register.Fetch.paused(
        {"requestId": "wan2", "request": {"url": "https://example.com/other", "method": "GET", "headers": {}}}
    )
    await asyncio.sleep(0)
    assert any(item[0] == "continueRequest" and item[1].get("requestId") == "wan2" for item in fetch.calls)


def test_udp_lan_ipv4_ignores_cgnat(monkeypatch):
    from app.mobile import igd

    class FakeSock:
        def connect(self, addr):
            return None

        def getsockname(self):
            return ("100.64.1.8", 12345)

        def close(self):
            return None

    monkeypatch.setattr(igd.socket, "socket", lambda *a, **k: FakeSock())
    assert igd._udp_lan_ipv4() == ""


@pytest.mark.asyncio
async def test_ssh_reverse_is_used_when_upnp_unavailable(tmp_path, monkeypatch):
    from app.mobile import connectivity, store
    from tests.test_mobile_connectivity import FakeConnection

    monkeypatch.setattr(store, "data_dir", lambda: tmp_path)
    monkeypatch.setattr(connectivity, "lan_hosts", lambda: ["192.168.1.12"])
    monkeypatch.setattr(connectivity, "router_candidate", lambda *a, **k: (_ for _ in ()).throw(ValueError("No public IPv4")))
    key = tmp_path / "id_ed25519"
    key.write_text("dummy", encoding="utf-8")

    async def fake_tunnel(settings):
        assert settings["ssh_host"] == "vpn.example.test"
        return "https://vpn.example.test:4781"

    monkeypatch.setattr("app.mobile.wan_forward.apply_ssh_reverse", fake_tunnel)
    connection = FakeConnection()
    result = await connection.configure(
        True,
        True,
        {
            "wan_method": "ssh_reverse",
            "ssh_host": "vpn.example.test",
            "ssh_user": "taco",
            "ssh_identity_file": str(key),
        },
    )
    assert result["state"] == "ready"
    assert any(endpoint == "https://vpn.example.test:4781" for endpoint in result["endpoints"])
    assert result.get("wan_path") == "ssh_reverse"
    from app.mobile.gateway import identity_covers
    assert identity_covers(connection.identity, ["vpn.example.test", "192.168.1.12"])


@pytest.mark.asyncio
async def test_upnp_double_nat_falls_through_to_reverse_tunnel(tmp_path, monkeypatch):
    from app.mobile import connectivity, store
    from tests.test_mobile_connectivity import FakeConnection, Router

    monkeypatch.setattr(store, "data_dir", lambda: tmp_path)
    monkeypatch.setattr(connectivity, "lan_hosts", lambda: ["192.168.1.12"])
    router = Router()
    natpmp_hits = {"n": 0}
    monkeypatch.setattr(connectivity, "router_candidate", lambda *a, **k: (router, "198.51.100.8"))
    monkeypatch.setattr("app.mobile.wan_forward.lookup_egress_ipv4", lambda: "203.0.113.50")
    monkeypatch.setattr("app.mobile.wan_forward.rfc1918_default_gateways", lambda: ["192.168.1.1"])
    monkeypatch.setattr("app.mobile.wan_forward.default_gateway_ipv4", lambda: "192.168.1.1")
    monkeypatch.setattr(
        "app.mobile.natpmp.apply_natpmp",
        lambda *a, **k: natpmp_hits.__setitem__("n", natpmp_hits["n"] + 1) or (_ for _ in ()).throw(TimeoutError("no NAT-PMP")),
    )
    monkeypatch.setattr("app.mobile.pcp.apply_pcp", lambda *a, **k: (_ for _ in ()).throw(TimeoutError("no PCP")))
    key = tmp_path / "id_ed25519"
    key.write_text("dummy", encoding="utf-8")

    async def fake_tunnel(settings):
        return "https://vpn.example.test:4781"

    monkeypatch.setattr("app.mobile.wan_forward.apply_ssh_reverse", fake_tunnel)
    result = await FakeConnection().configure(
        True,
        True,
        {
            "wan_method": "auto",
            "ssh_host": "vpn.example.test",
            "ssh_user": "taco",
            "ssh_identity_file": str(key),
        },
    )
    assert result["state"] == "ready"
    assert result.get("wan_path") == "ssh_reverse"
    assert natpmp_hits["n"] == 1
    assert "https://198.51.100.8:4781" not in result["endpoints"]
    assert any(endpoint == "https://vpn.example.test:4781" for endpoint in result["endpoints"])
    assert router.deleted == [(4781, "TCP")]
    assert "double nat" in (result.get("limitation") or "").lower()


@pytest.mark.asyncio
async def test_upnp_double_nat_still_tries_owner_gateway_ssh(tmp_path, monkeypatch):
    from app.mobile import connectivity, store
    from tests.test_mobile_connectivity import FakeConnection, Router

    monkeypatch.setattr(store, "data_dir", lambda: tmp_path)
    monkeypatch.setattr(connectivity, "lan_hosts", lambda: ["192.168.1.12"])
    router = Router()
    natpmp_hits = {"n": 0}
    gateway_hits = {"n": 0}
    monkeypatch.setattr(connectivity, "router_candidate", lambda *a, **k: (router, "198.51.100.8"))
    monkeypatch.setattr("app.mobile.wan_forward.lookup_egress_ipv4", lambda: "203.0.113.50")
    monkeypatch.setattr("app.mobile.wan_forward.rfc1918_default_gateways", lambda: ["192.168.1.1"])
    monkeypatch.setattr("app.mobile.wan_forward.default_gateway_ipv4", lambda: "192.168.1.1")
    monkeypatch.setattr(
        "app.mobile.natpmp.apply_natpmp",
        lambda *a, **k: natpmp_hits.__setitem__("n", natpmp_hits["n"] + 1) or (_ for _ in ()).throw(TimeoutError("no NAT-PMP")),
    )
    monkeypatch.setattr("app.mobile.pcp.apply_pcp", lambda *a, **k: (_ for _ in ()).throw(TimeoutError("no PCP")))
    key = tmp_path / "id_ed25519"
    key.write_text("dummy", encoding="utf-8")

    async def fake_gateway(settings, lan_ip, public_host=""):
        gateway_hits["n"] += 1
        assert lan_ip == "192.168.1.12"
        assert settings["gateway_host"] == "192.168.1.1"
        assert public_host == "home.example.test"
        return "https://home.example.test:4781", "Owner gateway mapped TCP 4781"

    async def fake_tunnel(_settings):
        raise AssertionError("SSH reverse should not run after gateway SSH mapped")

    monkeypatch.setattr("app.mobile.wan_forward.apply_gateway_ssh", fake_gateway)
    monkeypatch.setattr("app.mobile.wan_forward.apply_ssh_reverse", fake_tunnel)
    result = await FakeConnection().configure(
        True,
        True,
        {
            "wan_method": "auto",
            "gateway_host": "192.168.1.1",
            "gateway_user": "root",
            "gateway_identity_file": str(key),
            "wan_public_host": "home.example.test",
        },
    )
    assert result["state"] == "ready"
    assert result.get("wan_path") == "gateway_ssh"
    assert gateway_hits["n"] == 1
    assert natpmp_hits["n"] == 1
    assert "https://198.51.100.8:4781" not in result["endpoints"]
    assert any(endpoint == "https://home.example.test:4781" for endpoint in result["endpoints"])
    assert router.deleted == [(4781, "TCP")]


@pytest.mark.asyncio
async def test_upnp_double_nat_then_natpmp_on_second_gateway(tmp_path, monkeypatch):
    from app.mobile import connectivity, store
    from tests.test_mobile_connectivity import FakeConnection, Router

    monkeypatch.setattr(store, "data_dir", lambda: tmp_path)
    monkeypatch.setattr(connectivity, "lan_hosts", lambda: ["10.0.0.8", "192.168.1.12"])
    router = Router()
    monkeypatch.setattr(connectivity, "router_candidate", lambda *a, **k: (router, "198.51.100.8"))
    monkeypatch.setattr("app.mobile.wan_forward.lookup_egress_ipv4", lambda: "203.0.113.50")
    monkeypatch.setattr("app.mobile.wan_forward.rfc1918_default_gateways", lambda: ["10.0.0.1", "192.168.1.1"])
    monkeypatch.setattr("app.mobile.wan_forward.default_gateway_ipv4", lambda: "10.0.0.1")
    seen: list[str] = []

    def fake_natpmp(gw, lan):
        seen.append(gw)
        if gw == "192.168.1.1":
            return "203.0.113.50"
        return "198.51.100.9"

    monkeypatch.setattr("app.mobile.natpmp.apply_natpmp", fake_natpmp)
    monkeypatch.setattr("app.mobile.pcp.apply_pcp", lambda *a, **k: (_ for _ in ()).throw(TimeoutError("no PCP")))
    result = await FakeConnection().configure(True, True, {"wan_method": "auto"})
    assert result.get("wan_path") == "natpmp"
    assert seen == ["10.0.0.1", "192.168.1.1"]
    assert "https://203.0.113.50:4781" in result["endpoints"]
    assert "https://198.51.100.8:4781" not in result["endpoints"]
    assert router.deleted == [(4781, "TCP")]


@pytest.mark.asyncio
async def test_natpmp_skips_inner_mapping_and_uses_next_gateway(tmp_path, monkeypatch):
    from app.mobile import connectivity, store
    from tests.test_mobile_connectivity import FakeConnection

    monkeypatch.setattr(store, "data_dir", lambda: tmp_path)
    monkeypatch.setattr(connectivity, "lan_hosts", lambda: ["10.0.0.8", "192.168.1.12"])
    monkeypatch.setattr(connectivity, "router_candidate", lambda *a, **k: (_ for _ in ()).throw(ValueError("No IGD")))
    monkeypatch.setattr("app.mobile.wan_forward.lookup_egress_ipv4", lambda: "203.0.113.50")
    monkeypatch.setattr("app.mobile.wan_forward.rfc1918_default_gateways", lambda: ["10.0.0.1", "192.168.1.1"])
    monkeypatch.setattr("app.mobile.wan_forward.default_gateway_ipv4", lambda: "10.0.0.1")
    seen: list[str] = []

    def fake_natpmp(gw, lan):
        del lan
        seen.append(gw)
        return "198.51.100.9" if gw == "10.0.0.1" else "203.0.113.50"

    monkeypatch.setattr("app.mobile.natpmp.apply_natpmp", fake_natpmp)
    monkeypatch.setattr("app.mobile.pcp.apply_pcp", lambda *a, **k: (_ for _ in ()).throw(TimeoutError("no PCP")))
    result = await FakeConnection().configure(True, True, {"wan_method": "auto"})
    assert result.get("wan_path") == "natpmp"
    assert seen == ["10.0.0.1", "192.168.1.1"]
    assert "https://203.0.113.50:4781" in result["endpoints"]
    assert "https://198.51.100.9:4781" not in result["endpoints"]


@pytest.mark.asyncio
async def test_gateway_ssh_without_dest_falls_through_to_reverse(tmp_path, monkeypatch):
    from app.mobile import connectivity, store
    from tests.test_mobile_connectivity import FakeConnection

    monkeypatch.setattr(store, "data_dir", lambda: tmp_path)
    monkeypatch.setattr(connectivity, "lan_hosts", lambda: ["192.168.1.12"])
    monkeypatch.setattr(connectivity, "router_candidate", lambda *a, **k: (_ for _ in ()).throw(ValueError("No IGD")))
    monkeypatch.setattr("app.mobile.natpmp.apply_natpmp", lambda *a, **k: (_ for _ in ()).throw(TimeoutError("no NAT-PMP")))
    monkeypatch.setattr("app.mobile.pcp.apply_pcp", lambda *a, **k: (_ for _ in ()).throw(TimeoutError("no PCP")))
    key = tmp_path / "id_ed25519"
    key.write_text("dummy", encoding="utf-8")
    gateway_hits = {"n": 0}

    async def fake_gateway(*_a, **_k):
        gateway_hits["n"] += 1
        raise AssertionError("Gateway SSH must not run without a dest IP on the router /24")

    async def fake_tunnel(settings):
        assert settings["ssh_host"] == "vpn.example.test"
        return "https://vpn.example.test:4781"

    monkeypatch.setattr("app.mobile.wan_forward.apply_gateway_ssh", fake_gateway)
    monkeypatch.setattr("app.mobile.wan_forward.apply_ssh_reverse", fake_tunnel)
    result = await FakeConnection().configure(
        True,
        True,
        {
            "wan_method": "auto",
            "gateway_host": "192.168.0.1",
            "gateway_user": "root",
            "gateway_identity_file": str(key),
            "ssh_host": "vpn.example.test",
            "ssh_user": "taco",
            "ssh_identity_file": str(key),
        },
    )
    assert result["state"] == "ready"
    assert gateway_hits["n"] == 0
    assert result.get("wan_path") == "ssh_reverse"
    assert any(endpoint == "https://vpn.example.test:4781" for endpoint in result["endpoints"])
    assert "router subnet" in (result.get("limitation") or "").lower()


@pytest.mark.asyncio
async def test_gateway_ssh_maps_without_public_hostname(tmp_path, monkeypatch):
    from app.mobile import connectivity, store
    from tests.test_mobile_connectivity import FakeConnection

    monkeypatch.setattr(store, "data_dir", lambda: tmp_path)
    monkeypatch.setattr(connectivity, "lan_hosts", lambda: ["192.168.1.12"])
    monkeypatch.setattr(connectivity, "router_candidate", lambda *a, **k: (_ for _ in ()).throw(ValueError("No public IPv4")))
    key = tmp_path / "id_ed25519"
    key.write_text("dummy", encoding="utf-8")

    async def fake_gateway(settings, lan_ip, public_host=""):
        assert lan_ip == "192.168.1.12"
        assert settings["gateway_host"] == "192.168.1.1"
        return None, "Gateway SSH mapped TCP 4781 on the router. Set a public hostname so the phone can dial it from outside this network."

    monkeypatch.setattr("app.mobile.wan_forward.apply_gateway_ssh", fake_gateway)
    result = await FakeConnection().configure(
        True,
        True,
        {
            "wan_method": "gateway_ssh",
            "gateway_host": "192.168.1.1",
            "gateway_user": "root",
            "gateway_identity_file": str(key),
        },
    )
    assert result["state"] == "ready"
    assert result.get("wan_path") == "gateway_ssh"
    assert "https://192.168.1.1:4781" not in result["endpoints"]
    assert "public hostname" in (result.get("limitation") or "")


@pytest.mark.asyncio
async def test_password_only_gateway_ssh_uses_default_gateway(tmp_path, monkeypatch):
    from app.mobile import connectivity, store
    from tests.test_mobile_connectivity import FakeConnection

    monkeypatch.setattr(store, "data_dir", lambda: tmp_path)
    monkeypatch.setattr(connectivity, "lan_hosts", lambda: ["192.168.1.12"])
    monkeypatch.setattr(connectivity, "router_candidate", lambda *a, **k: (_ for _ in ()).throw(ValueError("No public IPv4")))
    monkeypatch.setattr("app.mobile.wan_forward.default_gateway_ipv4", lambda: "192.168.1.1")
    monkeypatch.setattr("app.mobile.wan_forward.rfc1918_default_gateways", lambda: ["192.168.1.1"])
    monkeypatch.setattr("app.mobile.natpmp.apply_natpmp", lambda *a, **k: (_ for _ in ()).throw(TimeoutError("no NAT-PMP")))
    monkeypatch.setattr("app.mobile.pcp.apply_pcp", lambda *a, **k: (_ for _ in ()).throw(TimeoutError("no PCP")))

    seen: dict[str, str] = {}

    async def fake_gateway(settings, lan_ip, public_host=""):
        seen["host"] = settings.get("gateway_host") or ""
        seen["password"] = settings.get("gateway_password") or ""
        seen["lan"] = lan_ip
        return "https://home.example.test:4781", "mapped"

    monkeypatch.setattr("app.mobile.wan_forward.apply_gateway_ssh", fake_gateway)
    connection = FakeConnection()
    result = await connection.configure(
        True,
        True,
        {"wan_method": "auto", "gateway_password": "router-pass", "wan_public_host": "home.example.test"},
    )
    assert result["state"] == "ready"
    assert result.get("wan_path") == "gateway_ssh"
    assert seen["password"] == "router-pass"
    assert seen["host"] == "192.168.1.1"
    assert seen["lan"] == "192.168.1.12"
    assert any(endpoint == "https://home.example.test:4781" for endpoint in result["endpoints"])
    from app.mobile.gateway import identity_covers
    assert identity_covers(connection.identity, ["home.example.test", "192.168.1.12"])


def test_gateway_ssh_hosts_walks_rfc1918_when_host_blank(monkeypatch):
    from app.mobile.wan_forward import gateway_ssh_hosts, rfc1918_mapping_gateways

    monkeypatch.setattr("app.mobile.wan_forward.rfc1918_default_gateways", lambda: ["192.168.1.1", "10.8.0.1"])
    monkeypatch.setattr("app.mobile.wan_forward.default_gateway_ipv4", lambda: "192.168.1.1")
    assert rfc1918_mapping_gateways() == ["192.168.1.1", "10.8.0.1"]
    assert gateway_ssh_hosts({"gateway_password": "router-pass"}) == ["192.168.1.1", "10.8.0.1"]
    monkeypatch.setattr("app.mobile.wan_forward.rfc1918_default_gateways", lambda: ["10.8.0.1", "192.168.1.1"])
    monkeypatch.setattr("app.mobile.wan_forward.default_gateway_ipv4", lambda: "10.8.0.1")
    assert rfc1918_mapping_gateways() == ["10.8.0.1", "192.168.1.1"]
    assert gateway_ssh_hosts({"gateway_host": "192.168.0.1"}) == ["192.168.0.1"]


@pytest.mark.asyncio
async def test_gateway_ssh_tries_second_rfc1918_gateway_when_first_fails(tmp_path, monkeypatch):
    from app.mobile import connectivity, store
    from tests.test_mobile_connectivity import FakeConnection

    monkeypatch.setattr(store, "data_dir", lambda: tmp_path)
    monkeypatch.setattr(connectivity, "lan_hosts", lambda: ["10.0.0.8", "192.168.1.12"])
    monkeypatch.setattr(connectivity, "router_candidate", lambda *a, **k: (_ for _ in ()).throw(ValueError("No IGD")))
    monkeypatch.setattr("app.mobile.wan_forward.rfc1918_default_gateways", lambda: ["10.0.0.1", "192.168.1.1"])
    monkeypatch.setattr("app.mobile.wan_forward.default_gateway_ipv4", lambda: "10.0.0.1")
    monkeypatch.setattr("app.mobile.natpmp.apply_natpmp", lambda *a, **k: (_ for _ in ()).throw(TimeoutError("no NAT-PMP")))
    monkeypatch.setattr("app.mobile.pcp.apply_pcp", lambda *a, **k: (_ for _ in ()).throw(TimeoutError("no PCP")))
    seen: list[tuple[str, str]] = []

    async def fake_gateway(settings, lan_ip, public_host=""):
        host = str(settings.get("gateway_host") or "")
        seen.append((host, lan_ip))
        if host == "10.0.0.1":
            raise RuntimeError("VPN gateway is not OpenWrt")
        assert public_host == "home.example.test"
        return "https://home.example.test:4781", "Owner gateway mapped TCP 4781"

    monkeypatch.setattr("app.mobile.wan_forward.apply_gateway_ssh", fake_gateway)
    connection = FakeConnection()
    result = await connection.configure(
        True,
        True,
        {
            "wan_method": "auto",
            "gateway_password": "router-pass",
            "wan_public_host": "home.example.test",
        },
    )
    assert result["state"] == "ready"
    assert result.get("wan_path") == "gateway_ssh"
    assert seen == [("10.0.0.1", "10.0.0.8"), ("192.168.1.1", "192.168.1.12")]
    assert result.get("mapped_lan_ip") == "192.168.1.12"
    assert connection.ssh_gateway == "192.168.1.1"
    assert connection._live_wan_dest_ip() == "192.168.1.12"
    assert any(endpoint == "https://home.example.test:4781" for endpoint in result["endpoints"])


@pytest.mark.asyncio
async def test_gateway_ssh_explicit_host_does_not_walk_other_routers(tmp_path, monkeypatch):
    from app.mobile import connectivity, store
    from tests.test_mobile_connectivity import FakeConnection

    monkeypatch.setattr(store, "data_dir", lambda: tmp_path)
    monkeypatch.setattr(connectivity, "lan_hosts", lambda: ["10.0.0.8", "192.168.1.12"])
    monkeypatch.setattr(connectivity, "router_candidate", lambda *a, **k: (_ for _ in ()).throw(ValueError("No IGD")))
    monkeypatch.setattr("app.mobile.wan_forward.rfc1918_default_gateways", lambda: ["10.0.0.1", "192.168.1.1"])
    monkeypatch.setattr("app.mobile.wan_forward.default_gateway_ipv4", lambda: "10.0.0.1")
    monkeypatch.setattr("app.mobile.natpmp.apply_natpmp", lambda *a, **k: (_ for _ in ()).throw(TimeoutError("no NAT-PMP")))
    monkeypatch.setattr("app.mobile.pcp.apply_pcp", lambda *a, **k: (_ for _ in ()).throw(TimeoutError("no PCP")))
    key = tmp_path / "id_ed25519"
    key.write_text("dummy", encoding="utf-8")
    seen: list[str] = []

    async def fake_gateway(settings, lan_ip, public_host=""):
        del lan_ip, public_host
        seen.append(str(settings.get("gateway_host") or ""))
        raise RuntimeError("typed inner router refused SSH")

    async def fake_tunnel(settings):
        assert settings["ssh_host"] == "vpn.example.test"
        return "https://vpn.example.test:4781"

    monkeypatch.setattr("app.mobile.wan_forward.apply_gateway_ssh", fake_gateway)
    monkeypatch.setattr("app.mobile.wan_forward.apply_ssh_reverse", fake_tunnel)
    result = await FakeConnection().configure(
        True,
        True,
        {
            "wan_method": "auto",
            "gateway_host": "10.0.0.1",
            "gateway_user": "root",
            "gateway_identity_file": str(key),
            "ssh_host": "vpn.example.test",
            "ssh_user": "taco",
            "ssh_identity_file": str(key),
        },
    )
    assert result["state"] == "ready"
    assert seen == ["10.0.0.1"]
    assert result.get("wan_path") == "ssh_reverse"
    assert any(endpoint == "https://vpn.example.test:4781" for endpoint in result["endpoints"])


@pytest.mark.asyncio
async def test_gateway_ssh_renew_stays_on_working_router(tmp_path, monkeypatch):
    from app.mobile import connectivity, store
    from tests.test_mobile_connectivity import FakeConnection

    monkeypatch.setattr(store, "data_dir", lambda: tmp_path)
    monkeypatch.setattr(connectivity, "lan_hosts", lambda: ["10.0.0.8", "192.168.1.12"])
    monkeypatch.setattr(connectivity, "router_candidate", lambda *a, **k: (_ for _ in ()).throw(ValueError("No IGD")))
    monkeypatch.setattr("app.mobile.wan_forward.rfc1918_default_gateways", lambda: ["10.0.0.1", "192.168.1.1"])
    monkeypatch.setattr("app.mobile.wan_forward.default_gateway_ipv4", lambda: "10.0.0.1")
    monkeypatch.setattr("app.mobile.natpmp.apply_natpmp", lambda *a, **k: (_ for _ in ()).throw(TimeoutError("no NAT-PMP")))
    monkeypatch.setattr("app.mobile.pcp.apply_pcp", lambda *a, **k: (_ for _ in ()).throw(TimeoutError("no PCP")))
    seen: list[str] = []

    async def fake_gateway(settings, lan_ip, public_host=""):
        del lan_ip, public_host
        host = str(settings.get("gateway_host") or "")
        seen.append(host)
        if host == "10.0.0.1":
            raise RuntimeError("VPN gateway is not OpenWrt")
        return "https://home.example.test:4781", "mapped"

    monkeypatch.setattr("app.mobile.wan_forward.apply_gateway_ssh", fake_gateway)
    connection = FakeConnection()
    result = await connection.configure(
        True,
        True,
        {"wan_method": "auto", "gateway_password": "router-pass", "wan_public_host": "home.example.test"},
    )
    assert result.get("wan_path") == "gateway_ssh"
    assert seen == ["10.0.0.1", "192.168.1.1"]
    seen.clear()
    await connection._renew_gateway_ssh(connection.config())
    assert seen[0] == "192.168.1.1"
    assert "10.0.0.1" not in seen
    assert connection.ssh_gateway == "192.168.1.1"
    assert connection._live_wan_dest_ip() == "192.168.1.12"


@pytest.mark.asyncio
async def test_gateway_ssh_renews_when_lan_ip_changes(tmp_path, monkeypatch):
    from app.mobile import connectivity, store
    from tests.test_mobile_connectivity import FakeConnection

    monkeypatch.setattr(store, "data_dir", lambda: tmp_path)
    hosts = ["192.168.1.12"]
    monkeypatch.setattr(connectivity, "lan_hosts", lambda: list(hosts))
    monkeypatch.setattr(connectivity, "router_candidate", lambda *a, **k: (_ for _ in ()).throw(ValueError("No IGD")))
    monkeypatch.setattr("app.mobile.natpmp.apply_natpmp", lambda *a, **k: (_ for _ in ()).throw(TimeoutError("no NAT-PMP")))
    monkeypatch.setattr("app.mobile.pcp.apply_pcp", lambda *a, **k: (_ for _ in ()).throw(TimeoutError("no PCP")))
    key = tmp_path / "id_ed25519"
    key.write_text("dummy", encoding="utf-8")
    seen: list[str] = []

    async def fake_gateway(settings, lan_ip, public_host=""):
        del settings, public_host
        seen.append(lan_ip)
        return "https://home.example.test:4781", "Gateway SSH mapping applied; verify from outside this network"

    monkeypatch.setattr("app.mobile.wan_forward.apply_gateway_ssh", fake_gateway)
    connection = FakeConnection()
    result = await connection.configure(
        True,
        True,
        {
            "wan_method": "gateway_ssh",
            "gateway_host": "192.168.1.1",
            "gateway_user": "root",
            "gateway_identity_file": str(key),
            "wan_public_host": "home.example.test",
        },
    )
    assert result["state"] == "ready"
    assert result.get("wan_path") == "gateway_ssh"
    assert result.get("mapped_lan_ip") == "192.168.1.12"
    assert seen == ["192.168.1.12"]
    hosts[:] = ["192.168.1.40"]
    await connection._renew_wan_mapping(connection.config())
    assert seen == ["192.168.1.12", "192.168.1.40"]
    assert connection.state.get("mapped_lan_ip") == "192.168.1.40"
    assert "https://192.168.1.40:4781" in connection.state["endpoints"]
    assert "https://192.168.1.12:4781" not in connection.state["endpoints"]
    assert any(endpoint == "https://home.example.test:4781" for endpoint in connection.state["endpoints"])


@pytest.mark.asyncio
async def test_lan_refresh_rebuilds_gateway_ssh_when_egress_ipv4_changes(tmp_path, monkeypatch):
    import time

    from app.mobile import connectivity, store
    from tests.test_mobile_connectivity import FakeConnection

    monkeypatch.setattr(store, "data_dir", lambda: tmp_path)
    monkeypatch.setattr(connectivity, "lan_hosts", lambda: ["192.168.1.12"])
    monkeypatch.setattr(connectivity, "router_candidate", lambda *a, **k: (_ for _ in ()).throw(ValueError("No IGD")))
    monkeypatch.setattr("app.mobile.natpmp.apply_natpmp", lambda *a, **k: (_ for _ in ()).throw(TimeoutError("no NAT-PMP")))
    monkeypatch.setattr("app.mobile.pcp.apply_pcp", lambda *a, **k: (_ for _ in ()).throw(TimeoutError("no PCP")))
    egress = {"ip": "203.0.113.8"}
    monkeypatch.setattr("app.mobile.wan_forward.lookup_egress_ipv4", lambda: egress["ip"])
    key = tmp_path / "id_ed25519"
    key.write_text("dummy", encoding="utf-8")
    seen_hosts: list[str] = []

    async def fake_gateway(settings, lan_ip, public_host=""):
        del settings, lan_ip
        seen_hosts.append(public_host)
        return f"https://{public_host}:4781", "mapped"

    monkeypatch.setattr("app.mobile.wan_forward.apply_gateway_ssh", fake_gateway)
    connection = FakeConnection()
    result = await connection.configure(
        True,
        True,
        {
            "wan_method": "gateway_ssh",
            "gateway_host": "192.168.1.1",
            "gateway_user": "root",
            "gateway_identity_file": str(key),
        },
    )
    assert result.get("wan_path") == "gateway_ssh"
    assert connection.public_ip == "203.0.113.8"
    assert "https://203.0.113.8:4781" in result["endpoints"]
    held = time.time() + 1190
    connection.report(next_renewal_at=held)
    await connection._refresh_lan_dial_endpoints()
    assert connection.state.get("next_renewal_at") == held
    egress["ip"] = "203.0.113.9"
    await connection._refresh_lan_dial_endpoints()
    assert connection.public_ip == "203.0.113.9"
    assert "https://203.0.113.9:4781" in connection.state["endpoints"]
    assert "https://203.0.113.8:4781" not in connection.state["endpoints"]
    assert seen_hosts == ["203.0.113.8", "203.0.113.9"]


@pytest.mark.asyncio
async def test_gateway_ssh_drops_stale_typed_ipv4_when_egress_moves(tmp_path, monkeypatch):
    """Owner typed last week's public IPv4; live egress must win in the real SSH helper."""
    from app.mobile import connectivity, store
    from tests.test_mobile_connectivity import FakeConnection

    monkeypatch.setattr(store, "data_dir", lambda: tmp_path)
    monkeypatch.setattr(connectivity, "lan_hosts", lambda: ["192.168.1.12"])
    monkeypatch.setattr(connectivity, "router_candidate", lambda *a, **k: (_ for _ in ()).throw(ValueError("No IGD")))
    monkeypatch.setattr("app.mobile.natpmp.apply_natpmp", lambda *a, **k: (_ for _ in ()).throw(TimeoutError("no NAT-PMP")))
    monkeypatch.setattr("app.mobile.pcp.apply_pcp", lambda *a, **k: (_ for _ in ()).throw(TimeoutError("no PCP")))
    monkeypatch.setattr("app.mobile.wan_forward.lookup_egress_ipv4", lambda: "203.0.113.9")

    class FakeProc:
        returncode = 0

        async def communicate(self, _data):
            return b"", b""

    async def fake_exec(*_argv, **_kwargs):
        return FakeProc()

    monkeypatch.setattr("app.mobile.wan_forward.asyncio.create_subprocess_exec", fake_exec)
    monkeypatch.setattr("app.mobile.wan_forward.ssh_executable", lambda: "ssh")
    key = tmp_path / "id_ed25519"
    key.write_text("dummy", encoding="utf-8")
    connection = FakeConnection()
    result = await connection.configure(
        True,
        True,
        {
            "wan_method": "gateway_ssh",
            "gateway_host": "192.168.1.1",
            "gateway_user": "root",
            "gateway_identity_file": str(key),
            "wan_public_host": "203.0.113.8",
        },
    )
    assert result.get("wan_path") == "gateway_ssh"
    assert "https://203.0.113.9:4781" in result["endpoints"]
    assert "https://203.0.113.8:4781" not in result["endpoints"]
    from app.mobile.gateway import identity_covers

    assert identity_covers(connection.identity, ["203.0.113.9", "192.168.1.12"])


@pytest.mark.asyncio
async def test_gateway_ssh_renew_raises_when_dest_leaves_router_subnet(tmp_path, monkeypatch):
    from app.mobile import connectivity, store
    from tests.test_mobile_connectivity import FakeConnection

    monkeypatch.setattr(store, "data_dir", lambda: tmp_path)
    hosts = ["192.168.1.12"]
    monkeypatch.setattr(connectivity, "lan_hosts", lambda: list(hosts))
    monkeypatch.setattr(connectivity, "router_candidate", lambda *a, **k: (_ for _ in ()).throw(ValueError("No IGD")))
    monkeypatch.setattr("app.mobile.natpmp.apply_natpmp", lambda *a, **k: (_ for _ in ()).throw(TimeoutError("no NAT-PMP")))
    monkeypatch.setattr("app.mobile.pcp.apply_pcp", lambda *a, **k: (_ for _ in ()).throw(TimeoutError("no PCP")))
    key = tmp_path / "id_ed25519"
    key.write_text("dummy", encoding="utf-8")

    async def fake_gateway(settings, lan_ip, public_host=""):
        del settings, public_host
        return "https://home.example.test:4781", f"mapped {lan_ip}"

    monkeypatch.setattr("app.mobile.wan_forward.apply_gateway_ssh", fake_gateway)
    connection = FakeConnection()
    result = await connection.configure(
        True,
        True,
        {
            "wan_method": "gateway_ssh",
            "gateway_host": "192.168.1.1",
            "gateway_user": "root",
            "gateway_identity_file": str(key),
            "wan_public_host": "home.example.test",
        },
    )
    assert result.get("wan_path") == "gateway_ssh"
    hosts[:] = ["10.8.0.2"]
    with pytest.raises(RuntimeError, match="not on the router subnet"):
        await connection._renew_wan_mapping(connection.config())


@pytest.mark.asyncio
async def test_upnp_renew_refreshes_lan_endpoint_after_dhcp(tmp_path, monkeypatch):
    from app.mobile import connectivity, store
    from tests.test_mobile_connectivity import FakeConnection, Router

    monkeypatch.setattr(store, "data_dir", lambda: tmp_path)
    hosts = ["192.168.1.12"]
    monkeypatch.setattr(connectivity, "lan_hosts", lambda: list(hosts))
    router = Router()
    router.wan_ip = "203.0.113.8"
    monkeypatch.setattr(connectivity, "router_candidate", lambda *a, **k: (router, "203.0.113.8"))
    connection = FakeConnection()
    result = await connection.configure(True, True)
    assert result["state"] == "ready"
    assert result.get("wan_path") == "upnp"
    assert "https://192.168.1.12:4781" in result["endpoints"]
    assert "https://203.0.113.8:4781" in result["endpoints"]
    hosts[:] = ["192.168.1.40"]
    router.lanaddr = "192.168.1.40"
    await connection._renew_wan_mapping(connection.config())
    assert connection.state.get("mapped_lan_ip") == "192.168.1.40"
    assert router.added[-1][2] == "192.168.1.40"
    assert "https://192.168.1.40:4781" in connection.state["endpoints"]
    assert "https://192.168.1.12:4781" not in connection.state["endpoints"]
    assert "https://203.0.113.8:4781" in connection.state["endpoints"]


@pytest.mark.asyncio
async def test_lan_only_refresh_updates_endpoints_without_waiting_for_wan_renew(tmp_path, monkeypatch):
    from app.mobile import connectivity, store
    from app.mobile.lan_beacon import public_beacon_payload
    from tests.test_mobile_connectivity import FakeConnection

    monkeypatch.setattr(store, "data_dir", lambda: tmp_path)
    hosts = ["192.168.1.12"]
    monkeypatch.setattr(connectivity, "lan_hosts", lambda: list(hosts))
    monkeypatch.setattr(connectivity, "router_candidate", lambda *a, **k: (_ for _ in ()).throw(ValueError("No IGD")))
    connection = FakeConnection()
    result = await connection.configure(True, False)
    assert result["state"] == "ready"
    assert result.get("remote") is False
    assert "https://192.168.1.12:4781" in result["endpoints"]
    hosts[:] = ["192.168.1.40"]
    await connection._refresh_lan_dial_endpoints()
    assert "https://192.168.1.40:4781" in connection.state["endpoints"]
    assert "https://192.168.1.12:4781" not in connection.state["endpoints"]
    beacon = public_beacon_payload(connection.snapshot())
    assert beacon["https"] == "https://192.168.1.40:4781"
    hosts[:] = []
    kept = list(connection.state["endpoints"])
    await connection._refresh_lan_dial_endpoints()
    assert connection.state["endpoints"] == kept


@pytest.mark.asyncio
async def test_lan_refresh_remaps_upnp_dest_without_waiting_for_wan_renew(tmp_path, monkeypatch):
    import time

    from app.mobile import connectivity, store
    from tests.test_mobile_connectivity import FakeConnection, Router

    monkeypatch.setattr(store, "data_dir", lambda: tmp_path)
    hosts = ["192.168.1.12"]
    monkeypatch.setattr(connectivity, "lan_hosts", lambda: list(hosts))
    router = Router()
    router.wan_ip = "203.0.113.8"
    monkeypatch.setattr(connectivity, "router_candidate", lambda *a, **k: (router, "203.0.113.8"))
    connection = FakeConnection()
    result = await connection.configure(True, True)
    assert result["state"] == "ready"
    assert result.get("wan_path") == "upnp"
    assert result.get("mapped_lan_ip") == "192.168.1.12"
    assert router.added[-1][2] == "192.168.1.12"
    maps_before = len(router.added)
    held = time.time() + 1190
    connection.report(next_renewal_at=held)
    await connection._refresh_lan_dial_endpoints()
    assert len(router.added) == maps_before
    assert connection.state.get("next_renewal_at") == held
    hosts[:] = ["192.168.1.40"]
    router.lanaddr = "192.168.1.40"
    await connection._refresh_lan_dial_endpoints()
    assert connection.state.get("mapped_lan_ip") == "192.168.1.40"
    assert router.added[-1][2] == "192.168.1.40"
    assert connection.state.get("next_renewal_at", 0) > held
    assert "https://192.168.1.40:4781" in connection.state["endpoints"]
    assert "https://192.168.1.12:4781" not in connection.state["endpoints"]
    assert "https://203.0.113.8:4781" in connection.state["endpoints"]


@pytest.mark.asyncio
async def test_lan_refresh_remaps_gateway_ssh_dest_without_waiting_for_wan_renew(tmp_path, monkeypatch):
    import time

    from app.mobile import connectivity, store
    from tests.test_mobile_connectivity import FakeConnection

    monkeypatch.setattr(store, "data_dir", lambda: tmp_path)
    hosts = ["192.168.1.12"]
    monkeypatch.setattr(connectivity, "lan_hosts", lambda: list(hosts))
    monkeypatch.setattr(connectivity, "router_candidate", lambda *a, **k: (_ for _ in ()).throw(ValueError("No IGD")))
    monkeypatch.setattr("app.mobile.natpmp.apply_natpmp", lambda *a, **k: (_ for _ in ()).throw(TimeoutError("no NAT-PMP")))
    monkeypatch.setattr("app.mobile.pcp.apply_pcp", lambda *a, **k: (_ for _ in ()).throw(TimeoutError("no PCP")))
    key = tmp_path / "id_ed25519"
    key.write_text("dummy", encoding="utf-8")
    seen: list[str] = []

    async def fake_gateway(settings, lan_ip, public_host=""):
        del settings, public_host
        seen.append(lan_ip)
        return "https://home.example.test:4781", "Gateway SSH mapping applied; verify from outside this network"

    monkeypatch.setattr("app.mobile.wan_forward.apply_gateway_ssh", fake_gateway)
    connection = FakeConnection()
    result = await connection.configure(
        True,
        True,
        {
            "wan_method": "gateway_ssh",
            "gateway_host": "192.168.1.1",
            "gateway_user": "root",
            "gateway_identity_file": str(key),
            "wan_public_host": "home.example.test",
        },
    )
    assert result.get("wan_path") == "gateway_ssh"
    assert result.get("mapped_lan_ip") == "192.168.1.12"
    assert seen == ["192.168.1.12"]
    held = time.time() + 1190
    connection.report(next_renewal_at=held)
    hosts[:] = ["192.168.1.40"]
    await connection._refresh_lan_dial_endpoints()
    assert seen == ["192.168.1.12", "192.168.1.40"]
    assert connection.state.get("mapped_lan_ip") == "192.168.1.40"
    assert connection.state.get("next_renewal_at", 0) > held
    assert "https://192.168.1.40:4781" in connection.state["endpoints"]
    assert "https://192.168.1.12:4781" not in connection.state["endpoints"]
    assert any(endpoint == "https://home.example.test:4781" for endpoint in connection.state["endpoints"])


@pytest.mark.asyncio
async def test_lan_refresh_remaps_natpmp_dest_without_waiting_for_wan_renew(tmp_path, monkeypatch):
    import time

    from app.mobile import connectivity, store
    from tests.test_mobile_connectivity import FakeConnection

    monkeypatch.setattr(store, "data_dir", lambda: tmp_path)
    hosts = ["192.168.1.12"]
    monkeypatch.setattr(connectivity, "lan_hosts", lambda: list(hosts))
    monkeypatch.setattr(connectivity, "router_candidate", lambda *a, **k: (_ for _ in ()).throw(ValueError("No IGD")))
    monkeypatch.setattr("app.mobile.wan_forward.default_gateway_ipv4", lambda: "192.168.1.1")
    seen: list[str] = []

    def fake_natpmp(gw, lan):
        seen.append(lan)
        return "203.0.113.8"

    monkeypatch.setattr("app.mobile.natpmp.apply_natpmp", fake_natpmp)
    connection = FakeConnection()
    result = await connection.configure(True, True, {"wan_method": "auto"})
    assert result.get("wan_path") == "natpmp"
    assert result.get("mapped_lan_ip") == "192.168.1.12"
    assert seen == ["192.168.1.12"]
    held = time.time() + 1190
    connection.report(next_renewal_at=held)
    hosts[:] = ["192.168.1.40"]
    await connection._refresh_lan_dial_endpoints()
    assert seen == ["192.168.1.12", "192.168.1.40"]
    assert connection.state.get("mapped_lan_ip") == "192.168.1.40"
    assert connection.state.get("next_renewal_at", 0) > held
    assert "https://192.168.1.40:4781" in connection.state["endpoints"]
    assert "https://192.168.1.12:4781" not in connection.state["endpoints"]
    assert "https://203.0.113.8:4781" in connection.state["endpoints"]


@pytest.mark.asyncio
async def test_lan_refresh_rebuilds_upnp_when_public_ip_changes(tmp_path, monkeypatch):
    import time

    from app.mobile import connectivity, store
    from tests.test_mobile_connectivity import FakeConnection, Router

    monkeypatch.setattr(store, "data_dir", lambda: tmp_path)
    monkeypatch.setattr(connectivity, "lan_hosts", lambda: ["192.168.1.12"])
    router = Router()
    router.wan_ip = "203.0.113.8"
    monkeypatch.setattr(connectivity, "router_candidate", lambda *a, **k: (router, router.wan_ip))
    connection = FakeConnection()
    result = await connection.configure(True, True)
    assert result.get("wan_path") == "upnp"
    assert "https://203.0.113.8:4781" in result["endpoints"]
    held = time.time() + 1190
    connection.report(next_renewal_at=held)
    maps_before = len(router.added)
    await connection._refresh_lan_dial_endpoints()
    assert len(router.added) == maps_before
    assert connection.state.get("next_renewal_at") == held
    router.wan_ip = "203.0.113.9"
    await connection._refresh_lan_dial_endpoints()
    assert connection.public_ip == "203.0.113.9"
    assert "https://203.0.113.9:4781" in connection.state["endpoints"]
    assert "https://203.0.113.8:4781" not in connection.state["endpoints"]
    assert "https://192.168.1.12:4781" in connection.state["endpoints"]


@pytest.mark.asyncio
async def test_lan_refresh_rebuilds_natpmp_when_public_ip_changes(tmp_path, monkeypatch):
    import time

    from app.mobile import connectivity, store
    from tests.test_mobile_connectivity import FakeConnection

    monkeypatch.setattr(store, "data_dir", lambda: tmp_path)
    monkeypatch.setattr(connectivity, "lan_hosts", lambda: ["192.168.1.12"])
    monkeypatch.setattr(connectivity, "router_candidate", lambda *a, **k: (_ for _ in ()).throw(ValueError("No IGD")))
    monkeypatch.setattr("app.mobile.wan_forward.default_gateway_ipv4", lambda: "192.168.1.1")
    public = {"ip": "203.0.113.8"}

    def fake_natpmp(gw, lan):
        del gw, lan
        return public["ip"]

    def fake_query(gw, lan=""):
        del gw, lan
        return public["ip"]

    monkeypatch.setattr("app.mobile.natpmp.apply_natpmp", fake_natpmp)
    monkeypatch.setattr("app.mobile.natpmp.query_public_ip", fake_query)
    connection = FakeConnection()
    result = await connection.configure(True, True, {"wan_method": "auto"})
    assert result.get("wan_path") == "natpmp"
    assert "https://203.0.113.8:4781" in result["endpoints"]
    held = time.time() + 1190
    connection.report(next_renewal_at=held)
    await connection._refresh_lan_dial_endpoints()
    assert connection.state.get("next_renewal_at") == held
    public["ip"] = "203.0.113.9"
    await connection._refresh_lan_dial_endpoints()
    assert connection.public_ip == "203.0.113.9"
    assert "https://203.0.113.9:4781" in connection.state["endpoints"]
    assert "https://203.0.113.8:4781" not in connection.state["endpoints"]


@pytest.mark.asyncio
async def test_lan_refresh_rebuilds_pcp_when_public_ip_changes(tmp_path, monkeypatch):
    import time

    from app.mobile import connectivity, store
    from tests.test_mobile_connectivity import FakeConnection

    monkeypatch.setattr(store, "data_dir", lambda: tmp_path)
    monkeypatch.setattr(connectivity, "lan_hosts", lambda: ["192.168.1.12"])
    monkeypatch.setattr(connectivity, "router_candidate", lambda *a, **k: (_ for _ in ()).throw(ValueError("No IGD")))
    monkeypatch.setattr("app.mobile.wan_forward.default_gateway_ipv4", lambda: "192.168.1.1")
    monkeypatch.setattr(
        "app.mobile.natpmp.apply_natpmp",
        lambda gw, lan: (_ for _ in ()).throw(ValueError("NAT-PMP unsupported version")),
    )
    public = {"ip": "198.51.100.8"}

    def fake_pcp(gw, lan, nonce=None):
        del gw, lan, nonce
        return public["ip"], bytes([0x11]) * 12

    monkeypatch.setattr("app.mobile.pcp.apply_pcp", fake_pcp)
    monkeypatch.setattr("app.mobile.pcp.delete_pcp", lambda *a, **k: None)
    connection = FakeConnection()
    result = await connection.configure(True, True, {"wan_method": "auto"})
    assert result.get("wan_path") == "pcp"
    assert "https://198.51.100.8:4781" in result["endpoints"]
    held = time.time() + 1190
    connection.report(next_renewal_at=held)
    await connection._refresh_lan_dial_endpoints()
    assert connection.state.get("next_renewal_at") == held
    public["ip"] = "198.51.100.9"
    await connection._refresh_lan_dial_endpoints()
    assert connection.public_ip == "198.51.100.9"
    assert "https://198.51.100.9:4781" in connection.state["endpoints"]
    assert "https://198.51.100.8:4781" not in connection.state["endpoints"]
    assert "https://192.168.1.12:4781" in connection.state["endpoints"]


def test_igd_mapping_dest_never_uses_an_address_this_pc_does_not_hold(monkeypatch):
    from app.mobile import connectivity
    from tests.test_mobile_connectivity import Router

    monkeypatch.setattr(connectivity, "lan_hosts", lambda: ["10.8.0.2"])
    router = Router()
    router.lanaddr = "192.168.1.12"
    assert connectivity.igd_mapping_dest(router) == ""
    with pytest.raises(RuntimeError, match="No RFC1918 address"):
        connectivity.map_router(router, "Jarvis-owned")
    monkeypatch.setattr(connectivity, "lan_hosts", lambda: ["192.168.1.40"])
    assert connectivity.igd_mapping_dest(router) == "192.168.1.40"


@pytest.mark.asyncio
async def test_lan_refresh_rebuilds_when_mapped_dest_leaves_this_pc(tmp_path, monkeypatch):
    import time

    from app.mobile import connectivity, store
    from tests.test_mobile_connectivity import FakeConnection, Router

    monkeypatch.setattr(store, "data_dir", lambda: tmp_path)
    hosts = ["192.168.1.12"]
    monkeypatch.setattr(connectivity, "lan_hosts", lambda: list(hosts))
    router = Router()
    router.wan_ip = "203.0.113.8"
    monkeypatch.setattr(connectivity, "router_candidate", lambda *a, **k: (router, "203.0.113.8"))
    monkeypatch.setattr("app.mobile.natpmp.apply_natpmp", lambda *a, **k: (_ for _ in ()).throw(TimeoutError("no NAT-PMP")))
    monkeypatch.setattr("app.mobile.pcp.apply_pcp", lambda *a, **k: (_ for _ in ()).throw(TimeoutError("no PCP")))
    connection = FakeConnection()
    result = await connection.configure(True, True)
    assert result.get("mapped_lan_ip") == "192.168.1.12"
    assert result.get("wan_path") == "upnp"
    held = time.time() + 1190
    connection.report(next_renewal_at=held)
    hosts[:] = ["10.8.0.2"]
    await connection._refresh_lan_dial_endpoints()
    assert "https://10.8.0.2:4781" in connection.state["endpoints"]
    assert "https://192.168.1.12:4781" not in connection.state["endpoints"]
    assert connection.state.get("mapped_lan_ip") in {"", None}
    assert connection.state.get("wan_path") in {"", None}
    assert connection.router is None


@pytest.mark.asyncio
async def test_natpmp_is_used_when_upnp_unavailable(tmp_path, monkeypatch):
    from app.mobile import connectivity, store
    from tests.test_mobile_connectivity import FakeConnection

    monkeypatch.setattr(store, "data_dir", lambda: tmp_path)
    monkeypatch.setattr(connectivity, "lan_hosts", lambda: ["192.168.1.12"])
    monkeypatch.setattr(connectivity, "router_candidate", lambda *a, **k: (_ for _ in ()).throw(ValueError("No IGD")))
    monkeypatch.setattr("app.mobile.wan_forward.default_gateway_ipv4", lambda: "192.168.1.1")
    monkeypatch.setattr("app.mobile.natpmp.apply_natpmp", lambda gw, lan: "203.0.113.8" if gw == "192.168.1.1" else (_ for _ in ()).throw(ValueError(gw)))
    connection = FakeConnection()
    result = await connection.configure(True, True, {"wan_method": "auto"})
    assert result["state"] == "ready"
    assert result.get("wan_path") == "natpmp"
    assert "https://203.0.113.8:4781" in result["endpoints"]
    from app.mobile.gateway import identity_covers
    assert identity_covers(connection.identity, ["203.0.113.8", "192.168.1.12"])


@pytest.mark.asyncio
async def test_natpmp_uses_home_router_when_vpn_has_lower_metric(tmp_path, monkeypatch):
    from app.mobile import connectivity, store
    from app.mobile.wan_forward import parse_windows_route_print
    from tests.test_mobile_connectivity import FakeConnection

    monkeypatch.setattr(store, "data_dir", lambda: tmp_path)
    monkeypatch.setattr(connectivity, "lan_hosts", lambda: ["10.8.0.2", "192.168.1.12"])
    monkeypatch.setattr(connectivity, "router_candidate", lambda *a, **k: (_ for _ in ()).throw(ValueError("No IGD")))
    vpn_win = (
        "Network Destination        Netmask          Gateway       Interface  Metric\n"
        "          0.0.0.0          0.0.0.0         10.8.0.1         10.8.0.2      1\n"
        "          0.0.0.0          0.0.0.0      192.168.1.1     192.168.1.12    35\n"
    )
    monkeypatch.setattr("app.mobile.wan_forward.default_gateway_ipv4", lambda: parse_windows_route_print(vpn_win))
    seen: dict[str, str] = {}

    def fake_natpmp(gw, lan):
        seen["gw"] = gw
        seen["lan"] = lan
        return "203.0.113.8"

    monkeypatch.setattr("app.mobile.natpmp.apply_natpmp", fake_natpmp)
    result = await FakeConnection().configure(True, True, {"wan_method": "auto"})
    assert result.get("wan_path") == "natpmp"
    assert seen == {"gw": "192.168.1.1", "lan": "192.168.1.12"}
    assert "https://192.168.1.12:4781" in result["endpoints"]
    assert "https://10.8.0.2:4781" in result["endpoints"]


@pytest.mark.asyncio
async def test_natpmp_falls_through_to_second_rfc1918_gateway(tmp_path, monkeypatch):
    from app.mobile import connectivity, store
    from tests.test_mobile_connectivity import FakeConnection

    monkeypatch.setattr(store, "data_dir", lambda: tmp_path)
    monkeypatch.setattr(connectivity, "lan_hosts", lambda: ["10.8.0.2", "192.168.1.12"])
    monkeypatch.setattr(connectivity, "router_candidate", lambda *a, **k: (_ for _ in ()).throw(ValueError("No IGD")))
    monkeypatch.setattr("app.mobile.wan_forward.rfc1918_default_gateways", lambda: ["10.8.0.1", "192.168.1.1"])
    monkeypatch.setattr("app.mobile.wan_forward.default_gateway_ipv4", lambda: "10.8.0.1")
    seen: list[tuple[str, str]] = []

    def fake_natpmp(gw, lan):
        seen.append((gw, lan))
        if gw != "192.168.1.1":
            raise TimeoutError(f"no NAT-PMP on {gw}")
        return "203.0.113.8"

    monkeypatch.setattr("app.mobile.natpmp.apply_natpmp", fake_natpmp)
    monkeypatch.setattr("app.mobile.pcp.apply_pcp", lambda *a, **k: (_ for _ in ()).throw(TimeoutError("no PCP")))
    result = await FakeConnection().configure(True, True, {"wan_method": "auto"})
    assert result.get("wan_path") == "natpmp"
    assert seen[0] == ("10.8.0.1", "10.8.0.2")
    assert seen[-1] == ("192.168.1.1", "192.168.1.12")
    assert "https://203.0.113.8:4781" in result["endpoints"]


@pytest.mark.asyncio
async def test_natpmp_maps_rfc1918_when_cgnat_sorts_first(tmp_path, monkeypatch):
    from app.mobile import connectivity, store
    from tests.test_mobile_connectivity import FakeConnection

    monkeypatch.setattr(store, "data_dir", lambda: tmp_path)
    monkeypatch.setattr(connectivity, "lan_hosts", lambda: ["100.64.1.8", "192.168.1.12"])
    monkeypatch.setattr(connectivity, "router_candidate", lambda *a, **k: (_ for _ in ()).throw(ValueError("No IGD")))
    monkeypatch.setattr("app.mobile.wan_forward.default_gateway_ipv4", lambda: "192.168.1.1")
    seen: dict[str, str] = {}

    def fake_natpmp(gw, lan):
        seen["gw"] = gw
        seen["lan"] = lan
        return "203.0.113.8"

    monkeypatch.setattr("app.mobile.natpmp.apply_natpmp", fake_natpmp)
    connection = FakeConnection()
    result = await connection.configure(True, True, {"wan_method": "auto"})
    assert result["state"] == "ready"
    assert result.get("wan_path") == "natpmp"
    assert seen == {"gw": "192.168.1.1", "lan": "192.168.1.12"}
    assert "https://192.168.1.12:4781" in result["endpoints"]
    assert "https://100.64.1.8:4781" not in result["endpoints"]
    from app.mobile.gateway import identity_covers
    assert identity_covers(connection.identity, ["203.0.113.8", "192.168.1.12"])


@pytest.mark.asyncio
async def test_pcp_is_used_when_natpmp_unavailable(tmp_path, monkeypatch):
    from app.mobile import connectivity, store
    from tests.test_mobile_connectivity import FakeConnection

    monkeypatch.setattr(store, "data_dir", lambda: tmp_path)
    monkeypatch.setattr(connectivity, "lan_hosts", lambda: ["192.168.1.12"])
    monkeypatch.setattr(connectivity, "router_candidate", lambda *a, **k: (_ for _ in ()).throw(ValueError("No IGD")))
    monkeypatch.setattr("app.mobile.wan_forward.default_gateway_ipv4", lambda: "192.168.1.1")
    monkeypatch.setattr(
        "app.mobile.natpmp.apply_natpmp",
        lambda gw, lan: (_ for _ in ()).throw(ValueError("NAT-PMP unsupported version")),
    )
    monkeypatch.setattr(
        "app.mobile.pcp.apply_pcp",
        lambda gw, lan, nonce=None: ("198.51.100.8", bytes([0x11]) * 12) if gw == "192.168.1.1" else (_ for _ in ()).throw(ValueError(gw)),
    )
    connection = FakeConnection()
    result = await connection.configure(True, True, {"wan_method": "auto"})
    assert result["state"] == "ready"
    assert result.get("wan_path") == "pcp"
    assert "https://198.51.100.8:4781" in result["endpoints"]
    from app.mobile.gateway import identity_covers
    assert identity_covers(connection.identity, ["198.51.100.8", "192.168.1.12"])


def test_ssh_askpass_prints_secret_without_argv(tmp_path, monkeypatch):
    import subprocess

    from app.mobile import store
    from app.mobile.wan_forward import prepare_ssh_password_env

    monkeypatch.setattr(store, "data_dir", lambda: tmp_path)
    env, path = prepare_ssh_password_env("router-pass")
    assert "router-pass" not in env["SSH_ASKPASS"]
    result = subprocess.run([env["SSH_ASKPASS"]], env=env, capture_output=True, text=True, check=True)
    assert result.stdout == "router-pass"
    assert not Path(path).exists()


@pytest.mark.asyncio
async def test_apply_ssh_reverse_uses_askpass_when_password_only(tmp_path, monkeypatch):
    from app.mobile import store
    from app.mobile.wan_forward import REVERSE_TUNNEL, apply_ssh_reverse

    monkeypatch.setattr(store, "data_dir", lambda: tmp_path)
    monkeypatch.setattr("app.mobile.wan_forward.shutil.which", lambda name: "/usr/bin/ssh" if "ssh" in name else None)
    seen: dict[str, object] = {}

    async def fake_start(argv, endpoint, env=None):
        seen["argv"] = argv
        seen["endpoint"] = endpoint
        seen["env"] = env

    monkeypatch.setattr(REVERSE_TUNNEL, "start", fake_start)
    endpoint = await apply_ssh_reverse(
        {
            "ssh_host": "vpn.example.test",
            "ssh_user": "taco",
            "ssh_identity_file": "",
            "ssh_port": 22,
            "ssh_password": "vps-pass",
        }
    )
    assert endpoint == "https://vpn.example.test:4781"
    argv = list(seen["argv"])
    assert "vps-pass" not in " ".join(str(item) for item in argv)
    assert "-i" not in argv
    env = seen["env"]
    assert isinstance(env, dict)
    assert env.get("SSH_ASKPASS_REQUIRE") == "force"
    assert env.get("JARVIS_SSH_ASKPASS_FILE")


@pytest.mark.asyncio
async def test_browser_open_uses_data_dir_profile(monkeypatch, tmp_path):
    from app.tools import browser as browser_mod
    from app.tools.browser import BrowserTool

    monkeypatch.setattr("app.config.data_dir", lambda: tmp_path)

    class FakePage:
        url = "https://example.com/"

        async def title(self):
            return "Example"

        async def goto(self, url, wait_until="domcontentloaded", timeout=30000):
            self.url = url

        async def wait_for_load_state(self, state, timeout=1500):
            return None

    class FakeContext:
        pages = []
        routes = []

        async def new_page(self):
            return FakePage()

        async def close(self):
            return None

        async def route(self, pattern, handler):
            self.routes.append((pattern, handler))

    class FakeChromium:
        last_kwargs = None

        async def launch_persistent_context(self, user_dir, **kwargs):
            FakeChromium.last_kwargs = kwargs
            assert str(tmp_path / "browser-profile") == user_dir
            assert kwargs.get("accept_downloads") is True
            assert kwargs.get("downloads_path")
            ctx = FakeContext()
            ctx.pages = [FakePage()]
            FakeChromium.last_context = ctx
            return ctx

    class FakePlaywright:
        chromium = FakeChromium()

        async def stop(self):
            return None

    class FakeAsync:
        async def start(self):
            return FakePlaywright()

    monkeypatch.setattr(browser_mod, "_page", None)
    monkeypatch.setattr(browser_mod, "_context", None)
    monkeypatch.setattr(browser_mod, "_playwright", None)
    monkeypatch.setattr(browser_mod, "_browser", None)
    monkeypatch.setattr(browser_mod, "_pages", [])

    import sys
    from types import SimpleNamespace

    fake_module = SimpleNamespace(async_playwright=lambda: FakeAsync())
    monkeypatch.setitem(sys.modules, "playwright.async_api", fake_module)

    tool = BrowserTool(lambda: {"browser": {"headless": True}})
    result = await tool.execute(action="open", url="https://example.com/")
    assert result.success, result.error
    assert "Opened https://example.com/" in result.output
    assert FakeChromium.last_context.routes
    assert FakeChromium.last_context.routes[0][0] == "**/*"
    blocked = await tool.execute(action="open", url="file:///etc/passwd")
    assert not blocked.success
    await tool.execute(action="close")


@pytest.mark.asyncio
async def test_browser_opens_plugged_in_drive_without_settings_save(monkeypatch, tmp_path):
    from app.policy.computer_permissions import apply_grant, reset_computer_permission_state
    from app.tools import browser as browser_mod
    from app.tools.browser import BrowserTool, resolve_browser_open_url

    home = tmp_path / "home"
    extra = tmp_path / "E"
    home.mkdir()
    extra.mkdir()
    html = extra / "clip.html"
    html.write_text("<html><body>usb</body></html>", encoding="utf-8")
    monkeypatch.delenv("PYTEST_CURRENT_TEST", raising=False)
    monkeypatch.setattr("app.config.is_ephemeral_workspace_path", lambda path: False)
    monkeypatch.setattr("app.config.default_allowed_directories", lambda: [str(home), str(extra)])
    monkeypatch.setattr("app.policy.computer_permissions.data_dir", lambda: tmp_path)
    reset_computer_permission_state()
    apply_grant("network.internet", "deny")
    expected = resolve_browser_open_url(str(html), [str(home), str(extra)])

    class FakePage:
        url = "about:blank"

        async def goto(self, url, **kwargs):
            FakePage.url = url
            return None

        async def title(self):
            return "usb"

        async def wait_for_load_state(self, *args, **kwargs):
            return None

    async def fake_ensure(headless):
        return FakePage()

    monkeypatch.setattr(browser_mod, "_page", None)
    monkeypatch.setattr(browser_mod, "_context", None)
    monkeypatch.setattr(browser_mod, "_playwright", None)
    monkeypatch.setattr(browser_mod, "_browser", None)
    monkeypatch.setattr(browser_mod, "_pages", [])
    monkeypatch.setattr(browser_mod, "_ensure_page", fake_ensure)
    monkeypatch.setattr(browser_mod, "_allowed_override", None)
    tool = BrowserTool(lambda: {"allowed_directories": [str(home)], "browser": {"headless": True}})
    result = await tool.execute(action="open", url=str(html))
    assert result.success, result.error
    assert FakePage.url == expected


@pytest.mark.asyncio
async def test_browser_open_names_missing_chromium(monkeypatch):
    from app.tools import browser as browser_mod
    from app.tools.browser import BrowserTool

    async def boom(headless):
        raise RuntimeError("Executable doesn't exist at /missing/chromium")

    monkeypatch.setattr(browser_mod, "_page", None)
    monkeypatch.setattr(browser_mod, "_ensure_page", boom)
    tool = BrowserTool(lambda: {"browser": {"headless": True}})
    result = await tool.execute(action="open", url="https://example.com/")
    assert not result.success
    assert "Chromium is not installed" in (result.error or "")
