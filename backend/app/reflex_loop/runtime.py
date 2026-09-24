"""Runtime entry points used by browser/computer-use tools and API (RFC-0172)."""

from __future__ import annotations

from typing import Any, Callable

from ..policy.computer_permissions import evaluate_permission
from ..tools.base import ToolResult
from .adapters import build_browser_action_frame, build_desktop_action_frame, snapshot_browser_page
from .benchmark import run_benchmark_suite
from .executor import ReflexLoopExecutor
from .reflex_client import get_reflex_decide_client, set_reflex_decide_client
from .sandbox import DEFAULT_SANDBOX
from .schema import ActionFrame, ActionNode, Operation, ReflexDecision, SurfaceKind


def permission_gate_for_surface(surface: SurfaceKind) -> Callable[[ReflexDecision, ActionFrame], str | None]:
    """Map computer/network permissions — kept outside the decision model."""

    def _gate(decision: ReflexDecision, frame: ActionFrame) -> str | None:
        del frame
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
        # Browser surface uses network.internet / network.local depending on URL — soft check.
        net = evaluate_permission("network.internet")
        if net.status == "deny":
            return net.reason
        return None

    return _gate


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

    def _build() -> ActionFrame:
        if surface == SurfaceKind.BROWSER:
            return build_browser_action_frame(nodes, url=identity, title=title, page_id=identity)
        return build_desktop_action_frame(nodes, app_id=identity, window_title=title)

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
    "permission_gate_for_surface",
    "run_reflex_benchmark",
    "run_reflex_with_inmemory_world",
    "set_reflex_decide_client",
]
