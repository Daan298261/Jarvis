from __future__ import annotations

import pytest

from app.memory.obsidian_vault import bind_vault, index_file, reset_vault_store, unbind_vault
from app.persona.owner_chat import _owner_messages


@pytest.fixture
def bound_vault(tmp_path, monkeypatch):
    data_root = tmp_path / "obsidian-meta"
    data_root.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr("app.memory.obsidian_vault.data_dir", lambda: data_root)
    reset_vault_store()
    bind_vault(str(tmp_path), init_layout=True)
    (tmp_path / "Projects" / "jarvis.md").write_text(
        "# Jarvis\n\nkubernetes deploy uses rollout strategy alpha.\n",
        encoding="utf-8",
    )
    index_file("Projects/jarvis.md")
    yield tmp_path
    unbind_vault()
    reset_vault_store()


def test_owner_messages_include_vault_excerpt_when_bound(bound_vault):
    messages = _owner_messages("cid", "how does kubernetes deploy work for jarvis")
    bodies = [m.content for m in messages if m.role == "system"]
    assert any("Linked vault memory" in b for b in bodies)
    assert any("kubernetes" in b.lower() for b in bodies)


def test_owner_messages_skip_vault_when_unbound():
    reset_vault_store()
    messages = _owner_messages("cid", "hello")
    assert not any("Linked vault memory" in (m.content or "") for m in messages)
