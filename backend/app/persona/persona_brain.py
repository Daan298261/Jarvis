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
