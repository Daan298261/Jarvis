"""Cybersecurity module catalog member discovery and launch hooks (RFC-0105).

Wiring only — no exploit recipes, PoCs, attack steps, or payloads.
"""
from __future__ import annotations

import json
import logging
import os
import platform
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

from ..config import data_dir, repo_root
from ..agent import skill_packs
from .catalog_download import (
    desktop_projects_root,
    le_gated_roots,
    library_projects_path,
    owner_project_roots,
    recorded_local_path,
    register_allowlisted_source,
)
from .supervisor import (
    discover_graph_ui_url,
    get_supervisor,
    resolve_start_spec,
)

log = logging.getLogger(__name__)

MODULE_ID = "cybersecurity"
MODULE_DISPLAY = "Cybersecurity"

MemberRole = Literal["harness", "skill_pack", "library_backend", "graph_ui"]
MemberStatus = Literal["missing", "found", "starting", "running", "error", "disabled"]

MEMBER_ORDER: tuple[str, ...] = (
    "strix",
    "anthropic-cybersecurity-skills",
    "exploitarium",
    "pentagi",
    "claude-red",
    "flowsint",
)

# Jarvis-owned harness entries for bounded child workers (cwd = clone).
_HARNESS_ENTRIES: dict[str, dict[str, Any]] = {}


@dataclass(frozen=True)
class MemberDef:
    id: str
    display_name: str
    source_url: str
    role: MemberRole
    slug: str


MEMBERS: dict[str, MemberDef] = {
    "strix": MemberDef(
        id="strix",
        display_name="Strix",
        source_url="https://github.com/usestrix/strix",
        role="harness",
        slug="strix",
    ),
    "anthropic-cybersecurity-skills": MemberDef(
        id="anthropic-cybersecurity-skills",
        display_name="Anthropic Cybersecurity Skills",
        source_url="https://github.com/mukul975/Anthropic-Cybersecurity-Skills",
        role="skill_pack",
        slug="Anthropic-Cybersecurity-Skills",
    ),
    "exploitarium": MemberDef(
        id="exploitarium",
        display_name="Exploitarium",
        source_url="https://github.com/bikini/exploitarium",
        role="library_backend",
        slug="exploitarium",
    ),
    "pentagi": MemberDef(
        id="pentagi",
        display_name="Pentagi",
        source_url="https://github.com/vxcontrol/pentagi",
        role="harness",
        slug="pentagi",
    ),
    "claude-red": MemberDef(
        id="claude-red",
        display_name="Claude-Red",
        source_url="https://github.com/SnailSploit/Claude-Red",
        role="skill_pack",
        slug="Claude-Red",
    ),
    "flowsint": MemberDef(
        id="flowsint",
        display_name="Flowsint",
        source_url="https://github.com/reconurge/flowsint",
        role="graph_ui",
        slug="flowsint",
    ),
}


def _state_path() -> Path:
    return data_dir() / "cybersecurity-module.json"


def _default_state() -> dict[str, Any]:
    return {
        "module_enabled": False,
        "members": {member_id: {"enabled": False, "recorded_path": ""} for member_id in MEMBER_ORDER},
    }


def load_state() -> dict[str, Any]:
    path = _state_path()
    if not path.is_file():
        return _default_state()
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return _default_state()
    if not isinstance(payload, dict):
        return _default_state()
    members = payload.get("members")
    if not isinstance(members, dict):
        payload["members"] = _default_state()["members"]
    else:
        for member_id in MEMBER_ORDER:
            row = members.get(member_id)
            if not isinstance(row, dict):
                members[member_id] = {"enabled": False, "recorded_path": ""}
    payload.setdefault("module_enabled", False)
    return payload


def save_state(state: dict[str, Any]) -> None:
    path = _state_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(state, indent=2), encoding="utf-8")


def reset_state() -> None:
    path = _state_path()
    if path.exists():
        path.unlink()
    _HARNESS_ENTRIES.clear()


def _candidate_paths(member: MemberDef, state: dict[str, Any]) -> list[Path]:
    paths: list[Path] = []
    row = state.get("members", {}).get(member.id, {})
    recorded = str(row.get("recorded_path") or "").strip()
    if recorded:
        paths.append(Path(recorded).expanduser())
    downloaded = recorded_local_path(member.id)
    if downloaded:
        paths.append(Path(downloaded))
    for root in le_gated_roots():
        paths.append(root / member.slug)
        paths.append(root / member.id)
    lib = library_projects_path()
    paths.append(lib / member.slug)
    paths.append(lib / member.id)
    paths.append(repo_root() / "projects" / member.slug)
    paths.append(desktop_projects_root() / member.slug)
    paths.append(desktop_projects_root() / member.id)
    for root in owner_project_roots():
        paths.append(root / member.slug)
        paths.append(root / member.id)
    seen: set[str] = set()
    ordered: list[Path] = []
    for path in paths:
        key = str(path)
        if key in seen:
            continue
        seen.add(key)
        ordered.append(path)
    return ordered


