from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from ..config import data_dir
from .routing import classify_task

MAX_SKILLS = 40


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def skill_store_path() -> Path:
    return data_dir() / "skills.json"


def _slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", (text or "").lower()).strip("_")[:32] or "skill"


@dataclass
class Skill:
    name: str
    description: str
    parameters: list[dict[str, str]]
    required_tools: list[str]
    steps: list[dict[str, Any]]
    verification: str
    recovery: str
    task_class: str
    source: str
    keywords: list[str] = field(default_factory=list)
    builtin: bool = False
    use_count: int = 0
    updated_at: str = field(default_factory=_now)


BUILTIN_SKILLS: list[Skill] = [
    Skill(
        name="save_example_com_title",
        description="Open https://example.com, read the live page title, and write it to a file.",
        parameters=[{"name": "path", "description": "Output file for the page title"}],
        required_tools=["browser", "web_fetch", "filesystem"],
        steps=[
            {"tool": "browser", "action": "save_title", "url": "https://example.com", "path": "{path}"},
        ],
        verification="The output file exists and contains the live page title (Example Domain).",
        recovery="If Playwright fails, web_fetch https://example.com and write the title with filesystem.",
        task_class="browser",
        source="builtin-example-title",
        keywords=["example.com", "page title", "page-title", "title"],
        builtin=True,
        use_count=2,
    ),
]


def derive_skill_name(task_class: str, steps: list[dict[str, Any]], goal: str = "") -> str:
    tools = [str(step.get("tool") or "") for step in steps]
    actions = [str(step.get("action") or "") for step in steps]
    targets = [str(step.get("target") or step.get("url") or "") for step in steps if step.get("target") or step.get("url")]
    stem = _slug(Path(targets[0]).stem) if targets else ""
    if "browser" in tools and "save_title" in actions:
        return f"save_{stem or 'page'}_title"
    if "python" in tools:
        return f"run_python_{stem or 'task'}"
    if "desktop" in tools and "write" in actions:
        return "desktop_notepad_write"
    if "office" in tools:
        return f"office_{stem or 'document'}"
    if task_class == "software_engineering" and "fix" in (goal or "").lower():
        return "build_or_fix_python_project"
    if stem:
        return f"{_slug(task_class)}_{stem}"
    action = _slug(actions[0] if actions else "workflow")
    return f"{_slug(task_class)}_{action}"


def _parameters_from_steps(steps: list[dict[str, Any]]) -> list[dict[str, str]]:
    params: list[dict[str, str]] = []
    seen: set[str] = set()
    for step in steps:
        target = str(step.get("target") or "")
        url = str(step.get("url") or "")
        if target and "://" not in target and target not in seen:
            seen.add(target)
            params.append({"name": "path", "description": f"Output or input file (was {target})"})
            break
        if url.startswith("http") and "url" not in seen:
            seen.add("url")
            params.append({"name": "url", "description": f"Page URL (was {url})"})
    if not params:
        params.append({"name": "path", "description": "Primary file path for this task"})
    return params


def _verification_from(steps: list[dict[str, Any]], failures: list[dict[str, Any]] | None = None) -> str:
    targets = [str(step.get("target") or "") for step in steps if step.get("target")]
    if any(step.get("note") == "verify" for step in steps):
        return "Re-read the output file and confirm it exists and matches the requested content."
    if targets:
        return f"Confirm {targets[0]} exists on disk and matches the requested end state."
    return "Confirm the requested files or UI end state exist."


def _recovery_from(steps: list[dict[str, Any]], failures: list[dict[str, Any]] | None = None, recovered_with: str = "") -> str:
    if recovered_with:
        failed = ", ".join(sorted({str(item.get("tool") or "") for item in (failures or []) if item.get("tool")})) or "the first tool"
        return f"If {failed} fails, switch to {recovered_with}. Do not retry the failing call."
    tools = [str(step.get("tool") or "") for step in steps]
    if "browser" in tools:
        return "If Playwright fails, web_fetch the URL and still write the requested file."
    if "desktop" in tools:
        return "If UI Automation fails, write the file with filesystem."
    return "If the preferred tool fails, switch to filesystem or python. Do not rediscover from scratch."


