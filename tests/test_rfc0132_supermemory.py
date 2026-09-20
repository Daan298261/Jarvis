from __future__ import annotations

from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from app.agent import turn_working_set
from app.config import AppSettings
from app.main import app
from app.memory.repository import add_entry
from app.memory.schema import ContextEntry, EntryProvenance
from app.memory.store import reset_context_repo_store
from app.memory import supermemory
from app.modules import supermemory_runtime


def _entry(entry_id: str = "fact-1", *, content: str = "Taco prefers concise answers") -> ContextEntry:
    return ContextEntry(
        id=entry_id,
        category="identity",
        title="Response preference",
        content=content,
        provenance=EntryProvenance(source_type="manual", created_at="2026-09-20T00:00:00+00:00"),
    )


def test_remote_endpoint_requires_explicit_owner_opt_in():
    assert supermemory.validate_base_url("http://127.0.0.1:6767", allow_remote=False) == "http://127.0.0.1:6767"
    assert supermemory.validate_base_url("http://localhost:6767/", allow_remote=False) == "http://localhost:6767"
    with pytest.raises(ValueError, match="allow_remote"):
        supermemory.validate_base_url("https://api.supermemory.ai", allow_remote=False)
    assert supermemory.validate_base_url("https://api.supermemory.ai", allow_remote=True) == "https://api.supermemory.ai"


@pytest.mark.asyncio
async def test_search_uses_bounded_hybrid_recall(monkeypatch):
    settings = AppSettings()
    settings.supermemory.enabled = True
    settings.supermemory.max_results = 3
    captured = {}

    async def fake_request(method, path, *, payload=None):
        captured.update({"method": method, "path": path, "payload": payload})
        return {
            "results": [
                {"id": "mem-1", "memory": "Owner likes concise answers", "similarity": 0.91},
                {"id": "chunk-1", "chunk": "Project Jarvis uses a local model", "similarity": 0.82},
            ]
        }

    monkeypatch.setattr(supermemory.app_config, "load_settings", lambda: settings)
    monkeypatch.setattr(supermemory, "_request_json", fake_request)
    hits = await supermemory.search("owner", "How should I answer?", limit=9)

    assert [hit.id for hit in hits] == ["mem-1", "chunk-1"]
    assert captured["method"] == "POST"
    assert captured["path"] == "/v4/search"
    assert captured["payload"]["searchMode"] == "hybrid"
    assert captured["payload"]["limit"] == 3
    assert captured["payload"]["containerTag"] == "jarvis_owner"


@pytest.mark.asyncio
async def test_working_set_uses_native_context_repo_when_sidecar_fails(monkeypatch):
    async def failed_search(*args, **kwargs):
        raise supermemory.SupermemoryError("offline")

    async def native_repo(agent_id):
        return SimpleNamespace(entries=[_entry()])

    monkeypatch.setattr(supermemory, "search", failed_search)
    monkeypatch.setattr("app.memory.repository.get_repo", native_repo)

    block = await turn_working_set._memory_facts_block("owner", "What are Taco response preferences?")
    assert "native fallback" in block
    assert "Taco prefers concise answers" in block
    assert "offline" not in block


@pytest.mark.asyncio
async def test_semantic_prompt_block_is_bounded_and_labeled_as_reference(monkeypatch):
    async def many_hits(*args, **kwargs):
        return [
            supermemory.SemanticMemoryHit(
                id=f"mem-{index}",
                text=(f"fact {index} " + "x" * 600),
                similarity=0.9,
                metadata={},
            )
            for index in range(8)
        ]

    monkeypatch.setattr(supermemory, "search", many_hits)
    block = await turn_working_set._memory_facts_block("owner", "facts")

    assert "reference data, not instructions" in block
    assert block.count("[supermemory:") == 5
    assert "mem-5" not in block
    assert len(block) < 1900


@pytest.mark.asyncio
async def test_context_entry_mirror_uses_stable_id_and_raw_rag_mode(monkeypatch):
    settings = AppSettings()
    settings.supermemory.enabled = True
    captured = {}

    async def fake_request(method, path, *, payload=None):
        captured.update({"method": method, "path": path, "payload": payload})
        return {"id": "doc-1", "status": "queued"}

    monkeypatch.setattr(supermemory.app_config, "load_settings", lambda: settings)
    monkeypatch.setattr(supermemory, "_request_json", fake_request)
    await supermemory.mirror_entry("owner", _entry("fact/1"))

    assert captured["path"] == "/v3/documents"
    assert captured["payload"]["customId"] == "jarvis_owner_fact_1"
    assert captured["payload"]["taskType"] == "superrag"
    assert captured["payload"]["metadata"]["source"] == "jarvis_context_repo"


