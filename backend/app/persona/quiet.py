from __future__ import annotations

from ..config import AppSettings, load_settings


def is_quiet_or_dnd_active(settings: AppSettings | None = None) -> bool:
    """Hook stub for focus mode, quiet hours, and do-not-disturb.

    RFC-0055 will wire persona policy here. Until then this always returns False
    so chat TTS is governed only by ``tts.speak_chat_replies``.
    """
    return False


def should_speak_chat_reply(settings: AppSettings | None = None) -> bool:
    """Whether assistant chat replies should be spoken.

    Text replies are always shown; this only gates optional TTS playback.
    """
    current = settings or load_settings()
    if is_quiet_or_dnd_active(current):
        return False
    return bool(current.tts.speak_chat_replies)
