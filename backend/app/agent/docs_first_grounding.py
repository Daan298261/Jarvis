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


# Spec-vs-help ranking (trigger: RFC-0228 / #655). RFC specs under docs/rfcs/
# repeat product words such as "install" and "runtime" hundreds of times, so a
# raw term count lets a single long spec outrank the user-facing help page for
# a plain how-to question. RFCs stay indexed: for ordinary questions their body
# counts saturate and their score is down-weighted, so user-facing docs win;
# when the user explicitly asks about specs or an RFC they get full weight plus
# a boost, and a named RFC number ranks that RFC first.
RFC_DOC_PARTS = ("docs", "rfcs")
RFC_BODY_TERM_CAP = 12
RFC_HELP_QUERY_WEIGHT = 0.5
RFC_SPEC_QUERY_BONUS = 100
RFC_NAMED_NUMBER_BONUS = 400
RFC_ONLY_FEATURE_BONUS = 100

# Spec intent must come from RFC/spec-document phrasing, never from the bare
# word "spec": "what are the specs of my GPU" is a hardware question.
_STRONG_SPEC_INTENT_PATTERNS = (
    re.compile(r"\brfcs?\b", re.I),
    re.compile(r"\brfc[-_ ]?\d{1,4}\b", re.I),
    re.compile(r"\bproposals?\b", re.I),
    re.compile(r"\bdesign (?:docs?|documents?)\b", re.I),
    re.compile(r"\b(?:specification|spec|technical spec|feature spec) (?:docs?|documents?|files?)\b", re.I),
)
# "spec for/of <feature>" (article optional: "technical spec for the swarm",
# "spec for keep warm"), "which spec covers ...", "what does the spec say".
_SPEC_NOUN_PHRASE_PATTERNS = (
    re.compile(r"\b(?:spec|specification)\s+(?:for|of|on|about)\b", re.I),
    re.compile(
        r"\b(?:spec|specs|specification)\s+(?:say|says|said|describe|describes|define|defines|"
        r"cover|covers|specify|specifies)\b",
        re.I,
    ),
)
# The hardware veto applies only to hardware-spec phrasing, never to a query that
# merely contains a product word (phone companion, camera feature, display
# settings, device pairing, android companion are this product's own features).
_HARDWARE_NOUNS = (
    r"gpu|cpu|pc|laptop|desktop|computer|notebook|tablet|monitor|processor|motherboard|ram|ssd|"
    r"hardware|graphics card|video card|iphone|ipad|macbook|pixel|galaxy|phone|smartphone"
)
_HARDWARE_SPEC_PHRASING = (
    # "specs of my <anything>": possessive hardware question.
    re.compile(r"\bspecs?\s+(?:of|for|on)\s+(?:my|your|our|his|her|their)\b", re.I),
    # "specs of the <hw>" where the hardware noun ends the question.
    re.compile(
        rf"\bspecs?\s+(?:of|for|on)\s+(?:(?:the|this|that|a|an|new)\s+)?(?:\w+\s+){{0,2}}?(?:{_HARDWARE_NOUNS})\s*[?.!,]*\s*$",
        re.I,
    ),
    # "<hw> specs" / "<hw> spec sheet".
    re.compile(rf"\b(?:{_HARDWARE_NOUNS})\s+specs?\b", re.I),
    re.compile(r"\b(?:spec sheet|system specs?|tech specs? of)\b", re.I),
    # A model number: "specs of the RTX 4090", "specs for the iPhone 16".
    re.compile(r"\b(?:rtx|gtx|rx|radeon|geforce|iphone|ipad|galaxy|pixel|macbook)\s?[a-z]{0,2}\s?\d{1,4}\b", re.I),
)
_RFC_NUMBER_PATTERN = re.compile(r"\brfc[-_ ]?0*(\d{1,4})\b", re.I)
_RFC_FILE_NUMBER_PATTERN = re.compile(r"^(\d{1,4})-")


def query_targets_specs(query: str) -> bool:
    """True when the user explicitly asks about an RFC, spec document or proposal.

    Requires RFC/spec-doc phrasing. The bare word "spec"/"specs" (GPU specs,
    phone specs, "specs of my PC") never counts as spec intent.
    """
    text = query or ""
    if any(pattern.search(text) for pattern in _STRONG_SPEC_INTENT_PATTERNS):
        return True
    if any(pattern.search(text) for pattern in _HARDWARE_SPEC_PHRASING):
        return False
    return any(pattern.search(text) for pattern in _SPEC_NOUN_PHRASE_PATTERNS)


