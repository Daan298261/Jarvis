"""RFC-0060: Docs-first grounding for Jarvis self-about questions."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from ..config import data_dir, repo_root
from ..trajectories.redaction import redact_string


def _app_version() -> str:
    from ..diagnostics import app_version

    return app_version()

BUDGET_FILENAME = "docs_first_budget.json"
DEFAULT_BUDGET_REMAINING = 100
MAX_SNIPPET_CHARS = 1200
MAX_BUNDLE_CHARS = 4500

# Pack files that must exist for a healthy reference index.
REQUIRED_PACK_FILES = (
    "README.md",
    "capability-overview.md",
    "setup-pitfalls.md",
)

# In-repo docs indexed after the seeded pack (allowlist only).
ALLOWLISTED_DOC_ROOTS = (
    "docs",
)
ALLOWLISTED_DOC_FILES = (
    "AGENTS.md",
    "README.md",
    "INSTALLER.md",
    "WINDOWS_SHELL.md",
    "TROUBLESHOOTING.md",
    "SECURITY.md",
    "docs/INSTALL.md",
    "docs/PROCESS.md",
    "docs/DEVELOPMENT.md",
)

_SYSTEM_ABOUT_PATTERNS = (
    re.compile(r"\bwhat is jarvis\b", re.I),
    re.compile(r"\bhow (?:do|does) (?:i|jarvis)\b", re.I),
    re.compile(r"\bjarvis (?:can|cannot|can't|support|handle)\b", re.I),
    re.compile(r"\b(?:capabilities?|architecture|installer|portal|swarm)\b.*\bjarvis\b", re.I),
    re.compile(r"\bjarvis\b.*\b(?:capabilities?|architecture|installer|portal|swarm|settings?|ports?|models?)\b", re.I),
    re.compile(r"\b(?:bind|listen|lan|port[- ]?forward|private[- ]?key|vram|llama|lm studio|start-jarvis|stop-jarvis)\b", re.I),
    re.compile(r"\b(?:model profile|fast profile|balanced profile|quality profile)\b", re.I),
)

_JARVIS_ERROR_PATTERNS = (
    re.compile(r"\b(?:llama-server|jarvis)\b.*\b(?:error|failed|exit(?:ed)?|unloaded|oom)\b", re.I),
    re.compile(r"\b(?:ERROR|Traceback|HTTPException|503|502)\b.*\b(?:jarvis|4780|8088|llama)\b", re.I),
    re.compile(r"\bwaiting on model\b", re.I),
    re.compile(r"\bmodel shows unloaded\b", re.I),
    re.compile(r"\bport 4780\b.*\bin use\b", re.I),
)


@dataclass
class GroundingSnippet:
    citation_id: str
    source_path: str
    text: str


@dataclass
class GroundingBundle:
    triggered: bool
    trigger_reasons: list[str] = field(default_factory=list)
    snippets: list[GroundingSnippet] = field(default_factory=list)
    missing_refs: list[str] = field(default_factory=list)
    self_about: bool = False
    budget_remaining: int = 0

    def prompt_block(self) -> str:
        if not self.triggered:
            return ""
        lines = [
            "Docs-first grounding (RFC-0060): prefer the cited local references below over guessing Jarvis behavior.",
            "If the references do not cover the question, say what is missing instead of inventing product details.",
            "Never echo private keys, API tokens, or secrets from snippets or user context.",
        ]
        if self.missing_refs:
            lines.append(
                "Reference missing: "
                + ", ".join(self.missing_refs)
                + " — do not hallucinate content for these paths."
            )
        if not self.snippets and not self.missing_refs:
            lines.append("No matching local references were found; admit the gap.")
        for snip in self.snippets:
            lines.append(f"[{snip.citation_id}] {snip.source_path}\n{snip.text}")
        return "\n\n".join(lines)


@dataclass
class DocsFirstContext:
    user_message: str
    error_context: str | None = None
    app_version: str | None = None


def reference_pack_root() -> Path:
    return repo_root() / "project" / "jarvis" / "jarvis" / "internal" / "references"


def packaged_reference_root() -> Path:
    """Install-relative fallback when the dev tree pack is absent."""
    return repo_root() / "internal" / "references"


def _resolve_roots() -> list[Path]:
    roots: list[Path] = []
    pack = reference_pack_root()
    if pack.is_dir():
        roots.append(pack.resolve())
    packaged = packaged_reference_root()
    if packaged.is_dir() and packaged.resolve() not in roots:
        roots.append(packaged.resolve())
    docs = (repo_root() / "docs").resolve()
    if docs.is_dir():
        roots.append(docs)
    for rel in ALLOWLISTED_DOC_FILES:
        path = (repo_root() / rel).resolve()
        parent = path.parent
        if parent.is_dir() and parent not in roots:
            roots.append(parent)
    return roots


def _path_confined(path: Path, roots: list[Path]) -> bool:
    resolved = path.resolve()
    for root in roots:
        try:
            resolved.relative_to(root)
            return True
        except ValueError:
            continue
    return False


def _iter_index_files(roots: list[Path]) -> list[Path]:
    files: list[Path] = []
    seen: set[Path] = set()
    pack = reference_pack_root()
    if pack.is_dir():
        for path in sorted(pack.rglob("*.md")):
            resolved = path.resolve()
            if resolved not in seen:
                seen.add(resolved)
                files.append(resolved)
    for rel in ALLOWLISTED_DOC_FILES:
        candidate = (repo_root() / rel).resolve()
        if candidate.is_file() and candidate not in seen:
            seen.add(candidate)
            files.append(candidate)
    docs_root = (repo_root() / "docs").resolve()
    if docs_root.is_dir():
        for path in sorted(docs_root.rglob("*.md")):
            resolved = path.resolve()
            if _path_confined(resolved, roots) and resolved not in seen:
                seen.add(resolved)
                files.append(resolved)
    packaged = packaged_reference_root()
    if packaged.is_dir():
        for path in sorted(packaged.rglob("*.md")):
            resolved = path.resolve()
            if resolved not in seen:
                seen.add(resolved)
                files.append(resolved)
    return files


def _relative_source(path: Path) -> str:
    try:
        return str(path.resolve().relative_to(repo_root().resolve()))
    except ValueError:
        return str(path)


def _tokenize(query: str) -> list[str]:
    return [tok for tok in re.findall(r"[a-z0-9][a-z0-9_-]{2,}", query.lower()) if tok not in {"jarvis", "the", "and", "for", "how", "what"}]


def _score_text(text: str, terms: list[str]) -> int:
    lowered = text.lower()
    return sum(lowered.count(term) for term in terms)


def _score_document(path: Path, text: str, terms: list[str]) -> int:
    """Prefer a specifically named reference over broad docs with repeated terms."""
    score = _score_text(text, terms)
    # Only score the document name. Absolute worktree names can contain query
    # words (for example a feature branch called "humanoid-runtime").
    path_text = path.name.lower()
    heading = "\n".join(text.splitlines()[:3])
    score += sum(60 for term in terms if term in path_text)
    score += _score_text(heading, terms) * 12
    for pack_root in (reference_pack_root(), packaged_reference_root()):
        try:
            path.resolve().relative_to(pack_root.resolve())
            score += 100
            break
        except ValueError:
            continue
    return score


def _extract_snippet(text: str, terms: list[str], max_chars: int = MAX_SNIPPET_CHARS) -> str:
    if not text:
        return ""
    if not terms:
        return redact_string(text[:max_chars])
    lines = text.splitlines()
    best_idx = 0
    best_score = -1
    window = 12
    for idx in range(len(lines)):
        block = "\n".join(lines[max(0, idx - 2) : idx + window])
        score = _score_text(block, terms)
        if score > best_score:
            best_score = score
            best_idx = idx
    start = max(0, best_idx - 2)
    snippet = "\n".join(lines[start : start + window]).strip()
    if len(snippet) > max_chars:
        snippet = snippet[: max_chars - 3].rstrip() + "..."
    return redact_string(snippet)


def budget_path() -> Path:
    return data_dir() / BUDGET_FILENAME


def load_budget(version: str | None = None) -> dict[str, Any]:
    version = version or _app_version()
    path = budget_path()
    default = {"version": version, "remaining": DEFAULT_BUDGET_REMAINING}
    if not path.exists():
        return default
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return default
    if not isinstance(raw, dict):
        return default
    if str(raw.get("version") or "") != version:
        return default
    remaining = int(raw.get("remaining", DEFAULT_BUDGET_REMAINING))
    return {"version": version, "remaining": max(0, remaining)}


def save_budget(state: dict[str, Any]) -> dict[str, Any]:
    path = budget_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "version": str(state.get("version") or _app_version()),
        "remaining": max(0, int(state.get("remaining", 0))),
    }
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return payload


def consume_budget(state: dict[str, Any]) -> dict[str, Any]:
    remaining = max(0, int(state.get("remaining", 0)) - 1)
    return save_budget({"version": state.get("version"), "remaining": remaining})


def is_system_about(message: str) -> bool:
    text = (message or "").strip()
    if not text:
        return False
    return any(pattern.search(text) for pattern in _SYSTEM_ABOUT_PATTERNS)


def is_jarvis_error(message: str, error_context: str | None = None) -> bool:
    combined = "\n".join(part for part in (message, error_context or "") if part).strip()
    if not combined:
        return False
    return any(pattern.search(combined) for pattern in _JARVIS_ERROR_PATTERNS)


def evaluate_triggers(context: DocsFirstContext, budget: dict[str, Any]) -> tuple[bool, list[str], bool]:
    reasons: list[str] = []
    self_about = is_system_about(context.user_message)
    error_hit = is_jarvis_error(context.user_message, context.error_context)
    budget_hit = int(budget.get("remaining", 0)) > 0
    if self_about:
        reasons.append("system_about")
    if error_hit:
        reasons.append("on_screen_error")
    if budget_hit:
        reasons.append("new_install_budget")
    triggered = bool(reasons)
    return triggered, reasons, self_about or error_hit


def missing_pack_files() -> list[str]:
    pack = reference_pack_root()
    missing: list[str] = []
    for rel in REQUIRED_PACK_FILES:
        if not (pack / rel).is_file():
            missing.append(str((pack / rel).as_posix()))
    summaries = pack / "spec-summaries"
    if not summaries.is_dir() or not any(summaries.glob("*.md")):
        missing.append(str((summaries / "*.md").as_posix()))
    return missing


def search_internal_references(query: str, *, max_results: int = 5) -> list[GroundingSnippet]:
    roots = _resolve_roots()
    terms = _tokenize(query)
    ranked: list[tuple[int, Path, str]] = []
    for path in _iter_index_files(roots):
        if not _path_confined(path, roots):
            continue
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        score = _score_document(path, text, terms) if terms else 1
        if terms and score <= 0:
            continue
        ranked.append((score, path, text))
    ranked.sort(key=lambda item: (-item[0], str(item[1])))
    snippets: list[GroundingSnippet] = []
    total = 0
    for idx, (_score, path, text) in enumerate(ranked[:max_results], start=1):
        body = _extract_snippet(text, terms)
        if not body:
            continue
        rel = _relative_source(path)
        if total + len(body) > MAX_BUNDLE_CHARS:
            break
        total += len(body)
        snippets.append(GroundingSnippet(citation_id=f"ref-{idx}", source_path=rel, text=body))
    return snippets


def maybe_docs_first(context: DocsFirstContext) -> GroundingBundle | None:
    version = context.app_version or _app_version()
    budget = load_budget(version)
    triggered, reasons, self_about = evaluate_triggers(context, budget)
    if not triggered:
        return None

    query_parts = [context.user_message]
    if context.error_context:
        query_parts.append(context.error_context)
    query = "\n".join(query_parts)

    missing = missing_pack_files()
    snippets = search_internal_references(query)

    if triggered:
        budget = consume_budget(budget)

    bundle = GroundingBundle(
        triggered=True,
        trigger_reasons=reasons,
        snippets=snippets,
        missing_refs=missing,
        self_about=self_about,
        budget_remaining=int(budget.get("remaining", 0)),
    )
    return bundle


def reset_budget_for_tests(version: str | None = None) -> None:
    path = budget_path()
    if path.exists():
        path.unlink()


__all__ = [
    "DocsFirstContext",
    "GroundingBundle",
    "GroundingSnippet",
    "consume_budget",
    "evaluate_triggers",
    "is_jarvis_error",
    "is_system_about",
    "load_budget",
    "maybe_docs_first",
    "missing_pack_files",
    "reference_pack_root",
    "reset_budget_for_tests",
    "save_budget",
    "search_internal_references",
]
