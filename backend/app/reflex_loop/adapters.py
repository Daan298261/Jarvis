"""Observation adapters: browser DOM/a11y and desktop UI Automation → ActionFrame."""

from __future__ import annotations

from typing import Any
import time

from .schema import (
    ActionFrame,
    ActionNode,
    Geometry,
    NodeState,
    Operation,
    SurfaceKind,
    new_frame_id,
    new_target_id,
)

# Role → default supported operations for ordinary form/nav.
_ROLE_OPS: dict[str, tuple[Operation, ...]] = {
    "button": (Operation.CLICK, Operation.FOCUS),
    "link": (Operation.CLICK, Operation.FOCUS),
    "tab": (Operation.CLICK, Operation.FOCUS),
    "menuitem": (Operation.CLICK, Operation.FOCUS),
    "checkbox": (Operation.TOGGLE, Operation.CLICK, Operation.FOCUS),
    "radio": (Operation.SELECT, Operation.CLICK, Operation.FOCUS),
    "switch": (Operation.TOGGLE, Operation.CLICK, Operation.FOCUS),
    "textbox": (Operation.TYPE_TEXT, Operation.CLEAR, Operation.FOCUS, Operation.CLICK),
    "searchbox": (Operation.TYPE_TEXT, Operation.CLEAR, Operation.FOCUS, Operation.CLICK),
    "combobox": (Operation.TYPE_TEXT, Operation.SELECT, Operation.FOCUS, Operation.CLICK),
    "listbox": (Operation.SELECT, Operation.FOCUS, Operation.CLICK),
    "option": (Operation.SELECT, Operation.CLICK, Operation.FOCUS),
    "slider": (Operation.FOCUS, Operation.CLICK),
    "spinbutton": (Operation.TYPE_TEXT, Operation.FOCUS, Operation.CLICK),
    "edit": (Operation.TYPE_TEXT, Operation.CLEAR, Operation.FOCUS, Operation.CLICK),
    "document": (Operation.FOCUS, Operation.SCROLL_INTO_VIEW),
    "window": (Operation.FOCUS,),
}


def _ops_for_role(role: str) -> tuple[Operation, ...]:
    key = (role or "").strip().lower()
    return _ROLE_OPS.get(key, (Operation.CLICK, Operation.FOCUS))


def _geometry_from(raw: dict[str, Any] | None) -> Geometry:
    if not isinstance(raw, dict):
        return Geometry()
    return Geometry(
        x=float(raw.get("x") or raw.get("left") or 0.0),
        y=float(raw.get("y") or raw.get("top") or 0.0),
        width=float(raw.get("width") or 0.0),
        height=float(raw.get("height") or 0.0),
    )


def _state_from(raw: dict[str, Any] | None) -> NodeState:
    if not isinstance(raw, dict):
        return NodeState()
    checked = raw.get("checked")
    if checked is not None:
        checked = bool(checked)
    return NodeState(
        enabled=bool(raw.get("enabled", True)),
        focused=bool(raw.get("focused", False)),
        checked=checked,
        expanded=raw.get("expanded") if raw.get("expanded") is None else bool(raw.get("expanded")),
        selected=raw.get("selected") if raw.get("selected") is None else bool(raw.get("selected")),
        readonly=bool(raw.get("readonly", False)),
        busy=bool(raw.get("busy", False)),
        occluded=bool(raw.get("occluded", False)),
    )


def build_browser_action_frame(
    nodes: list[dict[str, Any]],
    *,
    url: str = "",
    title: str = "",
    page_id: str | None = None,
    frame_id: str | None = None,
    timestamp_ms: float | None = None,
    meta: dict[str, Any] | None = None,
) -> ActionFrame:
    """Build an ActionFrame from DOM/a11y/CDP identity nodes.

    Each input node may include: role, name, value, visible, state, geometry,
    and identity keys (dom_id, cdp_backend_node_id, aria_id, tag). Selectors and
    freeform JS are ignored — they never enter the frame as actionable payloads.
    """
    ts = time.time() * 1000.0 if timestamp_ms is None else timestamp_ms
    identity = page_id or url or title or "browser"
    out_nodes: list[ActionNode] = []
    focus_id: str | None = None
    for index, raw in enumerate(nodes):
        if not isinstance(raw, dict):
            continue
        role = str(raw.get("role") or raw.get("control_type") or "generic").strip() or "generic"
        name = str(raw.get("name") or raw.get("accessible_name") or raw.get("label") or "").strip()
        value = str(raw.get("value") or raw.get("text") or "")
        visible = bool(raw.get("visible", True))
        state = _state_from(raw.get("state") if isinstance(raw.get("state"), dict) else raw)
        geometry = _geometry_from(raw.get("geometry") if isinstance(raw.get("geometry"), dict) else raw)
        target_id = new_target_id(index)
        backend_ref = {
            "kind": "browser",
            "dom_id": str(raw.get("dom_id") or raw.get("id") or ""),
            "cdp_backend_node_id": raw.get("cdp_backend_node_id"),
            "aria_id": str(raw.get("aria_id") or ""),
            "tag": str(raw.get("tag") or ""),
            "role": role,
            "name": name,
        }
        # Strip forbidden fast-path keys if a caller accidentally passed them.
        for key in ("selector", "css", "xpath", "script", "js", "javascript"):
            backend_ref.pop(key, None)
        node = ActionNode(
            target_id=target_id,
            role=role,
            name=name,
            value=value,
            state=state,
            geometry=geometry,
            visible=visible,
            supported_operations=_ops_for_role(role),
            backend_ref=backend_ref,
        )
        out_nodes.append(node)
        if state.focused:
            focus_id = target_id

    return ActionFrame(
        frame_id=frame_id or new_frame_id(),
        surface=SurfaceKind.BROWSER,
        app_or_page_id=str(identity),
        timestamp_ms=ts,
        nodes=out_nodes,
        focus_target_id=focus_id,
        url_or_title=url or title,
        meta={"title": title, "url": url, **(meta or {})},
    )