def requested_rfc_numbers(query: str) -> set[int]:
    return {int(match) for match in _RFC_NUMBER_PATTERN.findall(query or "")}


def is_rfc_spec(path: Path) -> bool:
    """A file inside a ``docs/rfcs`` directory is an RFC spec, not user help."""
    parts = tuple(part.lower() for part in path.parts[:-1])
    width = len(RFC_DOC_PARTS)
    return any(parts[idx : idx + width] == RFC_DOC_PARTS for idx in range(len(parts) - width + 1))


def _rfc_file_number(path: Path) -> int | None:
    match = _RFC_FILE_NUMBER_PATTERN.match(path.name)
    return int(match.group(1)) if match else None


def _term_coverage(path: Path, text: str, terms: list[str]) -> int:
    """How many distinct query terms the document (or its file name) mentions as words."""
    name = path.name.lower()
    covered = 0
    for term in terms:
        word = re.compile(rf"\b{re.escape(term)}(?:s|es|d|ed|ing)?\b", re.I)
        if word.search(text) or term in name:
            covered += 1
    return covered


def _score_rfc_document(
    path: Path, text: str, terms: list[str], query: str, *, rfc_only_match: bool = False
) -> int:
    """Score an RFC spec by the query's intent: spec questions vs. help questions.

    ``rfc_only_match`` marks a help question whose best match is only in RFCs
    (no user-facing doc covers as many query terms); the RFC then ranks at full
    weight, like a user doc, instead of being down-weighted.
    """
    if query_targets_specs(query):
        score = _score_document(path, text, terms) + RFC_SPEC_QUERY_BONUS
        number = _rfc_file_number(path)
        if number is not None and number in requested_rfc_numbers(query):
            score += RFC_NAMED_NUMBER_BONUS
        return score
    lowered = text.lower()
    body = sum(min(lowered.count(term), RFC_BODY_TERM_CAP) for term in terms)
    heading = "\n".join(text.splitlines()[:3])
    bonus = sum(60 for term in terms if term in path.name.lower()) + _score_text(heading, terms) * 12
    if rfc_only_match:
        # Same footing as a user doc in the reference pack (+100 in _score_document).
        return body + bonus + RFC_ONLY_FEATURE_BONUS
    return int((body + bonus) * RFC_HELP_QUERY_WEIGHT)


def _rank_score(path: Path, text: str, terms: list[str], query: str, *, rfc_only_match: bool = False) -> int:
    if is_rfc_spec(path):
        return _score_rfc_document(path, text, terms, query, rfc_only_match=rfc_only_match)
    return _score_document(path, text, terms)


def _best_user_doc_coverage(docs: list[tuple[Path, str]], terms: list[str]) -> int:
    best = 0
    for path, text in docs:
        if not is_rfc_spec(path):
            best = max(best, _term_coverage(path, text, terms))
    return best


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
    docs: list[tuple[Path, str]] = []
    for path in _iter_index_files(roots):
        if not _path_confined(path, roots):
            continue
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        docs.append((path, text))
    # A feature documented only in an RFC: when no user-facing doc covers as many
    # of the question's terms as the RFC does, that RFC is ranked at full weight.
    best_user_coverage = _best_user_doc_coverage(docs, terms) if terms else 0
    ranked: list[tuple[int, Path, str]] = []
    for path, text in docs:
        rfc_only = bool(
            terms and is_rfc_spec(path) and _term_coverage(path, text, terms) > best_user_coverage
        )
        score = _rank_score(path, text, terms, query, rfc_only_match=rfc_only) if terms else 1
        if terms and score <= 0:
            continue
        ranked.append((score, path, text))
    # On equal scores, help questions prefer user-facing docs and spec
    # questions prefer the RFCs.
    spec_query = query_targets_specs(query)
    ranked.sort(key=lambda item: (-item[0], is_rfc_spec(item[1]) != spec_query, str(item[1])))
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
    "is_rfc_spec",
    "missing_pack_files",
    "query_targets_specs",
    "reference_pack_root",
    "requested_rfc_numbers",
    "reset_budget_for_tests",
    "save_budget",
    "search_internal_references",
]
