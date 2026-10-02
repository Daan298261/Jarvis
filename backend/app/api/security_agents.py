"""RFC-0197 security agent mode + target registry APIs (backend only)."""

from __future__ import annotations

import json
from typing import Any, Literal

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, ConfigDict, Field
from ..agent.loop import AGENT
from ..agent.tool_exposure import tool_names_for
from ..db.models import Task
from ..db.session import SessionLocal
from ..security.security_agents import (
    SecurityAgentDenied,
    SecurityAgentError,
    advance_purple_phase,
    assert_mode_entitled,
    init_purple,
    list_handoffs,
    load_purple_state,
    mode_summary,
    mode_tools,
    normalize_role,
    persona_bind_for_mode,
    stop_purple,
)
from ..security.security_audit import read_audit_lines
from ..security.target_registry import (
    TargetRegistryError,
    add_target,
    list_targets,
    remove_target,
)

router = APIRouter(prefix="/api/security-agents", tags=["security-agents"])


class ModeSetBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    mode: Literal["blue", "red", "purple"]
    task_id: str | None = None
    prompt: str | None = None


class TargetCreateBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: Literal["hostname", "ipv4", "ipv6", "cidr", "local_path", "container_image"]
    value: str = Field(min_length=1, max_length=1000)
    notes: str = Field(default="", max_length=240)
    id: str | None = Field(default=None, max_length=80)


class PurpleAdvanceBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    findings: list[Any] = Field(default_factory=list)
    evidence_paths: list[str] = Field(default_factory=list)
    open_questions: list[str] = Field(default_factory=list)


def _attach_specialists(task: Task, persona_ids: list[str]) -> None:
    existing_raw = getattr(task, "specialist_persona_ids", None) or "[]"
    try:
        existing = json.loads(existing_raw)
    except (TypeError, json.JSONDecodeError):
        existing = []
    if not isinstance(existing, list):
        existing = []
    merged: list[str] = []
    for item in [*existing, *persona_ids]:
        text = str(item or "").strip()
        if text and text not in merged:
            merged.append(text)
    task.specialist_persona_ids = json.dumps(merged)


async def _get_task(task_id: str) -> Task:
    async with SessionLocal() as session:
        task = await session.get(Task, task_id)
        if not task:
            raise HTTPException(404, "Task not found")
        return task


@router.get("/modes")
async def list_modes():
    return {"modes": [mode_summary(mode) for mode in ("blue", "red", "purple")]}


@router.get("/modes/{mode}")
async def get_mode(mode: str):
    try:
        return mode_summary(mode)
    except SecurityAgentError as exc:
        raise HTTPException(400, str(exc)) from exc


@router.post("/mode")
async def set_security_agent_mode(body: ModeSetBody):
    try:
        role = assert_mode_entitled(body.mode)
    except SecurityAgentDenied as exc:
        raise HTTPException(403, str(exc)) from exc
    except SecurityAgentError as exc:
        raise HTTPException(400, str(exc)) from exc

    bind = persona_bind_for_mode(body.mode)
    purple = None
    task_payload: dict[str, Any] | None = None

    if body.task_id:
        async with SessionLocal() as session:
            task = await session.get(Task, body.task_id)
            if not task:
                raise HTTPException(404, "Task not found")
            task.security_role = role
            _attach_specialists(task, list(bind.get("persona_ids") or []))
            extras: list[str] = []
            memory: dict[str, Any] = {}
            raw = getattr(task, "compact_memory", None) or ""
            if raw:
                try:
                    loaded = json.loads(raw)
                    if isinstance(loaded, dict):
                        memory = loaded
                        if isinstance(loaded.get("extra_tools"), list):
                            extras = [str(item) for item in loaded["extra_tools"]]
                except (TypeError, json.JSONDecodeError):
                    memory = {}
            memory["security_role"] = role
            memory["requires_tool_execution"] = True
            if role == "purple-team":
                state = init_purple(task.id)
                purple = state.as_dict()
                memory["purple_phase"] = state.phase
            task.compact_memory = json.dumps(memory, ensure_ascii=False)
            task.exposed_tools = ",".join(
                tool_names_for(
                    getattr(task, "task_class", None) or "mixed",
                    extras,
                    security_role=role,
                    prompt=task.prompt,
                )
            )
            await session.commit()
            await session.refresh(task)
            task_payload = {
                "id": task.id,
                "security_role": task.security_role,
                "exposed_tools": [item for item in (task.exposed_tools or "").split(",") if item],
                "specialist_persona_ids": json.loads(task.specialist_persona_ids or "[]"),
            }
    elif body.prompt:
        task = await AGENT.create_task(body.prompt, security_role=role)
        if role == "purple-team":
            purple = init_purple(task.id).as_dict()
        async with SessionLocal() as session:
            stored = await session.get(Task, task.id)
            if stored:
                _attach_specialists(stored, list(bind.get("persona_ids") or []))
                await session.commit()
                await session.refresh(stored)
                task_payload = {
                    "id": stored.id,
                    "security_role": stored.security_role,
                    "exposed_tools": [item for item in (stored.exposed_tools or "").split(",") if item],
                    "specialist_persona_ids": json.loads(stored.specialist_persona_ids or "[]"),
                }
        task_payload = task_payload or {
            "id": task.id,
            "security_role": role,
            "exposed_tools": tool_names_for("mixed", security_role=role, prompt=body.prompt),
            "specialist_persona_ids": list(bind.get("persona_ids") or []),
        }

    return {
        "mode": body.mode,
        "security_role": role,
        "persona_bind": bind,
        "tools": mode_tools(role),
        "purple": purple,
        "task": task_payload,
        "note": "Owner may override morph/voice in Appearance (RFC-0137); this response only suggests binds.",
    }


