"""Frame freshness, target integrity, and postcondition verification."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any
import time

from .schema import ActionFrame, ActionNode, Operation


# Default max age for an ActionFrame before execution is refused.
DEFAULT_MAX_AGE_MS = 2500.0


@dataclass(frozen=True)
class FreshnessCheck:
    ok: bool
    reason: str = ""


@dataclass(frozen=True)
class PostconditionResult:
    ok: bool
    reason: str = ""
    observed: dict[str, Any] | None = None


def check_frame_freshness(
    frame: ActionFrame,
    *,
    expected_frame_id: str | None = None,
    max_age_ms: float = DEFAULT_MAX_AGE_MS,
    now_ms: float | None = None,
    expected_app_or_page_id: str | None = None,
) -> FreshnessCheck:
    """Reject stale or swapped frames before any mutating action."""
    if expected_frame_id and frame.frame_id != expected_frame_id:
        return FreshnessCheck(False, f"frame_id mismatch: got {frame.frame_id}, expected {expected_frame_id}")
    age = frame.age_ms(now_ms)
    if age > max_age_ms:
        return FreshnessCheck(False, f"stale frame: age_ms={age:.0f} exceeds max_age_ms={max_age_ms:.0f}")
    if expected_app_or_page_id and frame.app_or_page_id != expected_app_or_page_id:
        return FreshnessCheck(
            False,
            f"app/page identity changed: got {frame.app_or_page_id!r}, expected {expected_app_or_page_id!r}",
        )
    return FreshnessCheck(True)


def resolve_target(
    frame: ActionFrame,
    target_id: str | None,
    *,
    require_enabled: bool = True,
    require_visible: bool = True,
) -> tuple[ActionNode | None, str]:
    """Resolve target_id against the current frame only — never invent nodes."""
    if not target_id:
        return None, "missing target_id"
    node = frame.node_by_id(target_id)
    if node is None:
        return None, f"target_id {target_id!r} not in current frame"
    if require_visible and not node.visible:
        return None, f"target {target_id} is not visible"
    if require_enabled and not node.state.enabled:
        return None, f"target {target_id} is disabled"
    if node.state.occluded:
        return None, f"target {target_id} is occluded"
    return node, "ok"


def target_changed(prior: ActionNode, current: ActionNode | None) -> str | None:
    """Detect fingerprint drift between observe and execute."""
    if current is None:
        return "target disappeared before execution"
    if prior.fingerprint and current.fingerprint and prior.fingerprint != current.fingerprint:
        return (
            f"target fingerprint changed: {prior.fingerprint!r} -> {current.fingerprint!r}"
        )
    if prior.role != current.role or prior.name != current.name:
        return f"target identity changed: {prior.role}/{prior.name} -> {current.role}/{current.name}"
    return None


def verify_postcondition(
    operation: Operation,
    *,
    prior_node: ActionNode | None,
    post_frame: ActionFrame,
    target_id: str | None,
    typed_text: str | None = None,
) -> PostconditionResult:
    """Check expected UI effects after a mutating action."""
    if operation in {Operation.DONE, Operation.BLOCK}:
        return PostconditionResult(True, "terminal — no mutate")

    if target_id is None:
        return PostconditionResult(False, "mutating operation missing target_id")

    post = post_frame.node_by_id(target_id)
    # Prefer fingerprint match when target_id may have been renumbered.
    if post is None and prior_node is not None:
        for candidate in post_frame.nodes:
            if candidate.fingerprint == prior_node.fingerprint:
                post = candidate
                break

    if operation == Operation.CLICK:
        # Click succeeded if frame advanced (url/title) or node still present and enabled.
        if post_frame.url_or_title and prior_node is not None:
            # Soft success: page identity may change after navigation click.
            return PostconditionResult(
                True,
                "click accepted — post frame observed",
                observed={"url_or_title": post_frame.url_or_title},
            )
        if post is None:
            # Control may have been removed by the click (dialog closed) — treat as ok.
            return PostconditionResult(True, "click target gone — likely consumed")
        return PostconditionResult(True, "click target still present", observed=post.as_dict())

    if operation == Operation.TYPE_TEXT:
        if post is None:
            return PostconditionResult(False, "TYPE_TEXT target missing after type")
        if typed_text is not None and typed_text and typed_text not in (post.value or ""):
            # Some controls don't echo value into a11y immediately — require value match when present.
            if post.value:
                return PostconditionResult(
                    False,
                    f"typed text not reflected in value (got {post.value!r})",
                    observed=post.as_dict(),
                )
        return PostconditionResult(True, "TYPE_TEXT postcondition ok", observed=post.as_dict())

    if operation == Operation.CLEAR:
        if post is None:
            return PostconditionResult(False, "CLEAR target missing")
        if post.value:
            return PostconditionResult(False, f"CLEAR left residual value {post.value!r}", observed=post.as_dict())
        return PostconditionResult(True, "cleared", observed=post.as_dict())

    if operation == Operation.TOGGLE:
        if post is None or prior_node is None:
            return PostconditionResult(False, "TOGGLE missing prior/post node")
        if prior_node.state.checked is not None and post.state.checked is not None:
            if prior_node.state.checked == post.state.checked:
                return PostconditionResult(False, "TOGGLE did not flip checked state", observed=post.as_dict())
        return PostconditionResult(True, "toggle observed", observed=post.as_dict())

    if operation == Operation.SELECT:
        if post is None:
            return PostconditionResult(False, "SELECT target missing")
        if post.state.selected is False:
            return PostconditionResult(False, "SELECT left selected=false", observed=post.as_dict())
        return PostconditionResult(True, "select observed", observed=post.as_dict())

    if operation == Operation.FOCUS:
        if post is None:
            return PostconditionResult(False, "FOCUS target missing")
        if not post.state.focused and post_frame.focus_target_id not in {None, target_id, post.target_id}:
            return PostconditionResult(False, "FOCUS did not move focus", observed=post.as_dict())
        return PostconditionResult(True, "focus ok", observed=post.as_dict())

    if operation == Operation.PRESS_KEY:
        return PostconditionResult(True, "key press accepted — post frame observed")

    if operation == Operation.SCROLL_INTO_VIEW:
        if post is None:
            return PostconditionResult(False, "scroll target missing")
        if not post.visible:
            return PostconditionResult(False, "scroll target still not visible", observed=post.as_dict())
        return PostconditionResult(True, "scrolled into view", observed=post.as_dict())

    return PostconditionResult(False, f"no postcondition handler for {operation}")


def now_ms() -> float:
    return time.time() * 1000.0
