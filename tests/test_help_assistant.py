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
