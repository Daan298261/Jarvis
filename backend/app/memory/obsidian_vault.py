"""RFC-0107: Obsidian-style linked vault — bind, watch, lexical index, graph memory."""

from __future__ import annotations

import hashlib
import json
import re
import threading
import time
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal

import yaml

from ..config import data_dir

WIKI_LINK_RE = re.compile(r"\[\[([^\]|#]+)(?:#[^\]|]+)?(?:\|[^\]]+)?\]\]")
MD_LINK_RE = re.compile(r"\[([^\]]*)\]\(([^)]+)\)")
FRONTMATTER_RE = re.compile(r"^---\s*\n(.*?)\n---\s*\n", re.DOTALL)
HEADING_RE = re.compile(r"^(#{1,6})\s+(.+)$", re.MULTILINE)

DEFAULT_LAYOUT_DIRS = (
    "_Config",
    "_Config/Taxonomy",
    "_Temporal/Sessions",
    "Projects",
    "Decisions",
    "People",
    "Systems",
    "Sources",
    "Home",
)

MAX_NEIGHBOR_HOPS = 2
MAX_SEARCH_RESULTS = 12
MAX_EXCERPT_CHARS = 900
WATCH_POLL_SECONDS = 1.5

_VAULT_RELEVANCE_TERMS = frozenset(
    {
        "project",
        "projects",
        "decision",
        "decisions",
        "note",
        "notes",
        "vault",
        "obsidian",
        "wiki",
        "wikilink",
        "documented",
        "remember",
        "brain",
        "router",
        "taxonomy",
        "manual",
        "runbook",
    }
)

_lock = threading.RLock()
_watch_stop = threading.Event()
_watch_thread: threading.Thread | None = None


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _vault_meta_path() -> Path:
    return data_dir() / "obsidian_vault.json"


def _index_path() -> Path:
    path = data_dir() / "obsidian-index"
    path.mkdir(parents=True, exist_ok=True)
    return path / "lexical.json"


def _managed_state_path() -> Path:
    return data_dir() / "obsidian-managed-state.json"


def content_hash(text: str) -> str:
    normalized = re.sub(r"\s+", " ", (text or "").strip())
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


@dataclass
class NoteIndexEntry:
    rel_path: str
    title: str
    headings: list[str] = field(default_factory=list)
    body_excerpt: str = ""
    content_hash: str = ""
    frontmatter: dict[str, Any] = field(default_factory=dict)
    outbound_wiki: list[str] = field(default_factory=list)
    outbound_md: list[str] = field(default_factory=list)
    indexed_at: str = ""


@dataclass
class VaultBindingState:
    bound: bool = False
    vault_path: str = ""
    jarvis_managed_layout: bool = False
    bound_at: str = ""
    last_index_at: str = ""
    note_count: int = 0


@dataclass
class VaultHit:
    rel_path: str
    title: str
    heading: str | None
    excerpt: str
    content_hash: str
    score: float
    provenance: str = "vault_lexical"


@dataclass
class ResolvedLink:
    target_path: str | None
    heading: str | None
    broken: bool
    via_id: str | None = None


@dataclass
class VaultHealth:
    broken_links: list[dict[str, str]] = field(default_factory=list)
    duplicate_ids: list[dict[str, Any]] = field(default_factory=list)
    stale_index_paths: list[str] = field(default_factory=list)
    missing_router: bool = False


def _load_meta() -> VaultBindingState:
    path = _vault_meta_path()
    if not path.exists():
        return VaultBindingState()
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return VaultBindingState()
    return VaultBindingState(
        bound=bool(raw.get("bound")),
        vault_path=str(raw.get("vault_path") or ""),
        jarvis_managed_layout=bool(raw.get("jarvis_managed_layout")),
        bound_at=str(raw.get("bound_at") or ""),
        last_index_at=str(raw.get("last_index_at") or ""),
        note_count=int(raw.get("note_count") or 0),
    )


def _save_meta(state: VaultBindingState) -> None:
    _vault_meta_path().write_text(
        json.dumps(
            {
                "bound": state.bound,
                "vault_path": state.vault_path,
                "jarvis_managed_layout": state.jarvis_managed_layout,
                "bound_at": state.bound_at,
                "last_index_at": state.last_index_at,
                "note_count": state.note_count,
            },
            indent=2,
        ),
        encoding="utf-8",
    )


