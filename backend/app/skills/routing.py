"""Skill search / routing hooks for personas and Goal Runtime (RFC-0173)."""

from __future__ import annotations

import re
from typing import Any

from .schema import LifecycleStatus, SkillVersion
from .store import get_active_version_id, get_version, list_skills

_TOKEN = re.compile(r"[a-z0-9]+", re.I)


def _tokens(text: str) -> set[str]:
    return {match.group(0).lower() for match in _TOKEN.finditer(text or "")}


def list_active_versions() -> list[SkillVersion]:
    versions: list[SkillVersion] = []
    for entry in list_skills():
        vid = entry.active_version_id or get_active_version_id(entry.skill_id)
        if not vid:
            continue
        version = get_version(vid)
        if version is None:
            continue
        if version.disabled or version.status != LifecycleStatus.ACTIVE:
            continue
        versions.append(version)
    return versions


def search_skills(
    query: str,
    *,
    persona_id: str | None = None,
    goal_id: str | None = None,
    task_class: str | None = None,
    limit: int = 5,
) -> list[dict[str, Any]]:
    """Rank active forged skills for routing into persona / goal contexts."""
    q_tokens = _tokens(query)
    if goal_id:
        q_tokens |= _tokens(goal_id)
    scored: list[tuple[float, SkillVersion]] = []
    for version in list_active_versions():
        manifest = version.manifest
        if persona_id and manifest.compatible_personas:
            if persona_id not in manifest.compatible_personas:
                continue
        score = 0.0
        if task_class and manifest.task_class and manifest.task_class == task_class:
            score += 3.0
        blob = f"{manifest.name} {manifest.purpose} {' '.join(manifest.tools)}"
        score += float(len(q_tokens & _tokens(blob)))
        if goal_id and any(goal_id in (ex.get("goal_id") or "") for ex in manifest.examples if isinstance(ex, dict)):
            score += 2.0
        if score > 0:
            scored.append((score, version))
    scored.sort(key=lambda item: item[0], reverse=True)
    out: list[dict[str, Any]] = []
    for score, version in scored[: max(1, min(limit, 20))]:
        out.append(
            {
                "skill_id": version.skill_id,
                "version_id": version.version_id,
                "name": version.manifest.name,
                "purpose": version.manifest.purpose,
                "task_class": version.manifest.task_class,
                "tools": list(version.manifest.tools),
                "score": score,
                "persona_id": persona_id,
                "goal_id": goal_id,
            }
        )
    return out


def skills_prompt_block(
    query: str,
    *,
    persona_id: str | None = None,
    goal_id: str | None = None,
    task_class: str | None = None,
    limit: int = 3,
) -> str:
    hits = search_skills(
        query,
        persona_id=persona_id,
        goal_id=goal_id,
        task_class=task_class,
        limit=limit,
    )
    if not hits:
        return ""
    lines = [
        "Skill Forge active skills (policy-bounded, owner-approved). Prefer matching one over rediscovery:"
    ]
    for hit in hits:
        lines.append(
            f"- {hit['name']}: {hit['purpose'][:200]} "
            f"[tools={','.join(hit['tools'])}; version={hit['version_id'][:8]}]"
        )
    return "\n".join(lines)


def persona_skill_context(persona_id: str | None, goal_or_prompt: str, *, task_class: str = "") -> str:
    """Thin real wiring for persona packs / named personas."""
    return skills_prompt_block(
        goal_or_prompt,
        persona_id=persona_id,
        task_class=task_class or None,
    )


def goal_runtime_skill_context(goal_id: str, objective: str, *, task_class: str = "") -> dict[str, Any]:
    """Public hook for Goal Runtime to attach ranked skills to a goal turn."""
    hits = search_skills(objective, goal_id=goal_id, task_class=task_class or None)
    return {
        "goal_id": goal_id,
        "skills": hits,
        "prompt_block": skills_prompt_block(objective, goal_id=goal_id, task_class=task_class or None),
    }
