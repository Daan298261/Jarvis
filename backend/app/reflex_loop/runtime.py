"""Runtime entry points used by browser/computer-use tools and API (RFC-0172)."""

from __future__ import annotations

from typing import Any, Callable
from urllib.parse import urljoin, urlparse

from ..policy.computer_permissions import evaluate_permission
from ..tools.base import ToolResult
from .adapters import build_browser_action_frame, build_desktop_action_frame, snapshot_browser_page
from .benchmark import run_benchmark_suite
from .executor import ReflexLoopExecutor
from .reflex_client import get_reflex_decide_client, set_reflex_decide_client
from .sandbox import DEFAULT_SANDBOX
from .schema import ActionFrame, ActionNode, Operation, ReflexDecision, SurfaceKind

_HTTP_SCHEMES = {"http", "https"}


def permission_gate_for_surface(surface: SurfaceKind) -> Callable[[ReflexDecision, ActionFrame], str | None]:
    """Map computer/network permissions — kept outside the decision model."""

    def _gate(decision: ReflexDecision, frame: ActionFrame) -> str | None:
        if decision.operation in {Operation.DONE, Operation.BLOCK}:
            return None
        if surface == SurfaceKind.DESKTOP:
            decision_perm = evaluate_permission("computer.this_device")
            if decision_perm.status == "deny":
                return decision_perm.reason
            # ask is allowed to proceed only when an upstream approval already granted;
            # here we surface ask as a soft block so the loop fails closed honestly.
            if decision_perm.status == "ask":
                return (
                    "computer.this_device requires owner approval before reflex execute "
                    f"({decision_perm.reason})"
                )
            return None
        # Browser surface uses network.local for RFC1918/.local pages, otherwise internet.
        from ..policy.computer_permissions import looks_local_network

        url = str(frame.url_or_title or frame.app_or_page_id or "")
        perm_id = "network.local" if looks_local_network({"url": url}) else "network.internet"
        net = evaluate_permission(perm_id)
        if net.status == "deny":
            return net.reason
        if net.status == "ask":
            return f"{perm_id} requires owner approval before reflex browse ({net.reason})"
        return None

    return _gate


def click_navigation_url(node: ActionNode, current: str) -> str:
    """Resolve a clicked node's href against the current page URL. Empty if none."""
    href = str((node.backend_ref or {}).get("href") or "").strip()
    if not href:
        return ""
    return urljoin(current or "", href).strip()


def _http_page_url(url: str) -> str:
    cleaned = (url or "").strip()
    if not cleaned:
        return ""
    scheme = (urlparse(cleaned).scheme or "").lower()
    if scheme and scheme not in _HTTP_SCHEMES:
        return ""
    return cleaned


async def run_reflex_with_inmemory_world(
    goal: str,
    *,
    surface: SurfaceKind,
    nodes: list[dict[str, Any]],
    identity: str = "",
    title: str = "",
    decide_client: Any | None = None,
    text_generator: Any | None = None,
    enforce_permissions: bool = False,
) -> ToolResult:
    """Execute one reflex loop against a provided node list (tests / dry-run)."""
    frame_holder: dict[str, ActionFrame] = {}
    world = {"identity": identity}

    def _build() -> ActionFrame:
        page = world["identity"]
        if surface == SurfaceKind.BROWSER:
            return build_browser_action_frame(nodes, url=page, title=title, page_id=page)
        return build_desktop_action_frame(nodes, app_id=page, window_title=title)

    async def observe() -> ActionFrame:
        frame = _build()
        frame_holder["frame"] = frame
        return frame

    async def act(operation: Operation, node: ActionNode, payload: dict[str, Any]) -> dict[str, Any]:
        if operation == Operation.TYPE_TEXT:
            for item in nodes:
                name = str(item.get("name") or "")
                if name == node.name or str(item.get("dom_id") or "") == str(
                    node.backend_ref.get("dom_id") or ""
                ):
                    item["value"] = str(payload.get("text") or "")
                    break
        elif operation == Operation.CLICK:
            # Mark click in meta for callers; node may disappear in richer worlds.
            item_meta = node.backend_ref.setdefault("_clicks", 0)
            node.backend_ref["_clicks"] = int(item_meta) + 1
            if surface == SurfaceKind.BROWSER:
                dest = click_navigation_url(node, world["identity"])
                if dest:
                    if enforce_permissions:
                        from ..tools.browser import gate_browser_url

                        blocked = gate_browser_url(dest, "open")
                        if blocked:
                            raise PermissionError(blocked)
                    page = _http_page_url(dest)
                    if page:
                        world["identity"] = page
        return {"protocol_calls": 1, "ok": True}

    client = decide_client or get_reflex_decide_client()
    executor = ReflexLoopExecutor(
        observe=observe,
        act=act,
        decide_client=client,
        text_generator=text_generator,
        sandbox=DEFAULT_SANDBOX,
        permission_gate=permission_gate_for_surface(surface) if enforce_permissions else None,
    )
    result = await executor.run(goal)
    data = result.as_dict()
    data["surface"] = surface.value
    # The world here is the caller's node list: nothing on screen was touched.
    data["simulated"] = True
    if surface == SurfaceKind.BROWSER:
        data["url"] = world["identity"]
    if result.success:
        return ToolResult(
            True,
            f"DRY RUN — no UI actions were executed on this device. Planned outcome: {result.reason or 'done'}",
            data=data,
        )
    return ToolResult(False, result.reason, data=data, error=result.reason or "reflex loop failed")