def _load_index() -> dict[str, NoteIndexEntry]:
    path = _index_path()
    if not path.exists():
        return {}
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    out: dict[str, NoteIndexEntry] = {}
    for key, item in (raw.get("notes") or {}).items():
        if isinstance(item, dict):
            out[key] = NoteIndexEntry(**{k: item.get(k) for k in NoteIndexEntry.__dataclass_fields__})
    return out


def _save_index(notes: dict[str, NoteIndexEntry]) -> None:
    payload = {
        "schema": 1,
        "updated_at": _utc_now(),
        "notes": {key: asdict(entry) for key, entry in notes.items()},
    }
    _index_path().write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")


def _load_managed_state() -> dict[str, dict[str, str]]:
    path = _managed_state_path()
    if not path.exists():
        return {}
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    return raw if isinstance(raw, dict) else {}


def _save_managed_state(state: dict[str, dict[str, str]]) -> None:
    _managed_state_path().write_text(json.dumps(state, indent=2, sort_keys=True), encoding="utf-8")


def vault_root() -> Path | None:
    meta = _load_meta()
    if not meta.bound or not meta.vault_path:
        return None
    root = Path(meta.vault_path).expanduser()
    if not root.is_dir():
        return None
    return root


def reset_vault_store() -> None:
    """Test helper: unbind and clear generated index state."""
    global _watch_thread
    stop_watch()
    with _lock:
        for path in (_vault_meta_path(), _index_path(), _managed_state_path()):
            if path.exists():
                path.unlink()
        _watch_thread = None


def public_binding_status() -> dict[str, Any]:
    """API-safe status — never echoes the full vault path."""
    meta = _load_meta()
    bound = meta.bound and vault_root() is not None
    vault_name = ""
    if bound and meta.vault_path:
        vault_name = Path(meta.vault_path).expanduser().name
    return {
        "bound": bound,
        "jarvis_managed_layout": meta.jarvis_managed_layout,
        "bound_at": meta.bound_at,
        "last_index_at": meta.last_index_at,
        "note_count": meta.note_count,
        "vault_name": vault_name,
    }


def _parse_frontmatter(text: str) -> tuple[dict[str, Any], str]:
    match = FRONTMATTER_RE.match(text)
    if not match:
        return {}, text
    try:
        fm = yaml.safe_load(match.group(1)) or {}
    except Exception:
        fm = {}
    if not isinstance(fm, dict):
        fm = {}
    body = text[match.end() :]
    return fm, body


def _note_title(rel_path: str, body: str, frontmatter: dict[str, Any]) -> str:
    if frontmatter.get("title"):
        return str(frontmatter["title"])
    for line in body.splitlines():
        if line.startswith("# "):
            return line[2:].strip()
    return Path(rel_path).stem


def _extract_links(body: str) -> tuple[list[str], list[str]]:
    wiki = [m.group(1).strip() for m in WIKI_LINK_RE.finditer(body)]
    md: list[str] = []
    for _label, target in MD_LINK_RE.findall(body):
        target = target.strip()
        if target and not target.startswith(("http://", "https://", "mailto:")):
            md.append(target.split("#")[0])
    return wiki, md


def _rel_markdown_path(root: Path, path: Path) -> str | None:
    try:
        rel = path.relative_to(root)
    except ValueError:
        return None
    if path.suffix.lower() not in {".md", ".markdown"}:
        return None
    return rel.as_posix()


def _iter_markdown_files(root: Path) -> list[Path]:
    files: list[Path] = []
    for child in root.rglob("*"):
        if child.is_file() and child.suffix.lower() in {".md", ".markdown"}:
            files.append(child)
    return files


def parse_note_file(root: Path, path: Path) -> NoteIndexEntry | None:
    rel = _rel_markdown_path(root, path)
    if rel is None:
        return None
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None
    frontmatter, body = _parse_frontmatter(text)
    headings = [m.group(2).strip() for m in HEADING_RE.finditer(body)]
    wiki, md = _extract_links(body)
    excerpt = body.strip()[:MAX_EXCERPT_CHARS]
    return NoteIndexEntry(
        rel_path=rel,
        title=_note_title(rel, body, frontmatter),
        headings=headings,
        body_excerpt=excerpt,
        content_hash=content_hash(text),
        frontmatter=frontmatter,
        outbound_wiki=wiki,
        outbound_md=md,
        indexed_at=_utc_now(),
    )


