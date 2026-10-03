import httpx

from app.tools.web_fetch import WebFetchTool


class _Handler(httpx.AsyncBaseTransport):
    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        if request.url.path == "/echo":
            body = request.content.decode()
            return httpx.Response(200, text=f"got={body}", headers={"content-type": "text/plain"})
        if request.url.path == "/fail":
            return httpx.Response(503, text="nope")
        return httpx.Response(200, text="<html>ok</html>", headers={"content-type": "text/html"})


async def test_rejects_file_and_blank_urls():
    tool = WebFetchTool(lambda: {})
    blank = await tool.execute(url="")
    assert blank.success is False
    ftp = await tool.execute(url="ftp://example.com/a")
    assert ftp.success is False
    assert "http and https" in ftp.error
    file_url = await tool.execute(url="file:///etc/passwd")
    assert file_url.success is False


async def test_post_body_and_download(tmp_path, monkeypatch):
    tool = WebFetchTool(lambda: {"allowed_directories": [str(tmp_path)]})

    class Client(httpx.AsyncClient):
        def __init__(self, **kwargs):
            kwargs["transport"] = _Handler()
            super().__init__(**kwargs)

    monkeypatch.setattr("app.tools.web_fetch.httpx.AsyncClient", Client)
    dest = tmp_path / "page.html"
    result = await tool.execute(url="https://example.test/echo", method="POST", body='{"q":1}', path=str(dest))
    assert result.success, result.error
    assert "got=" in result.output
    assert dest.exists()
    assert '{"q":1}' in dest.read_text(encoding="utf-8")

    failed = await tool.execute(url="https://example.test/fail")
    assert failed.success is False
    assert failed.error.startswith("HTTP 503")


async def test_get_retries_connect_errors_then_succeeds(monkeypatch):
    tool = WebFetchTool(lambda: {})
    hits = {"n": 0}

    class Flaky(httpx.AsyncBaseTransport):
        async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
            hits["n"] += 1
            if hits["n"] < 3:
                raise httpx.ConnectError("temporarily unreachable", request=request)
            return httpx.Response(200, text="recovered")

    class Client(httpx.AsyncClient):
        def __init__(self, **kwargs):
            kwargs["transport"] = Flaky()
            super().__init__(**kwargs)

    monkeypatch.setattr("app.tools.web_fetch.httpx.AsyncClient", Client)
    result = await tool.execute(url="https://example.test/page")
    assert result.success, result.error
    assert hits["n"] == 3
    assert "recovered" in result.output


async def test_download_outside_sandbox_is_blocked(tmp_path, monkeypatch):
    tool = WebFetchTool(lambda: {"allowed_directories": [str(tmp_path)]})

    class Client(httpx.AsyncClient):
        def __init__(self, **kwargs):
            kwargs["transport"] = _Handler()
            super().__init__(**kwargs)

    monkeypatch.setattr("app.tools.web_fetch.httpx.AsyncClient", Client)
    result = await tool.execute(url="https://example.test/", path="/etc/passwd")
    assert result.success is False
    assert "outside allowed directories" in result.error


async def test_explicit_internet_deny_stops_web_fetch_execute(tmp_path, monkeypatch):
    from app.policy.computer_permissions import apply_grant, reset_computer_permission_state

    monkeypatch.setattr("app.policy.computer_permissions.data_dir", lambda: tmp_path)
    reset_computer_permission_state()
    apply_grant("network.internet", "deny")
    tool = WebFetchTool(lambda: {})
    result = await tool.execute(url="https://example.test/")
    assert result.success is False
    assert result.error
    assert "example.test" not in (result.output or "")


async def test_redirect_from_lan_to_wan_is_blocked(tmp_path, monkeypatch):
    from app.policy.computer_permissions import apply_grant, reset_computer_permission_state

    monkeypatch.setattr("app.policy.computer_permissions.data_dir", lambda: tmp_path)
    reset_computer_permission_state()
    apply_grant("network.internet", "deny")
    apply_grant("network.local", "always")

    class Bounce(httpx.AsyncBaseTransport):
        async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
            if request.url.host == "nas.local":
                return httpx.Response(302, headers={"location": "https://example.test/secret"})
            return httpx.Response(200, text="leaked")

    class Client(httpx.AsyncClient):
        def __init__(self, **kwargs):
            kwargs["transport"] = Bounce()
            super().__init__(**kwargs)

    monkeypatch.setattr("app.tools.web_fetch.httpx.AsyncClient", Client)
    tool = WebFetchTool(lambda: {})
    result = await tool.execute(url="http://nas.local/status")
    assert result.success is False
    assert "don't allow" in (result.error or "").lower()
    assert "leaked" not in (result.output or "")


