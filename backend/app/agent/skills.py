from __future__ import annotations

import json
import re
import uuid
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from typing import Any, Callable, Iterable

from sqlalchemy import select

from ..db.models import Skill, ToolCallRecord, Trajectory, utcnow
from ..db.session import SessionLocal
from ..tools.base import ToolResult
from .trajectory import keywords

MIN_REPEATS = 3
MAX_PROMPT_SKILLS = 2
BROWSER_TOOLS = {"browser", "web_fetch"}
DISCOVERY_ACTIONS = {"snapshot", "screenshot"}
STABLE_TARGET_KEYS = ("name", "label", "role", "aria_label", "placeholder", "test_id", "testid")
_PLACEHOLDER = re.compile(r"\{([a-zA-Z_][a-zA-Z0-9_]*)\}")
_PATH_RE = re.compile(r"(?:[A-Za-z]:[\\/]|/)[^\s\"']+")
_FILE_RE = re.compile(r"\b[\w.-]+\.[A-Za-z0-9]{1,5}\b")
_URL_RE = re.compile(r"https?://[^\s\"'<>]+", re.I)
_EPHEMERAL_SELECTOR = re.compile(r"^#?e\d+$", re.I)
_SECRET_KEYS = ("password", "passwd", "secret", "token", "api_key", "apikey", "credential", "auth")


@dataclass
class SkillCandidate:
    task_class: str
    tools: tuple[str, ...]
    goals: list[str] = field(default_factory=list)
    verifications: list[str] = field(default_factory=list)
    task_ids: list[str] = field(default_factory=list)

    @property
    def occurrences(self) -> int:
        return len(self.goals)


def _skill_name(goals: Iterable[str], task_class: str) -> str:
    counter: Counter[str] = Counter()
    for goal in goals:
        counter.update(keywords(goal))
    words = [word for word, _ in counter.most_common(3)]
    if not words:
        words = [task_class or "task"]
    slug = "_".join(re.sub(r"[^a-z0-9]+", "", word) for word in words if word)
    return slug[:80] or "reusable_workflow"


def _looks_like_path(value: str) -> bool:
    text = value or ""
    return bool(_PATH_RE.search(text) or "\\" in text or text.startswith("/") or _FILE_RE.fullmatch(text.strip()))


def _looks_like_url(value: str) -> bool:
    text = (value or "").strip()
    return bool(_URL_RE.fullmatch(text) or text.lower().startswith("http://") or text.lower().startswith("https://"))


def _is_ephemeral_selector(value: str) -> bool:
    text = (value or "").strip()
    if not text:
        return True
    if _EPHEMERAL_SELECTOR.fullmatch(text):
        return True
    if re.fullmatch(r"\d+", text):
        return True
    return False


def _looks_secret(key: str, values: list[Any] | None = None) -> bool:
    lowered = (key or "").lower()
    if any(token in lowered for token in _SECRET_KEYS):
        return True
    return False


def is_browser_workflow(tools: Iterable[str]) -> bool:
    return any(tool in BROWSER_TOOLS for tool in tools)


def is_discovery_step(step: dict[str, Any]) -> bool:
    if step.get("tool") != "browser":
        return False
    args = step.get("arguments") if isinstance(step.get("arguments"), dict) else {}
    return str(args.get("action") or "") in DISCOVERY_ACTIONS