def index_file(rel_path: str) -> NoteIndexEntry | None:
    root = vault_root()
    if root is None:
        return None
    path = (root / rel_path).resolve()
    if not path.is_file():
        with _lock:
            notes = _load_index()
            notes.pop(rel_path.replace("\\", "/"), None)
            _save_index(notes)
        return None
    entry = parse_note_file(root, path)
    if entry is None:
        return None
    with _lock:
        notes = _load_index()
        notes[entry.rel_path] = entry
        _save_index(notes)
        meta = _load_meta()
        meta.note_count = len(notes)
        meta.last_index_at = _utc_now()
        _save_meta(meta)
    return entry


def index_all_vault() -> int:
    root = vault_root()
    if root is None:
        return 0
    notes: dict[str, NoteIndexEntry] = {}
    for path in _iter_markdown_files(root):
        entry = parse_note_file(root, path)
        if entry:
            notes[entry.rel_path] = entry
    with _lock:
        _save_index(notes)
        meta = _load_meta()
        meta.note_count = len(notes)
        meta.last_index_at = _utc_now()
        _save_meta(meta)
    return len(notes)


def _init_managed_layout(root: Path) -> None:
    for sub in DEFAULT_LAYOUT_DIRS:
        (root / sub).mkdir(parents=True, exist_ok=True)
    router = root / "_Config" / "router.md"
    if not router.exists():
        router.write_text(
            "# Jarvis vault router\n\n"
            "Compact orientation for linked memory. Edit freely; Jarvis indexes this folder.\n\n"
            "- Projects live in [[Projects/Welcome]]\n"
            "- Home notes live in [[Home/Jarvis]]\n",
            encoding="utf-8",
        )
    welcome = root / "Projects" / "Welcome.md"
    if not welcome.exists():
        welcome.write_text(
            "---\nid: jarvis-welcome\ntype: project\njarvis_managed: true\n---\n\n"
            "# Welcome\n\n"
            "This is the default Jarvis-managed Obsidian vault. "
            "Bind a different folder in Settings → Integrations if you already have a vault.\n",
            encoding="utf-8",
        )
    home = root / "Home" / "Jarvis.md"
    if not home.exists():
        home.write_text(
            "---\nid: jarvis-home\ntype: home\njarvis_managed: true\n---\n\n"
            "# Jarvis\n\nLocal durable notes for this PC. Wiki-link freely; Jarvis retrieves excerpts per turn.\n",
            encoding="utf-8",
        )


def default_vault_path() -> Path:
    return data_dir() / "vault"


def ensure_default_vault(*, configured_path: str = "", init_layout: bool = True) -> dict[str, Any]:
    """Bind the configured vault, or create and bind ``data/vault`` with the managed layout."""
    if public_binding_status().get("bound"):
        meta = _load_meta()
        return {
            "bound": True,
            "created": False,
            "vault_path": meta.vault_path,
            "note_count": meta.note_count,
            "init_layout": meta.jarvis_managed_layout,
        }
    candidate: Path
    use_layout = init_layout
    raw = (configured_path or "").strip()
    if raw:
        candidate = Path(raw).expanduser()
        if candidate.exists() and not candidate.is_dir():
            candidate = default_vault_path()
            use_layout = True
        elif not candidate.exists():
            candidate.mkdir(parents=True, exist_ok=True)
            use_layout = True
    else:
        candidate = default_vault_path()
        candidate.mkdir(parents=True, exist_ok=True)
        use_layout = True
    result = bind_vault(str(candidate), init_layout=use_layout)
    return {**result, "created": True, "vault_path": str(Path(candidate).expanduser().resolve())}


def bind_vault(vault_path: str, *, init_layout: bool = False) -> dict[str, Any]:
    resolved = Path(vault_path).expanduser().resolve()
    if not resolved.is_dir():
        raise ValueError(f"Vault path is not a directory: {vault_path}")
    if init_layout:
        _init_managed_layout(resolved)
    state = VaultBindingState(
        bound=True,
        vault_path=str(resolved),
        jarvis_managed_layout=init_layout,
        bound_at=_utc_now(),
        note_count=0,
    )
    with _lock:
        _save_meta(state)
    count = index_all_vault()
    start_watch()
    return {"bound": True, "note_count": count, "init_layout": init_layout}


def unbind_vault() -> dict[str, Any]:
    stop_watch()
    with _lock:
        _save_meta(VaultBindingState())
        for path in (_index_path(), _managed_state_path()):
            try:
                path.unlink(missing_ok=True)
            except OSError:
                pass
    return {"bound": False}


