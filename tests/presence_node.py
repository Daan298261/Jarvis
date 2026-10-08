"""Run frontend node:test files that import TypeScript via --experimental-strip-types.

Node 22 is required. Older Node skips with an explicit reason instead of a
confusing syntax error. CI pins Node 22 and installs frontend dependencies.
"""

from __future__ import annotations

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
    assert result.returncode == 0, result.stdout + "\n" + result.stderr