async def test_same_scope_redirect_is_followed(monkeypatch):
    class Bounce(httpx.AsyncBaseTransport):
        async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
            if request.url.path == "/from":
                return httpx.Response(302, headers={"location": "/to"})
            return httpx.Response(200, text="landed")

    class Client(httpx.AsyncClient):
        def __init__(self, **kwargs):
            kwargs["transport"] = Bounce()
            super().__init__(**kwargs)

    monkeypatch.setattr("app.tools.web_fetch.httpx.AsyncClient", Client)
    tool = WebFetchTool(lambda: {})
    result = await tool.execute(url="https://example.test/from")
    assert result.success, result.error
    assert "landed" in result.output


async def test_binary_without_path_saves_to_downloads(tmp_path, monkeypatch):
    downloads = tmp_path / "Downloads"
    downloads.mkdir()
    monkeypatch.setattr("app.tools.owner_paths.Path.home", classmethod(lambda cls: tmp_path))

    class Pdf(httpx.AsyncBaseTransport):
        async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
            return httpx.Response(
                200,
                content=b"%PDF-1.4 fake",
                headers={"content-type": "application/pdf"},
            )

    class Client(httpx.AsyncClient):
        def __init__(self, **kwargs):
            kwargs["transport"] = Pdf()
            super().__init__(**kwargs)

    monkeypatch.setattr("app.tools.web_fetch.httpx.AsyncClient", Client)
    tool = WebFetchTool(lambda: {"allowed_directories": [str(tmp_path)]})
    result = await tool.execute(url="https://example.test/files/invoice.pdf")
    assert result.success, result.error
    dest = downloads / "invoice.pdf"
    assert dest.exists()
    assert dest.read_bytes().startswith(b"%PDF")
    assert str(dest) in result.output


async def test_html_without_path_does_not_save_file(tmp_path, monkeypatch):
    downloads = tmp_path / "Downloads"
    downloads.mkdir()
    monkeypatch.setattr("app.tools.owner_paths.Path.home", classmethod(lambda cls: tmp_path))

    class Client(httpx.AsyncClient):
        def __init__(self, **kwargs):
            kwargs["transport"] = _Handler()
            super().__init__(**kwargs)

    monkeypatch.setattr("app.tools.web_fetch.httpx.AsyncClient", Client)
    tool = WebFetchTool(lambda: {"allowed_directories": [str(tmp_path)]})
    result = await tool.execute(url="https://example.test/")
    assert result.success, result.error
    assert list(downloads.iterdir()) == []
    assert "<html>ok</html>" in result.output


async def test_save_to_extra_drive_directory(tmp_path, monkeypatch):
    extra = tmp_path / "E" / "Inbox"
    extra.mkdir(parents=True)

    class Zip(httpx.AsyncBaseTransport):
        async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
            return httpx.Response(
                200,
                content=b"PK\x03\x04",
                headers={
                    "content-type": "application/zip",
                    "content-disposition": 'attachment; filename="pack.zip"',
                },
            )

    class Client(httpx.AsyncClient):
        def __init__(self, **kwargs):
            kwargs["transport"] = Zip()
            super().__init__(**kwargs)

    monkeypatch.setattr("app.tools.web_fetch.httpx.AsyncClient", Client)
    tool = WebFetchTool(lambda: {"allowed_directories": [str(tmp_path)]})
    result = await tool.execute(url="https://example.test/pack", path=str(extra))
    assert result.success, result.error
    dest = extra / "pack.zip"
    assert dest.exists()
    assert dest.read_bytes().startswith(b"PK")


def test_suggested_fetch_name_and_downloadable():
    from app.tools.web_fetch import looks_downloadable_body, suggested_fetch_name

    assert suggested_fetch_name("https://x.test/a/b.pdf", {}) == "b.pdf"
    assert (
        suggested_fetch_name(
            "https://x.test/dl",
            {"content-disposition": 'attachment; filename="Report.PDF"'},
        )
        == "Report.PDF"
    )
    assert looks_downloadable_body("application/pdf", {}, b"%PDF")
    assert not looks_downloadable_body("text/html", {}, b"<html>")
    assert looks_downloadable_body("text/plain", {"content-disposition": "attachment; filename=x.txt"}, b"x")

