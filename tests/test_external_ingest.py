import json
from unittest.mock import AsyncMock, MagicMock

import httpx
import pytest

from app.ingest.adapters.instagram import InstagramAdapter
from app.ingest.adapters.base import IngestContext
from app.ingest.links import extract_repo_urls, extract_urls
from app.ingest.orchestrator import ingest_url
from app.ingest.platform import detect_platform
from app.ingest.redaction import redact_text
from app.ingest.schema import ExternalContentArtifact
from app.tools.external_ingest import ExternalIngestTool


INSTAGRAM_CAROUSEL_HTML = """
<html><head>
<meta property="og:title" content="Carousel post" />
<meta property="og:description" content="See https://github.com/Daan298261/Jarvis for code" />
<script>window._sharedData = {
  "entry_data": {
    "PostPage": [{
      "graphql": {
        "shortcode_media": {
          "__typename": "GraphSidecar",
          "username": "jarvis_demo",
          "edge_sidecar_to_children": {
            "edges": [
              {"node": {"display_url": "https://cdn.example/1.jpg", "__typename": "GraphImage"}},
              {"node": {"display_url": "https://cdn.example/2.jpg", "__typename": "GraphImage"}},
              {"node": {"video_url": "https://cdn.example/reel.mp4", "__typename": "GraphVideo"}}
            ]
          },
          "edge_media_to_caption": {"edges": [{"node": {"text": "Repo: https://github.com/Daan298261/Jarvis"}}]}
        }
      }
    }]
  }
};</script>
</head><body></body></html>
"""


class _InstagramHandler(httpx.AsyncBaseTransport):
    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        if "oembed" in str(request.url):
            return httpx.Response(404, text="not found")
        if "instagram.com" in str(request.url.host or ""):
            return httpx.Response(200, text=INSTAGRAM_CAROUSEL_HTML, headers={"content-type": "text/html"})
        return httpx.Response(404, text="missing")


def test_detect_platform():
    assert detect_platform("https://www.instagram.com/p/ABC123/") == "instagram"
    assert detect_platform("https://tiktok.com/@user/video/1") == "tiktok"
    assert detect_platform("https://x.com/user/status/1") == "x"
    assert detect_platform("https://youtu.be/abc") == "youtube"
    assert detect_platform("https://github.com/org/repo") == "github"
    assert detect_platform("https://example.com/page") == "web"


def test_extract_urls_and_repo_urls():
    text = "Check https://github.com/Daan298261/Jarvis and https://example.com/docs"
    links = extract_urls(text)
    assert "https://github.com/Daan298261/Jarvis" in links
    assert "https://example.com/docs" in links
    repos = extract_repo_urls(text)
    assert repos == ["https://github.com/Daan298261/Jarvis"]


def test_redact_secrets():
    raw = "sessionid=abc123; Authorization: Bearer secret-token"
    cleaned = redact_text(raw)
    assert "abc123" not in cleaned
    assert "secret-token" not in cleaned
    assert "REDACTED" in cleaned


async def test_instagram_carousel_http_parsing(monkeypatch):
    class Client(httpx.AsyncClient):
        def __init__(self, **kwargs):
            kwargs["transport"] = _InstagramHandler()
            super().__init__(**kwargs)

    monkeypatch.setattr("app.ingest.adapters.generic.httpx.AsyncClient", Client)
    monkeypatch.setattr("app.ingest.adapters.instagram.httpx.AsyncClient", Client)

    adapter = InstagramAdapter()
    ctx = IngestContext(url="https://www.instagram.com/p/ABC123/", platform="instagram")
    artifact = await adapter.resolve_http(ctx)
    assert artifact is not None
    assert artifact.source == "instagram"
    assert len(artifact.images) == 2
    assert artifact.video == ["https://cdn.example/reel.mp4"]
    assert artifact.author == "jarvis_demo"
    assert "https://github.com/Daan298261/Jarvis" in artifact.links


async def test_fallback_to_provider_when_http_fails(monkeypatch):
    class FailClient(httpx.AsyncClient):
        def __init__(self, **kwargs):
            super().__init__(transport=httpx.MockTransport(self._handler), **kwargs)

        @staticmethod
        def _handler(request: httpx.Request) -> httpx.Response:
            if request.url.path.endswith("/resolve"):
                payload = {
                    "title": "Provider title",
                    "caption": "From provider",
                    "images": ["https://cdn.example/a.jpg", "https://cdn.example/b.jpg"],
                }
                return httpx.Response(200, json=payload)
            return httpx.Response(500, text="fail")

    monkeypatch.setattr("app.ingest.adapters.generic.httpx.AsyncClient", FailClient)
    monkeypatch.setattr("app.ingest.adapters.instagram.httpx.AsyncClient", FailClient)
    monkeypatch.setenv("JARVIS_INGEST_PROVIDER_INSTAGRAM", "https://resolver.test/resolve")

    result = await ingest_url("https://www.instagram.com/p/XYZ/")
    assert result["source"] == "instagram"
    assert result["metadata"]["tier"] == "provider"
    assert len(result["images"]) == 2
    assert "provider" in result["metadata"]["tiers_attempted"]


