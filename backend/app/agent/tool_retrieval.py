"""Retrieve tools for the current user message instead of stuffing the catalog.

The durable tool list must not live in llama.cpp n_keep. Each turn searches
installed (and, separately, installable) capabilities that actually match the
prompt. Obsidian-backed memory is RFC-0107 — this module only looks at the
in-process registry and optional-worker catalog.
"""

from __future__ import annotations

import re
from typing import Iterable

from ..tools.registry import REGISTRY
from ..workers.install import OPTIONAL_WORKER_IDS

MAX_RETRIEVED_TOOLS = 6
_STOPWORDS = {
    "a",
    "an",
    "and",
    "the",
    "to",
    "for",
    "of",
    "on",
    "in",
    "with",
    "is",
    "it",
    "do",
    "my",
    "me",
    "please",
    "just",
    "this",
    "that",
    "check",
    "voice",
    "hello",
    "hi",
}

# Optional worker id → native tool name. Hints only; never a fake install.
_WORKER_TOOLS: dict[str, str] = {
    "browser-use": "browser_use",
    "ufo": "ufo",
    "cua": "cua",
    "open-interpreter": "open_interpreter",
    "openhands": "code_worker",
}

_TOKEN_RE = re.compile(r"[a-z0-9_]+")


def _tokens(text: str) -> set[str]:
    return {token for token in _TOKEN_RE.findall((text or "").lower()) if token not in _STOPWORDS and len(token) > 1}


def _alias_terms(name: str) -> tuple[str, ...]:
    from .tool_exposure import CAPABILITY_ALIASES

    return tuple(alias for alias, mapped in CAPABILITY_ALIASES.items() if mapped == name)


def _restricted() -> frozenset[str]:
    from .tool_exposure import RESTRICTED_TOOLS

    return RESTRICTED_TOOLS


# Distinctive prompt terms that should retrieve a tool. Generic verbs like
# "write" / "file" must not count — those bloated mixed tasks into a catalog.
_SEARCH_TERMS: dict[str, tuple[str, ...]] = {
    "office": ("excel", "spreadsheet", "powerpoint", "docx", "xlsx"),
    "browser": ("browse", "website", "webpage", "playwright"),
    "web_fetch": ("http", "https"),
    "docker": ("docker", "container", "compose"),
    "git": ("git", "github"),
    "desktop": ("pywinauto", "uia"),
    "screenshot": ("screenshot",),
    "terminal": ("powershell", "bash"),
    "python": ("python", "pytest"),
    "verify_code": ("verify_code", "pytest", "unit test", "run tests"),
    "blender": ("blender", "blend", "3d model", "stl", "glb", "mesh"),
    "openscad": ("openscad", "open scad", ".scad", "3d print"),
    "freecad": ("freecad", "cadquery"),
    "code_worker": ("openhands", "open hands"),
    "open_interpreter": ("open interpreter", "open-interpreter"),
    "browser_use": ("browser-use", "browser use"),
    "ufo": ("ufo2",),
    "cua": ("computer use",),
    "hexstrike_operator": ("hexstrike", "daybreak"),
    "mcp_call": ("mcp", "gmail", "email", "whatsapp", "imap", "smtp", "wappmcp"),
    "vault_memory": ("obsidian", "vault", "wiki", "wikilink", "backlink", "brain", "router"),
    "search_internal_references": ("jarvis", "install", "settings", "portal"),
}


def score_tool(prompt: str, name: str, description: str, extra_terms: Iterable[str] = ()) -> int:
    """Higher is a better match for this user message. Zero means ignore.

    Only the tool name, aliases, or distinctive search terms count. Description
    token overlap previously retrieved office/browser for ordinary file tasks.
    """
    del description
    text = (prompt or "").lower()
    if not text.strip():
        return 0
    tokens = _tokens(text)
    score = 0
    name_phrase = name.replace("_", " ")
    if name in tokens or (name_phrase != name and name_phrase in text):
        score += 8
    for term in extra_terms:
        cleaned = str(term or "").strip().lower()
        if not cleaned or len(cleaned) < 3:
            continue
        if " " in cleaned or "-" in cleaned:
            if cleaned in text:
                score += 6
        elif cleaned in tokens:
            score += 6
    return score


