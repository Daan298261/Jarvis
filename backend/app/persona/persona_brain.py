"""Optional main/brain runtime profiles bound to named personas."""

from __future__ import annotations

UMI_OLLAMA_MODEL = "hf.co/TheCidSama/Qwen3.5-9b-Claude-4.8-Opus-reasoning"

# RuntimeProfile.name values shipped via model_stack MODEL_CATALOG.
PERSONA_BRAIN_RUNTIME: dict[str, str] = {
    "umi": "umi-opus-9b",
}


def brain_runtime_name_for_persona(persona_id: str) -> str | None:
    key = (persona_id or "").strip().lower()
    return PERSONA_BRAIN_RUNTIME.get(key)


def reflex_verify_brain_runtime(
    *,
    persona_id: str,
    runtime_name: str,
    user_message: str = "",
) -> bool:
    """Laya/JEV persona_model_routing check before hotswapping a persona brain."""
    expected = brain_runtime_name_for_persona(persona_id)
    if not expected or expected != runtime_name:
        return True
    try:
        from ..decision.surfaces import answer_value, privacy_for_tier, route_persona_model
        from ..decision.tier import resolve_status
    except Exception:
        return True

    status = resolve_status()
    candidates = tuple(dict.fromkeys([expected, "balanced", "bootstrap", "ornith_9b"]))
    reflex = route_persona_model(
        user_message=user_message or f"Use the dedicated brain for persona {persona_id}.",
        candidates=list(candidates),
        preferred_profile=expected,
        active_persona=persona_id,
        privacy=privacy_for_tier(str(status.get("decision_tier") or "local")),
    )
    pick = answer_value(reflex, "route_profile")
    return pick == expected