def discover_local_path(member_id: str, state: dict[str, Any] | None = None) -> Path | None:
    member = MEMBERS.get(member_id)
    if member is None:
        return None
    state = state or load_state()
    for path in _candidate_paths(member, state):
        try:
            if path.is_dir():
                return path.resolve()
        except OSError:
            continue
    return None


def _role_supports_process(role: str) -> bool:
    key = (role or "").strip().lower().replace("-", "_")
    return key in {"harness", "graph_ui"}


def _member_enabled(state: dict[str, Any], member_id: str) -> bool:
    row = state.get("members", {}).get(member_id, {})
    return bool(state.get("module_enabled")) and bool(row.get("enabled"))


def _exploitarium_index(root: Path, *, limit: int = 200) -> list[dict[str, str]]:
    """Filename/title index only — never copy library bodies into Jarvis docs."""
    entries: list[dict[str, str]] = []
    if not root.is_dir():
        return entries
    for path in sorted(root.rglob("*")):
        if len(entries) >= limit:
            break
        if not path.is_file():
            continue
        if path.suffix.lower() not in {".md", ".txt", ".json", ".yaml", ".yml"}:
            continue
        # Skip VCS / node_modules noise
        parts = set(path.parts)
        if parts & {".git", "node_modules", "__pycache__", ".venv", "venv"}:
            continue
        try:
            rel = str(path.relative_to(root)).replace("\\", "/")
        except ValueError:
            continue
        if rel.count("/") > 4:
            continue
        title = path.stem.replace("_", " ").replace("-", " ")
        entries.append({"name": rel, "title": title[:120]})
    return entries


def library_index_for(member_id: str = "exploitarium") -> list[dict[str, str]]:
    """Public retrieval index (names/titles only) when the library member is enabled."""
    state = load_state()
    if member_id not in MEMBERS or MEMBERS[member_id].role != "library_backend":
        return []
    if not _member_enabled(state, member_id):
        return []
    root = discover_local_path(member_id, state)
    if root is None:
        return []
    return _exploitarium_index(root)


def harness_entries() -> list[dict[str, Any]]:
    """Enabled harness members with clone cwd for bounded child workers."""
    return [dict(row) for row in _HARNESS_ENTRIES.values()]


def get_harness_entry(member_id: str) -> dict[str, Any] | None:
    row = _HARNESS_ENTRIES.get(member_id)
    return dict(row) if row else None


def _sync_harness_entries(state: dict[str, Any]) -> None:
    _HARNESS_ENTRIES.clear()
    if not state.get("module_enabled"):
        return
    for member_id in MEMBER_ORDER:
        member = MEMBERS[member_id]
        if member.role != "harness":
            continue
        if not _member_enabled(state, member_id):
            continue
        root = discover_local_path(member_id, state)
        if root is None:
            continue
        spec = resolve_start_spec(root, member.role)
        _HARNESS_ENTRIES[member_id] = {
            "member_id": member_id,
            "module_id": MODULE_ID,
            "role": member.role,
            "cwd": str(root),
            "launchable": spec is not None,
            "health_url": spec.health_url if spec else "",
        }


def _member_status(member: MemberDef, state: dict[str, Any]) -> MemberStatus:
    row = state.get("members", {}).get(member.id, {})
    module_on = bool(state.get("module_enabled"))
    tool_on = bool(row.get("enabled"))
    local = discover_local_path(member.id, state)
    if not module_on or not tool_on:
        if local is None:
            return "missing"
        return "disabled"
    if local is None:
        return "missing"
    if _role_supports_process(member.role):
        supervisor = get_supervisor(member.id)
        snap = supervisor.snapshot()
        if snap.starting:
            return "starting"
        if snap.running:
            return "running"
        if snap.last_error:
            return "error"
    return "found"


