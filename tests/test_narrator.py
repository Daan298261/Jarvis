"""Plain-language task progress and outcomes — never speak tool dumps."""

from __future__ import annotations

from app.persona.narrator import (
    forget_task,
    outcome_phrase,
    plain_failure,
    progress_phrase,
    should_speak_progress,
)


def test_apps_progress_is_a_spoken_sentence():
    assert progress_phrase("apps", {"action": "open", "name": "steam"}) == "Opening Steam."
    assert progress_phrase("apps", {"action": "close", "name": "spotify"}) == "Closing Spotify."
    assert progress_phrase("python", {}) == "Working it out."
    assert progress_phrase("request_capability", {}) is None


def test_plain_failure_maps_tool_errors():
    assert "Steam" in plain_failure("No installed app matches 'Steam'")
    assert "administrator" in plain_failure("Access denied — needs the elevated backend")
    assert "same problem" in plain_failure("Step limit reached before verification")
    assert plain_failure("exit_code=1\n--- stdout ---\n") == "I couldn't finish that."


def test_success_outcome_strips_paths_and_markup():
    spoken = outcome_phrase(
        success=True,
        result=r"Opened **Steam** from C:\Program Files (x86)\Steam\steam.exe.",
    )
    assert "Steam" in spoken
    assert "\\" not in spoken
    assert "*" not in spoken


def test_failed_and_cancelled_outcomes():
    assert outcome_phrase(success=False, error="No installed app matches 'Steam'") == (
        "I couldn't find an app called Steam on this PC."
    )
    assert outcome_phrase(success=True, result="```python\nprint(1)\n```") == "That's done."
    assert outcome_phrase(success=False, cancelled=True) == "Okay, I stopped."


def test_progress_throttle_skips_repeats_and_respects_cap():
    forget_task("voice-1")
    assert should_speak_progress("voice-1", "Opening Steam.", now=100.0)
    assert not should_speak_progress("voice-1", "Opening Steam.", now=120.0)
    assert not should_speak_progress("voice-1", "Running that on the PC.", now=101.0)
    assert should_speak_progress("voice-1", "Running that on the PC.", now=107.0)
    forget_task("voice-1")