def _id_to_path(notes: dict[str, NoteIndexEntry], note_id: str) -> str | None:
    for rel, entry in notes.items():
        fm_id = str(entry.frontmatter.get("id") or "").strip()
        if fm_id and fm_id == note_id:
            return rel
    return None


def _resolve_link_target(target: str, from_rel: str, notes: dict[str, NoteIndexEntry]) -> ResolvedLink:
    target = target.strip()
    heading = None
    if "#" in target:
        target, heading_part = target.split("#", 1)
        heading = heading_part.strip() or None
    target = target.strip()
    if not target:
        return ResolvedLink(None, heading, True)

    # id: prefix
    if target.startswith("id:"):
        rel = _id_to_path(notes, target[3:].strip())
        return ResolvedLink(rel, heading, rel is None, via_id=target[3:].strip())

    root = vault_root()
    if root is None:
        return ResolvedLink(None, heading, True)

    candidates: list[Path] = []
    if target.endswith(".md") or target.endswith(".markdown"):
        candidates.append(root / target)
    else:
        candidates.append(root / f"{target}.md")
        candidates.append(root / target / "index.md")
        # wiki style basename search
        stem = Path(target).stem.lower()
        for rel, _entry in notes.items():
            if Path(rel).stem.lower() == stem:
                candidates.append(root / rel)

    for cand in candidates:
        if cand.is_file():
            rel = _rel_markdown_path(root, cand)
            if rel:
                return ResolvedLink(rel, heading, False)
    return ResolvedLink(None, heading, True)


def resolve_wiki_link(target: str, from_rel: str = "") -> ResolvedLink:
    notes = _load_index()
    return _resolve_link_target(target, from_rel, notes)


def _tokenize_query(query: str) -> list[str]:
    return [t for t in re.findall(r"[a-z0-9_]{2,}", (query or "").lower()) if len(t) > 1]


def search_vault(query: str, *, limit: int = MAX_SEARCH_RESULTS) -> list[VaultHit]:
    tokens = _tokenize_query(query)
    if not tokens:
        return []
    notes = _load_index()
    ranked: list[tuple[float, VaultHit]] = []
    for rel, entry in notes.items():
        hay = " ".join(
            [
                entry.title,
                entry.body_excerpt,
                " ".join(entry.headings),
                " ".join(str(v) for v in entry.frontmatter.values()),
            ]
        ).lower()
        score = sum(1.0 for tok in tokens if tok in hay)
        if score <= 0:
            continue
        ranked.append(
            (
                score,
                VaultHit(
                    rel_path=rel,
                    title=entry.title,
                    heading=entry.headings[0] if entry.headings else None,
                    excerpt=entry.body_excerpt[:400],
                    content_hash=entry.content_hash,
                    score=score,
                ),
            )
        )
    ranked.sort(key=lambda item: (-item[0], item[1].rel_path))
    return [hit for _score, hit in ranked[: max(1, limit)]]


def neighborhood(rel_path: str, *, hops: int = MAX_NEIGHBOR_HOPS) -> list[VaultHit]:
    notes = _load_index()
    key = rel_path.replace("\\", "/")
    if key not in notes:
        return []
    seen = {key}
    frontier = {key}
    hits: list[VaultHit] = []
    center = notes[key]
    hits.append(
        VaultHit(
            rel_path=key,
            title=center.title,
            heading=center.headings[0] if center.headings else None,
            excerpt=center.body_excerpt[:400],
            content_hash=center.content_hash,
            score=10.0,
        )
    )
    for _ in range(max(0, hops)):
        next_frontier: set[str] = set()
        for rel in frontier:
            entry = notes.get(rel)
            if not entry:
                continue
            for wiki_target in entry.outbound_wiki:
                resolved = _resolve_link_target(wiki_target, rel, notes)
                if resolved.target_path and not resolved.broken and resolved.target_path not in seen:
                    seen.add(resolved.target_path)
                    next_frontier.add(resolved.target_path)
            for md_target in entry.outbound_md:
                resolved = _resolve_link_target(md_target, rel, notes)
                if resolved.target_path and not resolved.broken and resolved.target_path not in seen:
                    seen.add(resolved.target_path)
                    next_frontier.add(resolved.target_path)
        for rel in next_frontier:
            entry = notes.get(rel)
            if not entry:
                continue
            hits.append(
                VaultHit(
                    rel_path=rel,
                    title=entry.title,
                    heading=entry.headings[0] if entry.headings else None,
                    excerpt=entry.body_excerpt[:300],
                    content_hash=entry.content_hash,
                    score=5.0,
                )
            )
        frontier = next_frontier
        if not frontier:
            break
    return hits


