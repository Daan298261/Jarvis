"""Owner-machine workspace, LAN cyberdefense, WAN companion, and internet browse."""
from __future__ import annotations

import os
from pathlib import Path

import pytest

from app.config import LOCAL_NETWORK_SCOPE, default_allowed_directories
from app.mobile.wan_forward import (
    gateway_ssh_argv,
    openwrt_redirect_script,
    redact_wan_config,
    reverse_tunnel_argv,
)
from app.tools.safety import resolve_allowed_path


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


def test_wan_config_redacts_gateway_password():
    public = redact_wan_config({"gateway_password": "secret", "ssh_host": "vpn.example.test"})
    assert "secret" not in str(public)
    assert public["gateway_password_set"] is True
    assert public["ssh_host"] == "vpn.example.test"


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
    assert "https://vpn.example.test:4781" in result["endpoints"]
    assert result.get("wan_path") == "ssh_reverse"


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
    await tool.execute(action="close")
