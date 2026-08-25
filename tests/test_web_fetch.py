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
