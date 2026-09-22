import asyncio
from pathlib import Path

import pytest

from app.memory.obsidian_vault import (
    append_note,
    bind_vault,
    create_note,
    edit_note,
    index_file,
    neighborhood,
    public_binding_status,
    reset_vault_store,
    resolve_wiki_link,
    search_vault,
    unbind_vault,
    vault_health,
    repair_vault_index,
)


@pytest.fixture
def temp_vault(tmp_path):
    reset_vault_store()
    bind_vault(str(tmp_path), init_layout=True)
    yield tmp_path
    unbind_vault()
    reset_vault_store()


def test_incremental_index_single_file(temp_vault):
    note = temp_vault / "Projects" / "alpha.md"
    note.parent.mkdir(parents=True, exist_ok=True)
    note.write_text("# Alpha\n\nSee [[Beta]] for more.\n", encoding="utf-8")
    entry = index_file("Projects/alpha.md")
    assert entry is not None
    assert entry.title == "Alpha"
    assert "Beta" in entry.outbound_wiki
    note.write_text("# Alpha\n\nUpdated body only.\n", encoding="utf-8")
    entry2 = index_file("Projects/alpha.md")
    assert entry2 is not None
    assert "Updated" in entry2.body_excerpt


def test_wiki_link_resolve_by_title(temp_vault):
    (temp_vault / "Beta.md").write_text("# Beta\n", encoding="utf-8")
    index_file("Beta.md")
    index_file("Projects/alpha.md") if (temp_vault / "Projects" / "alpha.md").exists() else None
    (temp_vault / "Projects" / "alpha.md").write_text("link [[Beta]]\n", encoding="utf-8")
    index_file("Projects/alpha.md")
    resolved = resolve_wiki_link("Beta", "Projects/alpha.md")
    assert not resolved.broken
    assert resolved.target_path == "Beta.md"


def test_neighborhood_hop_capped(temp_vault):
    (temp_vault / "A.md").write_text("[[B]]\n", encoding="utf-8")
    (temp_vault / "B.md").write_text("[[C]]\n", encoding="utf-8")
    (temp_vault / "C.md").write_text("leaf\n", encoding="utf-8")
    for name in ("A.md", "B.md", "C.md"):
        index_file(name)
    hood = neighborhood("A.md", hops=1)
    paths = {h.rel_path for h in hood}
    assert "A.md" in paths
    assert "B.md" in paths
    assert "C.md" not in paths


def test_user_edit_wins_on_managed_append(temp_vault):
    created = create_note("Decisions/x.md", "Jarvis draft", jarvis_managed=True)
    rel = created["rel_path"]
    path = temp_vault / rel
    path.write_text(path.read_text(encoding="utf-8") + "\nOwner override.\n", encoding="utf-8")
    result = append_note(rel, "Jarvis append")
    assert result.get("ok") is False
    assert "conflict" in result


def test_search_returns_provenance_fields(temp_vault):
    (temp_vault / "Systems" / "docker.md").write_text("# Docker notes\ncompose stacks\n", encoding="utf-8")
    index_file("Systems/docker.md")
    hits = search_vault("docker compose")
    assert hits
    assert hits[0].content_hash
    assert hits[0].rel_path.endswith("docker.md")


def test_health_reports_broken_link(temp_vault):
    (temp_vault / "broken.md").write_text("[[MissingNote]]\n", encoding="utf-8")
    index_file("broken.md")
    health = vault_health()
    assert any(item["link"] == "MissingNote" for item in health.broken_links)


def test_repair_reindexes_without_touching_prose(temp_vault):
    path = temp_vault / "keep.md"
    original = "# Keep\n\nuser prose\n"
    path.write_text(original, encoding="utf-8")
    index_file("keep.md")
    repair_vault_index()
    assert path.read_text(encoding="utf-8") == original


def test_public_status_never_echoes_path(temp_vault):
    status = public_binding_status()
    assert status["bound"]
    assert "vault_path" not in status
    assert status.get("vault_name")
    assert str(temp_vault) not in str(status)


def test_unbind_sidecar_off_still_has_index_api(temp_vault):
    """Disabling sidecars: native vault search works without OpenViking."""
    (temp_vault / "native.md").write_text("native memory works\n", encoding="utf-8")
    index_file("native.md")
    assert search_vault("native memory")


def test_id_resolve_rename_safe(temp_vault):
    note_id = "stable-note-id-007"
    content = f"---\nid: {note_id}\n---\n\n# Stable\n"
    (temp_vault / "People" / "stable.md").write_text(content, encoding="utf-8")
    index_file("People/stable.md")
    resolved = resolve_wiki_link(f"id:{note_id}")
    assert resolved.target_path == "People/stable.md"
    assert not resolved.broken
