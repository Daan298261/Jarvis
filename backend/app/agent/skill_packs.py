"""External skill pack registration for module connectors (RFC-0105)."""
from __future__ import annotations

from pathlib import Path
from typing import Any

from .local_harness import SKILL_HINTS

_SKILL_MANIFEST_NAMES = ("SKILL.md", "skill.md", "Skill.md")


def scan_skill_md_names(root: Path, *, limit: int = 500) -> list[str]:
    names: list[str] = []
    if not root.is_dir():
        return names
    for path in sorted(root.rglob("*")):
        if len(names) >= limit:
            break
        if path.name not in _SKILL_MANIFEST_NAMES:
            continue
        rel_parent = path.parent.relative_to(root)
        label = str(rel_parent) if str(rel_parent) != "." else path.parent.name
        cleaned = label.replace("\\", "/").strip("/")
        if cleaned and cleaned not in names:
            names.append(cleaned)
    return names


_MODULE_PACKS: dict[str, dict[str, dict[str, Any]]] = {}


def register_module_pack(module_id: str, member_id: str, names: list[str], *, root: str = "") -> None:
    key = (module_id or "").strip()
    member = (member_id or "").strip()
    if not key or not member:
        return
    bucket = _MODULE_PACKS.setdefault(key, {})
    bucket[member] = {"names": list(names), "root": root}
    hint_key = f"module:{key}:{member}"
    if names:
        SKILL_HINTS[hint_key] = (
            f"Cybersecurity skill pack ({member}) exposes {len(names)} skill manifest(s): "
            + ", ".join(names[:12])
            + ("…" if len(names) > 12 else "")
            + ". Load only the relevant SKILL.md for the task."
        )
    else:
        SKILL_HINTS.pop(hint_key, None)


def clear_module_packs(module_id: str) -> None:
    key = (module_id or "").strip()
    bucket = _MODULE_PACKS.pop(key, {})
    for member_id in bucket:
        SKILL_HINTS.pop(f"module:{key}:{member_id}", None)


def pack_names(module_id: str, member_id: str) -> list[str]:
    bucket = _MODULE_PACKS.get(module_id, {})
    row = bucket.get(member_id, {})
    names = row.get("names")
    return list(names) if isinstance(names, list) else []


def reset_skill_packs() -> None:
    """Test helper."""
    for module_id in list(_MODULE_PACKS):
        clear_module_packs(module_id)
    _MODULE_PACKS.clear()