def read_note(rel_path: str) -> dict[str, Any]:
    root = vault_root()
    if root is None:
        raise ValueError("Vault is not bound")
    path = (root / rel_path).resolve()
    if not path.is_file():
        raise FileNotFoundError(rel_path)
    text = path.read_text(encoding="utf-8", errors="replace")
    frontmatter, body = _parse_frontmatter(text)
    return {
        "rel_path": rel_path.replace("\\", "/"),
        "content": text,
        "body": body,
        "frontmatter": frontmatter,
        "content_hash": content_hash(text),
    }


def _record_managed_write(rel_path: str, content_hash_value: str) -> None:
    state = _load_managed_state()
    state[rel_path] = {"content_hash": content_hash_value, "written_at": _utc_now()}
    _save_managed_state(state)


def _user_edit_conflict(rel_path: str, current_hash: str, jarvis_managed: bool) -> dict[str, Any] | None:
    if not jarvis_managed:
        return None
    state = _load_managed_state()
    prior = state.get(rel_path)
    if not prior:
        return None
    if prior.get("content_hash") == current_hash:
        return None
    return {
        "rel_path": rel_path,
        "message": "User edits win: on-disk content changed since Jarvis last wrote this managed note.",
        "jarvis_hash": prior.get("content_hash"),
        "current_hash": current_hash,
    }


def create_note(
    rel_path: str,
    content: str,
    *,
    jarvis_managed: bool = True,
    memory_pointer: str | None = None,
) -> dict[str, Any]:
    root = vault_root()
    if root is None:
        raise ValueError("Vault is not bound")
    rel = rel_path.replace("\\", "/")
    if not rel.endswith(".md"):
        rel += ".md"
    path = root / rel
    if path.exists():
        raise FileExistsError(rel)
    path.parent.mkdir(parents=True, exist_ok=True)
    fm: dict[str, Any] = {}
    body = content
    if jarvis_managed:
        fm = {
            "id": str(uuid.uuid4()),
            "jarvis_managed": True,
            "created_at": _utc_now(),
            "source": "jarvis",
        }
        if memory_pointer:
            fm["memory_id"] = memory_pointer
        if not content.lstrip().startswith("---"):
            body = f"---\n{yaml.safe_dump(fm, sort_keys=False).rstrip()}\n---\n\n{content.lstrip()}"
    path.write_text(body, encoding="utf-8")
    h = content_hash(path.read_text(encoding="utf-8"))
    if jarvis_managed:
        _record_managed_write(rel, h)
    index_file(rel)
    return {"rel_path": rel, "content_hash": h, "created": True}


def append_note(rel_path: str, text: str) -> dict[str, Any]:
    root = vault_root()
    if root is None:
        raise ValueError("Vault is not bound")
    rel = rel_path.replace("\\", "/")
    path = root / rel
    if not path.is_file():
        raise FileNotFoundError(rel)
    existing = path.read_text(encoding="utf-8", errors="replace")
    fm, body = _parse_frontmatter(existing)
    conflict = _user_edit_conflict(rel, content_hash(existing), bool(fm.get("jarvis_managed")))
    if conflict:
        return {"ok": False, "conflict": conflict}
    updated = existing.rstrip() + "\n\n" + text.strip() + "\n"
    path.write_text(updated, encoding="utf-8")
    h = content_hash(updated)
    if fm.get("jarvis_managed"):
        _record_managed_write(rel, h)
    index_file(rel)
    return {"ok": True, "rel_path": rel, "content_hash": h}


def edit_note(rel_path: str, new_body: str, *, force: bool = False) -> dict[str, Any]:
    root = vault_root()
    if root is None:
        raise ValueError("Vault is not bound")
    rel = rel_path.replace("\\", "/")
    path = root / rel
    if not path.is_file():
        raise FileNotFoundError(rel)
    existing = path.read_text(encoding="utf-8", errors="replace")
    fm, _body = _parse_frontmatter(existing)
    conflict = _user_edit_conflict(rel, content_hash(existing), bool(fm.get("jarvis_managed")))
    if conflict and not force:
        return {"ok": False, "conflict": conflict}
    if fm:
        header = f"---\n{yaml.safe_dump(fm, sort_keys=False).rstrip()}\n---\n\n"
        updated = header + new_body.strip() + "\n"
    else:
        updated = new_body
    path.write_text(updated, encoding="utf-8")
    h = content_hash(updated)
    if fm.get("jarvis_managed"):
        _record_managed_write(rel, h)
    index_file(rel)
    return {"ok": True, "rel_path": rel, "content_hash": h}


