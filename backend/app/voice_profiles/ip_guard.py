from __future__ import annotations

import re

# Substrings forbidden in profile ids, display names, archetypes, and pack paths.
FORBIDDEN_TERMS: tuple[str, ...] = (
    "codsworth",
    "cortana",
    "ultron",
    "fallout",
    "halo",
    "marvel",
    "disney",
    "stephen_russell",
    "stephen russell",
    "microsoft",
    "mr_handy",
    "mr handy",
    "vault_tec",
    "vault-tec",
    "bethesda",
    "master_chief",
    "master chief",
    "jarvis_marvel",
    "tony_stark",
    "iron_man",
    "iron man",
)

_FORBIDDEN_RE = re.compile(
    "|".join(re.escape(term) for term in FORBIDDEN_TERMS),
    re.IGNORECASE,
)


def contains_forbidden_ip_term(value: str) -> bool:
    normalized = (value or "").strip()
    if not normalized:
        return False
    return _FORBIDDEN_RE.search(normalized) is not None


def validate_profile_ip_fields(
    *,
    profile_id: str,
    display_name: str,
    archetype: str,
    pack_path: str = "",
) -> None:
    for label, value in (
        ("id", profile_id),
        ("display_name", display_name),
        ("archetype", archetype),
        ("pack_path", pack_path),
    ):
        if contains_forbidden_ip_term(value):
            raise ValueError(
                f"Voice profile {label} contains a forbidden copyrighted-character or trademark term: {value!r}"
            )
