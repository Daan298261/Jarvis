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
    printed = "Network Destination        Netmask          Gateway       Interface  Metric\n          0.0.0.0          0.0.0.0      192.168.0.1     192.168.0.12     25\n"
    assert parse_windows_route_print(printed) == "192.168.0.1"
    assert resolved_gateway_user({"gateway_profile": "openwrt_uci"}) == "root"
    assert resolved_gateway_user({"gateway_username": "admin"}) == "admin"
    assert resolved_gateway_host({"gateway_host": "192.168.1.1"}) == "192.168.1.1"


def test_wan_origin_rejects_lan_and_accepts_public_hosts():
    assert is_public_dial_host("vpn.example.test")
    assert is_public_dial_host("8.8.8.8")
    assert not is_public_dial_host("192.168.1.1")
    assert not is_public_dial_host("router.local")
    with pytest.raises(ValueError):
        companion_wan_origin("192.168.1.1")
    assert companion_wan_origin("home.example.test") == "https://home.example.test:4781"
    public = redact_wan_config({"gateway_password": "secret", "ssh_host": "vpn.example.test"})
    assert "secret" not in str(public)
    assert public["gateway_password_set"] is True
    assert public["ssh_host"] == "vpn.example.test"


def test_mapping_lan_ipv4_skips_cgnat_and_prefers_gateway_subnet():
    assert is_rfc1918_ipv4("192.168.1.12")
    assert is_rfc1918_ipv4("10.0.0.5")
    assert not is_rfc1918_ipv4("100.64.1.8")
    assert not is_rfc1918_ipv4("8.8.8.8")
    assert mapping_lan_ipv4(["100.64.1.8", "192.168.1.12"], "192.168.1.1") == "192.168.1.12"
    assert mapping_lan_ipv4(["10.0.0.5", "192.168.1.12"], "192.168.1.1") == "192.168.1.12"
    assert mapping_lan_ipv4(["10.0.0.5", "192.168.0.9"], "192.168.1.1") == "192.168.0.9"
    assert mapping_lan_ipv4(["100.64.1.8"], "192.168.1.1") == ""
    assert mapping_lan_ipv4([], "192.168.1.1") == ""
    assert mapping_lan_ipv4(["192.168.1.12", "10.0.0.5"], "") == "192.168.1.12"


def test_lan_hosts_drops_cgnat(monkeypatch):
    from app.mobile import connectivity

    monkeypatch.setattr("app.api.mobile._lan_hosts", lambda: ["100.64.1.8", "8.8.8.8", "192.168.1.12"])
    assert connectivity.lan_hosts() == ["192.168.1.12"]


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
    monkeypatch.setattr(
        "app.mobile.natpmp.apply_natpmp",
        lambda *a, **k: natpmp_hits.__setitem__("n", natpmp_hits["n"] + 1) or (_ for _ in ()).throw(TimeoutError("should skip")),
    )
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
    assert natpmp_hits["n"] == 0
    assert "https://198.51.100.8:4781" not in result["endpoints"]
    assert any(endpoint == "https://vpn.example.test:4781" for endpoint in result["endpoints"])
    assert router.deleted == [(4781, "TCP")]
    assert "double nat" in (result.get("limitation") or "").lower()


@pytest.mark.asyncio
async def test_gateway_ssh_does_not_advertise_private_router_as_wan(tmp_path, monkeypatch):
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
    assert any(endpoint == "https://home.example.test:4781" for endpoint in result["endpoints"])
    from app.mobile.gateway import identity_covers
    assert identity_covers(connection.identity, ["home.example.test", "192.168.1.12"])


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
        lambda gw, lan, nonce=None: ("198.51.100.8", b"\x11" * 12) if gw == "192.168.1.1" else (_ for _ in ()).throw(ValueError(gw)),
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
async def test_browser_open_uses_data_dir_profile(monkeypatch, tmp_path):
    from app.tools import browser as browser_mod
    from app.tools.browser import BrowserTool

    monkeypatch.setattr(browser_mod, "data_dir", lambda: tmp_path)

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

        async def new_page(self):
            return FakePage()

        async def close(self):
            return None

    class FakeChromium:
        async def launch_persistent_context(self, user_dir, **kwargs):
            assert str(tmp_path / "browser-profile") == user_dir
            ctx = FakeContext()
            ctx.pages = [FakePage()]
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
    blocked = await tool.execute(action="open", url="file:///etc/passwd")
    assert not blocked.success
    await tool.execute(action="close")


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