def _sync_skill_packs(state: dict[str, Any]) -> None:
    skill_packs.clear_module_packs(MODULE_ID)
    if not state.get("module_enabled"):
        return
    for member_id in MEMBER_ORDER:
        member = MEMBERS[member_id]
        if member.role != "skill_pack":
            continue
        row = state.get("members", {}).get(member_id, {})
        if not row.get("enabled"):
            continue
        root = discover_local_path(member_id, state)
        if root is None:
            continue
        names = skill_packs.scan_skill_md_names(root)
        skill_packs.register_module_pack(
            MODULE_ID,
            member_id,
            names,
            root=str(root),
        )


def _connector_payload(member: MemberDef, state: dict[str, Any], local: Path | None, enabled: bool) -> dict[str, Any]:
    """Honest per-role connector fields — no silent 'running' décor."""
    base: dict[str, Any] = {
        "kind": member.role,
        "cwd": str(local) if local else None,
        "ready": bool(enabled and local is not None),
    }
    if member.role == "harness":
        entry = _HARNESS_ENTRIES.get(member.id)
        launchable = bool(entry and entry.get("launchable"))
        base.update(
            {
                "launchable": launchable,
                "harness_entry": entry,
                "start_requires": "jarvis-module.json or start.sh/main.py under clone",
            }
        )
    elif member.role == "skill_pack":
        names = skill_packs.pack_names(MODULE_ID, member.id) if enabled and local else []
        base.update(
            {
                "registered": bool(enabled and local and names),
                "skill_pack_names": names,
                "on_demand": True,
            }
        )
    elif member.role == "library_backend":
        index = _exploitarium_index(local) if local else []
        base.update(
            {
                "library_index_count": len(index),
                "library_index": index if enabled else [],
                "bodies_embedded": False,
            }
        )
    elif member.role == "graph_ui":
        ui_url = discover_graph_ui_url(local) if local else None
        launchable = bool(local and resolve_start_spec(local, member.role) is not None)
        base.update(
            {
                "ui_url": ui_url,
                "launchable": launchable,
                "connector_mode": "loopback_ui" if launchable else ("open_folder" if local else "missing"),
            }
        )
    return base


def build_module_payload() -> dict[str, Any]:
    state = load_state()
    _sync_skill_packs(state)
    _sync_harness_entries(state)
    members_out: list[dict[str, Any]] = []
    for member_id in MEMBER_ORDER:
        member = MEMBERS[member_id]
        local = discover_local_path(member_id, state)
        row = state.get("members", {}).get(member_id, {})
        enabled = bool(state.get("module_enabled")) and bool(row.get("enabled"))
        connector = _connector_payload(member, state, local, enabled)
        payload: dict[str, Any] = {
            "id": member.id,
            "display_name": member.display_name,
            "source_url": member.source_url,
            "local_path": str(local) if local else None,
            "enabled": enabled,
            "status": _member_status(member, state),
            "role": member.role,
            "connector": connector,
        }
        # Backward-compatible top-level fields used by Daybreak / tests
        if member.role == "skill_pack" and enabled and local:
            payload["skill_pack_names"] = connector.get("skill_pack_names", [])
        if member.role == "library_backend" and local:
            payload["library_index_count"] = connector.get("library_index_count", 0)
            if enabled:
                payload["library_index"] = connector.get("library_index", [])
        if member.role == "graph_ui":
            payload["ui_url"] = connector.get("ui_url")
            payload["connector_mode"] = connector.get("connector_mode")
        if member.role == "harness":
            payload["harness_entry"] = connector.get("harness_entry")
            payload["launchable"] = connector.get("launchable")
        members_out.append(payload)
    return {
        "id": MODULE_ID,
        "display_name": MODULE_DISPLAY,
        "enabled": bool(state.get("module_enabled")),
        "members": members_out,
        "harness_entries": harness_entries(),
    }


async def _stop_process_member(member_id: str) -> None:
    if member_id not in MEMBERS or not _role_supports_process(MEMBERS[member_id].role):
        return
    supervisor = get_supervisor(member_id)
    if supervisor.is_running or supervisor.managed_pid is not None:
        await supervisor.stop()


async def set_module_enabled(enabled: bool) -> dict[str, Any]:
    state = load_state()
    state["module_enabled"] = bool(enabled)
    save_state(state)
    if not enabled:
        for member_id in MEMBER_ORDER:
            await _stop_process_member(member_id)
    _sync_skill_packs(state)
    _sync_harness_entries(state)
    return build_module_payload()


