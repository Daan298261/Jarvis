from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .runtime_profiles import (
    PRIVACY_LOCAL_ONLY,
    PRIVACY_ORDER,
    PRIVACY_PUBLIC_REMOTE,
    PRIVACY_TRUSTED_REMOTE,
    RuntimeProfile,
    get_runtime_profile,
    list_runtime_profiles,
)

ROUTING_POLICIES = ("local-only", "local-first", "best-result", "cost-optimized")

PRIVACY_FLOOR_LOCAL_ONLY = PRIVACY_LOCAL_ONLY
PRIVACY_FLOOR_TRUSTED_REMOTE = PRIVACY_TRUSTED_REMOTE
PRIVACY_FLOOR_PUBLIC_REMOTE = PRIVACY_PUBLIC_REMOTE

WARM_MODEL_BONUS = 80
SPECIALIZATION_BONUS = 60
PREFERRED_PROFILE_BONUS = 40
LOCAL_BONUS = 30
QUALITY_BONUS = 25

ESTIMATED_COST_PER_1K: dict[str, float] = {
    "local-llama": 0.0,
    "openai-compat": 0.002,
    "anthropic": 0.003,
    "google": 0.0015,
}


@dataclass
class AgentRoutingPreferences:
    preferred_profiles: tuple[str, ...] = ()
    forbidden_profiles: tuple[str, ...] = ()
    force_profile: str | None = None
    policy: str = "local-first"
    required_capabilities: tuple[str, ...] = ()
    task_specialization: str | None = None
    privacy_floor: str = PRIVACY_PUBLIC_REMOTE
    max_cost_usd: float | None = None


@dataclass
class RuntimeNodeState:
    node_id: str
    hostname: str = "localhost"
    is_local: bool = True
    warm_models: tuple[str, ...] = ()
    load_factor: float = 0.0
    hardware_fit: float = 1.0


@dataclass
class RoutingScore:
    total: float
    expected_success: float = 0.0
    latency: float = 0.0
    cost: float = 0.0
    privacy: float = 0.0
    load: float = 0.0
    network: float = 0.0
    warm_bonus: float = 0.0
    specialization_bonus: float = 0.0
    preferred_bonus: float = 0.0
    reasons: list[str] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return {
            "total": self.total,
            "expected_success": self.expected_success,
            "latency": self.latency,
            "cost": self.cost,
            "privacy": self.privacy,
            "load": self.load,
            "network": self.network,
            "warm_bonus": self.warm_bonus,
            "specialization_bonus": self.specialization_bonus,
            "preferred_bonus": self.preferred_bonus,
            "reasons": list(self.reasons),
        }


@dataclass
class RoutingDecision:
    accepted: bool
    runtime_profile: RuntimeProfile | None = None
    node: RuntimeNodeState | None = None
    score: RoutingScore | None = None
    reason: str = ""
    code: str = ""
    alternatives: list[dict[str, Any]] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "accepted": self.accepted,
            "reason": self.reason,
            "code": self.code,
            "alternatives": self.alternatives,
        }
        if self.runtime_profile is not None:
            payload["runtime_profile"] = self.runtime_profile.as_dict()
        if self.node is not None:
            payload["node"] = {
                "node_id": self.node.node_id,
                "hostname": self.node.hostname,
                "is_local": self.node.is_local,
                "warm_models": list(self.node.warm_models),
                "load_factor": self.node.load_factor,
                "hardware_fit": self.node.hardware_fit,
            }
        if self.score is not None:
            payload["score"] = self.score.as_dict()
        return payload


def _normalize_policy(policy: str | None) -> str:
    key = (policy or "local-first").strip().lower()
    if key not in ROUTING_POLICIES:
        return "local-first"
    return key


def _privacy_allows(profile: RuntimeProfile, floor: str) -> bool:
    floor_rank = PRIVACY_ORDER.get(floor, PRIVACY_ORDER[PRIVACY_PUBLIC_REMOTE])
    profile_rank = PRIVACY_ORDER.get(profile.privacy_class, PRIVACY_ORDER[PRIVACY_PUBLIC_REMOTE])
    return profile_rank <= floor_rank


def _estimated_cost(profile: RuntimeProfile) -> float:
    if profile.cost_ceiling_usd is not None and profile.cost_ceiling_usd >= 0:
        return float(profile.cost_ceiling_usd)
    return ESTIMATED_COST_PER_1K.get(profile.provider, 0.002)


def _has_capabilities(profile: RuntimeProfile, required: tuple[str, ...]) -> bool:
    if not required:
        return True
    held = set(profile.capability_tags)
    return set(required).issubset(held)


