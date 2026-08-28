from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from typing import Any, Iterable

from ..schema import (
    CandidateSkill,
    JarvisTrajectoryV1,
    TrajectoryEvent,
    TrajectoryOutcome,
    TrajectoryProvenance,
    TrajectoryVerification,
    TrajectoryWorkspace,
)
from ..store import new_trajectory_id


class TrajectoryAdapterError(ValueError):
    """Raised when a harness log cannot be parsed."""


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _parse_timestamp(raw: Any, *, fallback_index: int) -> str:
    if isinstance(raw, (int, float)):
        try:
            return datetime.fromtimestamp(float(raw), tz=timezone.utc).isoformat()
        except (OSError, OverflowError, ValueError):
            pass
    if isinstance(raw, str) and raw.strip():
        text = raw.strip()
        if text.endswith("Z"):
            text = text[:-1] + "+00:00"
        try:
            return datetime.fromisoformat(text).astimezone(timezone.utc).isoformat()
        except ValueError:
            pass
    base = datetime(2026, 1, 1, tzinfo=timezone.utc)
    return (base.replace(microsecond=fallback_index * 1000)).isoformat()


def _iter_jsonl_lines(text: str) -> Iterable[tuple[int, dict[str, Any]]]:
    for index, line in enumerate(text.splitlines()):
        stripped = line.strip()
        if not stripped:
            continue
        try:
            row = json.loads(stripped)
        except json.JSONDecodeError as exc:
            raise TrajectoryAdapterError(f"line {index + 1}: invalid JSON") from exc
        if not isinstance(row, dict):
            raise TrajectoryAdapterError(f"line {index + 1}: expected JSON object")
        yield index, row


def _extract_text(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, str):
        return value
    if isinstance(value, dict):
        for key in ("text", "content", "message", "value"):
            if key in value and isinstance(value[key], str):
                return value[key]
        return json.dumps(value, default=str)
    if isinstance(value, list):
        parts = [_extract_text(item) for item in value]
        return "\n".join(part for part in parts if part)
    return str(value)


def _tool_args(raw: Any) -> dict[str, Any] | None:
    if raw is None:
        return None
    if isinstance(raw, dict):
        return raw
    if isinstance(raw, str):
        try:
            parsed = json.loads(raw)
        except json.JSONDecodeError:
            return {"raw": raw}
        return parsed if isinstance(parsed, dict) else {"raw": raw}
    return {"raw": raw}


