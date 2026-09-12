from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Literal


ModelRole = Literal[
    "micro",
    "small",
    "primary",
    "presentation",
    "expert",
    "lab",
]


@dataclass(frozen=True)
class ModelCandidate:
    """Advisory local-model candidate used by RFC-0063.

    Candidates are deliberately separate from the active runtime profile list.
    A candidate must win the local Jarvis benchmark before it can be promoted to
    the default runtime. This avoids silently replacing a proven model based on
    external benchmark reputation alone.
    """

    key: str
    label: str
    model_id: str
    role: ModelRole
    runtime: str
    quantization: str
    weight_gb: float | None
    context_limit: int
    uncensored: bool
    license_id: str
    recommended: bool = False
    benchmark_required: bool = True
    notes: str = ""

    def as_dict(self) -> dict[str, object]:
        return asdict(self)


@dataclass(frozen=True)
class TtsCandidate:
    key: str
    label: str
    role: Literal["quality", "fallback", "low-latency"]
    model_id: str
    license_id: str
    loading_policy: Literal["resident", "lazy", "cpu-preferred"]
    notes: str = ""

    def as_dict(self) -> dict[str, object]:
        return asdict(self)


@dataclass(frozen=True)
class PersonalityPreset:
    key: str
    label: str
    verbosity: Literal["very-short", "concise", "balanced", "detailed", "exhaustive", "auto"]
    warmth: float
    formality: float
    humor_frequency: float
    dryness: float
    directness: float

    def as_dict(self) -> dict[str, object]:
        return asdict(self)


MODEL_CANDIDATES: dict[str, ModelCandidate] = {
    "qwen38-9b-heretic-q6": ModelCandidate(
        key="qwen38-9b-heretic-q6",
        label="Qwen3.8 9B Distill Uncensored — Q6",
        model_id="petruhonk/Qwen3.8-9B-Distill-uncensored-heretic",
        role="primary",
        runtime="llama.cpp/lm-studio",
        quantization="Q6_K",
        weight_gb=7.7,
        context_limit=32768,
        uncensored=True,
        license_id="apache-2.0",
        recommended=True,
        notes="First primary benchmark candidate; balanced residency target for 16 GB VRAM.",
    ),
    "qwen38-9b-heretic-q8": ModelCandidate(
        key="qwen38-9b-heretic-q8",
        label="Qwen3.8 9B Distill Uncensored — Q8",
        model_id="petruhonk/Qwen3.8-9B-Distill-uncensored-heretic-GGUF",
        role="primary",
        runtime="llama.cpp/lm-studio",
        quantization="Q8_0",
        weight_gb=9.79,
        context_limit=32768,
        uncensored=True,
        license_id="apache-2.0",
        notes="Quality-reference primary candidate; tighter KV/TTS headroom than Q6.",
    ),
    "lfm25-8b-a1b-uncensored-q6": ModelCandidate(
        key="lfm25-8b-a1b-uncensored-q6",
        label="LFM2.5 8B-A1B Uncensored — Q6",
        model_id="zaakirio/LFM2.5-8B-A1B-Uncensored-GGUF",
        role="primary",
        runtime="llama.cpp/lm-studio",
        quantization="Q6_K",
        weight_gb=6.96,
        context_limit=32768,
        uncensored=True,
        license_id="lfm-1.0",
        notes="Fast-primary challenger; ~1.5B active params/token. Review redistribution license before bundling.",
    ),
    "lfm25-8b-a1b-uncensored-q8": ModelCandidate(
        key="lfm25-8b-a1b-uncensored-q8",
        label="LFM2.5 8B-A1B Uncensored — Q8",
        model_id="zaakirio/LFM2.5-8B-A1B-Uncensored-GGUF",
        role="primary",
        runtime="llama.cpp/lm-studio",
        quantization="Q8_0",
        weight_gb=9.01,
        context_limit=32768,
        uncensored=True,
        license_id="lfm-1.0",
        notes="Quality reference for the LFM fast-primary candidate.",
    ),
    "minicpm5-2b-abliterated": ModelCandidate(
        key="minicpm5-2b-abliterated",
        label="MiniCPM5 2B Abliterated",
        model_id="SC117/MiniCPM5-2B-abliterated-FIT-GGUF",
        role="small",
        runtime="llama.cpp/lm-studio",
        quantization="benchmark-best-fit",
        weight_gb=2.7,
        context_limit=32768,
        uncensored=True,
        license_id="apache-2.0-base",
        recommended=True,
        notes="Preferred small-worker benchmark; strong official agent/tool results for its size.",
    ),
    "minicpm5-1b-abliterated": ModelCandidate(
        key="minicpm5-1b-abliterated",
        label="MiniCPM5 1B Abliterated",
        model_id="huihui-ai/Huihui-MiniCPM5-1B-abliterated",
        role="micro",
        runtime="llama.cpp/lm-studio",
        quantization="Q8-class",
        weight_gb=1.2,
        context_limit=32768,
        uncensored=True,
        license_id="apache-2.0-base",
        recommended=True,
        notes="Always-on router/event-triage candidate; benchmark against 2B before assigning multiple resident models.",
    ),
    "nemotron3-nano-4b-uncensored": ModelCandidate(
        key="nemotron3-nano-4b-uncensored",
        label="Nemotron3 Nano 4B Uncensored",
        model_id="Unrestricted/Nemotron3-Nano-4B-Uncensored-HauhauCS-Aggressive",
        role="small",
        runtime="llama.cpp/lm-studio",
        quantization="Q8_K_P",
        weight_gb=4.4,
        context_limit=32768,
        uncensored=True,
        license_id="check-upstream",
        notes="Alternative compact general worker; compare tool reliability with MiniCPM5-2B.",
    ),
    "qwen35-08b-presentation": ModelCandidate(
        key="qwen35-08b-presentation",
        label="Qwen3.5 0.8B Abliterated Presentation Worker",
        model_id="mradermacher/Huihui-Qwen3.5-0.8B-abliterated-GGUF",
        role="presentation",
        runtime="llama.cpp/lm-studio",
        quantization="Q8-class",
        weight_gb=1.0,
        context_limit=16384,
        uncensored=True,
        license_id="check-upstream",
        recommended=True,
        notes="First language/verbosity/personality candidate; must preserve structured spans byte-exactly.",
    ),
    "qwen36-35b-a3b-colibri-abliterated": ModelCandidate(
        key="qwen36-35b-a3b-colibri-abliterated",
        label="Qwen3.6 35B-A3B Abliterated via Colibri",
        model_id="wangzhang/Qwen3.6-35B-A3B-abliterated-v2",
        role="expert",
        runtime="colibri/openai-compat",
        quantization="int4-gs64-compatible-experiment",
        weight_gb=20.0,
        context_limit=32768,
        uncensored=True,
        license_id="apache-2.0",
        recommended=True,
        notes="Heavy-local challenger: ~3B active/token. Requires Colibri conversion/compatibility and single-5070-Ti benchmark.",
    ),
    "kimi-k3-colibri": ModelCandidate(
        key="kimi-k3-colibri",
        label="Kimi K3 via Colibri",
        model_id="moonshotai/Kimi-K3",
        role="lab",
        runtime="colibri/openai-compat",
        quantization="native-MXFP4-experts",
        weight_gb=None,
        context_limit=32768,
        uncensored=False,
        license_id="check-upstream",
        notes="Frontier local lab/expert only; 2.8T total / 104B active is not an interactive default on current hardware.",
    ),
}


