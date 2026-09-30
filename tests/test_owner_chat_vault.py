"""RFC-0107: owner /api/owner/chat path must use compose_turn_working_set."""

from __future__ import annotations

import pytest

from app.memory.obsidian_vault import (
    bind_vault,
    index_file,
    query_looks_vault_relevant,
    reset_vault_store,
    stop_watch,
    unbind_vault,
)
from app.persona.owner_chat import compose_owner_turn_messages, _owner_messages


@pytest.fixture
def bound_vault(tmp_path, monkeypatch):
    data_root = tmp_path / "obsidian-meta"
    vault_root = tmp_path / "vault"
    data_root.mkdir(parents=True, exist_ok=True)
    vault_root.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr("app.memory.obsidian_vault.data_dir", lambda: data_root)
    reset_vault_store()
    bind_vault(str(vault_root), init_layout=True)
    stop_watch()
    (vault_root / "Projects" / "jarvis.md").write_text(
        "# Jarvis\n\nkubernetes deploy uses rollout strategy alpha.\n",
        encoding="utf-8",
    )
    index_file("Projects/jarvis.md")
    yield vault_root
    stop_watch()
    unbind_vault()
    reset_vault_store()


@pytest.mark.asyncio
async def test_owner_messages_include_vault_excerpt_when_bound(bound_vault):
    messages = await _owner_messages("cid", "how does kubernetes deploy work for jarvis")
    bodies = [m.content or "" for m in messages if m.role == "system"]
    joined = "\n".join(bodies)
    assert "Linked vault memory" in joined
    assert "kubernetes" in joined.lower()
    # Provenance format from composer (path#heading + hash), not skip-if-empty soft path.
    assert "Projects/jarvis.md#" in joined or "jarvis.md#" in joined
    assert "hash:" in joined


@pytest.mark.asyncio
async def test_owner_messages_skip_vault_when_unbound():
    reset_vault_store()
    messages = await _owner_messages("cid", "hello")
    assert not any("Linked vault memory" in (m.content or "") for m in messages)


@pytest.mark.asyncio
async def test_owner_chat_path_uses_compose_turn_working_set(bound_vault):
    """Live owner chat builder must go through compose — vault hits + installable search."""
    assert query_looks_vault_relevant("what is our project kubernetes deploy decision")
    messages, working = await compose_owner_turn_messages(
        "cid-owner",
        "what is our project kubernetes deploy decision about the obsidian brain vault",
    )
    assert working.vault_block, "empty-by-construction is a fail on the owner path"
    assert working.vault_hits
    hit = working.vault_hits[0]
    assert hit.rel_path and hit.content_hash and hit.heading
    system = "\n".join(m.content or "" for m in messages if m.role == "system")
    assert hit.rel_path in system
    assert hit.content_hash[:12] in system
    assert "provenance:" in system or "hash:" in system
    # Per-ask installable search still runs on owner Q&A (schemas may be withheld).
    assert working.installable_offers
    assert any("obsidian-brain" in o.entry_id for o in working.installable_offers)
    assert any("/api/modules/catalog/" in (o.download_api or "") for o in working.installable_offers)
    assert "Installable capabilities" in system or "obsidian-brain" in system


@pytest.mark.asyncio
async def test_owner_chat_vault_relevant_miss_is_not_skip_if_empty(tmp_path, monkeypatch):
    """Bound + vault-relevant with no lexical hits must still surface a composer miss block."""
    data_root = tmp_path / "obsidian-meta"
    vault_root = tmp_path / "vault"
    data_root.mkdir(parents=True, exist_ok=True)
    vault_root.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr("app.memory.obsidian_vault.data_dir", lambda: data_root)
    reset_vault_store()
    bind_vault(str(vault_root), init_layout=False)
    stop_watch()
    # Empty vault (no notes indexed) — still bound.
    assert query_looks_vault_relevant("remember our project decision notes")
    _messages, working = await compose_owner_turn_messages(
        "cid-miss",
        "remember our project decision notes",
    )
    assert working.vault_block
    assert "vault is bound" in working.vault_block.lower() or "Linked vault memory" in working.vault_block
    stop_watch()
    unbind_vault()
    reset_vault_store()
