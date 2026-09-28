"""Run linked pytest targets for capability records (deterministic, no live keys)."""

from __future__ import annotations

import os
import platform
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from ..capabilities.registry import get_capability, list_capabilities
from ..config import repo_root


def _unique_test_paths(test_ids: list[str]) -> list[str]:
    """Deduplicate test ids, keeping only targets that resolve inside ``tests/``."""
    tests_root = (repo_root() / "tests").resolve()
    seen: set[str] = set()
    ordered: list[str] = []
    for raw in test_ids:
        path = str(raw or "").strip().replace("\\", "/")
        if not path or path in seen or path.startswith("-"):
            continue
        file_part = (repo_root() / path.split("::", 1)[0]).resolve()
        try:
            file_part.relative_to(tests_root)
        except ValueError:
            continue
        if not file_part.exists():
            continue
        seen.add(path)
        ordered.append(path)
    return ordered


def run_capability_tests(
    capability_ids: list[str] | None = None,
    *,
    live: bool = False,
) -> dict[str, Any]:
    """Execute pytest for registry-linked tests. ``live`` is reserved for future opt-in provider runs."""
    if live:
        return {
            "ok": False,
            "mode": "live",
            "error": "Live provider benchmarks are opt-in and not enabled from this endpoint yet.",
            "ran_at": datetime.now(timezone.utc).isoformat(),
        }

    targets: list[str] = []
    rows: list[dict[str, Any]] = []
    if capability_ids:
        for cap_id in capability_ids:
            row = get_capability(cap_id)
            if row is None:
                rows.append({"capability_id": cap_id, "error": "unknown capability"})
                continue
            targets.extend(_unique_test_paths(row.test_ids))
            rows.append({"capability_id": cap_id, "test_ids": list(row.test_ids)})
    else:
        for row in list_capabilities():
            if row.test_ids:
                targets.extend(_unique_test_paths(row.test_ids))
        rows.append({"capability_id": "*", "test_ids": targets})

    paths = _unique_test_paths(targets)
    if not paths:
        return {
            "ok": True,
            "mode": "deterministic",
            "skipped": True,
            "message": "No executable test_ids linked for the requested capabilities.",
            "capabilities": rows,
            "ran_at": datetime.now(timezone.utc).isoformat(),
        }

    root = repo_root()
    env = {**os.environ, "PYTHONPATH": str(root / "backend"), "JARVIS_SKIP_MODEL": "1"}
    cmd = [sys.executable, "-m", "pytest", *paths, "-q", "--tb=line", "--no-header"]
    started = time.perf_counter()
    proc = subprocess.run(
        cmd,
        cwd=str(root),
        env=env,
        capture_output=True,
        text=True,
        timeout=600,
    )
    elapsed_ms = round((time.perf_counter() - started) * 1000, 2)
    return {
        "ok": proc.returncode == 0,
        "mode": "deterministic",
        "exit_code": proc.returncode,
        "elapsed_ms": elapsed_ms,
        "command": cmd,
        "stdout_tail": (proc.stdout or "")[-4000:],
        "stderr_tail": (proc.stderr or "")[-2000:],
        "capabilities": rows,
        "hardware_label": f"{platform.system()} {platform.machine()} / {platform.processor() or 'cpu'}",
        "python": platform.python_version(),
        "provider": "pytest_scripted",
        "ran_at": datetime.now(timezone.utc).isoformat(),
    }
