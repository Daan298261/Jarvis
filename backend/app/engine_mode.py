"""Owner-selected generation and structured-decision lanes (RFC-0244)."""

from .config import AppSettings


def engine_mode(settings: AppSettings | None = None) -> str:
    from .config import load_settings
    return getattr(settings or load_settings(), "engine_mode", "hybrid")


def model_enabled(settings: AppSettings | None = None) -> bool:
    return engine_mode(settings) != "reflex_only"


def decision_engines_enabled(settings: AppSettings | None = None) -> bool:
    return engine_mode(settings) != "model_only"


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
