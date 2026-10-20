"""RFC-0229 S1: structured, viewable debug log of Manager actions.

``logs/manager-debug.log`` holds JSON lines (``ts``, ``level``, ``event``,
``action``, ``request_id``, ``duration_ms``, ``ok``, ``detail``). It is rotated
with the existing ``supervisor.rotate_file`` at 2 MiB per file with 5 rotated
files kept, so it never uses more than 12 MiB on disk. Every record goes through
``redact.redact`` before it is written and again before it is returned.

Verbose (DEBUG) lives only in this process's memory (``_verbose``): it is off on
every Manager start and is never written to any file.
"""
from __future__ import annotations

import contextvars
import json
import logging
import re
import secrets
import threading
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Iterable, Mapping

from .. import config
from .redact import redact, redact_argv, redact_env
from .supervisor import LAUNCH_LOG_MAX_BYTES, LAUNCH_LOGS_KEPT, rotate_file

log = logging.getLogger(__name__)

LOG_NAME = "manager-debug.log"
MAX_BYTES = LAUNCH_LOG_MAX_BYTES  # 2 MiB per file
KEPT = LAUNCH_LOGS_KEPT  # 5 rotated files (current + 5 <= 12 MiB)
MAX_LINE_BYTES = 16 * 1024
LEVELS = {"DEBUG": 10, "INFO": 20, "WARNING": 30, "ERROR": 40}
EVENTS = frozenset(("press", "control_start", "control_end", "supervisor", "status_error"))
_REQUEST_ID = re.compile(r"^[A-Za-z0-9._:-]{1,64}$")

_verbose = False
_lock = threading.Lock()
_root: Callable[[], Path] = config.repo_root
# (action, request_id) of the owner control running in this context, if any;
# asyncio.to_thread copies it, so launcher spawns are attributed to their press.
_current_control: contextvars.ContextVar[tuple[str, str] | None] = contextvars.ContextVar(
    "manager_current_control", default=None
)


def configure(root: Callable[[], Path]) -> None:
    global _root
    _root = root


def log_path() -> Path:
    return _root() / "logs" / LOG_NAME


def is_verbose() -> bool:
    return _verbose


def set_verbose(enabled: bool) -> None:
    global _verbose
    _verbose = bool(enabled)


def level_enabled(level: str) -> bool:
    return LEVELS[level] >= (LEVELS["DEBUG"] if _verbose else LEVELS["INFO"])


def new_request_id() -> str:
    return f"srv-{secrets.token_hex(8)}"


def clean_request_id(value: str | None) -> str:
    """The client's id when it is well formed, otherwise a fresh server id."""
    return value if value and _REQUEST_ID.fullmatch(value) else new_request_id()


def bind_control(action: str, request_id: str) -> contextvars.Token:
    return _current_control.set((action, request_id))


def unbind_control(token: contextvars.Token) -> None:
    _current_control.reset(token)


def write(
    level: str,
    event: str,
    *,
    action: str | None = None,
    request_id: str | None = None,
    duration_ms: int | None = None,
    ok: bool | None = None,
    detail: Any = None,
) -> dict | None:
    """Append one redacted JSON line. Returns the record written, or None when filtered."""
    if level not in LEVELS:
        raise ValueError(f"unknown debug-log level {level!r}")
    if event not in EVENTS:
        raise ValueError(f"unknown debug-log event {event!r}")
    if not level_enabled(level):
        return None
    record = redact(
        {
            "ts": datetime.now().astimezone().isoformat(timespec="milliseconds"),
            "level": level,
            "event": event,
            "action": action,
            "request_id": request_id,
            "duration_ms": duration_ms,
            "ok": ok,
            "detail": detail,
        },
        debug=_verbose,
    )
    data = (json.dumps(record, ensure_ascii=False, default=str) + "\n").encode("utf-8")
    if len(data) > MAX_LINE_BYTES:
        record["detail"] = {"truncated": True, "bytes": len(data)}
        data = (json.dumps(record, ensure_ascii=False, default=str) + "\n").encode("utf-8")
    path = log_path()
    with _lock:
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            if path.exists() and path.stat().st_size + len(data) > MAX_BYTES:
                rotate_file(path, KEPT)
            with path.open("ab") as handle:
                handle.write(data)
        except OSError:
            # The debug log must never break a control action; Python logging still records it.
            log.warning("Manager debug log write failed for %s", path, exc_info=True)
            return None
    return record


def spawn(launch_action: str, argv: Iterable[Any], env: Mapping[str, Any]) -> dict | None:
    """DEBUG record of a launcher spawn: redacted argv, environment names only."""
    current = _current_control.get()
    detail = {
        "launch": launch_action,
        "argv_redacted": redact_argv(argv),
        "env_names": redact_env(env, debug=True),
    }
    if current:
        return write("DEBUG", "control_start", action=current[0], request_id=current[1], detail=detail)
    return write("DEBUG", "supervisor", action=launch_action, detail=detail)


def _files_newest_first() -> list[Path]:
    path = log_path()
    return [path] + [path.with_name(f"{path.name}.{index}") for index in range(1, KEPT + 1)]


def read_tail(limit: int) -> list[dict]:
    """Last ``limit`` parsed lines (oldest first), redacted again before returning."""
    collected: list[dict] = []
    for path in _files_newest_first():
        if len(collected) >= limit:
            break
        try:
            lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
        except FileNotFoundError:
            continue
        except OSError:
            log.warning("Manager debug log read failed for %s", path, exc_info=True)
            continue
        for line in reversed(lines):
            if len(collected) >= limit:
                break
            try:
                parsed = json.loads(line)
            except ValueError:
                continue
            if isinstance(parsed, dict):
                collected.append(parsed)
    collected.reverse()
    return [redact(item, debug=_verbose) for item in collected]