def _load_learned() -> list[Skill]:
    path = skill_store_path()
    if not path.exists():
        return []
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return []
    rows = raw if isinstance(raw, list) else raw.get("skills") or []
    out: list[Skill] = []
    for row in rows:
        if not isinstance(row, dict) or row.get("builtin"):
            continue
        try:
            skill = Skill(
                name=str(row.get("name") or ""),
                description=str(row.get("description") or ""),
                parameters=list(row.get("parameters") or []),
                required_tools=list(row.get("required_tools") or []),
                steps=list(row.get("steps") or []),
                verification=str(row.get("verification") or ""),
                recovery=str(row.get("recovery") or ""),
                task_class=str(row.get("task_class") or "mixed"),
                source=str(row.get("source") or ""),
                keywords=list(row.get("keywords") or []),
                builtin=False,
                use_count=int(row.get("use_count") or 0),
                updated_at=str(row.get("updated_at") or _now()),
            )
        except (TypeError, ValueError):
            continue
        if skill.name and skill.steps:
            out.append(skill)
    return out


def _trim(rows: list[Skill], protect: str | None = None) -> list[Skill]:
    learned = [row for row in rows if not row.builtin]
    if len(learned) <= MAX_SKILLS:
        return learned
    protected = next((row for row in learned if protect and row.name == protect), None)
    rest = [row for row in learned if protected is None or row.name != protected.name]
    rest.sort(key=lambda row: (row.use_count, row.updated_at))
    budget = MAX_SKILLS - (1 if protected is not None else 0)
    kept = rest[-budget:] if budget > 0 else []
    if protected is not None:
        kept.append(protected)
    return kept


def _save(rows: list[Skill], protect: str | None = None) -> None:
    payload = [asdict(row) for row in _trim(rows, protect)]
    skill_store_path().write_text(json.dumps(payload, indent=2), encoding="utf-8")


def all_skills() -> list[Skill]:
    learned = _load_learned()
    builtin_names = {row.name for row in BUILTIN_SKILLS}
    return list(BUILTIN_SKILLS) + [row for row in learned if row.name not in builtin_names]


def list_skills() -> list[dict[str, Any]]:
    sync_from_stores()
    rows = sorted(all_skills(), key=lambda row: (row.builtin, row.use_count, row.updated_at), reverse=True)
    return [
        {
            "name": row.name,
            "description": row.description,
            "task_class": row.task_class,
            "required_tools": row.required_tools,
            "parameters": row.parameters,
            "steps": row.steps,
            "verification": row.verification,
            "recovery": row.recovery,
            "builtin": row.builtin,
            "source": row.source,
            "use_count": row.use_count,
        }
        for row in rows
    ]


def get_skill(name: str) -> Skill | None:
    key = (name or "").strip()
    sync_from_stores()
    for row in all_skills():
        if row.name == key:
            return row
    return None


def _upsert(skill: Skill) -> Skill:
    learned = _load_learned()
    for index, row in enumerate(learned):
        if row.source == skill.source or row.name == skill.name:
            skill.use_count = max(row.use_count, skill.use_count)
            skill.updated_at = _now()
            learned[index] = skill
            _save(learned, protect=skill.name)
            return skill
    existing = {row.name for row in learned} | {row.name for row in BUILTIN_SKILLS}
    name = skill.name
    suffix = 2
    while name in existing:
        name = f"{skill.name}_{suffix}"
        suffix += 1
    skill.name = name
    learned.append(skill)
    _save(learned, protect=skill.name)
    return skill


def promote_from_trajectory(traj) -> Skill | None:
    if not getattr(traj, "stable", False):
        return None
    steps = list(getattr(traj, "steps", []) or [])
    if not steps:
        return None
    failures = list(getattr(traj, "failures", []) or [])
    name = derive_skill_name(getattr(traj, "task_class", "mixed"), steps, getattr(traj, "goal", ""))
    skill = Skill(
        name=name,
        description=(getattr(traj, "goal", "") or name)[:200],
        parameters=_parameters_from_steps(steps),
        required_tools=list(dict.fromkeys(str(step.get("tool") or "") for step in steps if step.get("tool"))),
        steps=steps,
        verification=_verification_from(steps, failures),
        recovery=_recovery_from(steps, failures, getattr(traj, "recovered_with", "") or ""),
        task_class=str(getattr(traj, "task_class", "") or "mixed"),
        source=str(getattr(traj, "id", "") or name),
        keywords=list(getattr(traj, "keywords", []) or []),
        builtin=False,
        use_count=int(getattr(traj, "success_count", 2) or 2),
    )
    return _upsert(skill)


