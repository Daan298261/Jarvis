"""Docs-first grounding ranks user help above RFC specs (trigger: RFC-0228 / #655).

Long RFC specs repeat "install" and "runtime" hundreds of times, which made
RFC-0228 outrank the humanoid-runtime help page for a plain how-to question.
The competing spec is generated here, so the tests do not depend on (or rot
with) the text of any real RFC; when the live ``docs/rfcs/0228-*`` file exists
it is also checked.
"""

from __future__ import annotations

import asyncio
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

RFC_NAME = "9990-installer-update-default-model-idle-unload.md"
HELP_QUERY = "How do I install the humanoid runtime?"
LIVE_0228 = sorted((Path(__file__).resolve().parents[1] / "docs" / "rfcs").glob("0228-*.md"))


def competing_installer_spec(repeats: int = 300) -> str:
    """A synthetic installer spec that out-counts the help page on install/runtime words."""
    lines = [
        "# RFC-9990: Installer update mode, default model and idle unload",
        "",
        "**Status:** Proposed",
        "",
    ]
    for idx in range(repeats):
        lines.append(
            f"S{idx}: the installer must install the humanoid runtime and update the runtime "
            "install state; the runtime install step unloads the idle default model."
        )
    return "\n".join(lines) + "\n"


def only_in_rfc_spec() -> str:
    return (
        "# RFC-9991: Flux capacitor calibration\n\n**Status:** Proposed\n\n"
        "Calibrate the flux capacitor with the calibration wizard. "
        "The flux capacitor calibration runs at startup.\n"
    )


def _index_extra_rfcs(monkeypatch, tmp_path, rfcs: dict[str, str]) -> dict[str, Path]:
    """Index synthetic RFCs as docs/rfcs/<name> next to the real corpus."""
    written: dict[str, Path] = {}
    for name, body in rfcs.items():
        path = tmp_path / "docs" / "rfcs" / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(body, encoding="utf-8")
        written[name] = path.resolve()
    real_roots = grounding._resolve_roots
    real_iter = grounding._iter_index_files

    def roots() -> list[Path]:
        return [*real_roots(), tmp_path.resolve()]

    def index(found_roots: list[Path]) -> list[Path]:
        return [*real_iter(found_roots), *written.values()]

    monkeypatch.setattr(grounding, "_resolve_roots", roots)
    monkeypatch.setattr(grounding, "_iter_index_files", index)
    return written


@pytest.fixture
def rfc_indexed(tmp_path, monkeypatch) -> Path:
    return _index_extra_rfcs(monkeypatch, tmp_path, {RFC_NAME: competing_installer_spec()})[RFC_NAME]


@pytest.fixture
def rfc_only_indexed(tmp_path, monkeypatch) -> Path:
    name = "9991-flux-capacitor-calibration.md"
    return _index_extra_rfcs(monkeypatch, tmp_path, {name: only_in_rfc_spec()})[name]


def test_synthetic_spec_really_competes_with_the_help_page(rfc_indexed):
    terms = grounding._tokenize(HELP_QUERY)
    help_path = grounding.reference_pack_root() / "humanoid-runtime.md"
    help_text = help_path.read_text(encoding="utf-8")
    rfc_text = rfc_indexed.read_text(encoding="utf-8")

    # Guard against rot: the raw count must beat the help page, otherwise the
    # ranking tests below would pass without exercising the fix.
    assert grounding._score_document(rfc_indexed, rfc_text, terms) > grounding._score_document(
        help_path, help_text, terms
    )


def test_humanoid_help_ranks_first_with_competing_rfc_indexed(rfc_indexed):
    hits = search_internal_references(HELP_QUERY)

    assert hits
    assert hits[0].source_path.endswith("humanoid-runtime.md")


def test_rfc_is_down_weighted_not_dropped_for_help_questions(rfc_indexed):
    terms = grounding._tokenize(HELP_QUERY)
    rfc_text = rfc_indexed.read_text(encoding="utf-8")
    help_path = grounding.reference_pack_root() / "humanoid-runtime.md"
    help_text = help_path.read_text(encoding="utf-8")

    rfc_score = grounding._rank_score(rfc_indexed, rfc_text, terms, HELP_QUERY)
    help_score = grounding._rank_score(help_path, help_text, terms, HELP_QUERY)

    assert 0 < rfc_score < help_score


@pytest.mark.parametrize(
    "query",
    [
        "What does RFC-9990 say about idle unload?",
        "Which RFC covers the installer update mode?",
        "What does the spec say about the installer update and idle unload?",
        "Show me the proposal for the default model with idle unload",
        "the spec for the installer update default model idle unload",
    ],
)
def test_spec_questions_still_return_the_rfc_first(rfc_indexed, query):
    hits = search_internal_references(query)

    assert hits
    assert hits[0].source_path.endswith(RFC_NAME)


def test_named_rfc_number_beats_other_rfcs(rfc_indexed):
    hits = search_internal_references("rfc 9990 installer runtime")

    assert hits[0].source_path.endswith(RFC_NAME)


