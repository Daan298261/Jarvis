import httpx

from app.help.assistant import answer_help, help_status, reset_help_conversations, retrieve_local_docs
from app.help.topics import get_topic, list_topics


def test_help_topics_include_distinguished_features():
    ids = {topic.id for topic in list_topics()}
    assert {"phone-pairing", "custom-models", "swarms", "autonomy"} <= ids
    pairing = get_topic("phone-pairing")
    assert pairing is not None
    assert pairing.href == "/phone"


def test_retrieve_local_docs_hits_help_topics():
    snippets = retrieve_local_docs("How do I pair my phone with Jarvis?")
    assert snippets
    joined = " ".join(item.source_path + " " + item.text for item in snippets).lower()
    assert "pair" in joined or "phone" in joined


def test_help_status_is_docs_first():
    status = help_status()
    assert status["docs_first"] is True
    assert status["web_fallback"] is True
    assert any(topic["id"] == "custom-models" for topic in status["topics"])


async def test_help_chat_answers_from_docs_without_web(monkeypatch):
    reset_help_conversations()

    async def _fail_web(_query: str, **_kwargs):
        raise AssertionError("web fallback should not run when local docs hit")

    monkeypatch.setattr("app.help.assistant.search_public_web", _fail_web)
    result = await answer_help("How do I pair the Android phone companion?")
    assert result["ok"] is True
    assert result["used_web"] is False
    assert result["citations"]
    assert "pair" in result["text"].lower() or "phone" in result["text"].lower()


async def test_help_chat_uses_web_when_local_empty(monkeypatch):
    reset_help_conversations()
    monkeypatch.setattr("app.help.assistant.retrieve_local_docs", lambda _q: [])

    async def _search(query: str, **_kwargs):
        assert "obscure-unrelated-query-xyz" in query
        return [{"title": "Example", "url": "https://example.test/help"}]

    async def _fetch(url: str, **_kwargs):
        assert url.startswith("https://")
        return "Public note about the topic."

    monkeypatch.setattr("app.help.assistant.search_public_web", _search)
    monkeypatch.setattr("app.help.assistant.fetch_public_page", _fetch)
    result = await answer_help("obscure-unrelated-query-xyz")
    assert result["ok"] is True
    assert result["used_web"] is True
    assert result["web"][0]["url"] == "https://example.test/help"
    assert "Public note" in result["text"]


async def test_help_web_search_honors_internet_deny(tmp_path, monkeypatch):
    from app.help.web_fallback import search_public_web
    from app.policy.computer_permissions import apply_grant, reset_computer_permission_state

    monkeypatch.setattr("app.policy.computer_permissions.data_dir", lambda: tmp_path)
    reset_computer_permission_state()
    apply_grant("network.internet", "deny")
    seen = {"n": 0}

    def _count(request: httpx.Request) -> httpx.Response:
        seen["n"] += 1
        return httpx.Response(200, text='<a class="result__a" href="https://evil.example">Nope</a>')

    class Client(httpx.AsyncClient):
        def __init__(self, **kwargs):
            kwargs["transport"] = httpx.MockTransport(_count)
            super().__init__(**kwargs)

    monkeypatch.setattr("app.policy.network_http.httpx.AsyncClient", Client)
    hits = await search_public_web("obscure-unrelated-query-xyz")
    assert hits == []
    assert seen["n"] == 0


async def test_help_page_hop_does_not_follow_denied_wan(tmp_path, monkeypatch):
    from app.help.web_fallback import fetch_public_page
    from app.policy.computer_permissions import apply_grant, reset_computer_permission_state

    monkeypatch.setattr("app.policy.computer_permissions.data_dir", lambda: tmp_path)
    reset_computer_permission_state()
    apply_grant("network.internet", "deny")
    apply_grant("network.local", "always")
    seen = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request.url.host or "")
        if (request.url.host or "").startswith("192.168."):
            return httpx.Response(302, headers={"location": "https://evil.example/docs"})
        return httpx.Response(200, text="<html>leaked secret</html>")

    class Client(httpx.AsyncClient):
        def __init__(self, **kwargs):
            kwargs["transport"] = httpx.MockTransport(handler)
            super().__init__(**kwargs)

    monkeypatch.setattr("app.policy.network_http.httpx.AsyncClient", Client)
    body = await fetch_public_page("http://192.168.1.10/docs")
    assert body == ""
    assert "evil.example" not in seen
