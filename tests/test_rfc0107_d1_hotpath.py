"""RFC-0107 D1: prove bound vault is used on owner turns (hot-path working set)."""

from __future__ import annotations

import pytest

from app.agent.tool_retrieval import suggest_installable_catalog, suggest_tools_for_prompt
from app.agent.turn_working_set import (
    MAX_RECENT_TURNS,
    MAX_WORKING_SET_TOOLS,
    compose_turn_working_set,
)
from app.memory.obsidian_vault import (
    bind_vault,
    follow_wiki_link,
    index_file,
    public_binding_status,
    query_looks_vault_relevant,
    reset_vault_store,
    resolve_wiki_link,
    stop_watch,
    unbind_vault,
    vault_prompt_block,
    vault_turn_hits,
)
from app.persona.pack import build_persona_instructions
from app.providers.base import ChatMessage
from app.tools.registry import REGISTRY
from app.tools.vault_memory import VaultMemoryTool


@pytest.fixture
def vault_project_graph(tmp_path, monkeypatch):
    """Isolated vault + meta dir (meta outside the vault tree)."""
    data_root = tmp_path / "obsidian-meta"
    vault_root = tmp_path / "vault"
    data_root.mkdir(parents=True, exist_ok=True)
    vault_root.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr("app.memory.obsidian_vault.data_dir", lambda: data_root)
    stop_watch()
    reset_vault_store()
    bind_vault(str(vault_root), init_layout=True)
    stop_watch()  # avoid watch-thread races in unit tests
    (vault_root / "Decoy.md").write_text(
        "RFC0107_DECOY_UNIQUE_MARKER_SHOULD_NOT_APPEAR_IN_PROMPT\n" * 40,
        encoding="utf-8",
    )
    history_dump = vault_root / "Sources" / "CHAT_HISTORY_DUMP.md"
    history_dump.parent.mkdir(parents=True, exist_ok=True)
    history_dump.write_text(
        "# Chat history dump\n\nHISTORY_DUMP_UNIQUE_BYTE_ZZZ never belongs in prompts.\n" * 20,
        encoding="utf-8",
    )
    (vault_root / "Projects" / "deploy.md").write_text(
        "---\nid: deploy-note-1\ntype: project\n---\n\n"
        "# Deploy rollout\n\n"
        "kubernetes rollout for production cluster.\n\n"
        "See [[Beta]] for rollback.\n",
        encoding="utf-8",
    )
    (vault_root / "Beta.md").write_text("# Beta\n\nrollback runbook steps\n", encoding="utf-8")
    for rel in ("Decoy.md", "Sources/CHAT_HISTORY_DUMP.md", "Projects/deploy.md", "Beta.md"):
        index_file(rel)
    from app.memory.obsidian_vault import _load_index

    assert public_binding_status().get("bound"), "fixture must leave vault bound"
    assert "Beta.md" in _load_index(), "fixture must index Beta for wiki-link tests"
    yield vault_root
    stop_watch()
    unbind_vault()
    reset_vault_store()


@pytest.mark.asyncio
async def test_vault_relevant_ask_includes_path_heading_hash_provenance(vault_project_graph):
    assert query_looks_vault_relevant("what is our project deploy decision")
    assert public_binding_status().get("bound")
    ws = await compose_turn_working_set(
        "what is our project deploy kubernetes rollout",
        task_class="conversation",
        include_memory=False,
        needs_tools=False,
    )
    assert ws.vault_block, "empty-by-construction is a fail for vault-relevant asks"
    assert ws.vault_hits, "structured provenance hits required"
    hit = next(h for h in ws.vault_hits if "deploy" in h.rel_path.lower())
    assert hit.rel_path.endswith("deploy.md")
    assert hit.heading  # path + heading + hash
    assert hit.content_hash
    assert len(hit.content_hash) >= 12
    blob = ws.serialized_prompt_text()
    assert hit.rel_path in blob
    assert hit.heading in blob
    assert hit.content_hash[:12] in blob
    assert "provenance:" in blob
    assert "RFC0107_DECOY_UNIQUE_MARKER" not in blob
    assert "HISTORY_DUMP_UNIQUE_BYTE_ZZZ" not in blob


