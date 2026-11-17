#!/usr/bin/env python3
"""es_verify: the single verification runner of the engineering standards.

Reads ``quality-gates.toml`` from the project root, enforces the gate policy
(mandatory gates may be extended but never silently removed or disabled),
runs every required gate, writes per-gate logs plus a machine-readable report
to ``.verify/`` and exits non-zero when anything mandatory fails.

Exit codes: 0 = all required gates passed, 1 = at least one gate failed,
2 = the gate policy or configuration is invalid.

Standard library only (Python >= 3.11) so it can be vendored into any repo.
"""

from __future__ import annotations

import argparse
import contextlib
import datetime as dt
import json
import os
import platform
import re
import shlex
import subprocess
import sys
import time
import tomllib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

STANDARDS_VERSION = "1.0.0"

# The 15 mandatory gates of the directive, in execution order.
MANDATORY_GATES: tuple[str, ...] = (
    "install",
    "format",
    "lint",
    "static_analysis",
    "typecheck",
    "unit_tests",
    "integration_tests",
    "contract_tests",
    "db_migrations",
    "build",
    "startup",
    "health_checks",
    "e2e_tests",
    "dependency_scan",
    "secret_scan",
)
# Gates that can never be waived or declared not applicable.
UNWAIVABLE: frozenset[str] = frozenset({"secret_scan", "static_analysis"})
VALID_STATUS: frozenset[str] = frozenset({"required", "not_applicable", "waived"})
MIN_REASON_LEN = 15
MAX_WAIVER_DAYS = 120
DEFAULT_TIMEOUT_S = 1800
# Shell fragments that turn a failing command into a passing one.
BYPASS_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"\|\|\s*(true|:|exit\s+0)\b"),
    re.compile(r";\s*exit\s+0\b"),
    re.compile(r"--passWithNoTests\b"),
    re.compile(r"--exit-zero\b"),
    re.compile(r"\bcontinue-on-error\b"),
    re.compile(r"-ErrorAction\s+SilentlyContinue", re.IGNORECASE),
)


@dataclass
class Gate:
    gate_id: str
    status: str
    run: list[str] | list[list[str]] | str | None = None
    reason: str = ""
    owner: str = ""
    expires: str = ""
    timeout: int = DEFAULT_TIMEOUT_S
    mandatory: bool = True
    cwd: str = "."
    env: dict[str, str] = field(default_factory=dict)


@dataclass
class GateResult:
    gate_id: str
    status: str
    result: str  # passed | failed | not_applicable | waived | skipped
    exit_code: int | None = None
    duration_s: float = 0.0
    log: str | None = None
    detail: str = ""


class PolicyError(Exception):
    """Raised when quality-gates.toml violates the mandatory gate policy."""


def _today() -> dt.date:
    override = os.environ.get("ES_VERIFY_TODAY")
    return dt.date.fromisoformat(override) if override else dt.date.today()


def _steps(run: list[str] | list[list[str]] | str) -> list[list[str] | str]:
    """Normalise a gate's run value to a list of commands executed in sequence."""
    if isinstance(run, str):
        return [run]
    if run and all(isinstance(p, list) for p in run):
        return [[str(x) for x in p] for p in run if isinstance(p, list)]
    return [[str(p) for p in run]]


def _command_text(run: list[str] | list[list[str]] | str) -> str:
    return " && ".join(s if isinstance(s, str) else " ".join(s) for s in _steps(run))


