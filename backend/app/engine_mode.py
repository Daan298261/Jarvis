"""Owner-selected generation and structured-decision lanes (RFC-0244)."""

from contextlib import contextmanager
from contextvars import ContextVar

from .config import AppSettings

_REQUEST_MODE: ContextVar[str | None] = ContextVar("engine_mode", default=None)


@contextmanager
def engine_mode_scope(settings: AppSettings | None):
    """Carry the caller's snapshot through the bounded decision without disk I/O."""
    # Without a settings snapshot, only deterministic rules are safe to enable.
    token = _REQUEST_MODE.set(getattr(settings, "engine_mode", "_rules_only") if settings is not None else "_rules_only")
    try:
        yield
    finally:
        _REQUEST_MODE.reset(token)


def engine_mode(settings: AppSettings | None = None) -> str:
    if settings is not None:
        return getattr(settings, "engine_mode", "hybrid")
    scoped = _REQUEST_MODE.get()
    if scoped is not None:
        return scoped
    from .config import load_settings
    return getattr(settings or load_settings(), "engine_mode", "hybrid")


def model_enabled(settings: AppSettings | None = None) -> bool:
    return engine_mode(settings) not in {"reflex_only", "_rules_only"}


def decision_engines_enabled(settings: AppSettings | None = None) -> bool:
    return engine_mode(settings) not in {"model_only", "_rules_only"}


class ModelDisabledError(RuntimeError):
    pass


def require_model(settings: AppSettings | None = None) -> None:
    if not model_enabled(settings):
        raise ModelDisabledError("JEV/Laya only is active. Select Model + JEV/Laya or Model only to use a generative model.")


async def reflex_only_reply(text: str, settings: AppSettings) -> tuple[str, str]:
    from .agent.planning import route_request
    from .agent.request_routing import evaluate_request_route
    from .decision.owner_turn import is_explicit_action

    turn = await evaluate_request_route(text, route_request(text), settings=settings,
                                       decision_tier=settings.decision.tier)
    source = str(getattr(turn.reflex, "source", "rules") or "rules")
    if turn.reply_shape == "literal" and turn.literal_text and not is_explicit_action(text):
        return turn.literal_text, source
    if turn.reply_shape == "social":
        return "Hello. JEV/Laya only is active; generative replies are off.", source
    if turn.reply_shape == "clarify":
        return "What structured decision would you like me to make? Generative replies are off.", source
    return (
        "JEV/Laya only is active. This request needs a generative model; no requested work was run. "
        "Choose Model + JEV/Laya or Model only to continue.", source,
    )