def promote_from_workflow(workflow) -> Skill | None:
    if not getattr(workflow, "stable", False):
        return None
    steps = list(getattr(workflow, "steps", []) or [])
    if not steps:
        return None
    name = str(getattr(workflow, "name", "") or "") or derive_skill_name("browser", steps, getattr(workflow, "goal", ""))
    if getattr(workflow, "builtin", False) and name == "save_example_com_title":
        return BUILTIN_SKILLS[0]
    skill = Skill(
        name=_slug(name).replace("-", "_"),
        description=(getattr(workflow, "goal", "") or name)[:200],
        parameters=_parameters_from_steps(steps),
        required_tools=list(dict.fromkeys(str(step.get("tool") or "") for step in steps if step.get("tool"))),
        steps=steps,
        verification="The requested title file exists and contains the live page title.",
        recovery="If Playwright fails, web_fetch the URL and write the title with filesystem.",
        task_class="browser",
        source=str(getattr(workflow, "id", "") or name),
        keywords=list(getattr(workflow, "keywords", []) or []),
        builtin=False,
        use_count=int(getattr(workflow, "success_count", 2) or 2),
    )
    return _upsert(skill)


def sync_from_stores() -> None:
    try:
        from .trajectories import all_trajectories

        for row in all_trajectories():
            if row.stable:
                promote_from_trajectory(row)
    except Exception:
        pass
    try:
        from .browser_workflows import all_workflows

        for row in all_workflows():
            if row.stable and not row.builtin:
                promote_from_workflow(row)
    except Exception:
        pass


def _score(skill: Skill, prompt: str, task_class: str) -> int:
    text = (prompt or "").lower()
    hosts = [
        key.strip().lower().rstrip(".,);:]'\"")
        for key in skill.keywords
        if "." in (key or "")
        and not str(key).lower().endswith((".txt", ".py", ".json", ".md", ".png", ".csv", ".xlsx", ".docx"))
        and "/" not in str(key)
        and "\\" not in str(key)
    ]
    if hosts and not any(host in text for host in hosts):
        name = skill.name.replace("_", " ")
        if skill.name not in text and name not in text:
            return 0
    score = 0
    if skill.name.replace("_", " ") in text or skill.name in text:
        score += 6
    if skill.task_class == task_class:
        score += 2
    distinctive = 0
    generic = {
        "filesystem",
        "python",
        "terminal",
        "browser",
        "write",
        "read",
        "native",
        "title",
        "page",
        "file",
        "save",
        skill.task_class,
    }
    for keyword in skill.keywords:
        key = (keyword or "").lower()
        if not key or key not in text or key in generic:
            continue
        distinctive += 1
        score += 2
    if distinctive == 0 and skill.task_class != task_class and score < 6:
        return 0
    return score


def match_skills(prompt: str, task_class: str | None = None, limit: int = 2) -> list[Skill]:
    if not task_class:
        task_class = classify_task(prompt).task_class
    sync_from_stores()
    ranked: list[tuple[int, int, Skill]] = []
    for skill in all_skills():
        score = _score(skill, prompt, task_class)
        if score >= 4:
            ranked.append((score, skill.use_count, skill))
    ranked.sort(key=lambda item: (item[0], item[1]), reverse=True)
    return [item[2] for item in ranked[:limit]]


def format_skill_card(skill: Skill) -> str:
    lines = [
        f"Named skill `{skill.name}` — do not rediscover this workflow.",
        f"Description: {skill.description}",
        "Parameters: " + ", ".join(f"{item.get('name')} ({item.get('description')})" for item in skill.parameters),
        "Required tools: " + ", ".join(skill.required_tools),
        "Steps:",
    ]
    for index, step in enumerate(skill.steps, start=1):
        extra = step.get("url") or step.get("target") or step.get("path") or step.get("note") or ""
        lines.append(f"  {index}. {step.get('tool')} {step.get('action') or ''} {extra}".rstrip())
    lines.append(f"Verification: {skill.verification}")
    lines.append(f"Recovery: {skill.recovery}")
    lines.append("Call the native tools in this order. Substitute this task's paths for the parameters.")
    return "\n".join(lines)


def format_skill_hint(prompt: str, task_class: str | None = None) -> str:
    matches = match_skills(prompt, task_class)
    if not matches:
        return ""
    blocks = ["Use a named Jarvis skill instead of rediscovering the workflow."]
    for skill in matches:
        blocks.append(format_skill_card(skill))
    return "\n\n".join(blocks)
