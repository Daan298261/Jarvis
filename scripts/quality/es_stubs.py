#!/usr/bin/env python3
"""es_stubs: detects fake/placeholder implementations and quality-gate bypasses.

Part of the mandatory ``static_analysis`` gate. Two finding classes:

* ``stub``   - production code that pretends to work: NotImplementedError,
               "not implemented", "coming soon", placeholder returns, untracked
               TODO/FIXME (a TODO must reference a ticket: ``TODO(#123)``).
* ``bypass`` - anything that makes a failing check look green: skipped tests
               without a reason, ``|| true`` in CI, ``continue-on-error``,
               ``--passWithNoTests``, ``--exit-zero``, blanket ``noqa``/``type: ignore``.

Legacy repos may freeze existing findings in a baseline (ratchet): only NEW
findings fail. Suppress a reviewed line with ``es:allow-stub <reason>``.
"""

from __future__ import annotations

import argparse
import fnmatch
import hashlib
import json
import re
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

CODE_SUFFIXES = {
    ".py",
    ".ts",
    ".tsx",
    ".js",
    ".jsx",
    ".mjs",
    ".cjs",
    ".kt",
    ".kts",
    ".java",
    ".rs",
    ".ps1",
    ".psm1",
    ".sh",
    ".go",
    ".cs",
    ".vue",
    ".svelte",
    ".astro",
    ".html",
}
CI_GLOBS = (
    ".github/workflows/*.yml",
    ".github/workflows/*.yaml",
    "Makefile",
    "scripts/verify*",
    "quality-gates.toml",
    "package.json",
)
TEST_HINTS = ("/tests/", "/test/", "/__tests__/", "/spec/", "/androidTest/", "/fixtures/")
TEST_NAME = re.compile(r"(^test_.*\.py$|_test\.py$|\.(test|spec)\.[cm]?[jt]sx?$|Test\.kt$|Tests?\.ps1$)")

STUB_RULES: tuple[tuple[str, re.Pattern[str]], ...] = (
    (
        "not-implemented",
        re.compile(
            r"raise\s+NotImplementedError|throw\s+new\s+Error\(\s*['\"`]not\s+implemented|"
            r"TODO\(\)|NotImplementedException|unimplemented!\(|todo!\(",
            re.IGNORECASE,
        ),
    ),
    (
        "placeholder-text",
        re.compile(
            r"(?i)\b(coming\s+soon|not\s+(yet\s+)?implemented|lorem\s+ipsum|stub(bed)?\s+(response|data|implementation)|"
            r"fake\s+(success|response|data|implementation)|placeholder\s+(implementation|response|logic|button|data))\b"
        ),
    ),
    ("untracked-todo", re.compile(r"\b(TODO|FIXME|XXX|HACK)\b(?!\s*\((#|[A-Z]+-)\w+)")),
)
TEST_BYPASS_RULES: tuple[tuple[str, re.Pattern[str]], ...] = (
    (
        "skip-without-reason",
        re.compile(
            r"@pytest\.mark\.skip\s*(\(\s*\))?\s*$|@unittest\.skip\s*$|"
            r"\b(it|test|describe)\.skip\(|\bx(it|describe|test)\(|@Ignore\s*$|@Disabled\s*$"
        ),
    ),
    ("focused-test", re.compile(r"\b(it|test|describe)\.only\(|\bf(it|describe)\(")),
)
CODE_BYPASS_RULES: tuple[tuple[str, re.Pattern[str]], ...] = (
    (
        "blanket-noqa",
        re.compile(r"#\s*noqa\s*$|#\s*type:\s*ignore\s*$|eslint-disable\s*(\*/)?\s*$|@ts-nocheck"),
    ),
)
CI_BYPASS_RULES: tuple[tuple[str, re.Pattern[str]], ...] = (
    (
        "ci-bypass",
        re.compile(
            r"\|\|\s*(true|:|exit\s+0)\b|continue-on-error:\s*true|--passWithNoTests|--exit-zero|"
            r"exit\s+0\s*#\s*(always|force)"
        ),
    ),
)
ALLOW_MARKER = "es:allow-stub"
DEFAULT_EXCLUDES = (
    "*site-packages/*",
    "node_modules/*",
    "*/node_modules/*",
    "vendor/*",
    ".vendor/*",
    "third_party/*",
    "*/third_party/*",
    ".verify/*",
    "*.min.js",
    "dist/*",
    "build/*",
)


@dataclass(frozen=True)
class Finding:
    path: str
    line: int
    kind: str
    rule: str
    text: str
    fingerprint: str