def parse_cursor_transcript(
    text: str,
    *,
    source_uri: str | None = None,
    import_id: str | None = None,
    model: str | None = None,
    repository: str | None = None,
    branch: str | None = None,
    workspace_path: str | None = None,
) -> JarvisTrajectoryV1:
    """Convert a Cursor agent transcript JSONL export into JarvisTrajectoryV1."""
    rows = list(_iter_jsonl_lines(text))
    if not rows:
        raise TrajectoryAdapterError("empty transcript")

    events: list[TrajectoryEvent] = []
    failures: list[str] = []
    recovery: str | None = None
    ordered_tools: list[str] = []
    goal: str | None = None
    verification_details: str | None = None
    verification_passed = False
    outcome_status = "attempted"
    harness_version: str | None = None
    last_timestamp: str | None = None

    for sequence, (line_no, row) in enumerate(rows):
        if row.get("repository") and not repository:
            repository = str(row["repository"])
        if row.get("branch") and not branch:
            branch = str(row["branch"])
        if row.get("workspace_path") and not workspace_path:
            workspace_path = str(row["workspace_path"])
        if set(row.keys()) <= {"repository", "branch", "workspace_path"}:
            continue

        ts = _parse_timestamp(
            row.get("timestamp") or row.get("createdAt") or row.get("created_at"),
            fallback_index=sequence,
        )
        if last_timestamp and ts < last_timestamp:
            ts = last_timestamp
        last_timestamp = ts

        role = str(row.get("role") or row.get("type") or row.get("kind") or "").lower()
        if not harness_version and row.get("harness_version"):
            harness_version = str(row["harness_version"])
        if not model and row.get("model"):
            model = str(row["model"])

        message = row.get("message") or row.get("content") or row.get("text")
        if role in {"user", "human"}:
            content = _extract_text(message or row.get("user_message"))
            if content and not goal:
                goal = content[:400]
            events.append(
                TrajectoryEvent(
                    sequence=sequence,
                    timestamp=ts,
                    event_type="user_message",
                    content=content,
                    metadata={"source_line": line_no + 1},
                )
            )
            continue

        if role in {"assistant", "agent", "ai"}:
            content = _extract_text(message)
            events.append(
                TrajectoryEvent(
                    sequence=sequence,
                    timestamp=ts,
                    event_type="assistant_message",
                    content=content,
                    metadata={"source_line": line_no + 1},
                )
            )
            tool_calls = row.get("tool_calls") or row.get("toolCalls") or []
            if isinstance(tool_calls, dict):
                tool_calls = [tool_calls]
            for tool_index, call in enumerate(tool_calls or []):
                if not isinstance(call, dict):
                    continue
                fn = call.get("function") if isinstance(call.get("function"), dict) else call
                tool_name = str(fn.get("name") or call.get("name") or call.get("tool") or "unknown")
                args = _tool_args(fn.get("arguments") if isinstance(fn, dict) else call.get("arguments"))
                if tool_name not in ordered_tools:
                    ordered_tools.append(tool_name)
                events.append(
                    TrajectoryEvent(
                        sequence=sequence,
                        timestamp=ts,
                        event_type="tool_call",
                        tool_name=tool_name,
                        tool_args=args,
                        metadata={"source_line": line_no + 1, "tool_index": tool_index},
                    )
                )
            continue

        if role in {"tool", "tool_result", "tool-result"} or row.get("tool_name") or row.get("toolName"):
            tool_name = str(row.get("tool_name") or row.get("toolName") or row.get("name") or "unknown")
            result_text = _extract_text(row.get("result") or row.get("output") or row.get("content"))
            success = row.get("success")
            if success is None and row.get("is_error") is not None:
                success = not bool(row.get("is_error"))
            if success is None and row.get("error"):
                success = False
            if success is False:
                problem = _extract_text(row.get("error")) or result_text or "tool failed"
                failures.append(f"{tool_name}: {problem}")
            events.append(
                TrajectoryEvent(
                    sequence=sequence,
                    timestamp=ts,
                    event_type="tool_result",
                    tool_name=tool_name,
                    tool_result=result_text,
                    success=success,
                    metadata={"source_line": line_no + 1},
                )
            )
            continue

        if role in {"verification", "verify"} or row.get("verification"):
            verification_details = _extract_text(row.get("verification") or message)
            verification_passed = bool(row.get("passed", row.get("success", False)))
            events.append(
                TrajectoryEvent(
                    sequence=sequence,
                    timestamp=ts,
                    event_type="verification",
                    content=verification_details,
                    success=verification_passed,
                    metadata={"source_line": line_no + 1},
                )
            )
            continue

        if role in {"outcome", "result", "summary"}:
            outcome_status = str(row.get("status") or row.get("outcome") or message or outcome_status)
            events.append(
                TrajectoryEvent(
                    sequence=sequence,
                    timestamp=ts,
                    event_type="outcome",
                    content=_extract_text(message or row.get("summary")),
                    metadata={"source_line": line_no + 1},
                )
            )
            continue

        if role in {"recovery"}:
            recovery = _extract_text(message or row.get("recovery"))
            events.append(
                TrajectoryEvent(
                    sequence=sequence,
                    timestamp=ts,
                    event_type="recovery",
                    content=recovery,
                    metadata={"source_line": line_no + 1},
                )
            )
            continue

        # Generic action / metadata row
        events.append(
            TrajectoryEvent(
                sequence=sequence,
                timestamp=ts,
                event_type=role or "action",
                content=_extract_text(message or row),
                metadata={"source_line": line_no + 1, "raw_type": role or None},
            )
        )

    if not recovery and failures and ordered_tools:
        failed = {event.tool_name for event in events if event.event_type == "tool_result" and event.success is False}
        succeeded = [tool for tool in ordered_tools if tool not in failed]
        if failed and succeeded:
            recovery = f"{next(iter(failed))} failed, {succeeded[-1]} worked instead"

    if verification_passed:
        outcome_status = "completed"
    elif failures and outcome_status == "attempted":
        outcome_status = "failed"

    candidate_skills: list[CandidateSkill] = []
    if ordered_tools and outcome_status == "completed" and verification_passed:
        candidate_skills.append(
            CandidateSkill(
                name=None,
                tools=ordered_tools,
                description=goal,
                confidence=0.5,
            )
        )

    return JarvisTrajectoryV1(
        trajectory_id=new_trajectory_id(),
        goal=goal,
        provenance=TrajectoryProvenance(
            harness="cursor",
            harness_version=harness_version,
            model=model,
            source_uri=source_uri,
            source_format="cursor-jsonl",
            imported_at=_utc_now(),
            import_id=import_id or str(uuid.uuid4()),
            trusted=False,
        ),
        workspace=TrajectoryWorkspace(
            repository=repository,
            branch=branch,
            workspace_path=workspace_path,
        ),
        events=events,
        outcome=TrajectoryOutcome(
            status=outcome_status,
            attempted=True,
            verified=verification_passed,
            summary=goal,
        ),
        verification=TrajectoryVerification(
            attempted=bool(verification_details),
            passed=verification_passed,
            details=verification_details,
        ),
        failures=failures,
        recovery=recovery,
        candidate_skills=candidate_skills,
    )
