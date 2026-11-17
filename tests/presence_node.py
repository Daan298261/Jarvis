"""Run frontend node:test files that import TypeScript via --experimental-strip-types.

Node 22 is required. Older Node skips with an explicit reason instead of a
confusing syntax error. CI pins Node 22 and installs frontend dependencies.
"""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
FRONTEND = ROOT / "frontend"


def node_major() -> int | None:
    node = shutil.which("node")
    if not node:
        return None
    try:
        result = subprocess.run(
            [node, "--version"],
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    text = (result.stdout or "").strip().lstrip("v")
    major = text.split(".", 1)[0]
    try:
        return int(major)
    except ValueError:
        return None


def missing_frontend_packages() -> list[str]:
    """Packages frontend/package.json declares that frontend/node_modules does not have."""
    manifest = json.loads((FRONTEND / "package.json").read_text(encoding="utf-8"))
    declared = {**manifest.get("dependencies", {}), **manifest.get("devDependencies", {})}
    return sorted(name for name in declared if not (FRONTEND / "node_modules" / name).is_dir())


def run_presence_node_suite(*files: str, timeout: int = 180) -> None:
    major = node_major()
    if major is None or major < 22:
        found = "missing" if major is None else f"v{major}"
        pytest.skip(
            "presence .mjs suites need Node 22 or newer for --experimental-strip-types "
            f"(found {found})"
        )
    result = subprocess.run(
        ["node", "--experimental-strip-types", "--test", *files],
        cwd=FRONTEND,
        capture_output=True,
        text=True,
        timeout=timeout,
        check=False,
    )
    output = result.stdout + "\n" + result.stderr
    if result.returncode != 0 and "ERR_MODULE_NOT_FOUND" in output:
        missing = missing_frontend_packages()
        if missing:
            # A failure, not a skip: CI installs these, so a skip there would hide the suites.
            pytest.fail(
                f"frontend dependencies are not installed ({', '.join(missing)}); "
                "run `npm ci` in frontend/ before these .mjs suites",
                pytrace=False,
            )
    assert result.returncode == 0, output