def list_files(root: Path) -> list[str]:
    try:
        out = subprocess.run(
            ["git", "ls-files", "-z", "--cached", "--others", "--exclude-standard"],
            cwd=root,
            capture_output=True,
            check=True,
            timeout=60,
        )
        return [n for n in out.stdout.decode("utf-8", "replace").split("\0") if n]
    except (OSError, subprocess.SubprocessError):
        return [
            p.relative_to(root).as_posix() for p in root.rglob("*") if p.is_file() and ".git" not in p.parts
        ]


def is_test_path(rel: str) -> bool:
    return any(h in f"/{rel}" for h in TEST_HINTS) or bool(TEST_NAME.search(Path(rel).name))


def _fingerprint(rel: str, rule: str, text: str) -> str:
    normalized = re.sub(r"\s+", " ", text.strip())
    return hashlib.sha256(f"{rel}\0{rule}\0{normalized}".encode()).hexdigest()[:24]


def scan_file(rel: str, text: str) -> list[Finding]:
    is_ci = any(fnmatch.fnmatch(rel, g) for g in CI_GLOBS)
    is_code = Path(rel).suffix.lower() in CODE_SUFFIXES
    is_test = is_test_path(rel)
    rules: list[tuple[str, str, re.Pattern[str]]] = []
    if is_ci:
        rules += [("bypass", r, p) for r, p in CI_BYPASS_RULES]
    if is_code and is_test:
        rules += [("bypass", r, p) for r, p in TEST_BYPASS_RULES]
    if is_code:
        rules += [("bypass", r, p) for r, p in CODE_BYPASS_RULES]
    if is_code and not is_test:
        rules += [("stub", r, p) for r, p in STUB_RULES]
    findings: list[Finding] = []
    if not rules:
        return findings
    for lineno, line in enumerate(text.splitlines(), start=1):
        if ALLOW_MARKER in line or len(line) > 2000:
            continue
        for kind, rule, pattern in rules:
            if pattern.search(line):
                findings.append(
                    Finding(rel, lineno, kind, rule, line.strip()[:160], _fingerprint(rel, rule, line))
                )
                break
    return findings


def scan(root: Path, exclude: list[str]) -> list[Finding]:
    out: list[Finding] = []
    self_name = Path(__file__).name
    for rel in list_files(root):
        if Path(rel).name in (self_name, "es_verify.py", "es_secrets.py"):
            continue  # the scanners contain their own patterns
        if any(fnmatch.fnmatch(rel, pat) for pat in (*DEFAULT_EXCLUDES, *exclude)):
            continue
        path = root / rel
        try:
            if not path.is_file() or path.stat().st_size > 1_000_000:
                continue
            raw = path.read_bytes()
        except OSError:
            continue
        if b"\0" in raw[:8192]:
            continue
        out.extend(scan_file(rel, raw.decode("utf-8", "replace")))
    return out


def _console_safe() -> None:
    """Never crash on a legacy console code page (cp1252 on Windows): replace unencodable characters."""
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is not None:
            reconfigure(errors="replace")


def main(argv: list[str] | None = None) -> int:
    _console_safe()
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--root", default=".")
    ap.add_argument("--baseline", default=".quality/stubs-baseline.json")
    ap.add_argument("--exclude", action="append", default=[])
    ap.add_argument("--write-baseline", action="store_true")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args(argv)
    root = Path(args.root).resolve()
    findings = scan(root, args.exclude)
    baseline_path = root / args.baseline
    if args.write_baseline:
        baseline_path.parent.mkdir(parents=True, exist_ok=True)
        baseline_path.write_text(
            json.dumps(
                {
                    "note": "legacy stub/bypass findings frozen at onboarding; shrink, never grow",
                    "fingerprints": sorted({f.fingerprint for f in findings}),
                },
                indent=2,
            )
            + "\n",
            encoding="utf-8",
        )
        print(f"es-stubs: wrote {len(findings)} fingerprints to {baseline_path}")
        return 0
    known: set[str] = set()
    if baseline_path.is_file():
        known = set(json.loads(baseline_path.read_text(encoding="utf-8")).get("fingerprints", []))
    new = [f for f in findings if f.fingerprint not in known]
    if args.json:
        print(
            json.dumps(
                {
                    "total": len(findings),
                    "baselined": len(findings) - len(new),
                    "by_kind": {k: sum(1 for f in findings if f.kind == k) for k in ("stub", "bypass")},
                    "new": [f.__dict__ for f in new],
                },
                indent=2,
            )
        )
    else:
        for f in new:
            print(f"{f.kind.upper()} {f.path}:{f.line} [{f.rule}] {f.text}")
        print(f"es-stubs: {len(new)} new finding(s), {len(findings) - len(new)} baselined")
    return 1 if new else 0


if __name__ == "__main__":
    sys.exit(main())
