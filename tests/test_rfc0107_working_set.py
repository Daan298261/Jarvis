import asyncio
from pathlib import Path

import pytest

from app.agent.tool_retrieval import suggest_installable_catalog, suggest_tools_for_prompt
from app.agent.turn_working_set import compose_turn_working_set
from app.memory.obsidian_vault import bind_vault, reset_vault_store, stop_watch, unbind_vault
from app.persona.pack import build_persona_instructions, compact_identity_instructions
from app.tools.registry import REGISTRY


@pytest.fixture
def vault_with_decoy(tmp_path, monkeypatch):
    data_root = tmp_path / "obsidian-meta"
    data_root.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr("app.memory.obsidian_vault.data_dir", lambda: data_root)
    stop_watch()
    reset_vault_store()
    bind_vault(str(tmp_path), init_layout=True)
    (tmp_path / "Decoy.md").write_text(
        "RFC0107_DECOY_UNIQUE_MARKER_SHOULD_NOT_APPEAR_IN_PROMPT\n" * 50,
        encoding="utf-8",
    )
    (tmp_path / "Projects" / "deploy.md").write_text(
        "# Deploy\n\nkubernetes rollout for production\n",
        encoding="utf-8",
    )
    from app.memory.obsidian_vault import index_file

    index_file("Decoy.md")
    index_file("Projects/deploy.md")
    yield tmp_path
    unbind_vault()
    reset_vault_store()


@pytest.mark.asyncio
async def test_prompt_excludes_full_vault_persona_and_catalog(vault_with_decoy):
    full_persona = build_persona_instructions()
    ws = await compose_turn_working_set(
        "help me with kubernetes deploy rollout",
        task_class="mixed",
        include_memory=False,
    )
    blob = ws.serialized_prompt_text()
    assert "RFC0107_DECOY_UNIQUE_MARKER" not in blob
    assert "Personality traits:" not in blob
    assert "You must not:" not in blob
    assert len(ws.identity_block) < len(full_persona) / 2
    schema_names = [item["function"]["name"] for item in ws.tool_schemas]
    for name in ("docker", "office", "desktop", "browser", "hexstrike_defensive"):
        if name not in ws.tool_names:
            assert name not in schema_names


@pytest.mark.asyncio
async def test_tool_search_hits_installed_and_installable():
    ws_git = await compose_turn_working_set(
        "run git status on this repository",
        task_class="software engineering",
        include_vault=False,
        include_memory=False,
    )
    assert "git" in ws_git.tool_names
    ws_obsidian = await compose_turn_working_set(
        "organize my obsidian brain vault router taxonomy",
        task_class="mixed",
        include_vault=False,
        include_memory=False,
    )
    catalog = suggest_installable_catalog("obsidian brain router taxonomy")
    assert catalog
    assert ws_obsidian.installable_offers
    assert any("obsidian-brain" in o.entry_id for o in ws_obsidian.installable_offers)
    assert any("/api/modules/catalog/" in (o.download_api or "") for o in ws_obsidian.installable_offers)


def test_suggest_tools_does_not_return_full_catalog():
    prompt = "docker compose up the stack"
    hits = suggest_tools_for_prompt(prompt)
    assert "docker" in hits
    enabled = [n for n, t in REGISTRY.tools.items() if t.enabled and n not in {"request_tools", "request_capability"}]
    assert len(hits) < len(enabled)


@pytest.mark.asyncio
async def test_vault_hit_in_working_set_only(vault_with_decoy):
    ws = await compose_turn_working_set(
        "kubernetes deploy rollout",
        include_memory=False,
    )
    assert "kubernetes" in ws.vault_block.lower() or "deploy" in ws.vault_block.lower()
    assert "RFC0107_DECOY" not in ws.serialized_prompt_text()


def test_compact_identity_is_short():
    compact = compact_identity_instructions()
    full = build_persona_instructions()
    assert len(compact) < len(full)
