from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from ..config import data_dir

MAX_BENCHMARKS = 40
PROFILE_ORDER = (
    "abliterated-fast",
    "abliterated-balanced",
    "fast",
    "balanced",
    "quality",
    "unrestricted-fast",
    "unrestricted-balanced",
    "unrestricted-quality",
)
METRIC_KEYS = (
    "tokens_per_second",
    "prompt_tokens_per_second",
    "vram_used_mib",
    "ram_used_gb",
    "load_time_seconds",
)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def benchmark_store_path() -> Path:
    return data_dir() / "model_benchmarks.json"


def _empty_store() -> dict[str, Any]:
    return {"version": 1, "profiles": {}, "samples": []}


def _read_store() -> dict[str, Any]:
    path = benchmark_store_path()
    if not path.exists():
        return _empty_store()
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return _empty_store()
    if isinstance(raw, list):
        samples = [row for row in raw if isinstance(row, dict)]
        return {"version": 1, "profiles": _profiles_from_samples(samples), "samples": samples}
    if not isinstance(raw, dict):
        return _empty_store()
    samples = raw.get("samples") or []
    if not isinstance(samples, list):
        samples = []
    samples = [row for row in samples if isinstance(row, dict)]
    profiles = raw.get("profiles") or {}
    if not isinstance(profiles, dict) or not profiles:
        profiles = _profiles_from_samples(samples)
    else:
        profiles = {
            str(name).strip().lower(): dict(row)
            for name, row in profiles.items()
            if str(name).strip() and isinstance(row, dict)
        }
    return {"version": int(raw.get("version") or 1), "profiles": profiles, "samples": samples}


def _profiles_from_samples(samples: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    profiles: dict[str, dict[str, Any]] = {}
    for row in samples:
        name = str(row.get("profile") or "").strip().lower()
        if name:
            profiles[name] = dict(row)
    return profiles


def _public_row(row: dict[str, Any]) -> dict[str, Any]:
    out = dict(row)
    out["quantization"] = out.get("quantization") or out.get("quant") or ""
    out["updated_at"] = out.get("updated_at") or out.get("recorded_at") or ""
    return out


def load_benchmarks() -> list[dict[str, Any]]:
    return list(_read_store().get("samples") or [])


def save_benchmarks(rows: list[dict[str, Any]]) -> None:
    path = benchmark_store_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    samples = rows[-MAX_BENCHMARKS:]
    payload = {
        "version": 1,
        "profiles": _profiles_from_samples(samples),
        "samples": samples,
    }
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def latest_for_profile(profile: str) -> dict[str, Any] | None:
    name = (profile or "").strip().lower()
    if not name:
        return None
    store = _read_store()
    row = store.get("profiles", {}).get(name)
    if isinstance(row, dict):
        return dict(row)
    for sample in reversed(store.get("samples") or []):
        if str(sample.get("profile") or "").strip().lower() == name:
            return dict(sample)
    return None


def get_benchmark(profile: str) -> dict[str, Any] | None:
    row = latest_for_profile(profile)
    return _public_row(row) if row else None


def list_benchmarks() -> list[dict[str, Any]]:
    store = _read_store()
    profiles = dict(store.get("profiles") or {})
    rows: list[dict[str, Any]] = []
    seen: set[str] = set()
    for name in PROFILE_ORDER:
        row = profiles.get(name) or latest_for_profile(name)
        if row:
            public = _public_row(row)
            public["profile"] = name
            rows.append(public)
            seen.add(name)
    for name, row in profiles.items():
        if name in seen or not isinstance(row, dict):
            continue
        public = _public_row(row)
        public["profile"] = name
        rows.append(public)
    return rows


def recent_benchmarks(limit: int = 12) -> list[dict[str, Any]]:
    rows = load_benchmarks()
    rows.reverse()
    return rows[: max(1, min(int(limit or 12), MAX_BENCHMARKS))]


def _merge(previous: dict[str, Any] | None, incoming: dict[str, Any]) -> dict[str, Any]:
    base = dict(previous or {})
    sample: dict[str, Any] = {
        "profile": incoming.get("profile") or base.get("profile") or "",
        "quant": incoming.get("quant") or base.get("quant") or "",
        "context_size": incoming.get("context_size") if incoming.get("context_size") is not None else base.get("context_size"),
        "thinking": incoming.get("thinking") if incoming.get("thinking") is not None else base.get("thinking"),
        "source": incoming.get("source") or "generation",
        "recorded_at": _now(),
    }
    for key in METRIC_KEYS:
        value = incoming.get(key)
        sample[key] = value if value is not None else base.get(key)
    return sample


def record_benchmark(**fields: Any) -> dict[str, Any] | None:
    profile = str(fields.get("profile") or "").strip().lower()
    if not profile:
        return None
    incoming = dict(fields)
    incoming["profile"] = profile
    previous = latest_for_profile(profile)
    sample = _merge(previous, incoming)
    if not any(sample.get(key) is not None for key in METRIC_KEYS):
        return previous
    store = _read_store()
    samples = list(store.get("samples") or [])
    samples.append(sample)
    samples = samples[-MAX_BENCHMARKS:]
    profiles = dict(store.get("profiles") or {})
    profiles[profile] = dict(sample)
    path = benchmark_store_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps({"version": 1, "profiles": profiles, "samples": samples}, indent=2),
        encoding="utf-8",
    )
    return sample


def upsert_benchmark(profile: str, **metrics: Any) -> dict[str, Any] | None:
    return record_benchmark(profile=profile, **metrics)
