#!/usr/bin/env python3
"""es_secrets: dependency-free secret scanner (mandatory gate ``secret_scan``).

Scans git-tracked files (or every file when not in a git repo) for credentials.
Findings are printed masked; the secret value itself is never written anywhere.
Known historical findings can be frozen in a baseline (fingerprints only), so
legacy repos fail only on NEW secrets. Exit 1 on any non-baselined finding.

Suppress a reviewed false positive with an inline ``es:allow-secret <reason>``.
CI additionally runs gitleaks; this scanner is the always-available floor.
"""

from __future__ import annotations

import argparse
import fnmatch
import hashlib
import json
import math
import re
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

MAX_BYTES = 1_000_000
RULES: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("private-key", re.compile(r"-----BEGIN (?:RSA |EC |DSA |OPENSSH |PGP |ENCRYPTED )?PRIVATE KEY-----")),
    ("aws-access-key", re.compile(r"\b(?:AKIA|ASIA)[0-9A-Z]{16}\b")),
    ("github-token", re.compile(r"\b(?:gh[pousr]_[A-Za-z0-9]{36,}|github_pat_[A-Za-z0-9_]{60,})\b")),
    ("openai-key", re.compile(r"\bsk-(?:proj-|svcacct-)?[A-Za-z0-9_-]{32,}\b")),
    ("anthropic-key", re.compile(r"\bsk-ant-[A-Za-z0-9_-]{32,}\b")),
    ("slack-token", re.compile(r"\bxox[abprs]-[A-Za-z0-9-]{10,}\b")),
    ("google-api-key", re.compile(r"\bAIza[0-9A-Za-z_-]{35}\b")),
    ("stripe-live-key", re.compile(r"\b[sr]k_live_[0-9A-Za-z]{20,}\b")),
    ("huggingface-token", re.compile(r"\bhf_[A-Za-z0-9]{30,}\b")),
    ("telegram-bot-token", re.compile(r"\b\d{8,10}:AA[0-9A-Za-z_-]{33}\b")),
    ("url-credentials", re.compile(r"\b[a-z][a-z0-9+.-]*://[^\s:/@'\"]{2,}:([^\s@'\"]{6,})@[\w.-]+")),
    (
        "generic-assignment",
        re.compile(
            r"(?i)\b[\w.-]*(?:password|passwd|secret|api[_-]?key|access[_-]?key|auth[_-]?token|"
            r"private[_-]?key|client[_-]?secret|token)\b[\"']?\s*[:=]\s*[\"']([^\"'\s]{8,})[\"']"
        ),
    ),
)
PLACEHOLDER_HINTS = (
    "example",
    "changeme",
    "change-me",
    "change_me",
    "placeholder",
    "dummy",
    "your",
    "xxx",
    "redacted",
    "<",
    "${",
    "{{",
    "%(",
    "os.environ",
    "process.env",
    "getenv",
    "sample",
    "notasecret",
    "not-a-secret",
    "test",
    "fake",
    "secret_name",
    "env:",
)
SKIP_SUFFIXES = (
    ".png",
    ".jpg",
    ".jpeg",
    ".gif",
    ".webp",
    ".ico",
    ".pdf",
    ".zip",
    ".gz",
    ".tgz",
    ".7z",
    ".exe",
    ".dll",
    ".so",
    ".dylib",
    ".bin",
    ".gguf",
    ".onnx",
    ".pt",
    ".safetensors",
    ".mp3",
    ".mp4",
    ".wav",
    ".ogg",
    ".woff",
    ".woff2",
    ".ttf",
    ".otf",
    ".jar",
    ".apk",
    ".class",
    ".pyc",
    ".sqlite",
    ".db",
    ".e01",
    ".vhd",
    ".img",
    ".iso",
)
GENERIC_SKIP_GLOBS = (
    "*.lock",
    "*-lock.json",
    "*.lock.json",
    "*.min.js",
    "*.map",
    "*.svg",
    "*.manifest",
    "*.xml",
    "*.csproj",
    "*.sln",
)
DEFAULT_EXCLUDES = (
    "*site-packages/*",
    "node_modules/*",
    "*/node_modules/*",
    "vendor/*",
    ".vendor/*",
    "third_party/*",
    "*/third_party/*",
    ".verify/*",
)
# Test fixtures routinely use dummy credentials; only high-confidence token formats
# (which are never acceptable, even in tests) are checked there.
TEST_PATH = re.compile(
    r"(^|/)(tests?|__tests__|spec|fixtures)/|(^|/)test_[^/]*$|\.(test|spec)\.[cm]?[jt]sx?$"
)
ALLOW_MARKER = "es:allow-secret"


@dataclass(frozen=True)
class Finding:
    path: str
    line: int
    rule: str
    masked: str
    fingerprint: str


def shannon_entropy(value: str) -> float:
    if not value:
        return 0.0
    counts = {c: value.count(c) for c in set(value)}
    return -sum((n / len(value)) * math.log2(n / len(value)) for n in counts.values())