@router.get("/targets")
async def get_targets():
    return {"targets": list_targets()}


@router.post("/targets")
async def create_target(body: TargetCreateBody):
    try:
        row = add_target(kind=body.kind, value=body.value, notes=body.notes, target_id=body.id)
    except TargetRegistryError as exc:
        raise HTTPException(400, str(exc)) from exc
    return row


@router.delete("/targets/{target_id}")
async def delete_target(target_id: str):
    try:
        return remove_target(target_id)
    except KeyError as exc:
        raise HTTPException(404, "Target not found") from exc
    except TargetRegistryError as exc:
        raise HTTPException(400, str(exc)) from exc


@router.get("/tasks/{task_id}/purple")
async def get_purple_state(task_id: str):
    task = await _get_task(task_id)
    role = normalize_role(getattr(task, "security_role", None) or "")
    if role != "purple-team":
        raise HTTPException(400, "task is not in purple-team security mode")
    state = load_purple_state(task_id)
    return {"state": state.as_dict(), "handoffs": list_handoffs(task_id)}


@router.post("/tasks/{task_id}/purple/advance")
async def purple_advance(task_id: str, body: PurpleAdvanceBody):
    task = await _get_task(task_id)
    if normalize_role(getattr(task, "security_role", None) or "") != "purple-team":
        raise HTTPException(400, "task is not in purple-team security mode")
    try:
        result = advance_purple_phase(
            task_id,
            findings=body.findings,
            evidence_paths=body.evidence_paths,
            open_questions=body.open_questions,
        )
    except SecurityAgentDenied as exc:
        raise HTTPException(409, str(exc)) from exc
    # Persist phase into compact_memory for the agent loop
    async with SessionLocal() as session:
        stored = await session.get(Task, task_id)
        if stored:
            memory: dict[str, Any] = {}
            raw = getattr(stored, "compact_memory", None) or ""
            if raw:
                try:
                    loaded = json.loads(raw)
                    if isinstance(loaded, dict):
                        memory = loaded
                except (TypeError, json.JSONDecodeError):
                    memory = {}
            memory["purple_phase"] = result["state"]["phase"]
            memory["security_role"] = "purple-team"
            stored.compact_memory = json.dumps(memory, ensure_ascii=False)
            stored.exposed_tools = ",".join(
                tool_names_for(
                    getattr(stored, "task_class", None) or "mixed",
                    security_role="purple-team",
                    prompt=stored.prompt,
                )
            )
            await session.commit()
    return result


@router.post("/tasks/{task_id}/purple/stop")
async def purple_stop(task_id: str):
    task = await _get_task(task_id)
    if normalize_role(getattr(task, "security_role", None) or "") != "purple-team":
        raise HTTPException(400, "task is not in purple-team security mode")
    return stop_purple(task_id)


@router.get("/audit")
async def security_audit(limit: int = 100):
    return {"events": read_audit_lines(limit=limit)}
