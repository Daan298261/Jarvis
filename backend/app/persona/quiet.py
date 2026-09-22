from __future__ import annotations

from ..config import AppSettings, load_settings


def is_quiet_or_dnd_active(settings: AppSettings | None = None) -> bool:
    """Do-not-disturb flag from RFC-0055 commentary settings (chat TTS gate)."""
    current = settings or load_settings()
    return bool(current.social_commentary.do_not_disturb)


def should_speak_chat_reply(settings: AppSettings | None = None) -> bool:
    """Whether assistant chat replies should be spoken.

    Text replies are always shown; this only gates optional TTS playback.
    """
    current = settings or load_settings()
    if is_quiet_or_dnd_active(current):
        return False
    return bool(current.tts.speak_chat_replies)
