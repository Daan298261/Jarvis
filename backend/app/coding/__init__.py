"""Software-development worker operations: cost, model catalog, evidence-based routing."""

from .catalog import CURSOR_MODEL_CATALOG, probe_cursor_models, resolve_model
from .routing import estimate_complexity, recommend_worker, recommendation_prompt_block
from .usage import estimate_cost_usd, record_usage, usage_summary

__all__ = [
    "CURSOR_MODEL_CATALOG",
    "estimate_complexity",
    "estimate_cost_usd",
    "probe_cursor_models",
    "recommend_worker",
    "recommendation_prompt_block",
    "record_usage",
    "resolve_model",
    "usage_summary",
]
