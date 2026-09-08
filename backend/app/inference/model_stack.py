from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any

from .runtime_profiles import (
    PRIVACY_LOCAL_ONLY,
    PRIVACY_PUBLIC_REMOTE,
    RuntimeProfile,
)


@dataclass(frozen=True)
class SpecialistModel:
    """Recommended model for a Jarvis role.

    The catalog is advisory. Capability/specialization tags are the stable
    contract; administrators may replace any concrete model without changing
    role logic. ``manual_gate`` marks recommendations that generic Jarvis
    routing must not operationalize automatically.
    """

    key: str
    runtime_profile_name: str
    label: str
    model_id: str
    role: str
    provider: str
    endpoint: str
    context_limit: int
    quantization: str
    capability_tags: tuple[str, ...]
    specialization_tags: tuple[str, ...]
    is_local: bool
    privacy_class: str
    enabled_by_default: bool
    description: str = ""
    ship_runtime_template: bool = True
    manual_gate: bool = False

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)

    def runtime_profile(self) -> RuntimeProfile | None:
        if not self.ship_runtime_template:
            return None
        return RuntimeProfile(
            id=f"recommended-{self.runtime_profile_name}",
            name=self.runtime_profile_name,
            label=self.label,
            model=self.model_id,
            provider=self.provider,
            endpoint=self.endpoint,
            context_limit=self.context_limit,
            quantization=self.quantization,
            privacy_class=self.privacy_class,
            cost_ceiling_usd=0.0 if self.is_local else None,
            capability_tags=self.capability_tags,
            model_profile=None,
            specialization_tags=self.specialization_tags,
            is_local=self.is_local,
            description=self.description,
            enabled=self.enabled_by_default,
        )


@dataclass(frozen=True)
class RoleRoutingSpec:
    role: str
    preferred_profiles: tuple[str, ...]
    required_capabilities: tuple[str, ...]
    specialization: str | None


