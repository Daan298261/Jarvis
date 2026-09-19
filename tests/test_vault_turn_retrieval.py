from __future__ import annotations

import pytest

from app.memory.obsidian_vault import (
    bind_vault,
    reset_vault_store,
    unbind_vault,
    vault_prompt_block,
    vault_turn_hits,
)


@pytest.fixture
def vault_with_router_only(tmp_path):
    reset_vault_store()
    bind_vault(str(tmp_path), init_layout=True)
    router = tmp_path / "_Config" / "router.md"
    router.write_text(
        "# Router\n\nProjects live under Projects/. Decisions under Decisions/.\n",
        encoding="utf-8",
    )
    from app.memory.obsidian_vault import index_file

    index_file("_Config/router.md")
    yield tmp_path
    unbind_vault()
    reset_vault_store()


def test_vault_relevant_ask_gets_router_when_no_token_match(vault_with_router_only):
    hits = vault_turn_hits("what did we decide about the project roadmap")
    assert hits
    assert hits[0].rel_path == "_Config/router.md"
    block = vault_prompt_block("tell me about our project notes")
    assert "Linked vault memory" in block
    assert "router" in block.lower() or "Projects" in block