TTS_CANDIDATES: dict[str, TtsCandidate] = {
    "chatterbox-multilingual-v3": TtsCandidate(
        key="chatterbox-multilingual-v3",
        label="Chatterbox Multilingual V3",
        role="quality",
        model_id="resemble-ai/chatterbox",
        license_id="mit",
        loading_policy="lazy",
        notes="Primary natural multilingual/configurable-voice candidate; benchmark under RFC-0056.",
    ),
    "kokoro-82m": TtsCandidate(
        key="kokoro-82m",
        label="Kokoro 82M",
        role="fallback",
        model_id="hexgrad/Kokoro-82M",
        license_id="apache-2.0",
        loading_policy="cpu-preferred",
        notes="Tiny low-latency fallback so voice mode does not consume primary-model VRAM.",
    ),
    "chatterbox-turbo": TtsCandidate(
        key="chatterbox-turbo",
        label="Chatterbox Turbo",
        role="low-latency",
        model_id="resemble-ai/chatterbox-turbo",
        license_id="mit",
        loading_policy="lazy",
        notes="Optional low-latency expressive English voice candidate.",
    ),
}


PERSONALITY_PRESETS: dict[str, PersonalityPreset] = {
    "minimal": PersonalityPreset("minimal", "Minimal", "very-short", 0.10, 0.70, 0.0, 0.0, 1.0),
    "professional": PersonalityPreset("professional", "Professional", "concise", 0.20, 0.85, 0.0, 0.0, 0.90),
    "jarvis_dry": PersonalityPreset("jarvis_dry", "Jarvis / Dry", "concise", 0.35, 0.65, 0.12, 0.35, 0.90),
    "friendly": PersonalityPreset("friendly", "Friendly", "concise", 0.70, 0.45, 0.15, 0.10, 0.70),
}


RECOMMENDED_16GB_STACK = {
    "primary": "qwen38-9b-heretic-q6",
    "primary_quality_reference": "qwen38-9b-heretic-q8",
    "fast_primary_challenger": "lfm25-8b-a1b-uncensored-q6",
    "micro": "minicpm5-1b-abliterated",
    "small": "minicpm5-2b-abliterated",
    "presentation": "qwen35-08b-presentation",
    "expert": "qwen36-35b-a3b-colibri-abliterated",
    "tts_quality": "chatterbox-multilingual-v3",
    "tts_fallback": "kokoro-82m",
}


def list_model_candidates(role: ModelRole | None = None) -> list[ModelCandidate]:
    candidates = list(MODEL_CANDIDATES.values())
    if role is None:
        return candidates
    return [candidate for candidate in candidates if candidate.role == role]


def get_model_candidate(key: str) -> ModelCandidate | None:
    return MODEL_CANDIDATES.get((key or "").strip().lower())


def candidates_fitting_weights(
    max_weight_gb: float,
    *,
    role: ModelRole | None = None,
) -> list[ModelCandidate]:
    """Return candidates whose *weights* fit the supplied budget.

    This is intentionally not a VRAM-fit guarantee: KV cache, runtime workspace,
    vision and OS overhead must be reserved separately by the hardware gate.
    """

    return [
        candidate
        for candidate in list_model_candidates(role)
        if candidate.weight_gb is not None and candidate.weight_gb <= max_weight_gb
    ]


def get_personality_preset(key: str) -> PersonalityPreset:
    normalized = (key or "jarvis_dry").strip().lower().replace("-", "_")
    return PERSONALITY_PRESETS.get(normalized, PERSONALITY_PRESETS["jarvis_dry"])
