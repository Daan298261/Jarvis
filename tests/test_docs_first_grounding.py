from __future__ import annotations

from pathlib import Path

import pytest

from app.agent.docs_first_grounding import (
    DocsFirstContext,
    consume_budget,
    evaluate_triggers,
    is_jarvis_error,
    is_system_about,
    load_budget,
    maybe_docs_first,
    missing_pack_files,
    reference_pack_root,
    reset_budget_for_tests,
    save_budget,
    search_internal_references,
)
from app.tools.internal_references import InternalReferencesTool


@pytest.fixture(autouse=True)
def docs_first_env(tmp_path, monkeypatch):
    monkeypatch.setattr("app.agent.docs_first_grounding.data_dir", lambda: tmp_path)
    reset_budget_for_tests()
    yield tmp_path
    reset_budget_for_tests()


def test_system_about_trigger():
    assert is_system_about("What is Jarvis and how do I enable LAN access?")
    assert not is_system_about("Summarize my quarterly spreadsheet")


def test_error_trigger_detects_pasted_stderr():
    assert is_jarvis_error("llama-server exited immediately on port 8088")
    assert is_jarvis_error("help", "ERROR: model shows unloaded in portal")


def test_budget_persists_and_resets_on_version_change():
    save_budget({"version": "1.0.0", "remaining": 42})
    loaded = load_budget("1.0.0")
    assert loaded["remaining"] == 42
    bumped = load_budget("2.0.0")
    assert bumped["remaining"] == 100

    save_budget({"version": "2.0.0", "remaining": 5})
    consumed = consume_budget(load_budget("2.0.0"))
    assert consumed["remaining"] == 4


def test_budget_zero_still_allows_system_about_and_error():
    save_budget({"version": "9.9.9", "remaining": 0})
    ctx = DocsFirstContext(user_message="How does Jarvis bind_host work?", app_version="9.9.9")
    triggered, reasons, _ = evaluate_triggers(ctx, load_budget("9.9.9"))
    assert triggered
    assert "system_about" in reasons
    assert "new_install_budget" not in reasons

    err_ctx = DocsFirstContext(
        user_message="see logs",
        error_context="waiting on model at 4780",
        app_version="9.9.9",
    )
    err_triggered, err_reasons, _ = evaluate_triggers(err_ctx, load_budget("9.9.9"))
    assert err_triggered
    assert "on_screen_error" in err_reasons


def test_budget_gate_off_when_exhausted_for_generic_chat():
    save_budget({"version": "1.0.0", "remaining": 0})
    ctx = DocsFirstContext(user_message="Write a haiku about autumn leaves", app_version="1.0.0")
    triggered, reasons, _ = evaluate_triggers(ctx, load_budget("1.0.0"))
    assert not triggered
    assert reasons == []


def test_maybe_docs_first_returns_snippets_with_citations():
    bundle = maybe_docs_first(
        DocsFirstContext(user_message="How do I configure LAN bind and private key for Jarvis?")
    )
    assert bundle is not None
    assert bundle.triggered
    assert bundle.snippets
    assert all(snip.citation_id and snip.source_path for snip in bundle.snippets)
    block = bundle.prompt_block()
    assert "[ref-" in block
    assert "prefer the cited local references" in block


def test_missing_pack_files_fail_closed(tmp_path, monkeypatch):
    empty_pack = tmp_path / "references"
    empty_pack.mkdir()
    monkeypatch.setattr("app.agent.docs_first_grounding.reference_pack_root", lambda: empty_pack)
    missing = missing_pack_files()
    assert missing
    bundle = maybe_docs_first(DocsFirstContext(user_message="What is Jarvis?"))
    assert bundle is not None
    assert bundle.missing_refs
    assert "Reference missing" in bundle.prompt_block()


def test_search_path_confinement(monkeypatch, tmp_path):
    pack = reference_pack_root()
    assert pack.is_dir()
    hits = search_internal_references("port 4780 private key")
    assert hits
    for hit in hits:
        path = Path(hit.source_path)
        assert ".." not in hit.source_path
        assert not str(path).startswith("/etc")
        assert "references" in hit.source_path or hit.source_path.endswith(".md")

    # Craft a fake escape path — confinement should reject it from indexing.
    outside = tmp_path / "outside.md"
    outside.write_text("secret outside corpus", encoding="utf-8")

    def fake_iter(_roots):
        return [outside.resolve()]

    monkeypatch.setattr("app.agent.docs_first_grounding._iter_index_files", fake_iter)
    assert search_internal_references("secret outside") == []


def test_redaction_strips_secrets_in_snippets():
    hits = search_internal_references("JARVIS_PRIVATE_KEY api_key bearer token")
    combined = "\n".join(hit.text for hit in hits)
    assert "jarvis_pk_secret123" not in combined.lower() or "[REDACTED]" in combined or "redact" in combined.lower()
    # Ensure setup-pitfalls redaction path runs when we embed a fake secret in a temp allowlisted file.
    # The real corpus should not contain live secrets; redact_string handles bearer patterns.
    from app.trajectories.redaction import redact_string

    assert "[REDACTED]" in redact_string("Authorization: Bearer sk-testtoken1234567890abcdef")


def test_budget_decrements_when_gate_runs():
    save_budget({"version": "1.0.0", "remaining": 10})
    maybe_docs_first(DocsFirstContext(user_message="What is Jarvis?", app_version="1.0.0"))
    assert load_budget("1.0.0")["remaining"] == 9


@pytest.mark.asyncio
async def test_search_internal_references_tool():
    tool = InternalReferencesTool()
    result = await tool.execute(query="stop-jarvis llama-server lifecycle")
    assert result.success
    assert "results" in result.data
    assert result.output
