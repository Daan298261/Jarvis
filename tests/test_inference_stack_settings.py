from app.config import AppSettings, DialogueSettings, TtsSettings
from app.inference.default_candidates import RECOMMENDED_16GB_STACK


def test_dialogue_defaults_are_concise_and_configurable():
    settings = DialogueSettings()
    assert settings.enabled is True
    assert settings.verbosity == "auto"
    assert settings.auto_preference == "concise"
    assert settings.personality_preset == "jarvis_dry"
    assert settings.translate_only_when_needed is True
    assert settings.preserve_structured_content is True


def test_dialogue_rejects_out_of_range_personality_values():
    try:
        DialogueSettings(humor_frequency=1.1)
    except ValueError:
        pass
    else:
        raise AssertionError("humor_frequency > 1 must be rejected")


def test_tts_defaults_preserve_primary_vram_headroom():
    settings = TtsSettings()
    assert settings.engine == "auto"
    assert settings.quality_engine == "chatterbox_multilingual_v3"
    assert settings.fallback_engine == "kokoro"
    assert settings.loading_policy == "lazy"
    assert settings.prefer_cpu_fallback is True


def test_app_settings_include_dialogue_and_tts():
    settings = AppSettings()
    assert settings.dialogue.personality_preset == "jarvis_dry"
    assert settings.tts.fallback_engine == "kokoro"


def test_recommended_stack_does_not_promote_unbenchmarked_kimi():
    assert RECOMMENDED_16GB_STACK["primary"] == "qwen38-9b-heretic-q6"
    assert RECOMMENDED_16GB_STACK["tts_fallback"] == "kokoro-82m"
