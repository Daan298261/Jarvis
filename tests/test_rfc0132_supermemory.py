from __future__ import annotations

from types import SimpleNamespace

import pytest

from app.agent import turn_working_set
from app.config import AppSettings
from app.memory.repository import add_entry
from app.memory.schema import ContextEntry, EntryProvenance
from app.memory.store import reset_context_repo_store
from app.memory import supermemory


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
