import httpx
import pytest

from app.policy.network_http import gated_get, require_http_url_allowed


async def test_gated_get_blocks_denied_wan_before_request(tmp_path, monkeypatch):
    from app.policy.computer_permissions import apply_grant, reset_computer_permission_state

    monkeypatch.setattr("app.policy.computer_permissions.data_dir", lambda: tmp_path)
    reset_computer_permission_state()
    apply_grant("network.internet", "deny")
    seen = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["n"] += 1
        return httpx.Response(200, text="leaked")

    class Client(httpx.AsyncClient):
        def __init__(self, **kwargs):
            kwargs["transport"] = httpx.MockTransport(handler)
            super().__init__(**kwargs)

    monkeypatch.setattr("app.policy.network_http.httpx.AsyncClient", Client)
    with pytest.raises(PermissionError):
        await gated_get("https://evil.example/page", tool="web_fetch")
    assert seen["n"] == 0


async def test_gated_get_does_not_follow_lan_to_denied_wan(tmp_path, monkeypatch):
    from app.policy.computer_permissions import apply_grant, reset_computer_permission_state

    monkeypatch.setattr("app.policy.computer_permissions.data_dir", lambda: tmp_path)
    reset_computer_permission_state()
    apply_grant("network.internet", "deny")
    apply_grant("network.local", "always")
    seen = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request.url.host or "")
        if (request.url.host or "").startswith("192.168."):
            return httpx.Response(302, headers={"location": "https://evil.example/leak"})
        return httpx.Response(200, text="leaked")

    class Client(httpx.AsyncClient):
        def __init__(self, **kwargs):
            kwargs["transport"] = httpx.MockTransport(handler)
            super().__init__(**kwargs)

    monkeypatch.setattr("app.policy.network_http.httpx.AsyncClient", Client)
    with pytest.raises(PermissionError):
        await gated_get("http://192.168.1.10/home", tool="web_fetch")
    assert seen == ["192.168.1.10"]


def test_require_http_url_allowed_rejects_file_scheme():
    with pytest.raises(PermissionError, match="http and https"):
        require_http_url_allowed("file:///etc/passwd", tool="web_fetch")
