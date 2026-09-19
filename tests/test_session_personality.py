from __future__ import annotations

from app.persona.pack import build_persona_instructions
from app.persona.session_personality import (
    detect_mode_from_text,
    maybe_switch_from_owner_message,
    reset_session_personality_for_tests,
    session_personality_system_addendum,
    set_active_mode,
)


def setup_function() -> None:
    reset_session_personality_for_tests()


def test_detect_coding_session():
    assert detect_mode_from_text("Anzu, start a coding session") == "coding"
    assert detect_mode_from_text("back to general chat") == "core"


def test_detect_research_and_concise():
    assert detect_mode_from_text("switch to research mode") == "research"
    assert detect_mode_from_text("be concise please") == "concise"


def test_switch_and_active_mode():
    maybe_switch_from_owner_message("let's code this module")
    mode = set_active_mode("coding")
    assert mode.id == "coding"
    assert "coding" in session_personality_system_addendum().lower()
    set_active_mode("core")


def test_default_alias_maps_to_core():
    mode = set_active_mode("default")
    assert mode.id == "core"


def test_persona_pack_includes_session_addendum():
    set_active_mode("coding", persist_dialogue=False)
    text = build_persona_instructions()
    assert "Session mode: coding" in text
