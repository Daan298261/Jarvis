"""The voice never reads markup, paths, code or reasoning traces aloud."""

from __future__ import annotations

import pytest

from app.tts.speech_safe import name_paths_and_links, speech_safe


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        (
            r"I opened **Steam** from C:\Program Files (x86)\Steam\steam.exe for you.",
            "I opened Steam from steam for you.",
        ),
        ("Steam is open, sir.", "Steam is open, sir."),
        ("## Done\n- Saved to `notes.txt`\n- See https://www.example.com/docs", "Done. Saved to notes.txt. See example.com"),
    ],
)
def test_speech_safe_rewrites_markup_and_paths(raw, expected):
    assert speech_safe(raw) == expected


def test_reasoning_trace_is_never_spoken():
    leak = "Thinking Process:\n\n1.  **Analyze the Request:**\n    *   **Role:** Jarvis, address owner as sir."
    assert speech_safe(leak) == ""


def test_jinja_and_prompt_errors_are_never_spoken():
    assert speech_safe("Error rendering prompt with jinja template: No user query found in messages.") == ""


def test_code_block_alone_is_not_spoken():
    assert speech_safe("```python\nprint(1)\n```") == ""


@pytest.mark.parametrize(
    "raw",
    [
        r"Saved it to \\nas\share\backup and C:\Users\me\notes.md.",
        "Copied /home/me/project/README.md to the backup folder.",
        "**Bold** and *italic* and __under__ with ~~strike~~.",
    ],
)
def test_no_symbol_is_left_for_the_voice_to_pronounce(raw):
    spoken = speech_safe(raw)
    assert spoken
    for symbol in ("\\", "*", "_", "#", "`", "~", "/"):
        assert symbol not in spoken, (symbol, spoken)


def test_name_paths_and_links_keeps_the_sentence():
    named = name_paths_and_links(r"Opened Steam from C:\Program Files (x86)\Steam\steam.exe.")
    assert "Opened Steam from steam." in named or "steam" in named.lower()
    assert "C:" not in named
