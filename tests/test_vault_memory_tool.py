from __future__ import annotations

import pytest

from app.agent.tool_retrieval import suggest_tools_for_prompt
from app.memory.obsidian_vault import (
    bind_vault,
    index_file,
    mirror_owner_chat_turn,
    query_looks_vault_relevant,
    reset_vault_store,
    unbind_vault,
    vault_turn_hits,
)
from app.tools.registry import REGISTRY
from app.tools.vault_memory import VaultMemoryTool


@pytest.fixture
def bound_vault(tmp_path):
    reset_vault_store()
    bind_vault(str(tmp_path), init_layout=True)
    (tmp_path / "Projects" / "alpha.md").write_text(
        "# Alpha\n\nkubernetes deploy uses rollout.\n",
        encoding="utf-8",
    )
    index_file("Projects/alpha.md")
    yield tmp_path
    unbind_vault()
    reset_vault_store()


@pytest.mark.asyncio
async def test_vault_memory_search_and_append(bound_vault):
    tool = VaultMemoryTool()
    search = await tool.execute(action="search", query="kubernetes rollout")
    assert search.success
    assert "Projects/alpha.md" in search.output

    created = await tool.execute(
        action="create",
        rel_path="Decisions/test-note.md",
        content="Decision body from agent.",
    )
    assert created.success
    assert (bound_vault / "Decisions" / "test-note.md").is_file()


def test_tool_retrieval_includes_vault_memory_for_obsidian_ask():
    hits = suggest_tools_for_prompt("update my obsidian vault wiki link for the project")
    assert "vault_memory" in hits


def test_vault_turn_hits_and_relevance(bound_vault):
    assert query_looks_vault_relevant("what does our project decision say")
    hits = vault_turn_hits("kubernetes rollout")
    assert hits
    assert any("alpha" in h.rel_path.lower() or "kubernetes" in h.excerpt.lower() for h in hits)


def test_mirror_owner_chat_turn_creates_session_note(bound_vault):
    result = mirror_owner_chat_turn(
        conversation_id="conv-test-1",
        user_text="Hello",
        assistant_text="Good evening.",
    )
    assert result
    rel = result.get("rel_path") or ""
    assert rel.startswith("_Temporal/Sessions/")
    assert (bound_vault / rel).is_file()


def test_vault_memory_tool_registered():
    assert "vault_memory" in REGISTRY.tools