def vault_health() -> VaultHealth:
    notes = _load_index()
    root = vault_root()
    broken: list[dict[str, str]] = []
    id_map: dict[str, list[str]] = {}
    stale: list[str] = []
    for rel, entry in notes.items():
        note_id = str(entry.frontmatter.get("id") or "").strip()
        if note_id:
            id_map.setdefault(note_id, []).append(rel)
        for wiki in entry.outbound_wiki:
            resolved = _resolve_link_target(wiki, rel, notes)
            if resolved.broken:
                broken.append({"from": rel, "link": wiki, "kind": "wiki"})
        for md in entry.outbound_md:
            resolved = _resolve_link_target(md, rel, notes)
            if resolved.broken:
                broken.append({"from": rel, "link": md, "kind": "markdown"})
        if root:
            disk = root / rel
            if disk.is_file():
                if content_hash(disk.read_text(encoding="utf-8", errors="replace")) != entry.content_hash:
                    stale.append(rel)
            else:
                stale.append(rel)
    dupes = [{"id": nid, "paths": paths} for nid, paths in id_map.items() if len(paths) > 1]
    missing_router = bool(root and not (root / "_Config" / "router.md").is_file())
    return VaultHealth(
        broken_links=broken,
        duplicate_ids=dupes,
        stale_index_paths=stale,
        missing_router=missing_router,
    )


def repair_vault_index() -> dict[str, Any]:
    """Rebuild generated index only; never rewrite user prose."""
    count = index_all_vault()
    health = vault_health()
    return {
        "reindexed": count,
        "stale_remaining": len(health.stale_index_paths),
        "broken_links": len(health.broken_links),
        "duplicate_ids": len(health.duplicate_ids),
    }


def _watch_loop() -> None:
    mtimes: dict[str, float] = {}
    while not _watch_stop.is_set():
        root = vault_root()
        if root is None:
            time.sleep(WATCH_POLL_SECONDS)
            continue
        try:
            for path in _iter_markdown_files(root):
                rel = _rel_markdown_path(root, path)
                if not rel:
                    continue
                mtime = path.stat().st_mtime
                prev = mtimes.get(rel)
                if prev is None or mtime > prev:
                    index_file(rel)
                mtimes[rel] = mtime
            # drop removed files from index
            notes = _load_index()
            for rel in list(notes.keys()):
                if not (root / rel).is_file():
                    with _lock:
                        notes = _load_index()
                        notes.pop(rel, None)
                        _save_index(notes)
        except Exception:
            pass
        _watch_stop.wait(WATCH_POLL_SECONDS)


def start_watch() -> None:
    global _watch_thread
    if _watch_thread and _watch_thread.is_alive():
        return
    _watch_stop.clear()
    _watch_thread = threading.Thread(target=_watch_loop, name="obsidian-vault-watch", daemon=True)
    _watch_thread.start()


def stop_watch() -> None:
    _watch_stop.set()


async def sync_hit_to_context_repo(agent_id: str, hit: VaultHit) -> dict[str, Any]:
    """Vault → Jarvis: indexed excerpt with provenance (RFC-0011)."""
    from .repository import add_entry

    title = hit.title or Path(hit.rel_path).stem
    content = f"{hit.excerpt}\n\n(vault:{hit.rel_path} hash:{hit.content_hash[:12]})"
    entry = await add_entry(
        agent_id,
        category="vault",
        title=title[:200],
        content=content[:4000],
        source_type="obsidian_vault",
        source_id=hit.rel_path,
        note=f"RFC-0107 vault excerpt score={hit.score}",
    )
    return {"entry_id": entry.id, "rel_path": hit.rel_path}


