"""Owner-machine workspace, LAN cyberdefense, companion LAN routing, and internet browse."""
from __future__ import annotations

import os
from pathlib import Path

import pytest

from app.config import LOCAL_NETWORK_SCOPE, default_allowed_directories
from app.mobile.wan_forward import (
    is_rfc1918_ipv4,
    mapping_lan_ipv4,
    parse_proc_net_route,
    parse_windows_route_print,
)
from app.tools.safety import resolve_allowed_path
from app.tools.owner_paths import direct_child_env, python_child_env


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


def test_direct_child_env_drops_proxy_keeps_path(monkeypatch):
    monkeypatch.setenv("HTTP_PROXY", "http://10.8.0.1:8080")
    monkeypatch.setenv("https_proxy", "http://10.8.0.1:3128")
    monkeypatch.setenv("ALL_PROXY", "socks5://10.8.0.1:1080")
    monkeypatch.setenv("NO_PROXY", "*")
    monkeypatch.setenv("JARVIS_HOME", "/tmp/jarvis")
    env = direct_child_env()
    assert "HTTP_PROXY" not in env
    assert "https_proxy" not in env
    assert "ALL_PROXY" not in env
    assert "NO_PROXY" not in env
    assert env["JARVIS_HOME"] == "/tmp/jarvis"
    kept = direct_child_env({"PATH": "/usr/bin", "http_proxy": "http://proxy.example:8080", "HOME": "/home/taco"})
    assert "http_proxy" not in kept
    assert kept["PATH"] == "/usr/bin"
    assert kept["HOME"] == "/home/taco"
    assert "lan_ssh.py" in (env.get("RSYNC_RSH") or "")
    assert env["RSYNC_RSH"] == kept["RSYNC_RSH"]


def test_python_child_env_uses_lan_proxy_not_vpn(monkeypatch):
    monkeypatch.setenv("HTTP_PROXY", "http://10.8.0.1:8080")
    monkeypatch.setenv("https_proxy", "http://10.8.0.1:3128")
    env = python_child_env()
    assert env["HTTP_PROXY"].startswith("http://127.0.0.1:")
    assert env["HTTPS_PROXY"] == env["HTTP_PROXY"]
    assert env["http_proxy"] == env["HTTP_PROXY"]
    assert "10.8.0.1" not in env["HTTP_PROXY"]
    assert "lan_python_site" in env["PYTHONPATH"]
    from app.config import repo_root

    assert str(repo_root() / "backend") in env["PYTHONPATH"].split(os.pathsep)


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


def test_default_gateway_parsers():
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
    monkeypatch.setattr(
        "app.mobile.wan_forward.socket.getaddrinfo",
        lambda *a, **k: [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("127.0.0.1", 80))],
    )
    assert lan_http_bind_for_url("http://wsl.localhost:3000/") == ""
    assert lan_http_bind_for_url("http://host.docker.internal:8080/") == ""


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
    assert FakeChromium.last_kwargs["proxy"] == {"server": "direct://"}
    assert "--no-proxy-server" in FakeChromium.last_kwargs["args"]
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
