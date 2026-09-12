"""Docs-first help assistant (RFC-0078)."""

from __future__ import annotations

import uuid
from collections import defaultdict
from typing import Any

from ..agent.docs_first_grounding import (
    DocsFirstContext,
    GroundingSnippet,
    maybe_docs_first,
    search_internal_references,
)
from ..inference.manager import MANAGER
from ..inference.profiles import profile_gguf, resolve_profile
from ..providers.base import ChatMessage
from ..trajectories.redaction import redact_string
from .topics import get_topic, list_topics, topic_as_dict
from .web_fallback import fetch_public_page, search_public_web

HELP_SYSTEM = """You are Jarvis Help, a small on-device assistant for the owner.
Answer only from the local documentation snippets when they cover the question.
Cite source paths in square brackets. If local docs are incomplete, you may use
the secondary web notes — say that those came from the public web.
Never invent Jarvis settings, ports, or file paths. Never echo private keys,
tokens, or passwords. Keep answers short and practical."""

_conversations: dict[str, list[ChatMessage]] = defaultdict(list)
WEAK_LOCAL_HITS = 1


def reset_help_conversations() -> None:
    _conversations.clear()


def _topic_snippets(query: str) -> list[GroundingSnippet]:
    terms = {token.lower() for token in query.split() if len(token) > 2}
    snippets: list[GroundingSnippet] = []
    for topic in list_topics():
        hay = " ".join((topic.id, topic.title, topic.summary, topic.body, " ".join(topic.keywords))).lower()
        if terms and not any(term in hay for term in terms):
            continue
        snippets.append(
            GroundingSnippet(
                citation_id=f"topic-{topic.id}",
                source_path=f"help://{topic.id}",
                text=f"{topic.title}\n{topic.body}",
            )
        )
    return snippets[:3]


def retrieve_local_docs(question: str) -> list[GroundingSnippet]:
    snippets: list[GroundingSnippet] = []
    try:
        grounded = maybe_docs_first(DocsFirstContext(user_message=question))
        if grounded and grounded.snippets:
            snippets = list(grounded.snippets)
    except Exception:
        snippets = []
    if not snippets:
        try:
            snippets = search_internal_references(question, max_results=5)
        except Exception:
            snippets = []
    seen = {item.source_path for item in snippets}
    for extra in _topic_snippets(question):
        if extra.source_path not in seen:
            snippets.append(extra)
            seen.add(extra.source_path)
    return snippets[:6]


def _local_is_weak(snippets: list[GroundingSnippet]) -> bool:
    if len(snippets) < WEAK_LOCAL_HITS:
        return True
    combined = " ".join(item.text for item in snippets)
    return len(combined.strip()) < 80


async def _web_notes(question: str) -> list[dict[str, str]]:
    hits = await search_public_web(question)
    notes: list[dict[str, str]] = []
    for hit in hits:
        body = await fetch_public_page(hit["url"])
        notes.append(
            {
                "title": hit["title"],
                "url": hit["url"],
                "text": redact_string(body)[:1200] if body else "",
            }
        )
    return notes


def _extractive_answer(question: str, snippets: list[GroundingSnippet], web: list[dict[str, str]]) -> str:
    if snippets:
        parts = ["From the local docs:"]
        for item in snippets[:3]:
            parts.append(f"[{item.citation_id}] {item.source_path}\n{item.text[:500]}")
        if web:
            parts.append("Secondary public-web notes were also retrieved; prefer the local citations.")
        return "\n\n".join(parts)
    if web:
        lines = ["Local docs did not cover this. Secondary public-web notes:"]
        for note in web:
            lines.append(f"- {note['title']} ({note['url']})\n{note['text'][:400]}")
        return "\n\n".join(lines)
    return (
        "I could not find this in the local Jarvis docs, and the secondary web lookup "
        "did not return usable notes. Try the Guides tab (phone pairing, custom models, "
        "swarms, autonomy) or open README.md / docs/INSTALL.md on this PC."
    )


def _help_profile_name(settings) -> str:
    for name in ("bootstrap", "fast", "balanced"):
        profile = resolve_profile(name)
        if profile_gguf(profile).exists():
            return profile.name
    return settings.inference.profile


def _prompt_messages(question: str, snippets: list[GroundingSnippet], web: list[dict[str, str]]) -> list[ChatMessage]:
    blocks = [HELP_SYSTEM, "Local documentation (always consult first):"]
    if snippets:
        for item in snippets:
            blocks.append(f"[{item.citation_id}] {item.source_path}\n{item.text}")
    else:
        blocks.append("(no local hits)")
    if web:
        blocks.append("Secondary public-web notes:")
        for note in web:
            blocks.append(f"{note['title']} — {note['url']}\n{note['text']}")
    blocks.append(f"Owner question: {question}")
    return [ChatMessage(role="system", content="\n\n".join(blocks)), ChatMessage(role="user", content=question)]


async def answer_help(question: str, *, conversation_id: str | None = None) -> dict[str, Any]:
    cleaned = (question or "").strip()
    if not cleaned:
        return {"ok": False, "error": "message is required"}

    cid = conversation_id or str(uuid.uuid4())
    snippets = retrieve_local_docs(cleaned)
    web: list[dict[str, str]] = []
    used_web = False
    if _local_is_weak(snippets):
        web = await _web_notes(cleaned)
        used_web = bool(web)

    text = ""
    used_model = False
    model_name = ""
    try:
        from ..config import load_settings

        settings = load_settings()
        if MANAGER.provider and MANAGER.state.loaded:
            used_model = True
            model_name = MANAGER.state.alias or MANAGER.state.profile or "loaded"
            reply = await MANAGER.chat(_prompt_messages(cleaned, snippets, web))
            text = (getattr(reply, "content", None) or "").strip()
        else:
            model_name = _help_profile_name(settings)
    except Exception:
        text = ""

    if not text:
        text = _extractive_answer(cleaned, snippets, web)

    _conversations[cid].append(ChatMessage(role="user", content=cleaned))
    _conversations[cid].append(ChatMessage(role="assistant", content=text))
    return {
        "ok": True,
        "conversation_id": cid,
        "text": text,
        "used_model": used_model,
        "help_profile": model_name,
        "used_web": used_web,
        "citations": [
            {"id": item.citation_id, "path": item.source_path}
            for item in snippets
        ],
        "web": [{"title": note["title"], "url": note["url"]} for note in web],
    }


def help_status() -> dict[str, Any]:
    from ..config import load_settings
    from ..inference.profiles import preferred_startup_profile, qwen38_9b_profile

    settings = load_settings()
    extra = qwen38_9b_profile()
    return {
        "docs_first": True,
        "web_fallback": True,
        "help_profile": _help_profile_name(settings),
        "startup_profile": preferred_startup_profile(settings.inference.profile),
        "qwen38_9b_installed": extra is not None,
        "qwen38_9b_path": extra.absolute_path if extra else "",
        "topics": [topic_as_dict(topic) for topic in list_topics()],
    }


def get_help_conversation(conversation_id: str) -> list[ChatMessage]:
    return list(_conversations.get(conversation_id, []))
