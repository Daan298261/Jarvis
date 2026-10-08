from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any

from .base import RiskLevel, Tool, ToolResult
from ..reverse_engineering import provision, store
from ..reverse_engineering.runtime import SERVICE


class ReverseEngineerTool(Tool):
    name = "reverse_engineer"
    description = (
        "Investigate software from a local path and a specific question using REA/Ghidra/JADX. "
        "prepare returns a target identity and skill; catalog returns real operation schemas; "
        "call runs an advertised operation and saves evidence; evidence retrieves it; report saves "
        "findings citing evidence IDs. Runtime execution always needs owner approval. "
        "Use normal repository tools for complete source code."
    )
    risk = RiskLevel.LOW
    replay_policy = "never_auto_replay"
    parameters = {
        "type": "object", "properties": {
            "action": {"type": "string", "enum": ["status", "prepare", "catalog", "call", "evidence", "report", "close", "cancel", "guide", "record_source"]},
            "target": {"type": "string"}, "question": {"type": "string"},
            "origins": {"type": "array", "items": {"type": "string"}},
            "investigation_id": {"type": "string"}, "operation": {"type": "string"},
            "arguments": {"type": "object"}, "evidence_id": {"type": "string"},
            "path": {"type": "string", "description": "record_source: snapshot-relative source filename (also accepted inside arguments)"},
            "start": {"type": "integer", "minimum": 1},
            "end": {"type": "integer", "minimum": 1},
            "findings": {"type": "array", "items": {"type": "object", "properties": {
                "claim": {"type": "string"}, "kind": {"type": "string", "enum": ["observation", "inference"]},
                "evidence_ids": {"type": "array", "items": {"type": "string"}},
                "limitations": {"type": "string"}}, "required": ["claim", "kind", "evidence_ids"]}},
            "unknowns": {"type": "array", "items": {"type": "string"}},
        }, "required": ["action"],
    }

    def __init__(self, context_getter):
        self.context_getter = context_getter

    async def execute(self, _task_id=None, _grant_id=None, **kwargs: Any) -> ToolResult:
        context = dict(self.context_getter())
        action = kwargs.get("action")
        ident = kwargs.get("investigation_id", "")
        try:
            if action == "status":
                data = await asyncio.to_thread(provision.readiness)
            elif action == "prepare":
                data = await SERVICE.prepare(kwargs["target"], kwargs["question"], context.get("allowed_directories", []), _task_id, kwargs.get("origins"))
            else:
                row = SERVICE.owned(ident, _task_id)
                if action == "catalog":
                    data = await SERVICE.catalog(ident, _task_id, kwargs.get("operation", ""))
                elif action == "call":
                    data = await SERVICE.call(ident, kwargs["operation"], kwargs.get("arguments", {}), _task_id, _grant_id)
                elif action == "evidence":
                    evidence_id = kwargs["evidence_id"]
                    if evidence_id not in {e["id"] for e in row["evidence"]}:
                        raise ValueError("Unknown evidence id")
                    data = json.loads((store.directory(ident) / "evidence" / f"{evidence_id}.json").read_text(encoding="utf-8"))
                elif action == "report":
                    data = await SERVICE.report(ident, kwargs.get("findings", []), kwargs.get("unknowns", []), _task_id)
                    data["report_url"] = f"/api/investigations/{ident}/report?format=md"
                elif action in {"close", "cancel"}:
                    data = await SERVICE.close(ident, _task_id, cancelled=action == "cancel")
                elif action == "guide":
                    from ..reverse_engineering.skill import guide
                    data = {"skill": guide(row["kind"])}
                elif action == "record_source":
                    arguments = dict(kwargs.get("arguments") or {})
                    for field in ("path", "start", "end"):
                        if field in kwargs:
                            if field in arguments and arguments[field] != kwargs[field]:
                                raise ValueError(f"Conflicting record_source {field}")
                            arguments[field] = kwargs[field]
                    data = await SERVICE.record_source(ident, arguments, _task_id)
                else:
                    raise ValueError("Unknown reverse_engineer action")
            success = data.get("status") not in {"pending_approval", "denied", "analysis_failed"}
            view = data
            if action == "prepare":
                view = {k: v for k, v in data.items() if k not in {"manifest", "evidence", "findings", "unknowns"}}
            elif action in {"call", "evidence"} and "result" in data:
                result = data["result"]
                view = {k: v for k, v in data.items() if k != "result"}
                view["result"] = result.get("structuredContent") or result if isinstance(result, dict) else result
            return ToolResult(success, json.dumps(view, ensure_ascii=False), data=data,
                              error="" if success else data.get("reason", "Approval required"))
        except Exception as exc:
            return ToolResult(False, "", error=str(exc))
