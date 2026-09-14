"""Append-only daily UTC clock log (RFC-0087).

DST and timezone offset changes must not lock licenses. A UTC calendar
rollback more than one day behind the last trusted sample suspends licensed
modules until current UTC is again >= that sample. Household functions stay up.
Data is never deleted.
"""
from __future__ import annotations

import hmac
import json
import os
import threading
from dataclasses import dataclass
from datetime import datetime, timezone
from hashlib import sha256
from pathlib import Path
from typing import Any

from ..config import data_dir

CLOCK_ROLLBACK_MESSAGE = (
    "Clock rollback detected. Licensed modules are suspended until "
    "system time is consistent with the last trusted UTC log."
)

LOG_NAME = "clock-log.jsonl"
SECRET_NAME = "clock-log.secret"
ROLLBACK_DAYS = 1
SKEW_SECONDS = 300

_LOCK = threading.RLock()


def _utcnow() -> datetime:
    return datetime.now(timezone.utc).replace(microsecond=0)


def _iso(value: datetime) -> str:
    text = value.astimezone(timezone.utc).replace(microsecond=0).isoformat()
    return text.replace("+00:00", "Z")


def _parse_iso(value: str) -> datetime:
    text = (value or "").strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    parsed = datetime.fromisoformat(text)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def clock_log_path() -> Path:
    return data_dir() / LOG_NAME


def clock_secret_path() -> Path:
    return data_dir() / SECRET_NAME


def local_offset_minutes(now: datetime | None = None) -> int:
    current = now or datetime.now().astimezone()
    if current.tzinfo is None:
        current = current.replace(tzinfo=datetime.now().astimezone().tzinfo)
    offset = current.utcoffset()
    if offset is None:
        return 0
    return int(offset.total_seconds() // 60)


def _load_or_create_secret() -> bytes:
    path = clock_secret_path()
    if path.is_file():
        raw = path.read_bytes().strip()
        if raw:
            return raw
    secret = os.urandom(32)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_bytes(secret)
    try:
        os.chmod(tmp, 0o600)
    except OSError:
        pass
    os.replace(tmp, path)
    return secret


def _mac(secret: bytes, payload: dict[str, Any]) -> str:
    body = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hmac.new(secret, body, sha256).hexdigest()


def _parse_line(raw: str, secret: bytes) -> dict[str, Any] | None:
    text = raw.strip()
    if not text:
        return None
    try:
        record = json.loads(text)
    except json.JSONDecodeError:
        return None
    if not isinstance(record, dict):
        return None
    provided = str(record.get("hmac") or "")
    payload = {key: value for key, value in record.items() if key != "hmac"}
    expected = _mac(secret, payload)
    if not hmac.compare_digest(provided, expected):
        return None
    try:
        _parse_iso(str(payload.get("utc_datetime") or ""))
    except ValueError:
        return None
    return payload


def _iter_trusted_samples() -> list[dict[str, Any]]:
    path = clock_log_path()
    if not path.is_file():
        return []
    secret = _load_or_create_secret()
    trusted: list[dict[str, Any]] = []
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return []
    for line in lines:
        parsed = _parse_line(line, secret)
        if parsed is not None:
            trusted.append(parsed)
    return trusted


def last_trusted_sample() -> dict[str, Any] | None:
    samples = _iter_trusted_samples()
    return samples[-1] if samples else None


def _append_sample(now: datetime, *, offset_minutes: int | None = None) -> dict[str, Any]:
    secret = _load_or_create_secret()
    payload = {
        "utc_date": now.date().isoformat(),
        "utc_datetime": _iso(now),
        "local_offset_minutes": int(offset_minutes if offset_minutes is not None else local_offset_minutes()),
    }
    record = dict(payload)
    record["hmac"] = _mac(secret, payload)
    path = clock_log_path()
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(record, sort_keys=True) + "\n")
    return payload


@dataclass(frozen=True)
class ClockVerdict:
    ok: bool
    locked: bool
    reason: str = ""
    last_trusted_utc: str = ""
    sampled: bool = False

    def as_dict(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "locked": self.locked,
            "reason": self.reason,
            "last_trusted_utc": self.last_trusted_utc,
            "sampled": self.sampled,
        }


def inspect_clock(
    *,
    now: datetime | None = None,
    local_offset: int | None = None,
    record: bool = True,
) -> ClockVerdict:
    """Check UTC monotonicity. Optionally append a daily trusted sample.

    Rollback samples are not written as trusted. Unlock happens automatically
    when current UTC is again >= the last trusted sample.
    """
    current = now or _utcnow()
    if current.tzinfo is None:
        current = current.replace(tzinfo=timezone.utc)
    else:
        current = current.astimezone(timezone.utc)
    current = current.replace(microsecond=0)
    offset = local_offset if local_offset is not None else local_offset_minutes()

    with _LOCK:
        last = last_trusted_sample()
        if last is None:
            sampled = False
            if record:
                _append_sample(current, offset_minutes=offset)
                sampled = True
            return ClockVerdict(ok=True, locked=False, sampled=sampled)

        try:
            last_dt = _parse_iso(str(last["utc_datetime"]))
        except ValueError:
            sampled = False
            if record:
                _append_sample(current, offset_minutes=offset)
                sampled = True
            return ClockVerdict(ok=True, locked=False, sampled=sampled)

        if current.date() < last_dt.date():
            return ClockVerdict(
                ok=False,
                locked=True,
                reason=CLOCK_ROLLBACK_MESSAGE,
                last_trusted_utc=str(last.get("utc_datetime") or ""),
                sampled=False,
            )

        sampled = False
        last_date = str(last.get("utc_date") or last_dt.date().isoformat())
        if record and current.date().isoformat() != last_date and current >= last_dt:
            _append_sample(current, offset_minutes=offset)
            sampled = True
        return ClockVerdict(
            ok=True,
            locked=False,
            last_trusted_utc=str(last.get("utc_datetime") or ""),
            sampled=sampled,
        )


def record_clock_sample(*, now: datetime | None = None) -> ClockVerdict:
    return inspect_clock(now=now, record=True)


def licensed_modules_locked(*, now: datetime | None = None) -> bool:
    return inspect_clock(now=now, record=False).locked