def _is_warm(profile: RuntimeProfile, node: RuntimeNodeState) -> bool:
    warm = set(node.warm_models)
    return profile.model in warm or profile.name in warm or profile.id in warm


def _quality_score(profile: RuntimeProfile) -> float:
    score = 50.0
    if "high-quality" in profile.capability_tags:
        score += 20
    if profile.context_limit >= 32768:
        score += 10
    if profile.quantization in {"Q8_0", "Q6_K"}:
        score += 5
    if "reasoning" in profile.specialization_tags:
        score += 10
    return score


def score_runtime_candidate(
    profile: RuntimeProfile,
    node: RuntimeNodeState,
    prefs: AgentRoutingPreferences,
    *,
    policy: str,
) -> RoutingScore:
    reasons: list[str] = []
    expected_success = _quality_score(profile) * node.hardware_fit
    reasons.append(f"expected success {expected_success:.0f}")

    latency = 100.0 if profile.is_local and node.is_local else 40.0
    if "low-latency" in profile.specialization_tags:
        latency += 15
    reasons.append(f"latency score {latency:.0f}")

    cost_value = _estimated_cost(profile)
    cost_score = max(0.0, 100.0 - (cost_value * 1000.0))
    reasons.append(f"cost score {cost_score:.0f} (est ${cost_value:.4f}/1k)")

    privacy_score = 100.0 - (PRIVACY_ORDER.get(profile.privacy_class, 2) * 20.0)
    reasons.append(f"privacy score {privacy_score:.0f}")

    load_score = max(0.0, 100.0 - (node.load_factor * 100.0))
    reasons.append(f"load score {load_score:.0f}")

    network_score = 100.0 if profile.is_local and node.is_local else 55.0
    reasons.append(f"network score {network_score:.0f}")

    warm_bonus = WARM_MODEL_BONUS if _is_warm(profile, node) else 0.0
    if warm_bonus:
        reasons.append(f"warm model bonus +{warm_bonus:.0f}")

    specialization_bonus = 0.0
    if prefs.task_specialization:
        spec = prefs.task_specialization.strip().lower()
        if spec in {tag.lower() for tag in profile.specialization_tags}:
            specialization_bonus = SPECIALIZATION_BONUS
            reasons.append(f"specialization match +{specialization_bonus:.0f}")

    preferred_bonus = 0.0
    if profile.name in prefs.preferred_profiles or profile.id in prefs.preferred_profiles:
        preferred_bonus = PREFERRED_PROFILE_BONUS
        reasons.append(f"preferred profile +{preferred_bonus:.0f}")

    local_bonus = LOCAL_BONUS if profile.is_local and policy in {"local-only", "local-first"} else 0.0
    if local_bonus:
        reasons.append(f"local bonus +{local_bonus:.0f}")

    if policy == "cost-optimized":
        total = cost_score + privacy_score + warm_bonus + specialization_bonus + preferred_bonus
    elif policy == "best-result":
        total = expected_success + warm_bonus + specialization_bonus + preferred_bonus + (privacy_score * 0.2)
    elif policy == "local-only":
        total = (local_bonus * 2) + warm_bonus + specialization_bonus + preferred_bonus + latency
    else:  # local-first
        total = (
            local_bonus
            + warm_bonus
            + specialization_bonus
            + preferred_bonus
            + (latency * 0.4)
            + (expected_success * 0.3)
            + (cost_score * 0.2)
        )

    return RoutingScore(
        total=total,
        expected_success=expected_success,
        latency=latency,
        cost=cost_score,
        privacy=privacy_score,
        load=load_score,
        network=network_score,
        warm_bonus=warm_bonus,
        specialization_bonus=specialization_bonus,
        preferred_bonus=preferred_bonus,
        reasons=reasons,
    )


