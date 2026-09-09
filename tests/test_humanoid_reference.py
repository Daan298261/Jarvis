from __future__ import annotations

from app.agent.docs_first_grounding import search_internal_references


def test_humanoid_runtime_help_is_indexed_by_docs_first_grounding():
    hits = search_internal_references("How do I install the humanoid runtime?")

    assert hits
    assert hits[0].source_path.endswith("humanoid-runtime.md")
