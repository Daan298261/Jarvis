"""RFC-0107 Wave B: prove bound vault is used on owner turns — retrieve + write, no décor."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.agent.task_fastpath import admit_fastpath
from app.agent.turn_working_set import (
    VAULT_RETRIEVAL_HITS,
    VAULT_RETRIEVAL_ORIENTATION,
    VAULT_RETRIEVAL_UNBOUND,
    compose_turn_working_set,
    replace_vault_block_in_system,
)
from app.main import app
from app.memory.obsidian_vault import (
    bind_vault,
    index_file,
    mirror_owner_chat_turn,
    public_binding_status,
    query_looks_vault_relevant,
    reset_vault_store,
    search_vault,
    stop_watch,
    unbind_vault,
    vault_ask_requires_working_set,
    vault_prompt_block,
    vault_turn_hits,
)
from app.persona.owner_chat import compose_owner_turn_messages
from app.tools.vault_memory import VaultMemoryTool


@pytest.fixture
def wave_b_vault(tmp_path, monkeypatch):
    data_root = tmp_path / "obsidian-meta"
    vault_root = tmp_path / "vault"
    data_root.mkdir(parents=True, exist_ok=True)
    vault_root.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr("app.memory.obsidian_vault.data_dir", lambda: data_root)
    stop_watch()
    reset_vault_store()
    bind_vault(str(vault_root), init_layout=True)
    stop_watch()
    (vault_root / "Projects" / "wave-b.md").write_text(
        "---\nid: wave-b-project\ntype: project\n---\n\n"
        "# Wave B Project\n\n"
        "WAVE_B_UNIQUE_RETRIEVE_TOKEN kubernetes canary deploy.\n",
        encoding="utf-8",
    )
    index_file("Projects/wave-b.md")
    yield vault_root
    stop_watch()
    unbind_vault()
    reset_vault_store()


@pytest.mark.asyncio
async def test_owner_turn_retrieve_includes_real_hits_with_provenance(wave_b_vault):
    ask = "what is our project WAVE_B_UNIQUE_RETRIEVE_TOKEN kubernetes decision"
    assert query_looks_vault_relevant(ask)
    assert public_binding_status().get("bound")
    messages, working = await compose_owner_turn_messages("cid-wave-b-retrieve", ask)
    assert working.vault_retrieval == VAULT_RETRIEVAL_HITS
    assert working.vault_hits, "empty-by-construction is a fail"
    hit = next(h for h in working.vault_hits if "wave-b" in h.rel_path.lower())
    assert hit.rel_path == "Projects/wave-b.md"
    assert hit.heading
    assert hit.content_hash and len(hit.content_hash) >= 12
    assert "WAVE_B_UNIQUE_RETRIEVE_TOKEN" in (hit.excerpt or "")
    assert hit.provenance == "vault_lexical"
    system = "\n".join(m.content or "" for m in messages if m.role == "system")
    assert hit.rel_path in system
    assert f"{hit.rel_path}#" in system
    assert hit.content_hash[:12] in system
    assert "provenance:vault_lexical" in system
    assert "WAVE_B_UNIQUE_RETRIEVE_TOKEN" in system


@pytest.mark.asyncio
async def test_managed_write_lands_on_disk_and_is_rereadable(wave_b_vault):
    """create → append → edit must write real Markdown and reindex for retrieve."""
    tool = VaultMemoryTool()
    created = await tool.execute(
        action="create",
        rel_path="Decisions/wave-b-outcome.md",
        content="WAVE_B_WRITE_CREATE_MARKER verified outcome.",
        memory_pointer="task-wave-b-1",
    )
    assert created.success, created.error
    path = wave_b_vault / "Decisions" / "wave-b-outcome.md"
    assert path.is_file()
    text = path.read_text(encoding="utf-8")
    assert "jarvis_managed: true" in text
    assert "WAVE_B_WRITE_CREATE_MARKER" in text
    assert "task-wave-b-1" in text

    appended = await tool.execute(
        action="append",
        rel_path="Decisions/wave-b-outcome.md",
        content="WAVE_B_WRITE_APPEND_MARKER follow-up.",
    )
    assert appended.success, appended.error
    text = path.read_text(encoding="utf-8")
    assert "WAVE_B_WRITE_APPEND_MARKER" in text

    edited = await tool.execute(
        action="edit",
        rel_path="Decisions/wave-b-outcome.md",
        content="WAVE_B_WRITE_EDIT_MARKER replacement body.",
        force=True,
    )
    assert edited.success, edited.error
    text = path.read_text(encoding="utf-8")
    assert "WAVE_B_WRITE_EDIT_MARKER" in text
    assert "WAVE_B_WRITE_CREATE_MARKER" not in text

    # Watch/index path: search + owner composer must see the edited body.
    hits = search_vault("WAVE_B_WRITE_EDIT_MARKER", limit=6)
    assert hits
    assert any(h.rel_path.endswith("wave-b-outcome.md") for h in hits)
    assert all(h.content_hash for h in hits)

    ask = "remember our project decision WAVE_B_WRITE_EDIT_MARKER"
    ws = await compose_turn_working_set(ask, task_class="conversation", include_memory=False, needs_tools=False)
    assert ws.vault_retrieval == VAULT_RETRIEVAL_HITS
    assert any("WAVE_B_WRITE_EDIT_MARKER" in (h.excerpt or "") for h in ws.vault_hits)


def test_mirror_owner_chat_append_second_turn(wave_b_vault):
    first = mirror_owner_chat_turn(
        conversation_id="wave-b-mirror",
        user_text="first owner ask about project",
        assistant_text="first reply",
    )
    assert first and first.get("rel_path")
    rel = first["rel_path"]
    path = wave_b_vault / rel
    assert path.is_file()
    assert "jarvis_managed: true" in path.read_text(encoding="utf-8")

    second = mirror_owner_chat_turn(
        conversation_id="wave-b-mirror",
        user_text="second owner ask WAVE_B_MIRROR_APPEND",
        assistant_text="second reply",
    )
    assert second and second.get("appended") is True
    body = path.read_text(encoding="utf-8")
    assert "first owner ask" in body
    assert "WAVE_B_MIRROR_APPEND" in body
    assert body.count("## Turn") >= 2


def test_vault_relevant_bound_blocks_terminal_fastpath(wave_b_vault):
    assert vault_ask_requires_working_set("what is our project kubernetes decision")
    decision = admit_fastpath(
        "what is our project kubernetes decision",
        route_kind="direct_reply",
        front_action="final_basic",
        front_text="Sure — here is a short answer.",
    )
    assert not decision.admitted
    assert decision.reason == "vault_relevant_bound"


def test_unbound_does_not_require_vault_working_set():
    reset_vault_store()
    assert not vault_ask_requires_working_set("what is our project decision")
    decision = admit_fastpath(
        "what is our project decision",
        route_kind="direct_reply",
        front_action="final_basic",
        front_text="Hello there.",
    )
    assert decision.admitted
    assert decision.reason == "direct_reply_terminal_front"


@pytest.mark.asyncio
async def test_orientation_fallback_is_labeled_not_lexical_hit(tmp_path, monkeypatch):
    data_root = tmp_path / "obsidian-meta"
    vault_root = tmp_path / "vault"
    data_root.mkdir(parents=True, exist_ok=True)
    vault_root.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr("app.memory.obsidian_vault.data_dir", lambda: data_root)
    reset_vault_store()
    bind_vault(str(vault_root), init_layout=False)
    stop_watch()
    (vault_root / "_Config").mkdir(parents=True, exist_ok=True)
    (vault_root / "_Config" / "router.md").write_text(
        "# Router\n\nProjects live under Projects/.\n",
        encoding="utf-8",
    )
    index_file("_Config/router.md")
    ask = "what did we decide about the project roadmap"
    hits = vault_turn_hits(ask)
    assert hits
    assert hits[0].provenance == "vault_router"
    block = vault_prompt_block(ask)
    assert "orientation only" in block.lower()
    assert "not a lexical match" in block.lower()
    ws = await compose_turn_working_set(ask, include_memory=False, needs_tools=False)
    assert ws.vault_retrieval == VAULT_RETRIEVAL_ORIENTATION
    assert ws.vault_hits
    assert all(h.provenance == "vault_router" for h in ws.vault_hits)
    stop_watch()
    unbind_vault()
    reset_vault_store()


@pytest.mark.asyncio
async def test_agent_continue_replaces_stale_vault_block(wave_b_vault):
    first = await compose_turn_working_set(
        "kubernetes canary deploy project note",
        include_memory=False,
        needs_tools=False,
    )
    assert first.vault_retrieval == VAULT_RETRIEVAL_HITS
    system = f"{first.vault_block}\n\nYou are the agent system prompt."
    # Second ask about a note written after the first compose.
    (wave_b_vault / "Decisions" / "follow-up.md").write_text(
        "# Follow up\n\nWAVE_B_CONTINUE_UNIQUE_TOKEN decision.\n",
        encoding="utf-8",
    )
    index_file("Decisions/follow-up.md")
    follow = await compose_turn_working_set(
        "remember our project decision WAVE_B_CONTINUE_UNIQUE_TOKEN",
        include_memory=False,
        needs_tools=False,
    )
    assert follow.vault_retrieval == VAULT_RETRIEVAL_HITS
    refreshed = replace_vault_block_in_system(system, follow.vault_block)
    assert "WAVE_B_CONTINUE_UNIQUE_TOKEN" in refreshed
    assert refreshed.count("Linked vault memory") == 1
    assert "You are the agent system prompt." in refreshed


@pytest.mark.asyncio
async def test_compose_unbound_status(tmp_path, monkeypatch):
    data_root = tmp_path / "obsidian-meta"
    data_root.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr("app.memory.obsidian_vault.data_dir", lambda: data_root)
    reset_vault_store()
    ws = await compose_turn_working_set(
        "what is our project decision",
        include_memory=False,
        needs_tools=False,
    )
    assert ws.vault_retrieval == VAULT_RETRIEVAL_UNBOUND
    assert ws.vault_block == ""
    assert ws.vault_hits == []


def test_api_vault_act_create_search_roundtrip(wave_b_vault, allow_loopback_api, monkeypatch):
    """HTTP act create must land on disk and be searchable with provenance."""
    monkeypatch.setenv("JARVIS_SKIP_MODEL", "1")
    client = TestClient(app)
    created = client.post(
        "/api/vault/act",
        json={
            "action": "create",
            "rel_path": "Decisions/api-wave-b.md",
            "content": "WAVE_B_API_WRITE_MARKER from HTTP act.",
            "memory_pointer": "api-task-1",
        },
    )
    assert created.status_code == 200, created.text
    body = created.json()
    assert body.get("rel_path") == "Decisions/api-wave-b.md"
    path = wave_b_vault / "Decisions" / "api-wave-b.md"
    assert path.is_file()
    assert "WAVE_B_API_WRITE_MARKER" in path.read_text(encoding="utf-8")
    assert "jarvis_managed: true" in path.read_text(encoding="utf-8")

    searched = client.post(
        "/api/vault/search",
        json={"query": "WAVE_B_API_WRITE_MARKER", "limit": 8},
    )
    assert searched.status_code == 200, searched.text
    hits = searched.json().get("hits") or []
    assert hits
    assert any(h.get("rel_path") == "Decisions/api-wave-b.md" for h in hits)
    assert any(h.get("content_hash") for h in hits)
    assert any(h.get("provenance") for h in hits)
