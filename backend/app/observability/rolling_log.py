"""Append-only JSONL activity log with one-day rolling retention."""

from __future__ import annotations

import json
import logging
import sys
import threading
import traceback
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable

from ..config import logs_dir

_SECRET_KEY_FRAGMENTS = (
    "private_key",
    "auth_token",
    "api_key",
    "password",
    "secret",
    "token",
    "credential",
)


def _redact_mapping(value: Any) -> Any:
    if isinstance(value, dict):
        out: dict[str, Any] = {}
        for key, item in value.items():
            lowered = str(key).lower()
            if any(frag in lowered for frag in _SECRET_KEY_FRAGMENTS):
                out[str(key)] = "[redacted]"
            else:
                out[str(key)] = _redact_mapping(item)
        return out
    if isinstance(value, list):
        return [_redact_mapping(item) for item in value]
    return value

LOG_NAME = "rolling-log.jsonl"
RETENTION = timedelta(days=1)
_MAX_FIELD_CHARS = 8000
_PRUNE_EVERY_WRITES = 25

_lock = threading.RLock()
_write_count = 0
_prev_asyncio_handler: Callable[..., Any] | None = None
_prev_excepthook: Callable[..., Any] | None = None


def log_path() -> Path:
    logs_dir().mkdir(parents=True, exist_ok=True)
    return logs_dir() / LOG_NAME


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _iso(value: datetime) -> str:
    return value.astimezone(timezone.utc).replace(microsecond=0).isoformat()


def _parse_ts(value: str) -> datetime | None:
    text = (value or "").strip()
    if not text:
        return None
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _truncate(value: Any) -> Any:
    if isinstance(value, str) and len(value) > _MAX_FIELD_CHARS:
        return value[: _MAX_FIELD_CHARS] + "…[truncated]"
    if isinstance(value, dict):
        return {str(k): _truncate(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_truncate(item) for item in value[:200]]
    return value


def record_event(kind: str, *, message: str = "", **fields: Any) -> dict[str, Any]:
    """Append one redacted event and prune entries older than 24h."""
    event: dict[str, Any] = {
        "id": str(uuid.uuid4()),
        "ts": _iso(_utc_now()),
        "kind": str(kind or "event"),
        "message": _truncate(message or ""),
    }
    for key, value in fields.items():
        if key in event:
            continue
        event[key] = _truncate(_redact_mapping(value))

    line = json.dumps(event, default=str, ensure_ascii=False)
    path = log_path()
    global _write_count
    with _lock:
        with path.open("a", encoding="utf-8") as handle:
            handle.write(line + "\n")
        _write_count += 1
        if _write_count >= _PRUNE_EVERY_WRITES:
            _write_count = 0
            _prune_locked(path)
    return event


def _prune_locked(path: Path) -> None:
    if not path.is_file():
        return
    cutoff = _utc_now() - RETENTION
    kept: list[str] = []
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return
    for line in lines:
        if not line.strip():
            continue
        try:
            payload = json.loads(line)
        except json.JSONDecodeError:
            continue
        ts = _parse_ts(str(payload.get("ts") or ""))
        if ts is None or ts >= cutoff:
            kept.append(line)
    tmp = path.with_suffix(path.suffix + ".tmp")
    try:
        tmp.write_text("\n".join(kept) + ("\n" if kept else ""), encoding="utf-8")
        tmp.replace(path)
    except OSError:
        pass


def list_events(*, limit: int = 200, kind: str | None = None) -> list[dict[str, Any]]:
    path = log_path()
    if not path.is_file():
        return []
    cutoff = _utc_now() - RETENTION
    out: list[dict[str, Any]] = []
    with _lock:
        try:
            lines = path.read_text(encoding="utf-8").splitlines()
        except OSError:
            return []
    for line in reversed(lines):
        if not line.strip():
            continue
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue
        if not isinstance(event, dict):
            continue
        ts = _parse_ts(str(event.get("ts") or ""))
        if ts is not None and ts < cutoff:
            continue
        if kind and event.get("kind") != kind:
            continue
        out.append(event)
        if len(out) >= limit:
            break
    return out


class RollingLogHandler(logging.Handler):
    """Mirror logging errors (and warnings with tracebacks) into the rolling log."""

    def emit(self, record: logging.LogRecord) -> None:
        try:
            if record.levelno < logging.WARNING and not record.exc_info:
                return
            kind = "exception" if record.exc_info else "log"
            if record.levelno >= logging.ERROR:
                kind = "exception" if record.exc_info else "error"
            tb = ""
            if record.exc_info:
                tb = "".join(traceback.format_exception(*record.exc_info))
            record_event(
                kind,
                message=record.getMessage(),
                logger=record.name,
                level=record.levelname,
                pathname=record.pathname,
                lineno=record.lineno,
                traceback=_truncate(tb) if tb else None,
            )
        except Exception:
            pass


def _sys_excepthook(exc_type, exc, tb) -> None:
    record_event(
        "exception",
        message=str(exc),
        source="sys.excepthook",
        exc_type=getattr(exc_type, "__name__", str(exc_type)),
        traceback=_truncate("".join(traceback.format_exception(exc_type, exc, tb))),
    )
    if _prev_excepthook is not None:
        _prev_excepthook(exc_type, exc, tb)


def _asyncio_exception_handler(loop, context: dict[str, Any]) -> None:
    exc = context.get("exception")
    message = str(context.get("message") or "asyncio exception")
    fields: dict[str, Any] = {"source": "asyncio"}
    if exc is not None:
        fields["exc_type"] = type(exc).__name__
        fields["traceback"] = _truncate(
            "".join(traceback.format_exception(type(exc), exc, exc.__traceback__))
        )
    record_event("exception", message=message, **fields)
    if _prev_asyncio_handler is not None:
        _prev_asyncio_handler(loop, context)
    else:
        loop.default_exception_handler(context)


def install_rolling_log(*, loop: Any | None = None) -> None:
    """Register global hooks once (idempotent)."""
    global _prev_excepthook, _prev_asyncio_handler
    root = logging.getLogger()
    if not any(isinstance(h, RollingLogHandler) for h in root.handlers):
        handler = RollingLogHandler()
        handler.setLevel(logging.WARNING)
        root.addHandler(handler)

    if _prev_excepthook is None:
        _prev_excepthook = sys.excepthook
        sys.excepthook = _sys_excepthook

    import asyncio

    if loop is None:
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            loop = None
    if loop is not None and _prev_asyncio_handler is None:
        current = loop.get_exception_handler()
        if current is not _asyncio_exception_handler:
            _prev_asyncio_handler = current
            loop.set_exception_handler(_asyncio_exception_handler)


def record_tool_call(
    *,
    name: str,
    arguments: dict[str, Any] | None,
    success: bool,
    error: str | None = None,
    duration_ms: float | None = None,
    task_id: str | None = None,
) -> None:
    record_event(
        "tool_call",
        message=name,
        tool=name,
        arguments=arguments or {},
        success=success,
        error=error or "",
        duration_ms=duration_ms,
        task_id=task_id,
    )
