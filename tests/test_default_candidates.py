from app.inference.candidate_routing import (
    candidate_keys_for_role,
    candidates_for_role,
    normalize_candidate_role,
)
from app.inference.default_candidates import (
    MODEL_CANDIDATES,
    PERSONALITY_PRESETS,
    RECOMMENDED_16GB_STACK,
    TTS_CANDIDATES,
    candidates_fitting_weights,
    get_model_candidate,
    get_personality_preset,
    list_model_candidates,
)


def test_primary_candidates_include_qwen38_and_lfm25():
    primary = {candidate.key for candidate in list_model_candidates("primary")}
    assert "qwen38-9b-heretic-q6" in primary
    assert "qwen38-9b-heretic-q8" in primary
    assert "lfm25-8b-a1b-uncensored-q6" in primary


def test_recommended_stack_keeps_kimi_out_of_default_path():
    assert RECOMMENDED_16GB_STACK["primary"] == "qwen38-9b-heretic-q6"
    assert RECOMMENDED_16GB_STACK["expert"] == "qwen36-35b-a3b-colibri-abliterated"
    assert "kimi" not in RECOMMENDED_16GB_STACK["primary"]


def test_all_normal_primary_candidates_are_uncensored():
    for candidate in list_model_candidates("primary"):
        assert candidate.uncensored is True


def test_weight_fit_is_not_confused_with_unknown_frontier_size():
    fitting = {candidate.key for candidate in candidates_fitting_weights(10.0)}
    assert "qwen38-9b-heretic-q8" in fitting
    assert "lfm25-8b-a1b-uncensored-q8" in fitting
    assert "kimi-k3-colibri" not in fitting


def test_small_and_micro_roles_exist():
    assert get_model_candidate("minicpm5-1b-abliterated").role == "micro"
    assert get_model_candidate("minicpm5-2b-abliterated").role == "small"


def test_candidate_route_aliases_keep_kimi_lab_only():
    assert normalize_candidate_role("brain") == "primary"
    assert normalize_candidate_role("translator") == "presentation"
    assert normalize_candidate_role("colibri_expert") == "expert"
    assert "kimi-k3-colibri" == candidate_keys_for_role("lab")[0]
    assert "kimi-k3-colibri" not in candidate_keys_for_role("primary")


def test_candidate_routes_return_models_in_preference_order():
    primary = candidates_for_role("primary")
    assert primary[0].key == "qwen38-9b-heretic-q6"
    assert primary[1].key == "qwen38-9b-heretic-q8"
    assert all(candidate.role == "primary" for candidate in primary)


def test_tts_quality_and_fallback_are_separate():
    assert TTS_CANDIDATES["chatterbox-multilingual-v3"].role == "quality"
    assert TTS_CANDIDATES["kokoro-82m"].role == "fallback"
    assert TTS_CANDIDATES["kokoro-82m"].loading_policy == "cpu-preferred"


def test_personality_defaults_to_concise_jarvis_dry():
    preset = get_personality_preset("unknown")
    assert preset.key == "jarvis_dry"
    assert preset.verbosity == "concise"
    assert 0.0 < preset.humor_frequency < 0.5


def test_personality_presets_are_bounded():
    for preset in PERSONALITY_PRESETS.values():
        for value in (
            preset.warmth,
            preset.formality,
            preset.humor_frequency,
            preset.dryness,
            preset.directness,
        ):
            assert 0.0 <= value <= 1.0


def test_candidate_keys_are_stable_and_unique():
    assert len(MODEL_CANDIDATES) == len(set(MODEL_CANDIDATES))
    for key, candidate in MODEL_CANDIDATES.items():
        assert candidate.key == key