MODEL_CATALOG: dict[str, SpecialistModel] = {
    "ornith-orchestrator": SpecialistModel(
        key="ornith-orchestrator",
        runtime_profile_name="ornith_9b",
        label="Ornith 1.5 9B",
        model_id="ornith-ai/Ornith-1.5-9B",
        role="orchestrator",
        provider="local-llama",
        endpoint="127.0.0.1:8088",
        context_limit=32768,
        quantization="Q8_0",
        capability_tags=("llm_inference", "text", "agentic", "tool-use", "vision"),
        specialization_tags=("orchestration", "agentic"),
        is_local=True,
        privacy_class=PRIVACY_LOCAL_ONLY,
        enabled_by_default=True,
        description="Always-on orchestration and tool-use candidate.",
        ship_runtime_template=False,
    ),
    "qwen38-leader": SpecialistModel(
        key="qwen38-leader",
        runtime_profile_name="qwen38-27b",
        label="Qwen3.8 27B Leader",
        model_id="Qwen/Qwen3.8-27B",
        role="leader",
        provider="openai-compat",
        endpoint="http://127.0.0.1:8091/v1",
        context_limit=32768,
        quantization="configure-local",
        capability_tags=(
            "llm_inference",
            "text",
            "high-quality",
            "agentic",
            "coding",
            "vision",
            "computer-use",
        ),
        specialization_tags=("leader", "reasoning", "coding"),
        is_local=True,
        privacy_class=PRIVACY_LOCAL_ONLY,
        enabled_by_default=False,
        description=(
            "Primary heavyweight local/hybrid leader. Disabled until an OpenAI-compatible "
            "local endpoint and suitable quantization are configured."
        ),
    ),
    "redsage-blue": SpecialistModel(
        key="redsage-blue",
        runtime_profile_name="redsage-8b",
        label="RedSage Qwen3 8B Blue Team",
        model_id="RISys-Lab/RedSage-Qwen3-8B-DPO",
        role="blue-team",
        provider="openai-compat",
        endpoint="http://127.0.0.1:8092/v1",
        context_limit=32768,
        quantization="configure-local",
        capability_tags=(
            "llm_inference",
            "text",
            "cybersecurity",
            "blue-team",
            "soc",
            "threat-analysis",
        ),
        specialization_tags=("blue-team", "soc", "threat-analysis"),
        is_local=True,
        privacy_class=PRIVACY_LOCAL_ONLY,
        enabled_by_default=False,
        description="Local SOC/blue-team specialist. Password-gated and disabled until its serving endpoint is configured.",
    ),
    "imperum-dfir": SpecialistModel(
        key="imperum-dfir",
        runtime_profile_name="imperum-cyber",
        label="Imperum CybersecurityLLM DFIR",
        model_id="IMPERUM/Imperum-CybersecurityLLM-v1.0-GGUF",
        role="dfir",
        provider="openai-compat",
        endpoint="http://127.0.0.1:8093/v1",
        context_limit=32768,
        quantization="Q4_K_M",
        capability_tags=(
            "llm_inference",
            "text",
            "high-quality",
            "cybersecurity",
            "dfir",
            "detection-engineering",
        ),
        specialization_tags=("dfir", "blue-team", "reasoning"),
        is_local=True,
        privacy_class=PRIVACY_LOCAL_ONLY,
        enabled_by_default=False,
        description="Deeper DFIR/detection-engineering consult model; password-gated with the Blue security role.",
    ),
    "deephat-red": SpecialistModel(
        key="deephat-red",
        runtime_profile_name="deephat-7b",
        label="DeepHat V1 7B Red Team",
        model_id="DeepHat/DeepHat-V1-7B",
        role="red-team",
        provider="openai-compat",
        endpoint="http://127.0.0.1:8094/v1",
        context_limit=32768,
        quantization="configure-local",
        capability_tags=(
            "llm_inference",
            "text",
            "cybersecurity",
            "red-team",
            "code-security",
            "coding",
        ),
        specialization_tags=("red-team", "code-security"),
        is_local=True,
        privacy_class=PRIVACY_LOCAL_ONLY,
        enabled_by_default=False,
        description=(
            "Password-gated Red Team model template. Password unlock is only an operator "
            "factor; role routing still requires explicit manual/case authorization."
        ),
        ship_runtime_template=True,
        manual_gate=True,
    ),
    "frontier-general": SpecialistModel(
        key="frontier-general",
        runtime_profile_name="frontier-general",
        label="Provider-configured Frontier General",
        model_id="provider-configured",
        role="frontier",
        provider="openai-compat",
        endpoint="",
        context_limit=32768,
        quantization="remote",
        capability_tags=("llm_inference", "text", "high-quality", "reasoning"),
        specialization_tags=("frontier", "reasoning"),
        is_local=False,
        privacy_class=PRIVACY_PUBLIC_REMOTE,
        enabled_by_default=False,
        description="Placeholder for GPT/Claude-class escalation configured by the administrator.",
        ship_runtime_template=False,
    ),
    "cheap-frontier": SpecialistModel(
        key="cheap-frontier",
        runtime_profile_name="cheap-frontier",
        label="Provider-configured Cost-efficient Frontier",
        model_id="provider-configured",
        role="cheap-frontier",
        provider="openai-compat",
        endpoint="",
        context_limit=32768,
        quantization="remote",
        capability_tags=("llm_inference", "text", "reasoning", "agentic"),
        specialization_tags=("cheap-frontier", "reasoning"),
        is_local=False,
        privacy_class=PRIVACY_PUBLIC_REMOTE,
        enabled_by_default=False,
        description="Placeholder for GLM/DeepSeek-class cost-efficient remote escalation.",
        ship_runtime_template=False,
    ),
}