def test_internal_references_tool_uses_the_same_ranking(rfc_indexed):
    result = asyncio.run(InternalReferencesTool().execute(query=HELP_QUERY))

    assert result.success
    assert result.data["results"][0]["source_path"].endswith("humanoid-runtime.md")


@pytest.mark.skipif(not LIVE_0228, reason="docs/rfcs/0228-* is not on this branch yet")
def test_live_rfc_0228_does_not_outrank_the_humanoid_help_page():
    hits = search_internal_references(HELP_QUERY)

    assert hits[0].source_path.endswith("humanoid-runtime.md")
    spec_hits = search_internal_references("What does RFC-0228 say about idle unload?")
    assert spec_hits[0].source_path == LIVE_0228[0].relative_to(grounding.repo_root()).as_posix()


# --- D1 item 2: a feature documented only in an RFC must still surface -----------


def test_feature_documented_only_in_an_rfc_surfaces_for_how_to_questions(rfc_only_indexed):
    query = "how do I run the flux capacitor calibration wizard"
    hits = search_internal_references(query)

    assert hits
    assert hits[0].source_path.endswith("9991-flux-capacitor-calibration.md")


def test_rfc_only_fallback_uses_full_rank_not_the_down_weighted_score(rfc_only_indexed):
    query = "how do I run the flux capacitor calibration wizard"
    terms = grounding._tokenize(query)
    text = rfc_only_indexed.read_text(encoding="utf-8")

    down_weighted = grounding._rank_score(rfc_only_indexed, text, terms, query)
    full = grounding._rank_score(rfc_only_indexed, text, terms, query, rfc_only_match=True)

    assert full > down_weighted > 0


def test_fallback_does_not_fire_when_a_user_doc_covers_the_question(rfc_indexed):
    # humanoid-runtime.md covers every term of the question, so the competing
    # RFC stays down-weighted (this is the #655 regression).
    hits = search_internal_references(HELP_QUERY)

    assert hits[0].source_path.endswith("humanoid-runtime.md")


# --- D1 item 1: the bare word "spec" is not spec intent -------------------------


@pytest.mark.parametrize(
    "query",
    [
        "what are the specs of my GPU",
        "what are the specs of my phone",
        "phone specs for the pixel",
        "specs of my PC",
        "what's the spec of my laptop",
        "what are the specs of the RTX 4090",
        "show me the specifications of my computer",
        "my graphics card spec",
        "specs for the iPhone 16",
        "spec sheet of my laptop",
        "system specs of this PC",
        "what are the specs of the new phone",
        "what are the specs of my phone",
        "How do I install the humanoid runtime?",
        "respect my settings",
    ],
)
def test_hardware_and_bare_spec_words_are_not_spec_intent(query):
    assert not query_targets_specs(query)


@pytest.mark.parametrize(
    "query",
    [
        "What does RFC-0228 say?",
        "which rfc covers updates",
        "the spec for the installer update",
        "what does the spec say about idle unload",
        "which spec covers updates",
        "open the specification document for model downloads",
        "the installer proposal",
        "the design doc for engine modes",
        "show me the spec of the engine modes",
        # Product-feature words are not hardware vetoes (D1 round 2).
        "where is the spec for the android companion",
        "what does the spec say about the phone companion",
        "what does the spec say about the camera feature",
        "what does the spec say about the display settings",
        "what does the spec say about the device pairing",
        "what does the spec say about the screen capture",
        "what does the specification say about the card layout",
        # Article is optional.
        "technical spec for the swarm",
        "feature spec for persona",
        "spec for the swarm",
        "spec for keep warm",
    ],
)
def test_rfc_and_spec_document_phrasing_is_spec_intent(query):
    assert query_targets_specs(query)


@pytest.mark.parametrize(
    "query",
    ["what are the specs of my GPU", "specs of my PC", "phone specs for the pixel"],
)
def test_hardware_spec_questions_do_not_boost_rfcs(rfc_indexed, query):
    hits = search_internal_references(query, max_results=50)

    assert not any(hit.source_path.endswith(RFC_NAME) for hit in hits[:5])
    ranked = [hit.source_path for hit in hits]
    # No RFC is boosted to the top by the word "spec".
    assert not (ranked and ranked[0].startswith("docs/rfcs/"))


@pytest.mark.parametrize(
    "query",
    [
        "where is the spec for the android companion",
        "what does the spec say about the android companion",
    ],
)
def test_android_companion_spec_question_surfaces_the_companion_rfcs(query):
    hits = search_internal_references(query, max_results=8)
    sources = [hit.source_path for hit in hits]

    for number in ("0204-", "0139-", "0059-"):
        assert any(f"docs/rfcs/{number}" in src for src in sources), (number, sources)
    assert sources[0].startswith("docs/rfcs/"), sources


def test_rfc_number_parsing_and_rfc_path_detection():
    assert requested_rfc_numbers("RFC-0228 and rfc 60 and rfc_0003") == {228, 60, 3}
    assert is_rfc_spec(Path("/repo/docs/rfcs/0228-x.md"))
    assert not is_rfc_spec(Path("/repo/docs/INSTALL.md"))
    assert not is_rfc_spec(Path("/repo/project/jarvis/jarvis/internal/references/spec-summaries/rfc-0060.md"))
