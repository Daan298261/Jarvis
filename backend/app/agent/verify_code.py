from __future__ import annotations

import asyncio
import re
import sys
from pathlib import Path
from typing import Any

_PYTEST_COUNTS = re.compile(
    r"(?P<failed>\d+)\s+failed|(?P<passed>\d+)\s+passed|(?P<error>\d+)\s+error|(?P<skipped>\d+)\s+skipped",
    re.I,
)


async def _run(args: list[str], cwd: str, timeout: int) -> dict[str, Any]:
    proc = await asyncio.create_subprocess_exec(
        *args,
        cwd=cwd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    try:
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=timeout)
    except TimeoutError:
        proc.kill()
        await proc.wait()
        return {
            "ok": False,
            "command": " ".join(args),
            "returncode": None,
            "output": f"timed out after {timeout}s",
            "timed_out": True,
        }
    out = stdout.decode("utf-8", errors="replace")
    err = stderr.decode("utf-8", errors="replace")
    code = proc.returncode or 0
    return {
        "ok": code == 0,
        "command": " ".join(args),
        "returncode": code,
        "output": (out + ("\n" + err if err else "")).strip()[-12000:],
        "timed_out": False,
    }


def _parse_pytest(output: str) -> dict[str, int]:
    counts = {"passed": 0, "failed": 0, "error": 0, "skipped": 0}
    for match in _PYTEST_COUNTS.finditer(output or ""):
        for key in counts:
            if match.group(key):
                counts[key] = int(match.group(key))
    return counts


def looks_like_python_project(root: Path) -> bool:
    return any(
        (root / name).exists()
        for name in ("pytest.ini", "pyproject.toml", "setup.cfg", "tests", "test")
    )


async def inspect_git(root: Path, timeout: int = 20) -> dict[str, Any]:
    status = await _run(["git", "status", "--porcelain=v1", "-b"], str(root), timeout)
    diff = await _run(["git", "diff", "--stat", "HEAD"], str(root), timeout)
    return {
        "ok": bool(status["ok"]),
        "clean": status["ok"] and not any(
            line.strip() and not line.startswith("##")
            for line in (status.get("output") or "").splitlines()
        ),
        "status": status.get("output") or status.get("error") or "",
        "diff_stat": diff.get("output") or "",
        "error": "" if status["ok"] else (status.get("output") or "git status failed"),
    }


async def run_pytest(root: Path, timeout: int = 120) -> dict[str, Any]:
    python = sys.executable or "python3"
    result = await _run([python, "-m", "pytest", "-q", "--maxfail=8"], str(root), timeout)
    counts = _parse_pytest(result.get("output") or "")
    result["counts"] = counts
    result["ran"] = True
    return result


async def verify_software(
    path: str | Path,
    *,
    run_tests: bool = True,
    timeout_seconds: int = 120,
) -> dict[str, Any]:
    """Independently inspect a repo. A worker saying 'fixed' is never enough."""
    root = Path(path).expanduser().resolve()
    report: dict[str, Any] = {
        "ok": False,
        "path": str(root),
        "reason": "",
        "git": {},
        "tests": {"ran": False, "ok": True, "output": "", "counts": {}},
        "principle": "A worker claiming success does not constitute successful completion.",
    }
    if not root.exists() or not root.is_dir():
        report["reason"] = f"Path {root} is not a directory"
        return report

    git_dir = root / ".git"
    if git_dir.exists() or (root / ".git").is_file():
        report["git"] = await inspect_git(root)
    else:
        inside = await _run(["git", "rev-parse", "--show-toplevel"], str(root), 10)
        if inside["ok"] and (inside.get("output") or "").strip():
            report["git"] = await inspect_git(Path(inside["output"].strip()))
        else:
            report["git"] = {
                "ok": True,
                "clean": True,
                "status": "not a git repository",
                "diff_stat": "",
                "error": "",
            }

    if run_tests and looks_like_python_project(root):
        report["tests"] = await run_pytest(root, timeout=timeout_seconds)
    elif run_tests:
        report["tests"] = {
            "ran": False,
            "ok": True,
            "output": "No pytest.ini / tests directory; skipped test run.",
            "counts": {},
            "command": "",
        }

    git_ok = bool(report["git"].get("ok"))
    tests_ok = bool(report["tests"].get("ok"))
    report["ok"] = git_ok and tests_ok
    if not git_ok:
        report["reason"] = report["git"].get("error") or "git inspection failed"
    elif not tests_ok:
        report["reason"] = "tests failed"
    else:
        report["reason"] = "git inspected; tests passed or were not applicable"
    return report


def format_report(report: dict[str, Any]) -> str:
    tests = report.get("tests") or {}
    git = report.get("git") or {}
    counts = tests.get("counts") or {}
    lines = [
        f"ok={report.get('ok')}",
        f"path={report.get('path')}",
        f"reason={report.get('reason')}",
        f"principle={report.get('principle')}",
        "--- git ---",
        (git.get("status") or "")[:4000],
        git.get("diff_stat") or "(no diff)",
        "--- tests ---",
        f"ran={tests.get('ran')} ok={tests.get('ok')} command={tests.get('command') or ''}",
        f"passed={counts.get('passed', 0)} failed={counts.get('failed', 0)} "
        f"error={counts.get('error', 0)} skipped={counts.get('skipped', 0)}",
        (tests.get("output") or "")[-6000:],
    ]
    return "\n".join(lines)