async def test_fallback_to_browser_when_http_and_provider_fail(monkeypatch):
    class FailClient(httpx.AsyncClient):
        def __init__(self, **kwargs):
            super().__init__(transport=httpx.MockTransport(lambda r: httpx.Response(500, text="fail")), **kwargs)

    monkeypatch.setattr("app.ingest.adapters.generic.httpx.AsyncClient", FailClient)
    monkeypatch.delenv("JARVIS_INGEST_PROVIDER_URL", raising=False)
    monkeypatch.delenv("JARVIS_INGEST_PROVIDER_INSTAGRAM", raising=False)

    browser = AsyncMock()
    browser.execute = AsyncMock(
        side_effect=[
            MagicMock(success=True, output="opened"),
            MagicMock(
                success=True,
                output=json.dumps(
                    {
                        "title": "Browser title",
                        "text": "Browser body https://example.com/more",
                        "metas": {"og:description": "caption text"},
                        "images": ["https://cdn.example/browser.jpg"],
                        "videos": [],
                    }
                ),
            ),
        ]
    )

    result = await ingest_url("https://example.com/post", browser_tool=browser)
    assert result["metadata"]["tier"] == "browser"
    assert result["title"] == "Browser title"
    assert result["images"] == ["https://cdn.example/browser.jpg"]
    assert "https://example.com/more" in result["links"]
    assert browser.execute.await_count == 2


async def test_fallback_to_browser_use_last(monkeypatch):
    class FailClient(httpx.AsyncClient):
        def __init__(self, **kwargs):
            super().__init__(transport=httpx.MockTransport(lambda r: httpx.Response(500, text="fail")), **kwargs)

    monkeypatch.setattr("app.ingest.adapters.generic.httpx.AsyncClient", FailClient)

    browser = AsyncMock()
    browser.execute = AsyncMock(return_value=MagicMock(success=False, error="browser down"))

    browser_use = AsyncMock()
    browser_use.execute = AsyncMock(
        return_value=MagicMock(
            success=True,
            output="Found image https://cdn.example/use.jpg and https://github.com/org/repo",
        )
    )

    result = await ingest_url(
        "https://example.com/hard",
        browser_tool=browser,
        browser_use_tool=browser_use,
    )
    assert result["metadata"]["tier"] == "browser_use"
    assert "https://cdn.example/use.jpg" in result["images"]
    assert "https://github.com/org/repo" in result["research"]["repo_urls"]


async def test_external_ingest_tool_wraps_orchestrator(monkeypatch):
    artifact = ExternalContentArtifact(
        source="web",
        url="https://example.com",
        title="Hello",
        text="Hello",
    )

    async def _fake_ingest(url, **kwargs):
        from app.ingest.hooks import finalize_artifact

        return finalize_artifact(artifact, ["http"])

    monkeypatch.setattr("app.ingest.orchestrator.ingest_url", _fake_ingest)
    tool = ExternalIngestTool(lambda: {"browser": {"headless": True}})
    result = await tool.execute(url="https://example.com")
    assert result.success is True
    assert result.data["title"] == "Hello"


async def test_ingest_raises_when_all_tiers_fail(monkeypatch):
    class FailClient(httpx.AsyncClient):
        def __init__(self, **kwargs):
            super().__init__(transport=httpx.MockTransport(lambda r: httpx.Response(500, text="fail")), **kwargs)

    monkeypatch.setattr("app.ingest.adapters.generic.httpx.AsyncClient", FailClient)

    browser = AsyncMock()
    browser.execute = AsyncMock(return_value=MagicMock(success=False))
    browser_use = AsyncMock()
    browser_use.execute = AsyncMock(return_value=MagicMock(success=False))

    from app.ingest.orchestrator import IngestError

    with pytest.raises(IngestError) as exc:
        await ingest_url("https://example.com/none", browser_tool=browser, browser_use_tool=browser_use)
    assert "http" in exc.value.tiers_attempted
    assert "browser_use" in exc.value.tiers_attempted
