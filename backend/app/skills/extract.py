"""Candidate extraction — typed manifests and deterministic tests from eligible traces."""

from __future__ import annotations

import hashlib
import re
import uuid
from typing import Any

from ..trajectories.schema import JarvisTrajectoryV1
from .eligibility import evaluate_trajectory_eligibility
from .schema import (
    DeterministicTest,
    FieldType,
    Provenance,
    SkillManifest,
    SkillScope,
    SkillStep,
    TypedField,
)

_PLACEHOLDER = re.compile(r"\{([a-zA-Z_][a-zA-Z0-9_]*)\}")
_PATH_RE = re.compile(r"(?:[A-Za-z]:[\\/]|/)[^\s\"']+")
_URL_RE = re.compile(r"https?://[^\s\"'<>]+", re.I)
_SECRET_KEYS = ("password", "passwd", "secret", "token", "api_key", "apikey", "credential", "auth")


class ExtractionError(ValueError):
    pass


def _slug(text: str, fallback: str = "skill") -> str:
    words = re.findall(r"[a-zA-Z0-9]+", (text or "").lower())
    slug = "_".join(words[:4]) if words else fallback
    return (slug or fallback)[:80]


def _looks_path(value: Any) -> bool:
    text = value if isinstance(value, str) else ""
    return bool(_PATH_RE.search(text) or "\\" in text or text.startswith("/"))


def _looks_url(value: Any) -> bool:
    text = (value if isinstance(value, str) else "").strip()
    return bool(_URL_RE.fullmatch(text) or text.lower().startswith("http://") or text.lower().startswith("https://"))


def _field_type(key: str, value: Any) -> FieldType:
    lowered = (key or "").lower()
    if any(token in lowered for token in _SECRET_KEYS):
        return FieldType.SECRET
    if isinstance(value, bool):
        return FieldType.BOOLEAN
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return FieldType.NUMBER
    if isinstance(value, dict):
        return FieldType.OBJECT
    if isinstance(value, list):
        return FieldType.ARRAY
    if _looks_url(value):
        return FieldType.URL
    if _looks_path(value):
        return FieldType.PATH
    return FieldType.STRING


def _param_name(key: str, used: set[str]) -> str:
    base = re.sub(r"[^a-z0-9_]+", "_", (key or "value").lower()).strip("_") or "value"
    name = base
    index = 2
    while name in used:
        name = f"{base}_{index}"
        index += 1
    used.add(name)
    return name


def _tool_events(trajectory: JarvisTrajectoryV1) -> list[Any]:
    events = []
    for event in trajectory.events:
        if event.tool_name and event.event_type in {"tool_call", "tool_result", "action"}:
            events.append(event)
        elif event.tool_name:
            events.append(event)
    return events


def _generalize_steps(trajectory: JarvisTrajectoryV1) -> tuple[list[SkillStep], list[TypedField], list[str]]:
    """Build templated steps and typed input fields from tool events."""
    events = _tool_events(trajectory)
    if not events:
        raise ExtractionError("trajectory has no tool events to extract")

    # Prefer tool_call-like events with args; fall back to any tool-bearing event.
    calls: list[Any] = []
    seen_seq: set[int] = set()
    for event in events:
        if event.tool_args is not None and event.sequence not in seen_seq:
            calls.append(event)
            seen_seq.add(event.sequence)
    if not calls:
        for event in events:
            if event.sequence not in seen_seq:
                calls.append(event)
                seen_seq.add(event.sequence)

    used: set[str] = set()
    inputs: list[TypedField] = []
    steps: list[SkillStep] = []
    tools: list[str] = []

    for event in calls:
        tool = str(event.tool_name or "").strip()
        if not tool:
            continue
        if tool not in tools:
            tools.append(tool)
        args = dict(event.tool_args or {}) if isinstance(event.tool_args, dict) else {}
        templated: dict[str, Any] = {}
        for key, value in args.items():
            ftype = _field_type(str(key), value)
            if ftype == FieldType.SECRET:
                name = _param_name(str(key), used)
                inputs.append(
                    TypedField(
                        name=name,
                        type=FieldType.SECRET,
                        description=f"Secret parameter from tool {tool}.{key}",
                        required=True,
                        examples=[],
                    )
                )
                templated[key] = "{" + name + "}"
                continue
            # Varying literals that look like I/O become parameters when goal mentions them.
            goal = trajectory.goal or ""
            if isinstance(value, str) and value and value in goal:
                name = _param_name(str(key), used)
                inputs.append(
                    TypedField(
                        name=name,
                        type=ftype,
                        description=f"Generalized from {tool}.{key}",
                        required=True,
                        examples=[value[:200]],
                    )
                )
                templated[key] = "{" + name + "}"
            else:
                templated[key] = value
        steps.append(SkillStep(tool=tool, arguments=templated, description=f"from event {event.sequence}"))

    if not steps:
        raise ExtractionError("no extractable skill steps")
    return steps, inputs, tools


