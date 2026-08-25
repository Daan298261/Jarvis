from __future__ import annotations

from typing import Any

from ..agent.verify_code import format_report, verify_software
from .base import RiskLevel, Tool, ToolResult
from .safety import resolve_allowed_path


class VerifyCodeTool(Tool):
    name = "verify_code"
    description = (
        "Independently verify software changes in a repository. Inspects git status/diff and "
        "runs pytest when a Python test layout exists. A worker or model saying 'tests pass' "
        "is not enough — call this before completing software tasks."
    )
    risk = RiskLevel.LOW
    parameters = {
        "type": "object",
        "properties": {
            "path": {"type": "string", "description": "Repository or project root to verify"},
            "run_tests": {"type": "boolean", "default": True},
            "timeout_seconds": {"type": "integer", "default": 120},
        },
        "required": ["path"],
    }

    def __init__(self, context_getter=None) -> None:
        self.context_getter = context_getter or (lambda: {})

    async def execute(self, **kwargs: Any) -> ToolResult:
        raw = kwargs.get("path") or ""
        if not raw:
            return ToolResult(False, "", error="path is required")
        try:
            allowed = list((self.context_getter() or {}).get("allowed_directories") or [])
            root = resolve_allowed_path(raw, allowed) if allowed else raw
        except PermissionError as exc:
            return ToolResult(False, "", error=str(exc))
        timeout = int(kwargs.get("timeout_seconds") or 120)
        run_tests = kwargs.get("run_tests")
        if run_tests is None:
            run_tests = True
        report = await verify_software(root, run_tests=bool(run_tests), timeout_seconds=timeout)
        return ToolResult(
            bool(report.get("ok")),
            format_report(report),
            data=report,
            error="" if report.get("ok") else (report.get("reason") or "verification failed"),
        )
