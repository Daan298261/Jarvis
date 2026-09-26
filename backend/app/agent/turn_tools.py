"""Keep the advertised tool list tractable for local 9B models."""

from __future__ import annotations

from typing import Any

from .tool_retrieval import score_tool


def select_turn_schemas(
    schemas: list[dict[str, Any]] | None,
    *,
    model_family: str,
    prompt: str,
    limit: int = 5,
) -> list[dict[str, Any]] | None:
    if not schemas or "9b" not in model_family.lower() or len(schemas) <= limit:
        return schemas
    named = [(str(item.get("function", {}).get("name") or ""), item) for item in schemas]
    escapes = [item for name, item in named if name in {"request_capability", "request_tools"}]
    candidates = [(name, item) for name, item in named if name not in {"request_capability", "request_tools"}]
    ranked = sorted(
        enumerate(candidates),
        key=lambda pair: (-score_tool(prompt, pair[1][0], ""), pair[0]),
    )
    slots = max(1, limit - len(escapes))
    chosen = {name for _, (name, _) in ranked[:slots]}
    selected = [item for name, item in named if name in chosen]
    selected.extend(escapes)
    return selected