def _filter_candidates(
    profiles: list[RuntimeProfile],
    prefs: AgentRoutingPreferences,
    *,
    policy: str,
) -> tuple[list[RuntimeProfile], str | None, str | None]:
    if prefs.force_profile:
        forced = get_runtime_profile(prefs.force_profile)
        if forced is None:
            return [], "Forced runtime profile not found", "forced_missing"
        if forced.name in prefs.forbidden_profiles or forced.id in prefs.forbidden_profiles:
            return [], "Forced runtime profile is forbidden", "forced_forbidden"
        if not _privacy_allows(forced, prefs.privacy_floor):
            return [], "Forced runtime profile violates privacy floor", "privacy_violation"
        if not _has_capabilities(forced, prefs.required_capabilities):
            return [], "Forced runtime profile lacks required capabilities", "missing_capability"
        if policy == "local-only" and not forced.is_local:
            return [], "Forced runtime profile is not local", "local_only_violation"
        return [forced], None, None

    eligible: list[RuntimeProfile] = []
    had_remote = False
    privacy_blocked_remote = False

    for profile in profiles:
        if profile.name in prefs.forbidden_profiles or profile.id in prefs.forbidden_profiles:
            continue
        if not _has_capabilities(profile, prefs.required_capabilities):
            continue
        if prefs.max_cost_usd is not None and _estimated_cost(profile) > prefs.max_cost_usd:
            continue
        if not profile.is_local:
            had_remote = True
        if not _privacy_allows(profile, prefs.privacy_floor):
            if not profile.is_local:
                privacy_blocked_remote = True
            continue
        if policy == "local-only" and not profile.is_local:
            continue
        eligible.append(profile)

    if eligible:
        return eligible, None, None

    if policy == "local-only":
        if had_remote and privacy_blocked_remote:
            return [], "Privacy policy forbids all available remote candidates", "privacy_forbidden"
        return [], "No local runtime profiles available for local-only policy", "no_local_profile"

    if had_remote and privacy_blocked_remote:
        return [], "Privacy policy forbids all available remote candidates", "privacy_forbidden"

    return [], "No eligible runtime profiles", "no_profile"


def route_runtime(
    prefs: AgentRoutingPreferences | dict[str, Any] | None = None,
    *,
    nodes: list[RuntimeNodeState] | None = None,
    profiles: list[RuntimeProfile] | None = None,
) -> RoutingDecision:
    """Select a runtime profile and execution node with explainable scoring."""
    if isinstance(prefs, dict):
        agent_prefs = AgentRoutingPreferences(
            preferred_profiles=tuple(prefs.get("preferred_profiles") or ()),
            forbidden_profiles=tuple(prefs.get("forbidden_profiles") or ()),
            force_profile=prefs.get("force_profile"),
            policy=_normalize_policy(prefs.get("policy")),
            required_capabilities=tuple(prefs.get("required_capabilities") or ()),
            task_specialization=prefs.get("task_specialization"),
            privacy_floor=str(prefs.get("privacy_floor") or PRIVACY_PUBLIC_REMOTE),
            max_cost_usd=prefs.get("max_cost_usd"),
        )
    elif prefs is None:
        agent_prefs = AgentRoutingPreferences()
    else:
        agent_prefs = prefs

    policy = _normalize_policy(agent_prefs.policy)
    catalog = profiles if profiles is not None else list_runtime_profiles()
    node_list = nodes or [
        RuntimeNodeState(node_id="localhost", hostname="localhost", is_local=True, warm_models=())
    ]

    eligible, reason, code = _filter_candidates(catalog, agent_prefs, policy=policy)
    if not eligible:
        return RoutingDecision(accepted=False, reason=reason or "No eligible runtime", code=code or "no_profile")

    ranked: list[tuple[RuntimeProfile, RuntimeNodeState, RoutingScore]] = []
    for profile in eligible:
        for node in node_list:
            if policy == "local-only" and not (profile.is_local and node.is_local):
                continue
            if policy == "local-first" and not profile.is_local and any(
                candidate.is_local for candidate in eligible
            ):
                # Defer remote unless no local node can serve it.
                local_nodes = [n for n in node_list if n.is_local]
                if local_nodes and not (profile.is_local and node.is_local):
                    continue
            score = score_runtime_candidate(profile, node, agent_prefs, policy=policy)
            ranked.append((profile, node, score))

    if not ranked:
        return RoutingDecision(
            accepted=False,
            reason="No runtime/node pairing satisfies routing policy",
            code="no_pairing",
        )

    ranked.sort(key=lambda item: (-item[2].total, item[0].name, item[1].node_id))
    chosen_profile, chosen_node, chosen_score = ranked[0]

    alternatives = [
        {
            "runtime_profile": profile.as_dict(),
            "node_id": node.node_id,
            "score": score.as_dict(),
        }
        for profile, node, score in ranked[1:4]
    ]

    reason_parts = [
        f"selected {chosen_profile.name} on {chosen_node.node_id}",
        f"policy={policy}",
        f"score={chosen_score.total:.1f}",
    ]
    if chosen_score.reasons:
        reason_parts.append(chosen_score.reasons[0])

    return RoutingDecision(
        accepted=True,
        runtime_profile=chosen_profile,
        node=chosen_node,
        score=chosen_score,
        reason="; ".join(reason_parts),
        code="routed",
        alternatives=alternatives,
    )