async def write_decision_to_vault(
    title: str,
    body: str,
    *,
    memory_id: str | None = None,
    subdir: str = "Decisions",
) -> dict[str, Any]:
    """Jarvis → vault durable decision note."""
    safe = re.sub(r"[^\w\s-]", "", title).strip().replace(" ", "-")[:80] or "decision"
    rel = f"{subdir}/{safe}.md"
    root = vault_root()
    if root is None:
        raise ValueError("Vault is not bound")
    path = root / rel
    if path.exists():
        rel = f"{subdir}/{safe}-{uuid.uuid4().hex[:8]}.md"
    pointer = memory_id or ""
    text = f"# {title}\n\n{body.strip()}\n"
    if pointer:
        text += f"\n\n<!-- jarvis_memory_id:{pointer} -->\n"
    return create_note(rel, text, jarvis_managed=True, memory_pointer=pointer or None)


def query_looks_vault_relevant(query: str) -> bool:
    tokens = set(_tokenize_query(query))
    return bool(tokens & _VAULT_RELEVANCE_TERMS)


def _router_orientation_excerpt() -> VaultHit | None:
    root = vault_root()
    if root is None:
        return None
    router = root / "_Config" / "router.md"
    if not router.is_file():
        return None
    text = router.read_text(encoding="utf-8", errors="replace")
    _fm, body = _parse_frontmatter(text)
    excerpt = re.sub(r"\s+", " ", body.strip())[:400]
    if not excerpt:
        return None
    rel = "_Config/router.md"
    return VaultHit(
        rel_path=rel,
        title="Vault router",
        heading=None,
        excerpt=excerpt,
        content_hash=content_hash(text),
        score=0.5,
        provenance="vault_router",
    )


def _reflex_rerank_hits(query: str, hits: list[VaultHit], *, limit: int) -> list[VaultHit]:
    """RFC-0171: typed memory relevance over lexical vault shortlist when System-One is active."""
    if not hits:
        return []
    try:
        from ..decision.laya import ready as laya_ready
        from ..decision.wire import cloud_opt_in_active, decide_memory_relevance

        if not laya_ready() and not cloud_opt_in_active():
            return hits[: max(1, limit)]

        ranked = decide_memory_relevance(
            query,
            [
                {
                    "rel_path": hit.rel_path,
                    "title": hit.title,
                    "excerpt": hit.excerpt,
                    "content_hash": hit.content_hash,
                    "score": hit.score,
                    "heading": hit.heading,
                    "provenance": getattr(hit, "provenance", "") or "",
                }
                for hit in hits
            ],
            deadline_ms=60,
            cloud_ok=cloud_opt_in_active(),
        )
    except Exception:
        return hits[: max(1, limit)]
    by_path = {hit.rel_path: hit for hit in hits}
    out: list[VaultHit] = []
    for row in ranked:
        path = str(row.get("rel_path") or "")
        hit = by_path.get(path)
        if hit is None:
            continue
        reflex_score = float(row.get("reflex_score") or 0.0)
        out.append(
            VaultHit(
                rel_path=hit.rel_path,
                title=hit.title,
                heading=hit.heading,
                excerpt=hit.excerpt,
                content_hash=hit.content_hash,
                score=max(float(hit.score or 0.0), reflex_score),
                provenance=getattr(hit, "provenance", "") or "",
            )
        )
        if len(out) >= max(1, limit):
            break
    return out or hits[: max(1, limit)]


def vault_turn_hits(query: str, *, limit: int = 6) -> list[VaultHit]:
    """Lexical search with vault-relevant fallbacks (router orientation, token retry)."""
    cleaned = (query or "").strip()
    hits = search_vault(cleaned, limit=limit)
    if hits:
        return _reflex_rerank_hits(cleaned, hits, limit=limit)
    tokens = _tokenize_query(cleaned)
    if len(tokens) > 1:
        for tok in sorted(tokens, key=len, reverse=True):
            if tok in _VAULT_RELEVANCE_TERMS:
                continue
            hits = search_vault(tok, limit=limit)
            if hits:
                return _reflex_rerank_hits(cleaned, hits, limit=limit)
    if not query_looks_vault_relevant(cleaned):
        return []
    router = _router_orientation_excerpt()
    if router:
        return [router]
    notes = _load_index()
    if not notes:
        return []
    fallback: list[VaultHit] = []
    for rel, entry in sorted(notes.items(), key=lambda item: item[1].indexed_at or "", reverse=True)[:3]:
        fallback.append(
            VaultHit(
                rel_path=rel,
                title=entry.title,
                heading=entry.headings[0] if entry.headings else None,
                excerpt=entry.body_excerpt[:320],
                content_hash=entry.content_hash,
                score=0.25,
                provenance="vault_recent",
            )
        )
    return fallback[:limit]


