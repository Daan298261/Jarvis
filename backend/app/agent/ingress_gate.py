"""RFC-0122 ingress size-gate — heuristic first, front_responder on metadata + preview only."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Any, Awaitable, Callable

from ..config import AppSettings, load_settings
from ..inference.prompt_budget import estimate_text_tokens
from ..memory.ingress_spill import (
    preview_for_gate,
    spill_metadata,
    spill_metadata_dict,
    store_ingress_blob,
    maybe_mirror_to_vault,
)
from ..providers.base import ChatMessage
from .planning import is_plain_conversation

# Hard ceilings — 50 KB pastes must never wait on a model to notice.
HEURISTIC_BIG_CHARS = 12_000
HEURISTIC_BIG_TOKENS = 3_200
AMBIGUOUS_CHAR_BAND = (4_000, HEURISTIC_BIG_CHARS)

PASTE_MARKERS = re.compile(
    r"(```[\s\S]*?```[\s\S]*?```)|(\{\s*\"[\s\S]{2000,})|(\n\s+at\s+[\w./]+\()",
    re.MULTILINE,
)
_ACTION_TOOL_RE = re.compile(
    r"\b(run|execute|write|create|delete|install|deploy|refactor|debug|fix|open\s+file|git\s+)",
    re.I,
)
_FACTUAL_QA_RE = re.compile(
    r"(?i)\b(what|which|how many|do i need)\b.{0,80}\b(port|ports|forward|companion|router)\b",
)

SAFE_LARGE_PASTE_SPEECH = (
    "That's a large paste. I've stored it and I'm working through it."
)

INGRESS_CLASSIFY_SYSTEM = """You classify owner ingress for size and tool need.
Return ONLY one JSON object with keys:
size_class (small|big), needs_tools (boolean), complexity_hint (integer 1-5),
front_action (final_basic|ack_continue|handoff_notice).
You only see metadata and short previews — never the full payload.
needs_tools is false for plain factual Q&A (ports, docs, weather) without execution requests."""

FrontClassifyFn = Callable[..., Awaitable[dict[str, Any] | None]]


@dataclass
class IngressGateResult:
    size_class: str
    needs_tools: bool
    complexity_hint: int
    front_action: str
    blob_id: str = ""
    byte_size: int = 0
    token_estimate: int = 0
    user_ask: str = ""
    preview_chars: int = 0
    vault_mirrored: bool = False

    def as_dict(self) -> dict[str, Any]:
        return {
            "size_class": self.size_class,
            "needs_tools": self.needs_tools,
            "complexity_hint": self.complexity_hint,
            "front_action": self.front_action,
            "blob_id": self.blob_id,
            "byte_size": self.byte_size,
            "token_estimate": self.token_estimate,
        }


def heuristic_size_class(text: str) -> str | None:
    """Return small|big when certain; None when ambiguous."""
    raw = text or ""
    chars = len(raw)
    tokens = estimate_text_tokens(raw)
    if chars >= HEURISTIC_BIG_CHARS or tokens >= HEURISTIC_BIG_TOKENS:
        return "big"
    if PASTE_MARKERS.search(raw) and chars > 2_500:
        return "big"
    if chars < AMBIGUOUS_CHAR_BAND[0] and tokens < 1_200:
        return "small"
    return None


def heuristic_needs_tools(text: str, task_class: str) -> bool | None:
    if _ACTION_TOOL_RE.search(text or ""):
        return True
    if _FACTUAL_QA_RE.search(text or ""):
        return False
    if is_plain_conversation(text):
        return False
    if (task_class or "").strip().lower() == "conversation":
        return False
    if (task_class or "").strip().lower() in {"filesystem", "shell", "software engineering", "browser automation"}:
        return True
    return None


def _parse_front_json(raw: str) -> dict[str, Any] | None:
    text = (raw or "").strip()
    if not text:
        return None
    start = text.find("{")
    end = text.rfind("}")
    if start < 0 or end <= start:
        return None
    try:
        payload = json.loads(text[start : end + 1])
    except json.JSONDecodeError:
        return None
    return payload if isinstance(payload, dict) else None


async def classify_with_front_responder(
    *,
    metadata: dict[str, Any],
    preview: str,
    user_ask: str,
    settings: AppSettings | None = None,
    classify_fn: FrontClassifyFn | None = None,
) -> dict[str, Any] | None:
    """Small model sees metadata + capped preview only."""
    if classify_fn is not None:
        return await classify_fn(metadata=metadata, preview=preview, user_ask=user_ask)

    from .front_responder import front_lane_config, front_provider

    app = settings or load_settings()
    if not app.front_responder.enabled:
        return None
    provider = front_provider(app)
    if provider is None or not hasattr(provider, "chat"):
        return None
    cfg = front_lane_config(app)
    user_block = (
        f"metadata={json.dumps(metadata, ensure_ascii=False)}\n"
        f"preview={preview[:480]}\n"
        f"user_ask={user_ask[:400]}"
    )
    messages = [
        ChatMessage(role="system", content=INGRESS_CLASSIFY_SYSTEM),
        ChatMessage(role="user", content=user_block),
    ]
    try:
        result = await provider.chat(
            messages,
            tools=None,
            temperature=0.0,
            max_tokens=96,
            thinking=False,
        )
    except Exception:
        return None
    content = getattr(result, "content", "") or ""
    return _parse_front_json(content)


def _coerce_gate(payload: dict[str, Any] | None, *, fallback_size: str, fallback_tools: bool) -> IngressGateResult:
    data = payload or {}
    size = str(data.get("size_class") or fallback_size).lower()
    if size not in {"small", "big"}:
        size = fallback_size
    needs_tools = bool(data.get("needs_tools")) if "needs_tools" in data else fallback_tools
    try:
        complexity = int(data.get("complexity_hint") or 1)
    except (TypeError, ValueError):
        complexity = 1
    complexity = max(1, min(5, complexity))
    front_action = str(data.get("front_action") or ("ack_continue" if size == "big" else "final_basic"))
    if front_action not in {"final_basic", "ack_continue", "handoff_notice"}:
        front_action = "ack_continue" if size == "big" else "final_basic"
    return IngressGateResult(
        size_class=size,
        needs_tools=needs_tools,
        complexity_hint=complexity,
        front_action=front_action,
    )


async def run_ingress_gate(
    *,
    user_text: str,
    task_class: str,
    task_id: str,
    conversation_id: str = "",
    settings: AppSettings | None = None,
    classify_fn: FrontClassifyFn | None = None,
    persist_small: bool = False,
) -> IngressGateResult:
    text = (user_text or "").strip()
    ask = text.splitlines()[0][:400] if text else ""
    size_hint = heuristic_size_class(text)
    tools_hint = heuristic_needs_tools(text, task_class)

    blob_id = ""
    byte_size = len(text.encode("utf-8"))
    token_estimate = estimate_text_tokens(text)
    preview = preview_for_gate(None, text)
    metadata: dict[str, Any] = {
        "byte_size": byte_size,
        "token_estimate": token_estimate,
        "chunk_count": 1,
    }

    if size_hint == "big" or (size_hint is None and byte_size > HEURISTIC_BIG_CHARS):
        row = await store_ingress_blob(body=text, conversation_id=conversation_id, task_id=task_id)
        blob_id = row.root_id or row.id
        metadata = await spill_metadata(blob_id)
        preview = preview_for_gate(row, text)
        size_hint = "big"

    if persist_small and not blob_id and text:
        row = await store_ingress_blob(body=text, conversation_id=conversation_id, task_id=task_id)
        blob_id = row.root_id or row.id
        metadata = spill_metadata_dict(row)

    fallback_tools = tools_hint if tools_hint is not None else True
    fallback_size = size_hint or "small"

    model_payload: dict[str, Any] | None = None
    if size_hint is None or tools_hint is None:
        model_payload = await classify_with_front_responder(
            metadata=metadata,
            preview=preview,
            user_ask=ask,
            settings=settings,
            classify_fn=classify_fn,
        )

    gate = _coerce_gate(
        model_payload,
        fallback_size=fallback_size,
        fallback_tools=fallback_tools if tools_hint is None else bool(tools_hint),
    )
    if size_hint == "big":
        gate.size_class = "big"
        gate.front_action = gate.front_action if gate.front_action != "final_basic" else "ack_continue"
    if tools_hint is not None:
        gate.needs_tools = bool(tools_hint)

    if gate.size_class == "big" and not blob_id and text:
        row = await store_ingress_blob(body=text, conversation_id=conversation_id, task_id=task_id)
        blob_id = row.root_id or row.id
        metadata = await spill_metadata(blob_id)
        preview = preview_for_gate(row, text)

    gate.blob_id = blob_id
    gate.byte_size = int(metadata.get("byte_size") or byte_size)
    gate.token_estimate = int(metadata.get("token_estimate") or token_estimate)
    gate.user_ask = ask
    gate.preview_chars = len(preview)

    if gate.size_class == "big" and blob_id:
        gate.vault_mirrored = await maybe_mirror_to_vault(blob_id, ask, preview)

    return gate
