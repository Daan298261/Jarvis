from __future__ import annotations

from dataclasses import dataclass

from .default_candidates import MODEL_CANDIDATES, ModelCandidate, ModelRole


@dataclass(frozen=True)
class CandidateRoute:
    role: ModelRole
    candidate_keys: tuple[str, ...]
    benchmark_required: bool = True

    def candidates(self) -> list[ModelCandidate]:
        return [MODEL_CANDIDATES[key] for key in self.candidate_keys if key in MODEL_CANDIDATES]


CANDIDATE_ROUTES: dict[ModelRole, CandidateRoute] = {
    "micro": CandidateRoute(
        role="micro",
        candidate_keys=("minicpm5-1b-abliterated",),
    ),
    "small": CandidateRoute(
        role="small",
        candidate_keys=("minicpm5-2b-abliterated", "nemotron3-nano-4b-uncensored"),
    ),
    "primary": CandidateRoute(
        role="primary",
        candidate_keys=(
            "qwen38-9b-heretic-q6",
            "qwen38-9b-heretic-q8",
            "lfm25-8b-a1b-uncensored-q6",
            "lfm25-8b-a1b-uncensored-q8",
        ),
    ),
    "presentation": CandidateRoute(
        role="presentation",
        candidate_keys=(
            "qwen35-08b-presentation",
            "minicpm5-1b-abliterated",
            "minicpm5-2b-abliterated",
        ),
    ),
    "expert": CandidateRoute(
        role="expert",
        candidate_keys=("qwen36-35b-a3b-colibri-abliterated",),
    ),
    "lab": CandidateRoute(
        role="lab",
        candidate_keys=("kimi-k3-colibri",),
    ),
}


ROLE_ALIASES = {
    "router": "micro",
    "micro-worker": "micro",
    "background": "small",
    "small-worker": "small",
    "default": "primary",
    "brain": "primary",
    "main": "primary",
    "translator": "presentation",
    "language": "presentation",
    "personality": "presentation",
    "heavy": "expert",
    "colibri-expert": "expert",
    "frontier-local": "lab",
}


def normalize_candidate_role(role: str) -> ModelRole:
    key = (role or "primary").strip().lower().replace("_", "-")
    normalized = ROLE_ALIASES.get(key, key)
    if normalized not in CANDIDATE_ROUTES:
        raise KeyError(f"unknown inference candidate role: {role}")
    return normalized  # type: ignore[return-value]


def candidate_route(role: str) -> CandidateRoute:
    return CANDIDATE_ROUTES[normalize_candidate_role(role)]


def candidate_keys_for_role(role: str) -> tuple[str, ...]:
    return candidate_route(role).candidate_keys


def candidates_for_role(role: str) -> list[ModelCandidate]:
    return candidate_route(role).candidates()
