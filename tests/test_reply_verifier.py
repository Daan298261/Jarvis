from __future__ import annotations

from app.persona.reply_verifier import materially_different


def test_materially_different_detects_change():
    assert materially_different("It is 18 degrees.", "It is 11 degrees.")
    assert not materially_different("Hello sir.", "hello sir.")
    assert not materially_different("Long answer about ports.", "Long answer about ports.")