def session_note_rel_path(conversation_id: str) -> str:
    safe = re.sub(r"[^\w-]", "", (conversation_id or "session"))[:48] or "session"
    day = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    return f"_Temporal/Sessions/{day}-{safe}.md"


def mirror_owner_chat_turn(
    *,
    conversation_id: str,
    user_text: str,
    assistant_text: str,
) -> dict[str, Any] | None:
    """Append this owner-chat exchange to a jarvis_managed session note (durable mirror)."""
    if vault_root() is None:
        return None
    rel = session_note_rel_path(conversation_id)
    root = vault_root()
    assert root is not None
    path = root / rel
    block = (
        f"\n\n## Turn {_utc_now()}\n\n"
        f"**Owner:** {user_text.strip()[:2000]}\n\n"
        f"**Jarvis:** {assistant_text.strip()[:4000]}\n"
    )
    try:
        if path.is_file():
            result = append_note(rel, block)
            if not result.get("ok"):
                return result
            return {"rel_path": rel, "appended": True}
        header = (
            f"# Owner chat session\n\n"
            f"conversation_id: `{conversation_id}`\n\n"
            f"Jarvis-managed mirror of portal owner dialogue (RFC-0107).\n"
        )
        return create_note(rel, header + block, jarvis_managed=True)
    except Exception as exc:
        return {"ok": False, "error": str(exc)[:400]}


def persist_verified_correction(
    *,
    user_prompt: str,
    initial_answer: str,
    correction: str,
    conversation_id: str | None = None,
) -> dict[str, Any] | None:
    """Write a background-verification correction into Decisions/ when vault is bound."""
    if vault_root() is None:
        return None
    title = re.sub(r"\s+", " ", user_prompt.strip())[:80] or "Verified correction"
    body = (
        f"Owner question:\n{user_prompt.strip()[:1500]}\n\n"
        f"Initial answer:\n{initial_answer.strip()[:1500]}\n\n"
        f"Corrected answer:\n{correction.strip()[:2000]}\n"
    )
    if conversation_id:
        body += f"\nconversation_id: `{conversation_id}`\n"
    safe = re.sub(r"[^\w\s-]", "", title).strip().replace(" ", "-")[:80] or "correction"
    rel = f"Decisions/{safe}-{uuid.uuid4().hex[:8]}.md"
    try:
        return create_note(
            rel,
            f"# {title}\n\n{body.strip()}\n",
            jarvis_managed=True,
            memory_pointer=conversation_id,
        )
    except Exception as exc:
        return {"ok": False, "error": str(exc)[:400]}


def vault_prompt_block(query: str, *, hop_cap: int = MAX_NEIGHBOR_HOPS) -> str:
    """Compact vault hits for the turn working set — never the full vault."""
    hits = vault_turn_hits(query, limit=6)
    if not hits:
        return ""
    lines = [
        "Linked vault memory (RFC-0107): use only these excerpts; the full vault is not in context.",
    ]
    seen_paths: set[str] = set()
    for hit in hits:
        lines.append(
            f"- [{hit.rel_path}] {hit.title}: {hit.excerpt[:280]} (hash:{hit.content_hash[:12]})"
        )
        seen_paths.add(hit.rel_path)
        for neighbor in neighborhood(hit.rel_path, hops=hop_cap):
            if neighbor.rel_path in seen_paths:
                continue
            seen_paths.add(neighbor.rel_path)
            lines.append(
                f"  ↳ [{neighbor.rel_path}] {neighbor.title}: {neighbor.excerpt[:200]}"
            )
            if len(seen_paths) >= 10:
                break
        if len(seen_paths) >= 10:
            break
    return "\n".join(lines)


def act_vault(
    action: Literal["open", "read", "create", "append", "edit"],
    *,
    rel_path: str = "",
    content: str = "",
    query: str = "",
    force: bool = False,
) -> dict[str, Any]:
    if action == "read" or action == "open":
        return read_note(rel_path)
    if action == "create":
        return create_note(rel_path, content)
    if action == "append":
        return append_note(rel_path, content)
    if action == "edit":
        return edit_note(rel_path, content, force=force)
    if action and not rel_path:
        return {"hits": [asdict(h) for h in search_vault(query)]}
    raise ValueError(f"Unsupported vault action: {action}")