def _parse_gate(gate_id: str, raw: Any, mandatory: bool) -> Gate:
    if not isinstance(raw, dict):
        raise PolicyError(f"gate '{gate_id}' must be a table")
    status = str(raw.get("status", ""))
    if status not in VALID_STATUS:
        raise PolicyError(f"gate '{gate_id}': status must be one of {sorted(VALID_STATUS)}, got '{status}'")
    run = raw.get("run")
    if run is not None and not isinstance(run, (str, list)):
        raise PolicyError(f"gate '{gate_id}': run must be a string or a list of strings")
    if isinstance(run, list) and run and all(isinstance(p, list) for p in run):
        if not all(isinstance(x, str) for step in run for x in step):
            raise PolicyError(f"gate '{gate_id}': run steps must be lists of strings")
    elif isinstance(run, list) and not all(isinstance(p, str) for p in run):
        raise PolicyError(f"gate '{gate_id}': run must be a string, an argv list or a list of argv lists")
    timeout = raw.get("timeout", DEFAULT_TIMEOUT_S)
    if not isinstance(timeout, int) or timeout <= 0:
        raise PolicyError(f"gate '{gate_id}': timeout must be a positive integer (seconds)")
    env = raw.get("env", {})
    if not isinstance(env, dict):
        raise PolicyError(f"gate '{gate_id}': env must be a table")
    return Gate(
        gate_id=gate_id,
        status=status,
        run=run,
        reason=str(raw.get("reason", "")).strip(),
        owner=str(raw.get("owner", "")).strip(),
        expires=str(raw.get("expires", "")).strip(),
        timeout=timeout,
        mandatory=mandatory,
        cwd=str(raw.get("cwd", ".")),
        env={str(k): str(v) for k, v in env.items()},
    )


def validate_gate(gate: Gate, today: dt.date) -> None:
    """Enforce the policy for a single gate; raise PolicyError on violation."""
    gid = gate.gate_id
    if gate.status == "required":
        if not gate.run:
            raise PolicyError(f"gate '{gid}' is required but has no 'run' command")
        text = _command_text(gate.run)
        for pattern in BYPASS_PATTERNS:
            if pattern.search(text):
                raise PolicyError(f"gate '{gid}': command contains a failure bypass ({pattern.pattern!r})")
        return
    if gid in UNWAIVABLE:
        raise PolicyError(f"gate '{gid}' is mandatory and can never be '{gate.status}'")
    if len(gate.reason) < MIN_REASON_LEN:
        raise PolicyError(
            f"gate '{gid}' is '{gate.status}' and needs a reason of at least {MIN_REASON_LEN} characters"
        )
    if gate.status == "waived":
        if not gate.owner:
            raise PolicyError(f"gate '{gid}' waiver needs an owner")
        try:
            expires = dt.date.fromisoformat(gate.expires)
        except ValueError as exc:
            raise PolicyError(f"gate '{gid}' waiver needs expires = 'YYYY-MM-DD'") from exc
        if expires < today:
            raise PolicyError(f"gate '{gid}' waiver expired on {expires.isoformat()}")
        if (expires - today).days > MAX_WAIVER_DAYS:
            raise PolicyError(f"gate '{gid}' waiver may last at most {MAX_WAIVER_DAYS} days")


def load_config(root: Path, today: dt.date | None = None) -> tuple[dict[str, Any], list[Gate]]:
    """Load and validate quality-gates.toml; return (project table, ordered gates)."""
    today = today or _today()
    path = root / "quality-gates.toml"
    if not path.is_file():
        raise PolicyError(f"{path} not found: every project must declare its gates")
    try:
        data = tomllib.loads(path.read_text(encoding="utf-8"))
    except tomllib.TOMLDecodeError as exc:
        raise PolicyError(f"quality-gates.toml is not valid TOML: {exc}") from exc
    project = data.get("project", {})
    if not isinstance(project, dict) or not project.get("name"):
        raise PolicyError("quality-gates.toml needs [project] with a name")
    gates_raw = data.get("gates", {})
    if not isinstance(gates_raw, dict):
        raise PolicyError("[gates] must be a table")
    missing = [g for g in MANDATORY_GATES if g not in gates_raw]
    if missing:
        raise PolicyError(
            "mandatory gates missing from quality-gates.toml (they may be declared "
            f"not_applicable/waived with a reason, never removed): {', '.join(missing)}"
        )
    gates: list[Gate] = []
    for gid in MANDATORY_GATES:
        gates.append(_parse_gate(gid, gates_raw[gid], mandatory=True))
    extra = gates_raw.get("extra", {})
    if not isinstance(extra, dict):
        raise PolicyError("[gates.extra] must be a table")
    for gid, raw in extra.items():
        gates.append(_parse_gate(f"extra.{gid}", raw, mandatory=False))
    unknown = set(gates_raw) - set(MANDATORY_GATES) - {"extra"}
    if unknown:
        raise PolicyError(
            f"unknown gate ids {sorted(unknown)}: put project-specific gates under [gates.extra.<id>]"
        )
    for gate in gates:
        validate_gate(gate, today)
    return project, gates