def suggest_tools_for_prompt(
    prompt: str,
    *,
    security_role: str = "",
    limit: int = MAX_RETRIEVED_TOOLS,
) -> list[str]:
    """Enabled tools that aid this message. Does not return the full catalog."""
    ranked: list[tuple[int, str]] = []
    blue = security_role == "blue-team"
    restricted = _restricted()
    for name, tool in REGISTRY.tools.items():
        if not tool.enabled:
            continue
        if name in {"request_tools", "request_capability"}:
            continue
        if name in restricted and not blue:
            continue
        extra = (*_alias_terms(name), *_SEARCH_TERMS.get(name, ()))
        score = score_tool(prompt, name, tool.description or "", extra)
        if score <= 0:
            continue
        ranked.append((score, name))
    ranked.sort(key=lambda item: (-item[0], item[1]))
    cap = max(1, int(limit or MAX_RETRIEVED_TOOLS))
    names = [name for _score, name in ranked[:cap]]
    try:
        from ..decision.policy import rerank_tools

        return rerank_tools(prompt, names)
    except Exception:
        return names


# Installable module catalog entries (RFC-0095) — searchable, not pre-stuffed in prompts.
_CATALOG_INSTALLABLE: tuple[dict[str, str], ...] = (
    {
        "entry_id": "obsidian-brain",
        "label": "Obsidian Brain patterns",
        "terms": ("obsidian", "brain", "router", "taxonomy", "linked", "vault", "wiki"),
        "download_api": "/api/modules/catalog/obsidian-brain/download",
    },
)


def _register_catalog_sources() -> None:
    from ..modules.catalog_download import register_allowlisted_source

    register_allowlisted_source(
        "obsidian-brain",
        "https://github.com/Rob-Morris/obsidian-brain",
        slug="obsidian-brain",
    )


_register_catalog_sources()


def suggest_installable_catalog(prompt: str, *, limit: int = 3) -> list[dict[str, str]]:
    """Module catalog packs that match the ask but are not integrated until downloaded."""
    text = (prompt or "").strip()
    if not text:
        return []
    tokens = _tokens(text)
    hits: list[tuple[int, dict[str, str]]] = []
    for row in _CATALOG_INSTALLABLE:
        score = 0
        terms = row.get("terms") or ()
        if isinstance(terms, str):
            terms = tuple(terms.split(","))
        for term in terms:
            cleaned = str(term).strip().lower()
            if not cleaned:
                continue
            if " " in cleaned and cleaned in text.lower():
                score += 6
            elif cleaned in tokens:
                score += 5
        if score <= 0:
            continue
        hits.append((score, dict(row)))
    hits.sort(key=lambda item: (-item[0], item[1]["entry_id"]))
    return [row for _score, row in hits[:limit]]


def suggest_installable_for_prompt(prompt: str, *, limit: int = 4) -> list[str]:
    """Optional workers that match this message and are not already retrieved."""
    text = (prompt or "").strip()
    if not text:
        return []
    hits: list[str] = []
    for worker_id in OPTIONAL_WORKER_IDS:
        tool_name = _WORKER_TOOLS.get(worker_id, worker_id.replace("-", "_"))
        tool = REGISTRY.tools.get(tool_name)
        if tool is not None and tool.enabled:
            continue
        terms = (worker_id, worker_id.replace("-", " "), tool_name.replace("_", " "), *_alias_terms(tool_name))
        if score_tool(text, tool_name, " ".join(terms), terms) <= 0:
            continue
        hits.append(worker_id)
        if len(hits) >= limit:
            break
    return hits
