"""RFC-0211 independent review gate for a development candidate.

The worker's own success claim is never enough. The trusted controller reviews the
committed candidate at an exact head SHA with two independent checks:

* ``policy_findings``: deterministic diff rules (architect-owned specs, stubs,
  removed tests, masked CI, unrelated protected files);
* ``model_review``: a fresh local Ollama review (no worker conversation) against the
  ticket and the pinned ANZU_PRODUCT_NORTH_STAR.md, returning a strict JSON verdict.

Approval is bound to the head SHA; any head change invalidates it.
"""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

import httpx

from .worktrees import run_git

MAX_REVIEW_DIFF = 120_000
PROTECTED_SPECS = {
    "JARVIS_MASTER_PLAN.md", "SWARM_ARCHITECTURE.md", "ADAPTIVE_DOMAIN_ARCHITECTURE.md", "ANDROID_CLIENT.md",
    "JARVIS_2.0.md", "HOME_IOT.md", "SECURITY_AGENTS.md", "BLUE_TEAM.md", "INSTALLER.md", "WINDOWS_SHELL.md",
    "PORTAL_UX.md", "ANZU_PRODUCT_NORTH_STAR.md", "AGENTS.md", "docs/PROCESS.md",
}
STUB_RE = re.compile(r"\b(TODO|FIXME|XXX)\b|NotImplementedError|raise NotImplemented\b|^\s*pass\s*#\s*stub|canned (?:success|response)", re.I)
TEST_DEF_RE = re.compile(r"^[-+]\s*(?:async\s+)?def\s+(test_\w+)")


class ReviewError(RuntimeError):
    """The review could not run; the candidate stays unapproved and needs attention."""


def candidate_diff(worktree: str, base_sha: str, head_sha: str) -> tuple[list[str], str]:
    names = run_git(worktree, ["diff", "--name-only", f"{base_sha}..{head_sha}"]).stdout.splitlines()
    diff = run_git(worktree, ["diff", "--unified=3", f"{base_sha}..{head_sha}"]).stdout
    return names, diff


def policy_findings(names: list[str], diff: str) -> list[dict[str, str]]:
    findings: list[dict[str, str]] = []
    if not names:
        findings.append({"severity": "blocker", "file": "", "issue": "The candidate has no changes"})
    for name in names:
        if name in PROTECTED_SPECS or (name.startswith("docs/rfcs/") and name.endswith(".md")):
            findings.append({"severity": "blocker", "file": name, "issue": "Architect-owned specification edited"})
        if name.startswith(".github/workflows/"):
            findings.append({"severity": "blocker", "file": name, "issue": "CI workflow changed by an autonomous mission"})
    current = ""
    removed_tests: dict[str, str] = {}
    added_tests: set[str] = set()
    for line in diff.splitlines():
        header = re.match(r"^diff --git a/(.+) b/(.+)$", line)
        if header:
            current = header.group(2)
            continue
        if line.startswith(("+++ ", "--- a/", "--- /dev/null")):
            continue
        match = TEST_DEF_RE.match(line)
        if match:
            if line.startswith("+"):
                added_tests.add(match.group(1))
            else:
                removed_tests.setdefault(match.group(1), current)
        if line.startswith("+"):
            if STUB_RE.search(line[1:]):
                findings.append({"severity": "blocker", "file": current, "issue": f"Stub or placeholder added: {line[1:].strip()[:160]}"})
            if "continue-on-error" in line:
                findings.append({"severity": "blocker", "file": current, "issue": "continue-on-error masks a failing check"})
            if re.search(r"pytest\.mark\.skip|@unittest\.skip|\.skip\(", line):
                findings.append({"severity": "blocker", "file": current, "issue": "Test skipped instead of fixed"})
    for name, file in sorted(removed_tests.items()):
        if name not in added_tests:
            findings.append({"severity": "blocker", "file": file, "issue": f"Test {name} removed without replacement"})
    return findings


def review_prompt(*, ticket: str, north_star: str, diff: str, evidence: dict[str, Any], findings: list[dict[str, str]]) -> str:
    checks = [{"command": " ".join(map(str, c.get("command", []))), "returncode": c.get("returncode")} for c in evidence.get("checks", [])]
    return (
        "You are ANZU's independent code reviewer. You did not write this change and must not trust the author's claims.\n"
        "Review the diff against the ticket acceptance criteria and the ANZU Product North Star "
        "(polished, luxurious, easy to use, capable, trustworthy). Reject stubs, canned success, weakened or "
        "removed tests, unrelated edits, missing error or cancellation handling, data loss and authorization bypasses.\n"
        "Answer with JSON only: {\"approved\": true|false, \"findings\": [{\"severity\": \"blocker\"|\"minor\", "
        "\"file\": \"path\", \"issue\": \"what is wrong and how to fix it\"}], \"north_star\": \"one sentence\"}.\n"
        "Approve only when there are no blocker findings. Every finding must be concrete.\n\n"
        f"## Ticket\n{ticket[:40_000]}\n\n## North Star\n{north_star[:30_000]}\n\n"
        f"## Trusted verification (exit codes from the controller)\n{json.dumps(checks)}\n\n"
        f"## Deterministic findings already recorded\n{json.dumps(findings)}\n\n## Diff\n{diff}"
    )