def build_desktop_action_frame(
    controls: list[Any],
    *,
    app_id: str = "",
    window_title: str = "",
    frame_id: str | None = None,
    timestamp_ms: float | None = None,
    meta: dict[str, Any] | None = None,
) -> ActionFrame:
    """Build an ActionFrame from native accessibility / UI Automation controls.

    Accepts ``UiControl``-like objects or dicts with name/automation_id/control_type.
    """
    ts = time.time() * 1000.0 if timestamp_ms is None else timestamp_ms
    identity = app_id or window_title or "desktop"
    out_nodes: list[ActionNode] = []
    focus_id: str | None = None
    for index, item in enumerate(controls):
        if isinstance(item, dict):
            name = str(item.get("name") or item.get("automation_id") or "").strip()
            auto_id = str(item.get("automation_id") or "")
            ctype = str(item.get("control_type") or item.get("role") or "").strip()
            enabled = bool(item.get("enabled", True))
            value = str(item.get("value") or "")
            visible = bool(item.get("visible", True))
            focused = bool(item.get("focused", False))
            geometry = _geometry_from(item.get("geometry") if isinstance(item.get("geometry"), dict) else item)
            handle = None
        else:
            name = str(getattr(item, "name", "") or "").strip()
            auto_id = str(getattr(item, "automation_id", "") or "")
            ctype = str(getattr(item, "control_type", "") or "").strip()
            enabled = bool(getattr(item, "enabled", True))
            value = str(getattr(item, "value", "") or "")
            visible = bool(getattr(item, "visible", True))
            focused = bool(getattr(item, "focused", False))
            geo_raw = getattr(item, "geometry", None)
            geometry = _geometry_from(geo_raw if isinstance(geo_raw, dict) else None)
            handle = getattr(item, "handle", None)
        if not name and not auto_id:
            continue
        role = ctype.lower() or "generic"
        # Map common UIA types onto semantic roles used by _ROLE_OPS.
        role_map = {
            "button": "button",
            "edit": "edit",
            "document": "document",
            "menuitem": "menuitem",
            "checkbox": "checkbox",
            "radiobutton": "radio",
            "hyperlink": "link",
            "tabitem": "tab",
            "listitem": "option",
            "combobox": "combobox",
            "slider": "slider",
            "window": "window",
        }
        role = role_map.get(role.replace(" ", ""), role)
        target_id = new_target_id(index)
        state = NodeState(enabled=enabled, focused=focused)
        backend_ref: dict[str, Any] = {
            "kind": "desktop",
            "automation_id": auto_id,
            "control_type": ctype,
            "name": name,
        }
        # Keep opaque handle for local executor only — never serialized to models.
        if handle is not None:
            backend_ref["_handle"] = handle
        node = ActionNode(
            target_id=target_id,
            role=role,
            name=name or auto_id,
            value=value,
            state=state,
            geometry=geometry,
            visible=visible,
            supported_operations=_ops_for_role(role),
            backend_ref=backend_ref,
        )
        out_nodes.append(node)
        if focused:
            focus_id = target_id

    return ActionFrame(
        frame_id=frame_id or new_frame_id(),
        surface=SurfaceKind.DESKTOP,
        app_or_page_id=str(identity),
        timestamp_ms=ts,
        nodes=out_nodes,
        focus_target_id=focus_id,
        url_or_title=window_title,
        meta={"window_title": window_title, "app_id": app_id, **(meta or {})},
    )


async def snapshot_browser_page(page: Any, *, max_nodes: int = 80) -> ActionFrame:
    """Collect actionable a11y nodes from a Playwright page via accessibility snapshot.

    Prefer role/name identity. Does not capture CSS selectors for the model path.
    """
    url = ""
    title = ""
    try:
        url = str(page.url or "")
    except Exception:
        url = ""
    try:
        title = str(await page.title())
    except Exception:
        title = ""

    nodes: list[dict[str, Any]] = []
    try:
        # Playwright accessibility snapshot is role/name based.
        snap = await page.accessibility.snapshot(interesting_only=True)
    except Exception:
        snap = None

    def walk(node: dict[str, Any] | None) -> None:
        if not isinstance(node, dict) or len(nodes) >= max_nodes:
            return
        role = str(node.get("role") or "")
        name = str(node.get("name") or "")
        if role and (name or role in {"textbox", "searchbox", "checkbox", "radio", "combobox"}):
            nodes.append(
                {
                    "role": role,
                    "name": name,
                    "value": str(node.get("value") or ""),
                    "visible": True,
                    "enabled": not bool(node.get("disabled", False)),
                    "focused": bool(node.get("focused", False)),
                    "checked": node.get("checked"),
                    "dom_id": str(node.get("id") or ""),
                    "tag": "",
                }
            )
        for child in node.get("children") or []:
            walk(child if isinstance(child, dict) else None)

    if isinstance(snap, dict):
        walk(snap)

    return build_browser_action_frame(
        nodes,
        url=url,
        title=title,
        page_id=url or title,
        meta={"source": "playwright_accessibility"},
    )