@pytest.mark.asyncio
async def test_unused_catalog_vault_history_absent_from_serialized_prompt(vault_project_graph):
    full_persona = build_persona_instructions()
    history = [
        ChatMessage(role="user", content=f"OLD_HISTORY_TURN_{i}_UNIQUE_MARKER " + ("x" * 200))
        for i in range(40)
    ]
    history += [
        ChatMessage(role="assistant", content=f"OLD_ASSISTANT_{i}_UNIQUE_MARKER")
        for i in range(40)
    ]
    ws = await compose_turn_working_set(
        "help with the kubernetes deploy project note",
        task_class="mixed",
        recent_messages=history,
        include_memory=False,
    )
    blob = ws.serialized_prompt_text()
    assert "RFC0107_DECOY_UNIQUE_MARKER" not in blob
    assert "HISTORY_DUMP_UNIQUE_BYTE_ZZZ" not in blob
    assert "OLD_HISTORY_TURN_0_UNIQUE_MARKER" not in blob
    assert "Personality traits:" not in blob
    assert len(ws.identity_block) < len(full_persona) / 2
    assert len(ws.recent_turns) <= MAX_RECENT_TURNS
    assert len(ws.tool_names) <= MAX_WORKING_SET_TOOLS
    enabled = [
        n
        for n, t in REGISTRY.tools.items()
        if t.enabled and n not in {"request_tools", "request_capability"}
    ]
    assert len(ws.tool_names) < len(enabled)
    schema_names = {item["function"]["name"] for item in ws.tool_schemas}
    for unused in ("hexstrike_defensive", "docker", "office", "blender"):
        if unused not in ws.tool_names:
            assert unused not in schema_names


@pytest.mark.asyncio
async def test_one_ask_hits_installed_tool_and_installable_pack():
    ws = await compose_turn_working_set(
        "organize my obsidian brain vault router taxonomy and run git status",
        task_class="software engineering",
        include_vault=False,
        include_memory=False,
    )
    installed = suggest_tools_for_prompt("run git status on this repository")
    assert "git" in installed
    catalog = suggest_installable_catalog("obsidian brain router taxonomy")
    assert catalog
    assert any(row["entry_id"] == "obsidian-brain" for row in catalog)
    assert any("/api/modules/catalog/" in (o.download_api or "") for o in ws.installable_offers)
    assert any("obsidian-brain" in o.entry_id for o in ws.installable_offers)
    assert "git" in ws.tool_names or "git" in suggest_tools_for_prompt(
        "organize my obsidian brain vault router taxonomy and run git status"
    )


@pytest.mark.asyncio
async def test_vault_memory_resolve_neighborhood_follow_and_managed_write(vault_project_graph):
    assert public_binding_status().get("bound")
    tool = VaultMemoryTool()
    resolved = await tool.execute(action="resolve", query="Beta", rel_path="Projects/deploy.md")
    assert resolved.success
    assert resolved.data and resolved.data.get("target_path") == "Beta.md"
    assert not resolved.data.get("broken")

    hood = await tool.execute(action="neighborhood", rel_path="Projects/deploy.md", hops=1)
    assert hood.success
    paths = {h["rel_path"] for h in (hood.data or {}).get("hits") or []}
    assert "Projects/deploy.md" in paths
    assert "Beta.md" in paths

    followed = follow_wiki_link("Beta", source_rel="Projects/deploy.md", hops=1)
    assert not followed["broken"]
    assert followed["target_path"] == "Beta.md"
    assert any(h["rel_path"] == "Beta.md" for h in followed["neighborhood"])

    created = await tool.execute(
        action="create",
        rel_path="Decisions/agent-outcome.md",
        content="Verified deploy outcome.",
        memory_pointer="task-abc-123",
    )
    assert created.success
    note_path = vault_project_graph / "Decisions" / "agent-outcome.md"
    text = note_path.read_text(encoding="utf-8")
    assert "jarvis_managed: true" in text
    assert "task-abc-123" in text


def test_prompt_block_provenance_format(vault_project_graph):
    block = vault_prompt_block("kubernetes deploy rollout")
    assert "Linked vault memory" in block
    assert "Projects/deploy.md#" in block
    assert "hash:" in block
    assert "provenance:" in block
    hits = vault_turn_hits("kubernetes deploy rollout")
    assert hits
    assert hits[0].content_hash
    assert hits[0].heading or hits[0].title


def test_wiki_link_resolve_still_works(vault_project_graph):
    resolved = resolve_wiki_link("Beta", "Projects/deploy.md")
    assert not resolved.broken
    assert resolved.target_path == "Beta.md"