async def model_review(*, ollama_url: str, model: str, prompt: str, keep_alive: str, timeout: float = 900) -> dict[str, Any]:
    body = {"model": model, "stream": False, "think": False, "format": "json", "keep_alive": keep_alive,
            "options": {"temperature": 0, "num_ctx": 32768},
            "messages": [{"role": "user", "content": prompt}]}
    try:
        async with httpx.AsyncClient(base_url=ollama_url.rstrip("/"), timeout=timeout) as client:
            response = await client.post("/api/chat", json=body)
    except httpx.HTTPError as exc:
        raise ReviewError(f"Independent review could not reach Ollama ({type(exc).__name__})") from exc
    if response.is_error:
        raise ReviewError(f"Independent review failed: Ollama HTTP {response.status_code}")
    try:
        raw = response.json()
        verdict = json.loads(raw.get("message", {}).get("content", ""))
    except (ValueError, AttributeError) as exc:
        raise ReviewError("Independent review returned an unreadable verdict") from exc
    if not isinstance(verdict, dict) or not isinstance(verdict.get("approved"), bool) or not isinstance(verdict.get("findings", []), list):
        raise ReviewError("Independent review verdict did not match the required schema")
    findings = []
    for finding in verdict.get("findings", []):
        if not isinstance(finding, dict) or not str(finding.get("issue", "")).strip():
            raise ReviewError("Independent review returned a finding without an issue")
        severity = "blocker" if str(finding.get("severity", "blocker")).lower() != "minor" else "minor"
        findings.append({"severity": severity, "file": str(finding.get("file", ""))[:300], "issue": str(finding["issue"])[:2000]})
    return {"approved": verdict["approved"], "findings": findings, "north_star": str(verdict.get("north_star", ""))[:1000]}


async def review_candidate(*, worktree: str, base_sha: str, head_sha: str, ticket: str, north_star: str,
                           evidence: dict[str, Any], ollama_url: str, model: str, keep_alive: str) -> dict[str, Any]:
    """Return a review record bound to ``head_sha``. Raises ReviewError when review cannot run."""
    import asyncio

    names, diff = await asyncio.to_thread(candidate_diff, worktree, base_sha, head_sha)
    findings = policy_findings(names, diff)
    if len(diff) > MAX_REVIEW_DIFF:
        findings.append({"severity": "blocker", "file": "", "issue": f"Diff is {len(diff)} characters; split it into a focused change under {MAX_REVIEW_DIFF}"})
    verdict = {"approved": False, "findings": [], "north_star": ""}
    if not any(f["severity"] == "blocker" for f in findings):
        verdict = await model_review(ollama_url=ollama_url, model=model, keep_alive=keep_alive,
                                     prompt=review_prompt(ticket=ticket, north_star=north_star, diff=diff, evidence=evidence, findings=findings))
    all_findings = findings + verdict["findings"]
    approved = verdict["approved"] and not any(f["severity"] == "blocker" for f in all_findings)
    return {"head_sha": head_sha, "base_sha": base_sha, "approved": approved, "findings": all_findings,
            "north_star": verdict["north_star"], "files": names, "reviewer": model}


def north_star_at(repo: str | Path, sha: str) -> tuple[str, str]:
    """(text, blob id) of the North Star pinned at ``sha``; missing guidance is a blocker."""
    for name in ("ANZU_PRODUCT_NORTH_STAR.md", "AGENTS.md", "docs/PROCESS.md"):
        if run_git(repo, ["cat-file", "-e", f"{sha}:{name}"], check=False).returncode != 0:
            raise ReviewError(f"{name} is missing at {sha[:12]}; missions need the actual guidance")
    blob = run_git(repo, ["rev-parse", f"{sha}:ANZU_PRODUCT_NORTH_STAR.md"]).stdout.strip()
    text = run_git(repo, ["show", f"{sha}:ANZU_PRODUCT_NORTH_STAR.md"]).stdout
    return text, blob