def replayable_calls(sequence: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Drop snapshot/screenshot discovery so a promoted browser skill can replay."""
    return [step for step in sequence if isinstance(step, dict) and not is_discovery_step(step)]


def _has_stable_target(args: dict[str, Any]) -> bool:
    selector = args.get("selector")
    if isinstance(selector, str) and selector.strip() and not _is_ephemeral_selector(selector):
        return True
    for key in STABLE_TARGET_KEYS:
        value = args.get(key)
        if isinstance(value, str) and value.strip() and not _is_ephemeral_selector(value):
            return True
    return False


def browser_sequence_is_stable(sequences: list[list[dict[str, Any]]]) -> bool:
    """Promote only browser procedures that can replay without snapshot element ids.

    Discovery runs that click `#e12`-style refs are one-off; named controls, CSS
    selectors, roles, and explicit URLs are BrowserCode-style and worth keeping.
    """
    has_entry = False
    has_interaction = False
    has_stable_target = False
    for seq in sequences:
        for step in replayable_calls(seq):
            tool = step.get("tool")
            args = step.get("arguments") if isinstance(step.get("arguments"), dict) else {}
            action = str(args.get("action") or "")
            if tool == "web_fetch" and args.get("url"):
                has_entry = True
            if tool == "browser" and action == "open" and args.get("url"):
                has_entry = True
            if tool == "browser" and action in {"click", "type", "fill", "download", "upload"}:
                has_interaction = True
                if _has_stable_target(args):
                    has_stable_target = True
    if not has_entry:
        return False
    if has_interaction and not has_stable_target:
        return False
    return True


def _param_kind(key: str, values: list[Any]) -> str:
    if _looks_secret(key, values):
        return "secret"
    if key in {"url", "href"}:
        return "url"
    if key in {"selector"}:
        return "selector"
    if key in {"name", "label", "role", "aria_label", "placeholder", "test_id", "testid"}:
        return "name"
    if key in {"path", "destination", "working_directory", "file", "filename"}:
        return "path"
    strings = [v for v in values if isinstance(v, str)]
    if strings and all(_looks_like_url(v) for v in strings):
        return "url"
    if strings and all(_looks_like_path(v) for v in strings):
        return "path"
    if key in {"text", "content", "value"}:
        return "text"
    return "string"


def _param_name(key: str, used: set[str]) -> str:
    base = re.sub(r"[^a-z0-9_]+", "_", (key or "value").lower()).strip("_") or "value"
    name = base
    index = 2
    while name in used:
        name = f"{base}_{index}"
        index += 1
    used.add(name)
    return name


def parameterize_call_sequences(sequences: list[list[dict[str, Any]]]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Turn aligned tool-call sequences into templated steps plus parameter specs."""
    if not sequences:
        return [], []
    length = len(sequences[0])
    if length == 0 or any(len(seq) != length for seq in sequences):
        return [], []
    for index in range(length):
        tools = {seq[index].get("tool") for seq in sequences}
        if len(tools) != 1:
            return [], []

    used_names: set[str] = set()
    parameters: list[dict[str, Any]] = []
    steps: list[dict[str, Any]] = []

    for index in range(length):
        tool = sequences[0][index].get("tool") or ""
        keys: set[str] = set()
        for seq in sequences:
            args = seq[index].get("arguments") or {}
            if isinstance(args, dict):
                keys.update(args.keys())
        templated: dict[str, Any] = {}
        for key in sorted(keys):
            values = []
            for seq in sequences:
                args = seq[index].get("arguments") or {}
                values.append(args.get(key) if isinstance(args, dict) else None)
            comparable = [json.dumps(v, sort_keys=True, default=str) for v in values]
            if key == "selector" and values and all(isinstance(v, str) and _is_ephemeral_selector(v) for v in values):
                continue
            if _looks_secret(str(key), values):
                name = _param_name(str(key), used_names)
                parameters.append({"name": name, "kind": "secret", "examples": [], "step": index, "key": key})
                templated[key] = "{" + name + "}"
                continue
            if len(set(comparable)) <= 1:
                templated[key] = values[0]
                continue
            name = _param_name(str(key), used_names)
            kind = _param_kind(str(key), values)
            examples = []
            for value in values:
                text = value if isinstance(value, str) else json.dumps(value, default=str)
                if text and text not in examples:
                    examples.append(text[:400])
            parameters.append({"name": name, "kind": kind, "examples": examples[:6], "step": index, "key": key})
            templated[key] = "{" + name + "}"
        steps.append({"tool": tool, "arguments": templated})
    return steps, parameters


def parse_steps(raw: str | None) -> list[Any]:
    try:
        data = json.loads(raw or "[]")
    except json.JSONDecodeError:
        return []
    return data if isinstance(data, list) else []


def normalize_parameters(raw: Any) -> list[dict[str, Any]]:
    if isinstance(raw, str):
        try:
            raw = json.loads(raw)
        except json.JSONDecodeError:
            return []
    if not isinstance(raw, list):
        return []
    out: list[dict[str, Any]] = []
    for item in raw:
        if isinstance(item, str) and item.strip():
            out.append({"name": item.strip(), "kind": "string", "examples": []})
        elif isinstance(item, dict) and item.get("name"):
            out.append(item)
    return out


def extract_goal_tokens(goal: str) -> list[str]:
    found: list[str] = []
    for match in re.finditer(r'"([^"]+)"|\'([^\']+)\'', goal or ""):
        token = match.group(1) or match.group(2)
        if token and token not in found:
            found.append(token)
    for match in _URL_RE.finditer(goal or ""):
        token = match.group(0).rstrip(").,;")
        if token not in found:
            found.append(token)
    for match in _PATH_RE.finditer(goal or ""):
        token = match.group(0)
        if token not in found:
            found.append(token)
    for match in _FILE_RE.finditer(goal or ""):
        token = match.group(0)
        if token not in found:
            found.append(token)
    return found


def bind_parameters(skill: Skill, goal: str, extra: dict[str, Any] | None = None) -> dict[str, str] | None:
    params = normalize_parameters(skill.parameters_json)
    bound: dict[str, str] = {}
    for key, value in (extra or {}).items():
        if value is None or value == "":
            continue
        bound[str(key)] = value if isinstance(value, str) else json.dumps(value, default=str)
    if not params:
        return bound
    tokens = extract_goal_tokens(goal)
    for param in params:
        name = str(param["name"])
        if name in bound:
            continue
        kind = param.get("kind") or "string"
        picked = None
        if kind == "secret":
            return None
        if kind == "url":
            picked = next((token for token in tokens if _looks_like_url(token)), None)
            if picked is None:
                match = _URL_RE.search(goal or "")
                picked = match.group(0).rstrip(").,;") if match else None
        if kind == "path":
            picked = next((token for token in tokens if _looks_like_path(token)), None)
        if kind in {"name", "selector", "text"} and picked is None and tokens:
            picked = next((token for token in tokens if not _looks_like_url(token) and not _looks_like_path(token)), tokens[0] if tokens else None)
        if picked is None and tokens:
            picked = tokens[0]
        if picked is None:
            return None
        if picked in tokens:
            tokens.remove(picked)
        bound[name] = picked
    return bound


def substitute(value: Any, bound: dict[str, str]) -> Any:
    if isinstance(value, str):
        def repl(match: re.Match[str]) -> str:
            name = match.group(1)
            return bound[name] if name in bound else match.group(0)

        return _PLACEHOLDER.sub(repl, value)
    if isinstance(value, dict):
        return {key: substitute(item, bound) for key, item in value.items()}
    if isinstance(value, list):
        return [substitute(item, bound) for item in value]
    return value


def placeholders_in(value: Any) -> set[str]:
    found: set[str] = set()
    if isinstance(value, str):
        found.update(_PLACEHOLDER.findall(value))
    elif isinstance(value, dict):
        for item in value.values():
            found.update(placeholders_in(item))
    elif isinstance(value, list):
        for item in value:
            found.update(placeholders_in(item))
    return found


def instantiate_steps(skill: Skill, bound: dict[str, str] | None) -> list[dict[str, Any]]:
    steps = parse_steps(skill.steps_json)
    templated = [step for step in steps if isinstance(step, dict) and step.get("tool")]
    if not templated:
        return []
    return substitute(templated, bound or {})


def steps_are_executable(steps: list[dict[str, Any]]) -> bool:
    if not steps:
        return False
    if any(placeholders_in(step) for step in steps):
        return False
    return any(isinstance(step.get("arguments"), dict) and step.get("arguments") for step in steps)


def skill_is_runnable(skill: Skill) -> bool:
    """True when the skill has tool steps that can run after parameters are bound."""
    steps = [step for step in parse_steps(skill.steps_json) if isinstance(step, dict) and step.get("tool")]
    return any(isinstance(step.get("arguments"), dict) and step.get("arguments") for step in steps)


def has_secret_parameters(skill: Skill) -> bool:
    return any((item.get("kind") or "") == "secret" for item in normalize_parameters(skill.parameters_json))


async def execute_bound_skill(
    steps: list[dict[str, Any]],
    runner: Callable[..., Any],
) -> list[dict[str, Any]]:
    """Run templated skill steps with an async (tool, arguments) -> ToolResult callback."""
    results: list[dict[str, Any]] = []
    for step in steps:
        name = step.get("tool") or ""
        arguments = step.get("arguments") if isinstance(step.get("arguments"), dict) else {}
        result = await runner(name, arguments)
        if isinstance(result, ToolResult):
            payload = {"tool": name, "arguments": arguments, "success": result.success, "output": result.text(), "error": result.error}
        elif isinstance(result, tuple) and len(result) >= 1:
            observation = result[0]
            failed = "ERROR:" in str(observation) or str(observation).lower().startswith("error")
            payload = {
                "tool": name,
                "arguments": arguments,
                "success": not failed,
                "output": observation,
                "attach": result[1] if len(result) > 1 else None,
            }
        else:
            payload = {"tool": name, "arguments": arguments, "success": False, "output": str(result), "error": "unexpected skill runner result"}
        results.append(payload)
        if not payload.get("success"):
            break
    return results


async def _successful_calls(session, task_id: str) -> list[dict[str, Any]]:
    rows = (
        await session.execute(
            select(ToolCallRecord)
            .where(ToolCallRecord.task_id == task_id, ToolCallRecord.success.is_(True))
            .order_by(ToolCallRecord.id)
        )
    ).scalars().all()
    out: list[dict[str, Any]] = []
    for row in rows:
        try:
            arguments = json.loads(row.arguments_json or "{}")
        except json.JSONDecodeError:
            arguments = {}
        if not isinstance(arguments, dict):
            arguments = {}
        out.append({"tool": row.tool_name, "arguments": arguments})
    return out


async def promote_from_trajectories(min_repeats: int = MIN_REPEATS) -> list[Skill]:
    """Turn repeated, stable, successful workflows into skills.

    A workflow only becomes a skill once the same task class has been solved
    with the same tool sequence several times. One-off successes stay as
    trajectory memory. When the underlying tool arguments are recorded,
    differing values become parameters so the skill can run itself later.
    """
    created: list[Skill] = []
    async with SessionLocal() as session:
        rows = (await session.execute(select(Trajectory).where(Trajectory.outcome == "completed"))).scalars().all()
        existing = (await session.execute(select(Skill))).scalars().all()
        known = {(skill.task_class, tuple(json.loads(skill.tools_json or "[]"))) for skill in existing}
        used_names = {skill.name for skill in existing}

        groups: dict[tuple[str, tuple[str, ...]], SkillCandidate] = defaultdict(lambda: SkillCandidate("", ()))
        for row in rows:
            tools = tuple(json.loads(row.tools_json or "[]"))
            if not tools:
                continue
            key = (row.task_class or "", tools)
            candidate = groups[key]
            candidate.task_class, candidate.tools = key
            candidate.goals.append(row.goal)
            candidate.task_ids.append(row.task_id)
            if row.verification:
                candidate.verifications.append(row.verification)

        for key, candidate in groups.items():
            if candidate.occurrences < min_repeats or key in known:
                continue
            sequences = [await _successful_calls(session, task_id) for task_id in candidate.task_ids]
            browserish = is_browser_workflow(candidate.tools)
            if browserish:
                sequences = [replayable_calls(seq) for seq in sequences]
                if not browser_sequence_is_stable(sequences):
                    continue
            templated, parameters = parameterize_call_sequences(sequences)
            if templated:
                steps_payload: list[Any] = templated
            else:
                steps_payload = [f"use {tool}" for tool in candidate.tools]
                parameters = sorted(keywords(" ".join(candidate.goals)))[:6]

            name = _skill_name(candidate.goals, candidate.task_class)
            if name in used_names:
                name = f"{name}_{len(used_names) + 1}"
            used_names.add(name)
            origin = "browser_promoted" if browserish else "promoted"
            kind_label = "browser procedure" if browserish else (candidate.task_class or "workflow")
            skill = Skill(
                id=str(uuid.uuid4()),
                name=name,
                description=(
                    f"Repeatable {kind_label} solved {candidate.occurrences} times "
                    f"with {', '.join(candidate.tools)}. Example goal: {candidate.goals[0][:200]}"
                ),
                task_class=candidate.task_class,
                parameters_json=json.dumps(parameters),
                tools_json=json.dumps(list(candidate.tools)),
                steps_json=json.dumps(steps_payload),
                verification=(candidate.verifications[0] if candidate.verifications else "")[:1000],
                recovery="Fall back to the alternatives suggested for the failing tool.",
                origin=origin,
            )
            session.add(skill)
            created.append(skill)
        if created:
            await session.commit()
    return created


async def relevant_skills(task_class: str, goal: str, limit: int = MAX_PROMPT_SKILLS) -> list[Skill]:
    goal_keywords = keywords(goal)
    async with SessionLocal() as session:
        rows = (await session.execute(select(Skill).where(Skill.enabled.is_(True)))).scalars().all()
        scored: list[tuple[Skill, float]] = []
        for row in rows:
            score = 2.0 if row.task_class and row.task_class == task_class else 0.0
            score += float(len(keywords(f"{row.name} {row.description}") & goal_keywords))
            if score >= 2.0:
                scored.append((row, score))
        picked = [row for row, _ in sorted(scored, key=lambda item: item[1], reverse=True)][:limit]
        for row in picked:
            row.times_used += 1
            row.updated_at = utcnow()
        if picked:
            await session.commit()
        return picked


async def get_skill(skill_id: str) -> Skill | None:
    async with SessionLocal() as session:
        return await session.get(Skill, skill_id)


def as_prompt_block(skills: Iterable[Skill]) -> str:
    entries = []
    for skill in skills:
        raw_steps = parse_steps(skill.steps_json)
        rendered: list[str] = []
        for step in raw_steps:
            if isinstance(step, str):
                rendered.append(step)
            elif isinstance(step, dict):
                tool = step.get("tool") or "tool"
                arguments = step.get("arguments") or {}
                if arguments:
                    rendered.append(f"{tool}({json.dumps(arguments, ensure_ascii=False)})")
                else:
                    rendered.append(f"use {tool}")
        params = normalize_parameters(skill.parameters_json)
        line = f"- {skill.name}: {skill.description}"
        if params:
            line += "\n  Parameters: " + ", ".join(f"{{{item['name']}}}" for item in params)
        if rendered:
            line += f"\n  Steps: {', '.join(rendered)}"
        if skill.verification:
            line += f"\n  Verify: {skill.verification[:200]}"
        if skill.origin == "browser_promoted":
            line += (
                "\n  BrowserCode-style skill: replay the recorded named clicks and fills. "
                "Do not rediscover the page unless a control is missing."
            )
        if any(isinstance(step, dict) and step.get("arguments") for step in raw_steps):
            line += "\n  This skill can run itself once parameters are bound. Prefer executing it over rediscovering the workflow."
        entries.append(line)
    if not entries:
        return ""
    return (
        "Reusable skills already proven on this machine. Follow one when it fits instead of rediscovering the workflow:\n"
        + "\n".join(entries)
    )