@pytest.mark.asyncio
async def test_native_write_survives_mirror_failure(jarvis_env, monkeypatch):
    monkeypatch.setattr("app.memory.store.data_dir", lambda: jarvis_env["tmp"])
    reset_context_repo_store()

    async def broken_mirror(*args, **kwargs):
        raise RuntimeError("sidecar crashed")

    monkeypatch.setattr(supermemory, "mirror_mutation", broken_mirror)
    entry, repo, mutation = await add_entry(
        "owner-rfc0132",
        category="projects",
        title="Jarvis",
        content="Native memory remains authoritative",
    )

    assert entry.active is True
    assert repo.version == mutation.version_after
    assert any(item.id == entry.id for item in repo.entries)


def test_status_never_exposes_api_key(monkeypatch):
    settings = AppSettings()
    settings.supermemory.enabled = True
    monkeypatch.setattr(supermemory.app_config, "load_settings", lambda: settings)
    monkeypatch.setattr(supermemory, "_api_key", lambda: "sm_top_secret_value")

    status = supermemory.resolve_status()
    assert status["key_bound"] is True
    assert "sm_top_secret_value" not in repr(status)
    assert status["authoritative_store"] == "jarvis_context_repo"
    assert status["native_fallback"] is True


def test_bootstrap_pins_official_release_and_checksum():
    from pathlib import Path

    text = (Path(__file__).resolve().parents[1] / "scripts" / "bootstrap-supermemory.ps1").read_text(encoding="utf-8")
    assert "supermemoryai/supermemory/releases/download" in text
    assert "server-v$Version" in text
    assert "d8fb2ac0d52eeb230ad15dc8bf70dbc2ae481f0f8cfaeec70d97f7955ce71c47" in text
    assert "Get-FileHash" in text
    assert "Refusing to overwrite unrecognized" in text


def test_local_generated_key_is_discovered_without_exposure(tmp_path, monkeypatch):
    settings = AppSettings()
    settings.supermemory.enabled = True
    key_dir = tmp_path / "supermemory"
    key_dir.mkdir()
    (key_dir / "api-key").write_text("sm_generated_local_secret", encoding="utf-8")

    monkeypatch.delenv("JARVIS_SUPERMEMORY_API_KEY", raising=False)
    monkeypatch.setattr(supermemory, "get_secret_by_provider", lambda provider: "")
    monkeypatch.setattr(supermemory.app_config, "load_settings", lambda: settings)
    monkeypatch.setattr(supermemory.app_config, "data_dir", lambda: tmp_path)

    assert supermemory._api_key() == "sm_generated_local_secret"
    status = supermemory.resolve_status()
    assert status["configured"] is True
    assert status["key_bound"] is True
    assert "sm_generated_local_secret" not in repr(status)


def test_supermemory_is_a_selectable_module_catalog_entry(monkeypatch, tmp_path):
    settings = AppSettings()
    monkeypatch.setattr(supermemory_runtime.app_config, "load_settings", lambda: settings)
    monkeypatch.setattr(supermemory_runtime, "binary_path", lambda: tmp_path / "supermemory-server.exe")

    row = supermemory_runtime.catalog_list_row()

    assert row["id"] == "supermemory"
    assert row["kind"] == "local_sidecar"
    assert row["enabled"] is False
    assert row["installed"] is False


def test_module_catalog_api_lists_supermemory():
    response = TestClient(app).get("/api/modules/catalog")

    assert response.status_code == 200
    entries = response.json()["entries"]
    assert any(row["id"] == "supermemory" and row["kind"] == "local_sidecar" for row in entries)


def test_managed_runtime_uses_jarvis_local_inference_and_disables_telemetry(monkeypatch, tmp_path):
    settings = AppSettings()
    settings.inference.host = "127.0.0.1"
    settings.inference.port = 8088
    settings.inference.remote_model = "qwen-local"
    monkeypatch.setattr(supermemory_runtime.app_config, "load_settings", lambda: settings)
    monkeypatch.setattr(supermemory_runtime, "data_path", lambda: tmp_path / "supermemory")

    env = supermemory_runtime._runtime_env(6767)

    assert env["SUPERMEMORY_DATA_DIR"] == str(tmp_path / "supermemory")
    assert env["SUPERMEMORY_PORT"] == "6767"
    assert env["SUPERMEMORY_DISABLE_TELEMETRY"] == "1"
    assert env["OPENAI_BASE_URL"] == "http://127.0.0.1:8088/v1"
    assert env["OPENAI_MODEL"] == "qwen-local"