ROLE_SPECS: dict[str, RoleRoutingSpec] = {
    "orchestrator": RoleRoutingSpec(
        role="orchestrator",
        preferred_profiles=("ornith_9b", "balanced", "fast"),
        required_capabilities=("llm_inference", "text"),
        specialization="orchestration",
    ),
    "leader": RoleRoutingSpec(
        role="leader",
        preferred_profiles=("qwen38-27b", "ornith_35b", "expert"),
        required_capabilities=("llm_inference", "text"),
        specialization="leader",
    ),
    "blue-team": RoleRoutingSpec(
        role="blue-team",
        preferred_profiles=("redsage-8b",),
        required_capabilities=("llm_inference", "cybersecurity", "blue-team"),
        specialization="blue-team",
    ),
    "dfir": RoleRoutingSpec(
        role="dfir",
        preferred_profiles=("imperum-cyber", "redsage-8b"),
        required_capabilities=("llm_inference", "cybersecurity", "dfir"),
        specialization="dfir",
    ),
    "red-team": RoleRoutingSpec(
        role="red-team",
        preferred_profiles=("deephat-7b",),
        required_capabilities=("llm_inference", "cybersecurity", "red-team"),
        specialization="red-team",
    ),
    "frontier": RoleRoutingSpec(
        role="frontier",
        preferred_profiles=("frontier-general",),
        required_capabilities=("llm_inference", "text"),
        specialization="frontier",
    ),
    "cheap-frontier": RoleRoutingSpec(
        role="cheap-frontier",
        preferred_profiles=("cheap-frontier",),
        required_capabilities=("llm_inference", "text"),
        specialization="cheap-frontier",
    ),
}

ROLE_ALIASES = {
    "general": "orchestrator",
    "orchestration": "orchestrator",
    "scheduler": "orchestrator",
    "tool-caller": "orchestrator",
    "senior-worker": "leader",
    "coding": "leader",
    "computer-use": "leader",
    "soc": "blue-team",
    "blue": "blue-team",
    "defensive-security": "blue-team",
    "forensics": "dfir",
    "incident-response": "dfir",
    "red": "red-team",
    "pentest": "red-team",
}


def normalize_role(role: str) -> str:
    key = (role or "orchestrator").strip().lower().replace("_", "-")
    return ROLE_ALIASES.get(key, key)


def get_specialist_model(key: str) -> SpecialistModel | None:
    return MODEL_CATALOG.get((key or "").strip().lower())


def list_specialist_models(*, role: str | None = None) -> list[SpecialistModel]:
    if role is None:
        return list(MODEL_CATALOG.values())
    normalized = normalize_role(role)
    return [entry for entry in MODEL_CATALOG.values() if entry.role == normalized]


def recommended_specialist_runtime_profiles() -> list[RuntimeProfile]:
    profiles: list[RuntimeProfile] = []
    for entry in MODEL_CATALOG.values():
        runtime = entry.runtime_profile()
        if runtime is not None:
            profiles.append(runtime)
    return profiles


def routing_preferences_for_role(
    role: str,
    *,
    policy: str = "local-first",
    privacy_floor: str = PRIVACY_PUBLIC_REMOTE,
    max_cost_usd: float | None = None,
    allow_manual_gate: bool = False,
):
    """Build RFC-0003 routing preferences for an allowed Jarvis model role.

    A manual-gated role is never enabled merely because a model profile exists.
    The caller must independently satisfy the relevant persistent operator gate
    and authorization requirements before passing ``allow_manual_gate=True``.
    """
    from .runtime_router import AgentRoutingPreferences

    normalized = normalize_role(role)
    if normalized == "red-team" and not allow_manual_gate:
        raise PermissionError(
            "red-team runtime activation requires the persistent Red Team password gate "
            "plus explicit manual/case authorization"
        )

    spec = ROLE_SPECS.get(normalized)
    if spec is None:
        raise KeyError(f"unknown model role: {role}")

    return AgentRoutingPreferences(
        preferred_profiles=spec.preferred_profiles,
        policy=policy,
        required_capabilities=spec.required_capabilities,
        task_specialization=spec.specialization,
        privacy_floor=privacy_floor,
        max_cost_usd=max_cost_usd,
    )
