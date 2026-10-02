from types import SimpleNamespace

from app.tools import browser as browser_mod
from app.tools.browser import BrowserTool, gate_browser_url, redirect_chain_urls, _goto_with_retry


async def test_browser_close_resets_page_list():
    browser_mod._page = object()
    browser_mod._pages = [object()]
    browser_mod._context = None
    browser_mod._playwright = None
    browser_mod._browser = None
    result = await BrowserTool(lambda: {"browser": {"headless": True}}).execute(action="close")
    assert result.success is True
    assert browser_mod._page is None
    assert browser_mod._pages == []
    assert browser_mod._browser is None


def test_redirect_chain_urls_oldest_first():
    first = SimpleNamespace(url="http://nas.local/status", redirected_from=None)
    second = SimpleNamespace(url="https://example.test/secret", redirected_from=first)
    response = SimpleNamespace(request=second)
    assert redirect_chain_urls(response, "https://example.test/secret") == [
        "http://nas.local/status",
        "https://example.test/secret",
    ]


def test_gate_browser_url_denies_wan_when_internet_denied(tmp_path, monkeypatch):
    from app.policy.computer_permissions import apply_grant, reset_computer_permission_state

    monkeypatch.setattr("app.policy.computer_permissions.data_dir", lambda: tmp_path)
    reset_computer_permission_state()
    apply_grant("network.internet", "deny")
    apply_grant("network.local", "always")
    assert gate_browser_url("http://nas.local/status") is None
    blocked = gate_browser_url("https://example.test/secret")
    assert blocked
    assert "don't allow" in blocked.lower()


async def test_goto_blocks_lan_to_wan_redirect_and_leaves_blank(tmp_path, monkeypatch):
    from app.policy.computer_permissions import apply_grant, reset_computer_permission_state

    monkeypatch.setattr("app.policy.computer_permissions.data_dir", lambda: tmp_path)
    reset_computer_permission_state()
    apply_grant("network.internet", "deny")
    apply_grant("network.local", "always")

    class FakePage:
        def __init__(self):
            self.url = "about:blank"
            self.gotos: list[str] = []

        async def goto(self, url, **kwargs):
            self.gotos.append(url)
            if url == "about:blank":
                self.url = url
                return None
            first = SimpleNamespace(url="http://nas.local/status", redirected_from=None)
            second = SimpleNamespace(url="https://example.test/secret", redirected_from=first)
            self.url = "https://example.test/secret"
            return SimpleNamespace(request=second)

        async def wait_for_load_state(self, *args, **kwargs):
            return None

    page = FakePage()
    try:
        await _goto_with_retry(page, "http://nas.local/status")
        raise AssertionError("expected PermissionError")
    except PermissionError as exc:
        assert "don't allow" in str(exc).lower()
    assert page.gotos[-1] == "about:blank"
    assert page.url == "about:blank"
