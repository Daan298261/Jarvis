from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable


@dataclass
class UiControl:
    name: str
    automation_id: str = ""
    control_type: str = ""
    enabled: bool = True
    handle: Any = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "automation_id": self.automation_id,
            "control_type": self.control_type,
            "enabled": self.enabled,
        }


def normalize(value: str | None) -> str:
    return (value or "").strip().lower()


def resolve_control(
    controls: Iterable[UiControl],
    *,
    name: str | None = None,
    automation_id: str | None = None,
    control_type: str | None = None,
) -> tuple[UiControl | None, str]:
    """Pick a named control. Order: automation_id, type+name, exact name, fuzzy name."""
    items = [item for item in controls if item]
    if not items:
        return None, "none"

    wanted_id = normalize(automation_id)
    if wanted_id:
        for item in items:
            if normalize(item.automation_id) == wanted_id:
                return item, "automation_id"

    wanted_name = normalize(name)
    wanted_type = normalize(control_type)
    if wanted_name and wanted_type:
        for item in items:
            if normalize(item.name) == wanted_name and normalize(item.control_type) == wanted_type:
                return item, "control_type+name"

    if wanted_name:
        for item in items:
            if normalize(item.name) == wanted_name:
                return item, "name"

    if wanted_name:
        for item in items:
            haystack = f"{item.name} {item.automation_id}"
            if wanted_name in normalize(haystack):
                return item, "fuzzy_name"

    if wanted_type:
        matches = [item for item in items if normalize(item.control_type) == wanted_type]
        if len(matches) == 1:
            return matches[0], "control_type"

    return None, "unresolved"


def click_backend(
    *,
    name: str | None = None,
    automation_id: str | None = None,
    control_type: str | None = None,
    x: int | None = None,
    y: int | None = None,
) -> str:
    if name or automation_id or control_type:
        return "semantic"
    if x is not None and y is not None:
        return "coordinate"
    return "missing"


def format_control_list(controls: Iterable[UiControl], limit: int = 80) -> str:
    rows = list(controls)[:limit]
    if not rows:
        return "No named controls"
    lines = []
    for item in rows:
        extra = []
        if item.control_type:
            extra.append(item.control_type)
        if item.automation_id:
            extra.append(f"id={item.automation_id}")
        if not item.enabled:
            extra.append("disabled")
        suffix = f" ({', '.join(extra)})" if extra else ""
        lines.append(f"- {item.name}{suffix}")
    return "\n".join(lines)
