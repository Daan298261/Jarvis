"""RFC-0198 thin tool: open owner-scoped LTA protected folders (authorized recovery)."""

from __future__ import annotations

import json
from typing import Any, Callable

from ..security.lta_archive import get_lta_job, start_protected_folder_open
from ..security.lta_errors import LtaError, PathDenied
from .base import RiskLevel, Tool, ToolResult


class LtaProtectedFolderTool(Tool):
    name = "lta_protected_folder"
    description = (
        "Open an owner-authorized LTA protected folder: resolve a local manifest.xml Access "
        "section with the owner's certificate/recovery key, decrypt the archive password via "
        "PKCS#7/CMS, and extract with 7-Zip into a Jarvis job directory. "
        "Paths must be under allowed_directories. Never ask the owner to paste PEM private keys "
        "into chat — use local cert-store / recovery-keys metadata. Does not call blue.re."
    )
    risk = RiskLevel.HIGH
    effect_class = "external"
    replay_policy = "MANUAL_RECOVERY"
    parameters = {
        "type": "object",
        "properties": {
            "operation": {
                "type": "string",
                "enum": ["open", "status"],
            },
            "manifest_path": {"type": "string", "minLength": 1, "maxLength": 4000},
            "archive_path": {"type": "string", "maxLength": 4000},
            "job_id": {"type": "string", "minLength": 8, "maxLength": 32},
            "sync": {"type": "boolean"},
        },
        "required": ["operation"],
        "additionalProperties": False,
    }

    def __init__(self, context: Callable[[], dict[str, Any]] | None = None) -> None:
        self._context = context or (lambda: {})

    async def execute(self, **kwargs: Any) -> ToolResult:
        operation = str(kwargs.get("operation") or "").strip().lower()
        if operation == "status":
            job_id = str(kwargs.get("job_id") or "").strip()
            if not job_id:
                return ToolResult(False, "", error="job_id is required for status")
            try:
                job = get_lta_job(job_id)
            except KeyError:
                return ToolResult(False, "", error="unknown_job")
            return ToolResult(True, json.dumps(job, default=str), data=job)
        if operation != "open":
            return ToolResult(False, "", error=f"Unknown operation: {operation}")

        manifest_path = str(kwargs.get("manifest_path") or "").strip()
        if not manifest_path:
            return ToolResult(
                False,
                "",
                error=(
                    "manifest_path is required. Ask the owner for a local path under allowed "
                    "directories — do not request PEM private keys in chat."
                ),
            )
        archive_path = kwargs.get("archive_path")
        archive = str(archive_path).strip() if archive_path else None
        sync = bool(kwargs.get("sync", False))
        try:
            result = start_protected_folder_open(
                manifest_path=manifest_path,
                archive_path=archive,
                sync=sync,
            )
        except PathDenied as exc:
            return ToolResult(False, "", error=exc.code, data=exc.as_dict())
        except LtaError as exc:
            return ToolResult(False, "", error=exc.code, data=exc.as_dict())
        hint = result.get("daybreak_jobs_hint") or f"Open Daybreak → Jobs / LTA for job {result.get('id')}"
        summary = {
            **result,
            "daybreak_jobs_hint": hint,
            "summary": (
                f"LTA job {result.get('id') or result.get('job_id')} {result.get('status')}"
                + (f": {result.get('error')}" if result.get("error") else "")
            ),
        }
        ok = str(result.get("status") or "") in {"queued", "running", "succeeded"}
        return ToolResult(
            ok,
            json.dumps(summary, default=str),
            data=summary,
            error="" if ok else str(result.get("error") or result.get("status")),
        )