IDENTIFIER_LIKE = (
    re.compile(r"^[A-Z][A-Z0-9_]+$"),  # ENV_VAR_NAME
    re.compile(r"^[a-z0-9_]+(?:[.:/][a-z0-9_]+)+$"),  # dotted.capability.name / paths
    re.compile(r"^[a-z]+(?:-[a-z]+)+$"),  # kebab-case words
)


def has_placeholder_hint(value: str) -> bool:
    low = value.lower()
    return any(h in low for h in PLACEHOLDER_HINTS)


def looks_like_placeholder(value: str) -> bool:
    """Heuristics for the generic rule: real secrets mix letters+digits and are random."""
    if has_placeholder_hint(value) or len(set(value)) <= 3:
        return True
    if any(p.match(value) for p in IDENTIFIER_LIKE):
        return True
    if not (re.search(r"[A-Za-z]", value) and re.search(r"\d", value)):
        return True
    return shannon_entropy(value) < 3.0


def mask(value: str) -> str:
    return value[:4] + "*" * min(12, max(4, len(value) - 4))


def list_files(root: Path) -> list[Path]:
    try:
        out = subprocess.run(
            ["git", "ls-files", "-z", "--cached", "--others", "--exclude-standard"],
            cwd=root,
            capture_output=True,
            check=True,
            timeout=60,
        )
        names = [n for n in out.stdout.decode("utf-8", "replace").split("\0") if n]
        return [root / n for n in names]
    except (OSError, subprocess.SubprocessError):
        return [p for p in root.rglob("*") if p.is_file() and ".git" not in p.parts]


def scan_text(rel: str, text: str) -> list[Finding]:
    findings: list[Finding] = []
    generic_ok = not any(fnmatch.fnmatch(Path(rel).name, g) for g in GENERIC_SKIP_GLOBS)
    generic_ok = generic_ok and not TEST_PATH.search(rel)
    for lineno, line in enumerate(text.splitlines(), start=1):
        if ALLOW_MARKER in line or len(line) > 4000:
            continue
        specific_hit = False
        for rule, pattern in RULES:
            if rule == "generic-assignment" and (not generic_ok or specific_hit):
                continue
            for match in pattern.finditer(line):
                value = match.group(1) if match.groups() else match.group(0)
                if rule in ("generic-assignment", "url-credentials"):
                    if looks_like_placeholder(value):
                        continue
                elif has_placeholder_hint(match.group(0)):
                    continue
                digest = hashlib.sha256(f"{rel}\0{rule}\0{value}".encode()).hexdigest()[:24]
                findings.append(Finding(rel, lineno, rule, mask(value), digest))
                specific_hit = specific_hit or rule != "generic-assignment"
    return findings


def scan(root: Path, exclude: list[str]) -> list[Finding]:
    findings: list[Finding] = []
    for path in list_files(root):
        rel = path.relative_to(root).as_posix()
        if any(fnmatch.fnmatch(rel, pat) for pat in (*DEFAULT_EXCLUDES, *exclude)):
            continue
        if path.suffix.lower() in SKIP_SUFFIXES or not path.is_file():
            continue
        try:
            if path.stat().st_size > MAX_BYTES:
                continue
            raw = path.read_bytes()
        except OSError:
            continue
        if b"\0" in raw[:8192]:
            continue
        findings.extend(scan_text(rel, raw.decode("utf-8", "replace")))
    return findings


def load_baseline(path: Path) -> set[str]:
    if not path.is_file():
        return set()
    data = json.loads(path.read_text(encoding="utf-8"))
    return {str(f) for f in data.get("fingerprints", [])}


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
    ap.add_argument("--baseline", default=".quality/secrets-baseline.json")
    ap.add_argument("--exclude", action="append", default=[], help="glob of paths to skip")
    ap.add_argument(
        "--write-baseline",
        action="store_true",
        help="freeze current findings (legacy onboarding only; review each first)",
    )
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
                    "note": "fingerprints of reviewed legacy findings; never add new ones casually",
                    "fingerprints": sorted({f.fingerprint for f in findings}),
                },
                indent=2,
            )
            + "\n",
            encoding="utf-8",
        )
        print(f"es-secrets: wrote {len(findings)} fingerprints to {baseline_path}")
        return 0
    known = load_baseline(baseline_path)
    new = [f for f in findings if f.fingerprint not in known]
    if args.json:
        print(
            json.dumps(
                {
                    "total": len(findings),
                    "baselined": len(findings) - len(new),
                    "new": [f.__dict__ for f in new],
                },
                indent=2,
            )
        )
    else:
        for f in new:
            print(f"SECRET {f.path}:{f.line} [{f.rule}] {f.masked}")
        print(f"es-secrets: {len(new)} new finding(s), {len(findings) - len(new)} baselined")
    return 1 if new else 0


if __name__ == "__main__":
    sys.exit(main())
