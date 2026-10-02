from types import SimpleNamespace

from app.tools import browser as browser_mod
from app.tools.browser import (
    BrowserTool,
    gate_browser_url,
    redirect_chain_urls,
    _goto_with_retry,
    _run_and_gate_navigation,
)


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


async def test_click_navigation_hops_lan_to_wan_are_blocked(tmp_path, monkeypatch):
    from app.policy.computer_permissions import apply_grant, reset_computer_permission_state

    monkeypatch.setattr("app.policy.computer_permissions.data_dir", lambda: tmp_path)
    reset_computer_permission_state()
    apply_grant("network.internet", "deny")
    apply_grant("network.local", "always")

    class FakePage:
        def __init__(self):
            self.url = "http://nas.local/home"
            self.gotos: list[str] = []
            self._handlers: list = []

        def on(self, event, handler):
            if event == "response":
                self._handlers.append(handler)

        def remove_listener(self, event, handler):
            self._handlers = [item for item in self._handlers if item is not handler]

        async def goto(self, url, **kwargs):
            self.gotos.append(url)
            self.url = url

        async def wait_for_load_state(self, *args, **kwargs):
            return None

    page = FakePage()

    async def click_link():
        first = SimpleNamespace(url="http://nas.local/go", redirected_from=None)
        second = SimpleNamespace(url="https://example.test/leaked", redirected_from=first)
        page.url = "https://example.test/leaked"
        response = SimpleNamespace(request=second, url="https://example.test/leaked")
        for handler in list(page._handlers):
            handler(response)

    try:
        await _run_and_gate_navigation(page, click_link(), "open")
        raise AssertionError("expected PermissionError")
    except PermissionError as exc:
        assert "don't allow" in str(exc).lower()
    assert page.gotos[-1] == "about:blank"
    assert page.url == "about:blank"


class _HopPage:
    def __init__(self, url: str = "http://nas.local/home"):
        self.url = url
        self.gotos: list[str] = []
        self._handlers: list = []

    def on(self, event, handler):
        if event == "response":
            self._handlers.append(handler)

    def remove_listener(self, event, handler):
        self._handlers = [item for item in self._handlers if item is not handler]

    async def goto(self, url, **kwargs):
        self.gotos.append(url)
        self.url = url

    async def wait_for_load_state(self, *args, **kwargs):
        return None

    def fire_wan_hop(self):
        first = SimpleNamespace(url="http://nas.local/go", redirected_from=None)
        second = SimpleNamespace(url="https://example.test/leaked", redirected_from=first)
        self.url = "https://example.test/leaked"
        response = SimpleNamespace(request=second, url="https://example.test/leaked")
        for handler in list(self._handlers):
            handler(response)


async def test_evaluate_navigation_hops_lan_to_wan_are_blocked(tmp_path, monkeypatch):
    from app.policy.computer_permissions import apply_grant, reset_computer_permission_state

    monkeypatch.setattr("app.policy.computer_permissions.data_dir", lambda: tmp_path)
    reset_computer_permission_state()
    apply_grant("network.internet", "deny")
    apply_grant("network.local", "always")
    page = _HopPage()

    async def eval_navigate():
        page.fire_wan_hop()
        return "navigated"

    try:
        await _run_and_gate_navigation(page, eval_navigate(), "open")
        raise AssertionError("expected PermissionError")
    except PermissionError as exc:
        assert "don't allow" in str(exc).lower()
    assert page.gotos[-1] == "about:blank"
    assert page.url == "about:blank"


async def test_fill_navigation_hops_lan_to_wan_are_blocked(tmp_path, monkeypatch):
    from app.policy.computer_permissions import apply_grant, reset_computer_permission_state

    monkeypatch.setattr("app.policy.computer_permissions.data_dir", lambda: tmp_path)
    reset_computer_permission_state()
    apply_grant("network.internet", "deny")
    apply_grant("network.local", "always")
    page = _HopPage()

    async def fill_and_submit():
        page.fire_wan_hop()

    try:
        await _run_and_gate_navigation(page, fill_and_submit(), "open")
        raise AssertionError("expected PermissionError")
    except PermissionError as exc:
        assert "don't allow" in str(exc).lower()
    assert page.gotos[-1] == "about:blank"
    assert page.url == "about:blank"


async def test_run_and_gate_returns_coro_result_when_url_allowed(tmp_path, monkeypatch):
    from app.policy.computer_permissions import apply_grant, reset_computer_permission_state

    monkeypatch.setattr("app.policy.computer_permissions.data_dir", lambda: tmp_path)
    reset_computer_permission_state()
    apply_grant("network.local", "always")
    apply_grant("network.internet", "deny")
    page = _HopPage()

    async def eval_title():
        return "NAS"

    assert await _run_and_gate_navigation(page, eval_title(), "open") == "NAS"
    assert page.url == "http://nas.local/home"


class _FakeContext:
    def __init__(self, pages: list | None = None):
        self.pages = list(pages or [])
        self._handlers: dict[str, list] = {}

    def on(self, event, handler):
        self._handlers.setdefault(event, []).append(handler)

    def remove_listener(self, event, handler):
        self._handlers[event] = [item for item in self._handlers.get(event, []) if item is not handler]

    def emit(self, event, payload):
        for handler in list(self._handlers.get(event, [])):
            handler(payload)


async def test_spawned_tab_wan_hop_blanks_all_pages(tmp_path, monkeypatch):
    from app.policy.computer_permissions import apply_grant, reset_computer_permission_state

    monkeypatch.setattr("app.policy.computer_permissions.data_dir", lambda: tmp_path)
    reset_computer_permission_state()
    apply_grant("network.internet", "deny")
    apply_grant("network.local", "always")
    home = _HopPage("http://nas.local/home")
    ctx = _FakeContext([home])
    home.context = ctx
    child = _HopPage("about:blank")
    child.context = ctx

    async def click_blank():
        child.url = "https://example.test/popup"
        ctx.pages.append(child)
        ctx.emit("page", child)

    try:
        await _run_and_gate_navigation(home, click_blank(), "open")
        raise AssertionError("expected PermissionError")
    except PermissionError as exc:
        assert "don't allow" in str(exc).lower()
    assert home.url == "about:blank"
    assert child.url == "about:blank"
    assert home.gotos[-1] == "about:blank"
    assert child.gotos[-1] == "about:blank"


async def test_spawned_lan_tab_becomes_active_page(tmp_path, monkeypatch):
    from app.policy.computer_permissions import apply_grant, reset_computer_permission_state
    from app.tools import browser as browser_mod

    monkeypatch.setattr("app.policy.computer_permissions.data_dir", lambda: tmp_path)
    reset_computer_permission_state()
    apply_grant("network.local", "always")
    apply_grant("network.internet", "deny")
    home = _HopPage("http://nas.local/home")
    ctx = _FakeContext([home])
    home.context = ctx
    child = _HopPage("about:blank")
    child.context = ctx
    previous = browser_mod._page
    previous_pages = list(browser_mod._pages)
    browser_mod._page = home
    browser_mod._pages = [home]
    try:

        async def click_lan_popup():
            child.url = "http://nas.local/share"
            ctx.pages.append(child)
            ctx.emit("page", child)
            return "ok"

        assert await _run_and_gate_navigation(home, click_lan_popup(), "open") == "ok"
        assert browser_mod._page is child
        assert child in browser_mod._pages
        assert child.url == "http://nas.local/share"
    finally:
        browser_mod._page = previous
        browser_mod._pages = previous_pages