def _git(root: Path, *args: str) -> str | None:
    try:
        out = subprocess.run(
            ["git", *args], cwd=root, capture_output=True, text=True, timeout=30, check=False
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    return out.stdout.strip() if out.returncode == 0 else None


def _group_kwargs() -> dict[str, Any]:
    """Start each gate in its own process group so a timeout kills the whole tree."""
    if sys.platform == "win32":
        return {"creationflags": subprocess.CREATE_NEW_PROCESS_GROUP}
    return {"start_new_session": True}


def _kill_tree(proc: subprocess.Popen[bytes]) -> None:
    if os.name == "nt":
        subprocess.run(["taskkill", "/T", "/F", "/PID", str(proc.pid)], capture_output=True, check=False)
        return
    import signal

    with contextlib.suppress(ProcessLookupError):
        os.killpg(proc.pid, signal.SIGKILL)


def run_gate(gate: Gate, root: Path, log_dir: Path, stream: bool) -> GateResult:
    if gate.status != "required":
        return GateResult(gate.gate_id, gate.status, gate.status, detail=gate.reason)
    if gate.run is None:  # guaranteed by policy validation; defensive for library callers
        return GateResult(gate.gate_id, gate.status, "failed", detail="required gate has no run command")
    commands: list[list[str] | str] = []
    for step in _steps(gate.run):
        if isinstance(step, list):
            commands.append([sys.executable if part == "{python}" else part for part in step])
        else:
            commands.append(step.replace("{python}", shlex.quote(sys.executable)))
    log_path = log_dir / f"{gate.gate_id}.log"
    env = {**os.environ, "ES_VERIFY": "1", **gate.env}
    start = time.monotonic()
    deadline = start + gate.timeout
    timed_out = False
    code: int | None = 0
    with log_path.open("w", encoding="utf-8") as log:
        for argv in commands:
            log.write(f"$ {argv if isinstance(argv, str) else ' '.join(argv)}\n")
            log.flush()
            try:
                proc = subprocess.Popen(
                    argv,
                    cwd=root / gate.cwd,
                    shell=isinstance(argv, str),
                    env=env,
                    stdout=log,
                    stderr=subprocess.STDOUT,
                    **_group_kwargs(),
                )
            except OSError as exc:
                log.write(f"failed to start: {exc}\n")
                return GateResult(
                    gate.gate_id,
                    gate.status,
                    "failed",
                    None,
                    time.monotonic() - start,
                    str(log_path),
                    f"could not start command: {exc}",
                )
            try:
                code = proc.wait(timeout=max(1.0, deadline - time.monotonic()))
            except subprocess.TimeoutExpired:
                timed_out = True
                _kill_tree(proc)
                code = proc.wait()
            if timed_out or code != 0:
                break
    if stream:
        for line in log_path.read_text(encoding="utf-8", errors="replace").splitlines():
            print(f"  [{gate.gate_id}] {line}")
    duration = time.monotonic() - start
    if timed_out:
        return GateResult(
            gate.gate_id,
            gate.status,
            "failed",
            code,
            duration,
            str(log_path),
            f"timed out after {gate.timeout}s",
        )
    result = "passed" if code == 0 else "failed"
    return GateResult(
        gate.gate_id,
        gate.status,
        result,
        code,
        duration,
        str(log_path),
        "" if code == 0 else f"exit code {code}",
    )


def write_report(
    root: Path, out_dir: Path, project: dict[str, Any], results: list[GateResult], policy_error: str | None
) -> dict[str, Any]:
    failed = [r.gate_id for r in results if r.result == "failed"]
    overall = "error" if policy_error else ("failed" if failed else "passed")
    report: dict[str, Any] = {
        "schema": "es-verify-report/1",
        "standards_version": STANDARDS_VERSION,
        "project": project.get("name"),
        "profile": project.get("profile"),
        "generated_at": dt.datetime.now(dt.UTC).isoformat(timespec="seconds"),
        "git": {
            "commit": _git(root, "rev-parse", "HEAD"),
            "branch": _git(root, "rev-parse", "--abbrev-ref", "HEAD"),
            "dirty": bool(_git(root, "status", "--porcelain")),
        },
        "host": {
            "os": platform.system(),
            "python": platform.python_version(),
            "ci": bool(os.environ.get("CI")),
        },
        "overall": overall,
        "policy_error": policy_error,
        "failed_gates": failed,
        "gates": [
            {
                "id": r.gate_id,
                "declared": r.status,
                "result": r.result,
                "exit_code": r.exit_code,
                "duration_s": round(r.duration_s, 2),
                "log": os.path.relpath(r.log, root) if r.log else None,
                "detail": r.detail,
            }
            for r in results
        ],
    }
    (out_dir / "report.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    return report


def _console_safe() -> None:
    """Never crash on a legacy console code page (cp1252 on Windows): replace unencodable characters."""
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is not None:
            reconfigure(errors="replace")


def main(argv: list[str] | None = None) -> int:
    _console_safe()
    parser = argparse.ArgumentParser(description="Run the mandatory quality gates.")
    parser.add_argument("--root", default=".", help="project root (default: cwd)")
    parser.add_argument("--only", action="append", default=[], help="run only these gate ids")
    parser.add_argument("--fail-fast", action="store_true", help="stop at the first failure")
    parser.add_argument("--list", action="store_true", help="print the gate plan and exit")
    parser.add_argument("--stream", action="store_true", help="echo each gate log after it finishes")
    parser.add_argument("--policy-only", action="store_true", help="validate policy only")
    args = parser.parse_args(argv)

    root = Path(args.root).resolve()
    out_dir = root / ".verify"
    log_dir = out_dir / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    try:
        project, gates = load_config(root)
    except PolicyError as exc:
        print(f"es-verify: POLICY ERROR: {exc}", file=sys.stderr)
        write_report(root, out_dir, {"name": root.name}, [], str(exc))
        return 2
    if args.list or args.policy_only:
        for g in gates:
            cmd = _command_text(g.run) if g.run else g.reason
            print(f"{g.gate_id:22} {g.status:15} {cmd}")
        print("es-verify: policy OK")
        return 0
    unknown_only = set(args.only) - {g.gate_id for g in gates}
    if unknown_only:
        print(f"es-verify: unknown gate(s) in --only: {sorted(unknown_only)}", file=sys.stderr)
        return 2
    selected = [g for g in gates if not args.only or g.gate_id in args.only]
    results: list[GateResult] = []
    stop = False
    for gate in selected:
        if stop:
            results.append(
                GateResult(
                    gate.gate_id, gate.status, "skipped", detail="not run: earlier gate failed (--fail-fast)"
                )
            )
            continue
        print(f"es-verify: >> {gate.gate_id} ({gate.status})", flush=True)
        res = run_gate(gate, root, log_dir, args.stream)
        results.append(res)
        print(f"es-verify:   {res.result.upper()} {res.detail}".rstrip(), flush=True)
        if res.result == "failed" and args.fail_fast:
            stop = True
    report = write_report(root, out_dir, project, results, None)
    print("\nes-verify summary")
    for r in results:
        mark = {"passed": "PASS", "failed": "FAIL", "skipped": "SKIP"}.get(r.result, "N/A ")
        print(f"  {mark}  {r.gate_id:22} {r.duration_s:7.1f}s  {r.detail}")
    partial = " (partial run: --only)" if args.only else ""
    print(f"es-verify: overall {report['overall'].upper()}{partial} -> {out_dir / 'report.json'}")
    if report["overall"] != "passed":
        for r in results:
            if r.result == "failed" and r.log:
                print(f"\n----- tail of {r.gate_id} log -----", file=sys.stderr)
                lines = Path(r.log).read_text(encoding="utf-8", errors="replace").splitlines()
                print("\n".join(lines[-40:]), file=sys.stderr)
        return 1
    if any(r.result == "skipped" for r in results):
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