def _capabilities_for_tools(tools: list[str]) -> list[str]:
    from ..policy.inheritance import resolve_capability

    caps: list[str] = []
    for tool in tools:
        cap = resolve_capability(tool, None)
        if cap not in caps:
            caps.append(cap)
    return caps


def _build_deterministic_tests(
    *,
    steps: list[SkillStep],
    tools: list[str],
    trajectory: JarvisTrajectoryV1,
    inputs: list[TypedField],
) -> list[DeterministicTest]:
    bindings: dict[str, Any] = {}
    for field in inputs:
        if field.examples:
            bindings[field.name] = field.examples[0]
        elif field.type == FieldType.SECRET:
            bindings[field.name] = "__test_secret__"
        else:
            bindings[field.name] = f"sample_{field.name}"

    step_tools = [step.tool for step in steps]
    golden: list[dict[str, Any]] = []
    for index, step in enumerate(steps):
        golden.append(
            {
                "index": index,
                "tool": step.tool,
                "success": True,
            }
        )

    return [
        DeterministicTest(
            id="golden_replay_sequence",
            description="Replay instantiated steps must match tool sequence and succeed",
            inputs=bindings,
            expected_tools=list(step_tools),
            expected_step_count=len(steps),
            golden_outputs=golden,
            require_success=True,
        ),
        DeterministicTest(
            id="manifest_integrity",
            description="Manifest must declare the same tools used in steps",
            inputs={},
            expected_tools=list(tools),
            expected_step_count=len(steps),
            golden_outputs=[{"check": "tools_match_steps"}],
            require_success=True,
        ),
    ]


def extract_candidate_manifest(
    trajectory: JarvisTrajectoryV1,
    *,
    require_eligible: bool = True,
    scope: SkillScope = SkillScope.WORKFLOW,
    created_by: str = "skill_forge",
) -> SkillManifest:
    if require_eligible:
        result = evaluate_trajectory_eligibility(trajectory)
        if not result.eligible:
            raise ExtractionError("trajectory is not eligible: " + "; ".join(result.reasons))

    steps, inputs, tools = _generalize_steps(trajectory)
    tests = _build_deterministic_tests(steps=steps, tools=tools, trajectory=trajectory, inputs=inputs)
    name = _slug(trajectory.goal or trajectory.task_class or "forged_skill")
    outputs = [
        TypedField(
            name="result",
            type=FieldType.STRING,
            description="Primary skill outcome summary",
            required=True,
            examples=[(trajectory.outcome.summary or "")[:200]],
        )
    ]
    secrets = [field.name for field in inputs if field.type == FieldType.SECRET]
    manifest = SkillManifest(
        name=name,
        purpose=(trajectory.goal or f"Reusable procedure for {trajectory.task_class or 'workflow'}")[:500],
        version="0.1.0",
        scope=scope,
        task_class=trajectory.task_class or "",
        inputs=inputs,
        outputs=outputs,
        steps=steps,
        tools=tools,
        required_capabilities=_capabilities_for_tools(tools),
        secrets=secrets,
        network_scope=["web_fetch", "browser"] if any(t in {"web_fetch", "browser"} for t in tools) else [],
        filesystem_scope=["eval_workspace"] if "filesystem" in tools else [],
        compatible_personas=[],
        compatible_models=[],
        examples=[{"goal": trajectory.goal, "trajectory_id": trajectory.trajectory_id}],
        tests=tests,
        provenance=Provenance(
            source="trace",
            trajectory_ids=[trajectory.trajectory_id],
            created_by=created_by,
            notes="Extracted by Skill Forge from eligible verified trace",
        ),
    )
    return sign_manifest(manifest)


def sign_manifest(manifest: SkillManifest) -> SkillManifest:
    from .provenance import attach_hash_and_signature

    return attach_hash_and_signature(manifest)


def new_ids() -> tuple[str, str, str]:
    """Return skill_id, candidate_id, version_id."""
    return str(uuid.uuid4()), str(uuid.uuid4()), str(uuid.uuid4())


def content_fingerprint(manifest: SkillManifest) -> str:
    payload = manifest.model_dump(mode="json")
    payload.pop("content_hash", None)
    payload.pop("signature", None)
    raw = repr(sorted(payload.items())).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()
