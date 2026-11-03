"""Docs-first grounding ranks user help above RFC specs (trigger: RFC-0228 / #655).

The fixture is the RFC-0228 spec text from #655 @ efbbc533. It repeats
"install" and "runtime" hundreds of times, which made it outrank the
humanoid-runtime help page for a plain how-to question.
"""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from app.agent import docs_first_grounding as grounding
from app.agent.docs_first_grounding import (
    is_rfc_spec,
    query_targets_specs,
    requested_rfc_numbers,
    search_internal_references,
)
from app.tools.internal_references import InternalReferencesTool

FIXTURE = (
    Path(__file__).resolve().parent
    / "fixtures"
    / "docs_first"
    / "rfc-0228-installer-update-default-9b-idle-unload.md"
)
RFC_NAME = "0228-installer-update-default-9b-idle-unload.md"


@pytest.fixture
def rfc0228_indexed(tmp_path, monkeypatch):
    """Index the RFC-0228 spec as docs/rfcs/0228-*.md next to the real corpus."""
    rfc = tmp_path / "docs" / "rfcs" / RFC_NAME
    rfc.parent.mkdir(parents=True)
    shutil.copyfile(FIXTURE, rfc)
    real_roots = grounding._resolve_roots
    real_iter = grounding._iter_index_files

    def roots() -> list[Path]:
        return [*real_roots(), tmp_path.resolve()]

    def index(found_roots: list[Path]) -> list[Path]:
        files = [path for path in real_iter(found_roots) if path.name != RFC_NAME]
        return [*files, rfc.resolve()]

    monkeypatch.setattr(grounding, "_resolve_roots", roots)
    monkeypatch.setattr(grounding, "_iter_index_files", index)
    return rfc


def test_fixture_is_the_competing_installer_spec():
    text = FIXTURE.read_text(encoding="utf-8").lower()
    assert text.startswith("# rfc-0228")
    assert text.count("install") > 200
    assert "runtime" in text


def test_humanoid_help_ranks_first_with_rfc0228_indexed(rfc0228_indexed):
    hits = search_internal_references("How do I install the humanoid runtime?")

    assert hits
    assert hits[0].source_path.endswith("humanoid-runtime.md")


def test_rfc_is_down_weighted_not_dropped_for_help_questions(rfc0228_indexed):
    query = "How do I install the humanoid runtime?"
    terms = grounding._tokenize(query)
    rfc_text = rfc0228_indexed.read_text(encoding="utf-8")
    help_path = grounding.reference_pack_root() / "humanoid-runtime.md"
    help_text = help_path.read_text(encoding="utf-8")

    rfc_score = grounding._rank_score(rfc0228_indexed, rfc_text, terms, query)
    help_score = grounding._rank_score(help_path, help_text, terms, query)
    raw_rfc_score = grounding._score_document(rfc0228_indexed, rfc_text, terms)

    # Before the fix the spec's raw count beat the help page outright.
    assert raw_rfc_score > help_score
    # Now it still scores (stays rankable) but below the user-facing help.
    assert 0 < rfc_score < help_score


@pytest.mark.parametrize(
    "query",
    [
        "What does RFC-0228 say about idle unload?",
        "Which RFC covers the installer update mode?",
        "What does the spec say about the installer update and idle unload?",
        "Show me the proposal for the 9B default with idle unload",
    ],
)
def test_spec_questions_still_return_the_rfc_first(rfc0228_indexed, query):
    hits = search_internal_references(query)

    assert hits
    assert hits[0].source_path.endswith(RFC_NAME)


def test_named_rfc_number_beats_other_rfcs(rfc0228_indexed):
    hits = search_internal_references("rfc 228 installer runtime")

    assert hits[0].source_path.endswith(RFC_NAME)


def test_internal_references_tool_uses_the_same_ranking(rfc0228_indexed):
    import asyncio

    result = asyncio.run(InternalReferencesTool().execute(query="How do I install the humanoid runtime?"))

    assert result.success
    results = result.data["results"]
    assert results[0]["source_path"].endswith("humanoid-runtime.md")


def test_spec_intent_and_rfc_detection():
    assert query_targets_specs("What does RFC-0228 say?")
    assert query_targets_specs("which spec covers updates")
    assert query_targets_specs("the installer proposal")
    assert not query_targets_specs("How do I install the humanoid runtime?")
    assert not query_targets_specs("respect my settings")
    assert requested_rfc_numbers("RFC-0228 and rfc 60 and rfc_0003") == {228, 60, 3}
    assert is_rfc_spec(Path("/repo/docs/rfcs/0228-x.md"))
    assert not is_rfc_spec(Path("/repo/docs/INSTALL.md"))
    assert not is_rfc_spec(Path("/repo/project/jarvis/jarvis/internal/references/spec-summaries/rfc-0060.md"))
