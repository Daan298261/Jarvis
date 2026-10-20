"""RFC-0229 S1: one redaction pass for everything the Manager logs or returns.

The debug logger (``debug_log.py``) runs every record through :func:`redact`
before it is written, and the debug-log endpoint runs every parsed line through
it again before it is returned, so a secret never reaches disk or the page.
"""
from __future__ import annotations

import re
from functools import lru_cache
from pathlib import Path
from typing import Any, Iterable, Mapping

from .. import config

MASK = "***"
CASE_FILE = "<case-file>"

# Header names whose values are never logged (compared case-insensitively).
SECRET_HEADERS = frozenset(
    name.lower()
    for name in (
        "Authorization",
        "Cookie",
        "Set-Cookie",
        "X-API-Key",
        "Api-Key",
        "X-Jarvis-Key",
        "X-Anzu-Manager-Token",  # manager/main.py::TOKEN_HEADER
    )
)

# Argv flags whose value is a secret: ``--flag value`` and ``--flag=value``.
SECRET_FLAGS = frozenset(
    ("--api-key", "--token", "--password", "--secret", "--key", "--hf-token", "--auth", "--bearer")
)

SECRET_NAME = re.compile(r"(KEY|TOKEN|SECRET|PASSWORD|PASS|AUTH|CREDENTIAL)", re.IGNORECASE)
_ASSIGNMENT = re.compile(r"^([A-Za-z_][A-Za-z0-9_.-]*)=(.*)$", re.DOTALL)
_BEARER = re.compile(r"(?i)\b(bearer|basic)\s+[^\s\"',;]+")

# Owner chat text: never logged, only its length.
CHAT_TEXT_FIELDS = frozenset(("text", "prompt", "message", "content", "transcript"))
_CHARS = re.compile(r"^<\d+ chars>$")
ENV_FIELDS = frozenset(("env", "environ", "environment"))
ARGV_FIELDS = frozenset(("argv", "args", "cmdline", "command"))

# Values registered at runtime (the Manager session token) are masked wherever
# they appear inside any string.
_SECRET_VALUES: set[str] = set()


def register_secret(value: str) -> None:
    if value:
        _SECRET_VALUES.add(value)


def investigations_dir() -> Path:
    """Case files live under ``data_dir()/investigations`` (reverse_engineering/store.py)."""
    return config.data_dir() / "investigations"


def _case_file_pattern() -> re.Pattern[str]:
    return _compile_case_file_pattern(str(investigations_dir()))


@lru_cache(maxsize=8)
def _compile_case_file_pattern(base: str) -> re.Pattern[str]:
    variants = {base, base.replace("\\", "/"), base.replace("/", "\\")}
    alternatives = "|".join(re.escape(v) for v in sorted(variants, key=len, reverse=True))
    # The directory itself or anything below it, up to whitespace or a quote.
    return re.compile(rf"(?:{alternatives})(?:[\\/][^\s\"'<>|]*)?", re.IGNORECASE)


def redact_text(value: str) -> str:
    out = value
    for secret in _SECRET_VALUES:
        if secret in out:
            out = out.replace(secret, MASK)
    out = _BEARER.sub(lambda m: f"{m.group(1)} {MASK}", out)
    out = _case_file_pattern().sub(CASE_FILE, out)
    return out


def redact_headers(headers: Mapping[str, Any]) -> dict[str, str]:
    return {
        str(name): MASK if str(name).lower() in SECRET_HEADERS else redact_text(str(value))
        for name, value in headers.items()
    }


def redact_argv(argv: Iterable[Any]) -> list[str]:
    out: list[str] = []
    mask_next = False
    for raw in argv:
        arg = str(raw)
        if mask_next:
            out.append(MASK)
            mask_next = False
            continue
        lowered = arg.lower()
        if lowered in SECRET_FLAGS:
            out.append(arg)
            mask_next = True
            continue
        flag, sep, _value = arg.partition("=")
        if sep and flag.lower() in SECRET_FLAGS:
            out.append(f"{flag}={MASK}")
            continue
        assignment = _ASSIGNMENT.match(arg)
        if assignment and SECRET_NAME.search(assignment.group(1)):
            out.append(f"{assignment.group(1)}={MASK}")
            continue
        out.append(redact_text(arg))
    return out


def redact_env(env: Mapping[str, Any], *, debug: bool) -> list[str] | None:
    """Environment values are never kept; names only, and only on DEBUG."""
    return sorted(str(name) for name in env) if debug else None


def _secret_key(key: str) -> bool:
    return key.lower() in SECRET_HEADERS or bool(SECRET_NAME.search(key))


def redact(value: Any, *, debug: bool = False) -> Any:
    """Return a redacted copy of ``value`` (dicts, lists, strings, scalars)."""
    if isinstance(value, Mapping):
        out: dict[str, Any] = {}
        for raw_key, item in value.items():
            key = str(raw_key)
            lowered = key.lower()
            if _secret_key(key):
                out[key] = MASK
            elif lowered in CHAT_TEXT_FIELDS and isinstance(item, str):
                out[key] = item if _CHARS.match(item) else f"<{len(item)} chars>"
            elif lowered in ENV_FIELDS and isinstance(item, Mapping):
                names = redact_env(item, debug=debug)
                if names is not None:
                    out[f"{key}_names"] = names
            elif lowered in ARGV_FIELDS and isinstance(item, (list, tuple)):
                out[key] = redact_argv(item)
            else:
                out[key] = redact(item, debug=debug)
        return out
    if isinstance(value, (list, tuple)):
        return [redact(item, debug=debug) for item in value]
    if isinstance(value, str):
        return redact_text(value)
    return value