_TYPE_KEYS_SPECIAL = set("{}+^%~()")


def _escape_type_keys(text: str) -> str:
    """pywinauto type_keys treats +^%~(){} as modifiers/groups; brace them to type literally."""
    return "".join(f"{{{ch}}}" if ch in _TYPE_KEYS_SPECIAL else ch for ch in text)


def _live_desktop_act(operation: Operation, node: ActionNode, payload: dict[str, Any]) -> dict[str, Any]:
    handle = node.backend_ref.get("_handle")
    if handle is None:
        raise RuntimeError(f"target {node.target_id} has no live UI Automation handle")
    if operation == Operation.CLICK:
        handle.click_input()
    elif operation == Operation.FOCUS:
        handle.set_focus()
    elif operation == Operation.TYPE_TEXT:
        text = str(payload.get("text") or "")
        try:
            handle.set_focus()
        except Exception:  # noqa: BLE001 — focus is best effort before typing
            pass
        if hasattr(handle, "set_edit_text"):
            handle.set_edit_text(text)
        else:
            handle.type_keys(_escape_type_keys(text), with_spaces=True)
    elif operation == Operation.CLEAR:
        if not hasattr(handle, "set_edit_text"):
            raise RuntimeError(f"target {node.target_id} does not support CLEAR")
        handle.set_edit_text("")
    elif operation == Operation.TOGGLE:
        (handle.toggle if hasattr(handle, "toggle") else handle.click_input)()
    elif operation == Operation.SELECT:
        (handle.select if hasattr(handle, "select") else handle.click_input)()
    else:
        raise RuntimeError(f"{operation.value} is not supported on the live desktop fast path")
    return {"protocol_calls": 1, "ok": True}


async def run_reflex_live_desktop(
    goal: str,
    *,
    app: str = "",
    decide_client: Any | None = None,
    text_generator: Any | None = None,
) -> ToolResult:
    """Execute the Reflex loop against the live Windows UI Automation tree."""
    from ..tools.desktop import _collect_controls, _find_window, windows_ui_available

    if not windows_ui_available():
        return ToolResult(False, "", error="Live reflex computer-use requires Windows UI Automation")
    try:
        from pywinauto import Desktop
    except Exception as exc:  # noqa: BLE001
        return ToolResult(False, "", error=f"pywinauto is unavailable: {exc}")
    desktop = Desktop(backend="uia")

    def observe() -> ActionFrame:
        window = _find_window(desktop, app or None)
        title = str(window.window_text() or "")
        return build_desktop_action_frame(
            _collect_controls(window)[:80],
            app_id=app or title,
            window_title=title,
        )

    executor = ReflexLoopExecutor(
        observe=observe,
        act=_live_desktop_act,
        decide_client=decide_client or get_reflex_decide_client(),
        text_generator=text_generator,
        sandbox=DEFAULT_SANDBOX,
        permission_gate=permission_gate_for_surface(SurfaceKind.DESKTOP),
    )
    try:
        result = await executor.run(goal)
    except Exception as exc:  # noqa: BLE001 — UIA errors must surface as a failed step
        return ToolResult(False, "", error=f"live reflex loop failed: {exc}")
    data = result.as_dict()
    data["surface"] = SurfaceKind.DESKTOP.value
    data["simulated"] = False
    if result.success:
        return ToolResult(True, result.reason or "reflex loop done", data=data)
    return ToolResult(False, result.reason, data=data, error=result.reason or "reflex loop failed")


async def action_frame_from_desktop_controls(
    controls: list[Any],
    *,
    app_id: str = "",
    window_title: str = "",
) -> ActionFrame:
    return build_desktop_action_frame(controls, app_id=app_id, window_title=window_title)


async def action_frame_from_browser_page(page: Any) -> ActionFrame:
    return await snapshot_browser_page(page)


async def run_reflex_benchmark() -> dict[str, Any]:
    return await run_benchmark_suite()


# Re-export injection helpers for tests.
__all__ = [
    "action_frame_from_browser_page",
    "action_frame_from_desktop_controls",
    "click_navigation_url",
    "permission_gate_for_surface",
    "run_reflex_benchmark",
    "run_reflex_live_desktop",
    "run_reflex_with_inmemory_world",
    "set_reflex_decide_client",
]
