from __future__ import annotations

from app.persona.session_personality import (
    detect_mode_from_text,
    maybe_switch_from_owner_message,
    set_active_mode,
)


def test_detect_coding_session():
    assert detect_mode_from_text("Anzu, start a coding session") == "coding"
    assert detect_mode_from_text("back to general chat") == "core"


def test_switch_and_active_mode():
    maybe_switch_from_owner_message("let's code this module")
    mode = set_active_mode("coding")
    assert mode.id == "coding"
    set_active_mode("core")