async def set_member_enabled(member_id: str, enabled: bool) -> dict[str, Any]:
    if member_id not in MEMBERS:
        raise KeyError(member_id)
    state = load_state()
    row = state.setdefault("members", {}).setdefault(member_id, {"enabled": False, "recorded_path": ""})
    row["enabled"] = bool(enabled)
    save_state(state)
    if not enabled:
        await _stop_process_member(member_id)
    _sync_skill_packs(state)
    _sync_harness_entries(state)
    return build_module_payload()


def record_member_path(member_id: str, local_path: Path) -> None:
    if member_id not in MEMBERS:
        return
    state = load_state()
    row = state.setdefault("members", {}).setdefault(member_id, {"enabled": False, "recorded_path": ""})
    row["recorded_path"] = str(local_path)
    save_state(state)


async def start_member(member_id: str) -> dict[str, Any]:
    member = MEMBERS.get(member_id)
    if member is None:
        raise KeyError(member_id)
    state = load_state()
    if not state.get("module_enabled") or not state.get("members", {}).get(member_id, {}).get("enabled"):
        return {"ok": False, "detail": "Enable the cybersecurity module and this tool first."}
    if not _role_supports_process(member.role):
        return {"ok": False, "detail": "This member does not support process control."}
    root = discover_local_path(member_id, state)
    if root is None:
        return {"ok": False, "detail": "Local checkout not found. Use Download first.", "status": "missing"}
    spec = resolve_start_spec(root, member.role)
    if spec is None:
        if member.role == "graph_ui":
            return {
                "ok": False,
                "detail": "No loopback UI start metadata in clone; use Open folder.",
                "status": "found",
                "connector_mode": "open_folder",
                "path": str(root),
            }
        return {
            "ok": False,
            "detail": "No start metadata found. Add jarvis-module.json (loopback) or a start script to the checkout root.",
            "status": "error",
            "path": str(root),
        }
    supervisor = get_supervisor(member_id)
    snap = await supervisor.start(spec)
    if snap.running:
        _sync_harness_entries(state)
        return {
            "ok": True,
            "detail": "Started.",
            "pid": snap.pid,
            "health_url": snap.health_url,
            "cwd": str(root),
            "status": "running",
        }
    return {"ok": False, "detail": snap.last_error or "Start failed.", "status": "error"}


async def stop_member(member_id: str) -> dict[str, Any]:
    member = MEMBERS.get(member_id)
    if member is None:
        raise KeyError(member_id)
    if not _role_supports_process(member.role):
        return {"ok": False, "detail": "This member does not support process control."}
    supervisor = get_supervisor(member_id)
    if not supervisor.is_running and supervisor.managed_pid is None:
        return {"ok": True, "detail": "No Jarvis-managed process was running."}
    snap = await supervisor.stop()
    return {"ok": True, "detail": "Stopped.", "pid": snap.pid}


def open_member_folder(member_id: str) -> dict[str, Any]:
    member = MEMBERS.get(member_id)
    if member is None:
        raise KeyError(member_id)
    root = discover_local_path(member_id)
    if root is None:
        return {"ok": False, "detail": "Local checkout not found.", "status": "missing"}
    try:
        if platform.system() == "Windows":
            os.startfile(str(root))  # type: ignore[attr-defined]
        elif platform.system() == "Darwin":
            subprocess.run(["open", str(root)], check=False)
        else:
            subprocess.run(["xdg-open", str(root)], check=False)
    except OSError as exc:
        return {"ok": False, "detail": str(exc)[:200]}
    return {"ok": True, "detail": "Opened folder in the system file manager.", "path": str(root)}


def bootstrap_allowlist() -> None:
    for member in MEMBERS.values():
        register_allowlisted_source(member.id, member.source_url, slug=member.slug)


bootstrap_allowlist()


def catalog_list_row() -> dict[str, Any]:
    payload = build_module_payload()
    local = None
    for member in payload.get("members", []):
        if member.get("local_path"):
            local = member["local_path"]
            break
    return {
        "id": MODULE_ID,
        "name": MODULE_DISPLAY,
        "display_name": MODULE_DISPLAY,
        "source_url": "",
        "local_path": local,
        "tags": ["module", "cybersecurity"],
        "review_bucket": "module",
        # Still partial — real launch hooks, not whole-app embed.
        "integrate_decision": "partial",
        "connector_depth": "launch_hooks",
        "integrate_note": (
            "Partial connectors with real discovery, enable, start/stop (Jarvis pids), "
            "skill-pack register, library index, and graph/UI hooks — not whole-app embed."
        ),
        "pipeline_stage": "implement",
        "downloadable": True,
        "members": payload.get("members", []),
        "harness_entries": payload.get("harness_entries", []),
    }
