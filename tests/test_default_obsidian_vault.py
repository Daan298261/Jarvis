from pathlib import Path

from app.memory.obsidian_vault import (
    default_vault_path,
    ensure_default_vault,
    public_binding_status,
    reset_vault_store,
    unbind_vault,
)


def test_ensure_default_vault_creates_managed_layout(tmp_path, monkeypatch):
    monkeypatch.setattr("app.memory.obsidian_vault.data_dir", lambda: tmp_path)
    reset_vault_store()
    unbind_vault()
    result = ensure_default_vault(configured_path="", init_layout=True)
    assert result["bound"] is True
    assert result["created"] is True
    vault = tmp_path / "vault"
    assert vault.is_dir()
    assert (vault / "_Config" / "router.md").is_file()
    assert (vault / "Projects" / "Welcome.md").is_file()
    assert (vault / "Home" / "Jarvis.md").is_file()
    status = public_binding_status()
    assert status["bound"] is True
    assert status["jarvis_managed_layout"] is True
    assert status["note_count"] >= 2
    assert "vault_path" not in status
    assert str(vault) not in str(status)


def test_ensure_default_vault_is_idempotent(tmp_path, monkeypatch):
    monkeypatch.setattr("app.memory.obsidian_vault.data_dir", lambda: tmp_path)
    reset_vault_store()
    unbind_vault()
    first = ensure_default_vault()
    second = ensure_default_vault()
    assert first["created"] is True
    assert second["created"] is False
    assert second["bound"] is True
    assert Path(first["vault_path"]) == default_vault_path()


def test_ensure_default_vault_uses_existing_configured_folder(tmp_path, monkeypatch):
    monkeypatch.setattr("app.memory.obsidian_vault.data_dir", lambda: tmp_path)
    reset_vault_store()
    unbind_vault()
    custom = tmp_path / "existing-obsidian"
    custom.mkdir()
    (custom / "note.md").write_text("# Existing\nowner note\n", encoding="utf-8")
    result = ensure_default_vault(configured_path=str(custom), init_layout=False)
    assert result["bound"] is True
    assert Path(result["vault_path"]) == custom.resolve()
    assert not (custom / "_Config").exists()
