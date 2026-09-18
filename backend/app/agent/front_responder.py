"""RFC-0117 tiny front-chat responder lane.

Produces a fast first owner-facing reply with tools and thinking disabled.
The larger router/worker path remains responsible for non-trivial turns.
"""

from __future__ import annotations

import asyncio
import json
import re
import time
from collections.abc import AsyncIterator, Awaitable, Callable
from dataclasses import asdict, dataclass, field
from typing import Any

from ..config import AppSettings, FrontResponderSettings, load_settings
from ..inference.manager import MANAGER
from ..providers.base import ChatMessage, ChatResult
from .planning import MANAGED_TASK, RequestRoute, is_plain_conversation, is_weather_query, route_request

RUNTIME_ROLE = "front_responder"
ANSWER_TIER = 1
FRONT_MAX_TOKENS_MIN = 96
FRONT_MAX_TOKENS_MAX = 160
FRONT_MAX_TOKENS_DEFAULT = 128
DEEPER_RESULT_LABEL = "Deeper result"

FRONT_ACTIONS = frozenset(
    {
        "final_basic",
        "ack_continue",
        "ask_clarification",
        "handoff_notice",
        "silent_skip",
    }
)

SAFE_ACK = "I can start with the short version while I check the details."
SAFE_HANDOFF = "A stronger model is taking this from here."
SAFE_CLARIFY = "Could you clarify what you need?"
SAFE_HELLO = "Hello, sir."

FRONT_SYSTEM = """You are Jarvis speaking with the owner. Runtime role: front_responder. Answer tier: 1.
Reply immediately, naturally, and briefly in a British-inspired operations-assistant register.
Put the useful answer in the first sentence, ideally no more than twelve words.
Default to one to three short sentences. Do not think out loud.
This lane cannot use tools, write code, change files, or verify work.
Do not claim an action succeeded. Do not invent live facts, numbers, scores, weather, or repository state.
Do not mention routing scores, hidden reasoning, or internal model names.
If the hint action is final_basic, answer the greeting or basic chat directly.
If the hint action is ack_continue, acknowledge and say you are checking the details in parallel.
If the hint action is ask_clarification, ask one short clarifying question.
If the hint action is handoff_notice, say a stronger model is taking over.
Never say the work is done. Never describe tool execution.
Return only the spoken reply text, not JSON and not a plan."""

_FAKE_DONE = re.compile(
    r"(?i)\b("
    r"done[,.]?\s+i\s+(?:fixed|did|handled|completed|finished|patched)|"
    r"i(?:'ve| have)\s+(?:fixed|done|completed|finished|patched|installed|deleted)|"
    r"all\s+(?:set|done|fixed)\b|"
    r"successfully\s+(?:fixed|deleted|installed|patched|deployed|completed)"
    r")"
)
_INVENTED_FACTS = re.compile(
    r"(?i)\b("
    r"\d+\s*(?:cve-|failing tests|vulnerabilit)|"
    r"(?:repo|repository|runtime)\s+(?:is|has|contains)\b|"
    r"currently\s+\d+|temperature\s+is\s+\d+|right now it(?:'s| is)\s+\d+"
    r")"
)
_REASONING_LEAK = re.compile(
    r"(?i)(hidden reasoning|routing score|chain of thought|<think>|answer_tier|runtime_role)"
)
_TOOL_CLAIM = re.compile(
    r"(?i)\b(i\s+(?:ran|called|executed|used)\s+(?:the\s+)?(?:tool|command|pytest|nmap|powershell))\b"
)
_VAGUE_PROMPT = re.compile(
    r"(?i)^(do it|fix it|handle it|you know|the thing|this|that|please|go|ok then)\s*[.!?]*$"
)
_TRIVIAL_CHAT = re.compile(
    r"(?i)\b("
    r"hi|hello|hey|yo|thanks|thank you|cheers|bye|goodbye|"
    r"good\s+(?:morning|afternoon|evening|night)|"
    r"how are you|how(?:'s| is) it going|what'?s up|"
    r"tell me a (?:quick )?hello"
    r")\b"
)
_NEEDS_STRONGER = re.compile(
    r"(?i)\b("
    r"refactor|security|hexstrike|vulnerability|cve-|forensic|"
    r"architecture|codebase|implement|deploy|migrate|pytest|"
    r"debug this|source code|pull request"
    r")\b"
)
_LIVE_FACT_HINT = re.compile(
    r"(?i)\b(weather|forecast|news|score|price|stock|latest|right now|currently|cve-)\b"
)

WorkerStream = Callable[[], AsyncIterator[str]]
DeltaCallback = Callable[[str, str], Awaitable[None] | None]

_last_timing: dict[str, Any] = {}
_timings: list[dict[str, Any]] = []


@dataclass
class FrontLaneConfig:
    runtime_role: str = RUNTIME_ROLE
    answer_tier: int = ANSWER_TIER
    tools_enabled: bool = False
    thinking: bool = False
    max_tokens: int = FRONT_MAX_TOKENS_DEFAULT
    temperature: float = 0.25
    timeout_ms: int = 3000
    context_turns: int = 4
    model: str = ""
    speak_immediately: bool = True

    def as_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["tools"] = None
        return payload


@dataclass
class FrontReply:
    action: str
    text: str
    model: str
    first_text_ms: float = 0.0
    complete_ms: float = 0.0
    first_audio_ms: float = 0.0
    skipped: bool = False
    safety_rejected: bool = False
    thinking: bool = False
    tools_enabled: bool = False
    max_tokens: int = FRONT_MAX_TOKENS_DEFAULT
    chunks: list[str] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return {
            "front_action": self.action,
            "text": self.text,
            "front_model": self.model,
            "front_first_text_ms": round(self.first_text_ms, 1),
            "front_complete_ms": round(self.complete_ms, 1),
            "front_first_audio_ms": round(self.first_audio_ms, 1) if self.first_audio_ms else 0.0,
            "skipped": self.skipped,
            "safety_rejected": self.safety_rejected,
            "thinking": self.thinking,
            "tools_enabled": self.tools_enabled,
            "max_tokens": self.max_tokens,
        }


@dataclass
class TwoLaneTiming:
    front_model: str = ""
    front_action: str = ""
    queue_ms: float = 0.0
    router_ms: float = 0.0
    front_first_text_ms: float = 0.0
    front_first_audio_ms: float = 0.0
    front_complete_ms: float = 0.0
    router_complete_ms: float = 0.0
    worker_first_text_ms: float = 0.0
    worker_complete_ms: float = 0.0
    tts_first_audio_ms: float = 0.0

    def as_dict(self) -> dict[str, Any]:
        return {
            "front_model": self.front_model,
            "front_action": self.front_action,
            "queue_ms": round(self.queue_ms, 1),
            "router_ms": round(self.router_ms, 1),
            "front_first_text_ms": round(self.front_first_text_ms, 1),
            "front_first_audio_ms": round(self.front_first_audio_ms, 1),
            "front_complete_ms": round(self.front_complete_ms, 1),
            "router_ms_complete": round(self.router_complete_ms, 1),
            "worker_first_text_ms": round(self.worker_first_text_ms, 1),
            "worker_complete_ms": round(self.worker_complete_ms, 1),
            "tts_first_audio_ms": round(self.tts_first_audio_ms, 1),
        }


def reset_front_responder() -> None:
    global _last_timing, _timings
    _last_timing = {}
    _timings = []


def last_front_timing() -> dict[str, Any]:
    return dict(_last_timing)


def record_front_timing(timing: dict[str, Any]) -> dict[str, Any]:
    global _last_timing, _timings
    payload = dict(timing)
    _last_timing = payload
    _timings.append(payload)
    _timings[:] = _timings[-12:]
    return payload


def front_settings(settings: AppSettings | None = None) -> FrontResponderSettings:
    app = settings or load_settings()
    return getattr(app, "front_responder", FrontResponderSettings())


def clamp_front_max_tokens(value: int | None) -> int:
    try:
        raw = int(value or FRONT_MAX_TOKENS_DEFAULT)
    except (TypeError, ValueError):
        raw = FRONT_MAX_TOKENS_DEFAULT
    return max(FRONT_MAX_TOKENS_MIN, min(FRONT_MAX_TOKENS_MAX, raw))


def front_lane_config(settings: AppSettings | None = None) -> FrontLaneConfig:
    cfg = front_settings(settings)
    return FrontLaneConfig(
        max_tokens=clamp_front_max_tokens(cfg.max_output_tokens),
        temperature=float(cfg.temperature),
        timeout_ms=max(250, int(cfg.timeout_ms or 3000)),
        context_turns=max(0, min(8, int(cfg.context_turns or 4))),
        model=(cfg.model or "").strip(),
        speak_immediately=bool(cfg.speak_immediately),
    )


def resolve_front_model_id(settings: AppSettings | None = None) -> str:
    """Configurable OpenAI-compat id on the existing local/LM Studio endpoint.

    Empty settings use the currently loaded remote_model / advertised alias.
    No vendor model name is hard-coded.
    """
    app = settings or load_settings()
    configured = (app.front_responder.model or "").strip()
    if configured:
        return configured
    advertised = list(getattr(MANAGER.state, "advertised_models", None) or [])
    return MANAGER.provider_model(app, advertised)


def worker_required(action: str) -> bool:
    return action in {"ack_continue", "handoff_notice", "silent_skip"}


def is_unsafe_front_claim(text: str) -> bool:
    sample = (text or "").strip()
    if not sample:
        return False
    return bool(
        _FAKE_DONE.search(sample)
        or _INVENTED_FACTS.search(sample)
        or _REASONING_LEAK.search(sample)
        or _TOOL_CLAIM.search(sample)
    )


def is_safe_front_speech(action: str, text: str) -> bool:
    if action in {"silent_skip", ""}:
        return False
    cleaned = (text or "").strip()
    if not cleaned:
        return False
    if is_unsafe_front_claim(cleaned):
        return False
    return True


def classify_front_action(user_text: str, *, route: RequestRoute | None = None) -> str:
    text = (user_text or "").strip()
    if not text:
        return "silent_skip"
    lowered = text.lower().strip()
    if _VAGUE_PROMPT.match(lowered):
        return "ask_clarification"
    resolved = route or route_request(text)
    if resolved.kind == MANAGED_TASK:
        return "handoff_notice" if _NEEDS_STRONGER.search(lowered) else "ack_continue"
    if is_weather_query(text) or _LIVE_FACT_HINT.search(lowered):
        return "ack_continue"
    if is_plain_conversation(text) and _is_trivial_chat(lowered):
        return "final_basic"
    if is_plain_conversation(text):
        return "ack_continue"
    return "ack_continue"


def fallback_text_for_action(action: str) -> str:
    if action == "final_basic":
        return SAFE_HELLO
    if action == "ask_clarification":
        return SAFE_CLARIFY
    if action == "handoff_notice":
        return SAFE_HANDOFF
    if action == "silent_skip":
        return ""
    return SAFE_ACK


def parse_front_payload(raw: str, *, fallback_action: str) -> tuple[str, str]:
    text = (raw or "").strip()
    action = fallback_action if fallback_action in FRONT_ACTIONS else "ack_continue"
    if not text:
        return action, ""
    blob = _extract_json_object(text)
    if blob:
        parsed_action = str(blob.get("front_action") or blob.get("action") or "").strip()
        parsed_text = str(blob.get("text") or blob.get("reply") or "").strip()
        if parsed_action in FRONT_ACTIONS:
            action = parsed_action
        if parsed_text:
            return action, parsed_text
    return action, text


def enforce_front_safety(action: str, text: str, *, user_text: str, heuristic: str) -> tuple[str, str, bool]:
    cleaned = (text or "").strip()
    resolved = action if action in FRONT_ACTIONS else heuristic
    rejected = False
    if heuristic != "final_basic" and resolved == "final_basic":
        resolved = "ack_continue" if heuristic != "ask_clarification" else heuristic
        rejected = True
    if is_unsafe_front_claim(cleaned):
        rejected = True
        if heuristic == "final_basic" and _is_trivial_chat(user_text.lower()):
            resolved = "final_basic"
            cleaned = SAFE_HELLO
        else:
            resolved = heuristic if heuristic in FRONT_ACTIONS else "ack_continue"
            if resolved == "final_basic":
                resolved = "ack_continue"
            cleaned = fallback_text_for_action(resolved)
    if rejected and not cleaned and resolved != "silent_skip":
        cleaned = fallback_text_for_action(resolved)
    return resolved, cleaned, rejected


def merge_front_and_worker(front_text: str, worker_text: str, action: str) -> str:
    front = (front_text or "").strip()
    worker = (worker_text or "").strip()
    if action == "silent_skip":
        return worker or front
    if action == "final_basic":
        return front or worker
    if action == "ask_clarification" and not worker:
        return front
    if not front:
        return worker
    if not worker:
        return front
    if _substantively_same(front, worker):
        return worker
    if worker.startswith(front):
        return worker
    if DEEPER_RESULT_LABEL.lower() in front.lower():
        return f"{front}\n\n{worker}"
    return f"{front}\n\n{DEEPER_RESULT_LABEL}\n{worker}"


def merge_consecutive_assistant_turns(turns: list[dict[str, Any]]) -> list[dict[str, Any]]:
    merged: list[dict[str, Any]] = []
    for turn in turns:
        role = turn.get("role")
        content = str(turn.get("content") or "").strip()
        if not content:
            continue
        if merged and merged[-1].get("role") == "assistant" and role == "assistant":
            previous = str(merged[-1].get("content") or "").strip()
            if not previous or previous == content:
                merged[-1]["content"] = content or previous
                continue
            if content.startswith(previous) or previous in content:
                merged[-1]["content"] = content
                continue
            if previous.startswith(content):
                continue
            merged[-1]["content"] = merge_front_and_worker(previous, content, "ack_continue")
            continue
        merged.append(dict(turn))
        merged[-1]["content"] = content
    return merged


def small_context_envelope(
    user_text: str,
    history: list[ChatMessage] | None = None,
    *,
    action_hint: str,
    context_turns: int = 4,
) -> list[ChatMessage]:
    hint = action_hint if action_hint in FRONT_ACTIONS else "ack_continue"
    messages = [
        ChatMessage(role="system", content=FRONT_SYSTEM),
        ChatMessage(role="system", content=f"Hint front_action: {hint}. Keep the reply spoken-ready."),
    ]
    keep = max(0, int(context_turns or 0))
    prior = [
        message
        for message in (history or [])
        if message.role in {"user", "assistant"} and str(message.content or "").strip()
    ]
    if keep:
        messages.extend(prior[-keep * 2 :])
    messages.append(ChatMessage(role="user", content=(user_text or "").strip()))
    return messages


def front_provider(settings: AppSettings | None = None):
    app = settings or load_settings()
    loaded = MANAGER.provider
    configured = (app.front_responder.model or "").strip()
    if loaded and not configured:
        return loaded
    loaded_id = str(getattr(loaded, "model", "") or "").strip()
    wanted = resolve_front_model_id(app)
    if loaded and (not wanted or wanted == loaded_id):
        return loaded
    if loaded and not configured:
        return loaded
    from ..providers.openai_compat import OpenAICompatProvider

    timeout = max(1.0, front_lane_config(app).timeout_ms / 1000.0)
    return OpenAICompatProvider(
        MANAGER.base_url(app),
        api_key=MANAGER.provider_api_key(app),
        model=wanted,
        timeout=timeout,
    )


async def generate_front_reply(
    user_text: str,
    *,
    history: list[ChatMessage] | None = None,
    settings: AppSettings | None = None,
    route: RequestRoute | None = None,
    turn_started: float | None = None,
    provider: Any | None = None,
    on_delta: Callable[[str], Awaitable[None] | None] | None = None,
) -> FrontReply:
    app = settings or load_settings()
    cfg = front_lane_config(app)
    started = turn_started if turn_started is not None else time.perf_counter()
    heuristic = classify_front_action(user_text, route=route)
    model_id = resolve_front_model_id(app)
    if not app.front_responder.enabled:
        return FrontReply(action="silent_skip", text="", model=model_id, skipped=True, max_tokens=cfg.max_tokens)
    chat = provider or front_provider(app)
    if chat is None or not hasattr(chat, "chat_stream"):
        action, text, rejected = enforce_front_safety(heuristic, fallback_text_for_action(heuristic), user_text=user_text, heuristic=heuristic)
        return FrontReply(
            action="silent_skip" if heuristic == "silent_skip" else action,
            text="" if heuristic == "silent_skip" else text,
            model=model_id,
            skipped=True,
            safety_rejected=rejected,
            max_tokens=cfg.max_tokens,
        )

    messages = small_context_envelope(
        user_text,
        history,
        action_hint=heuristic,
        context_turns=cfg.context_turns,
    )
    parts: list[str] = []
    first_text_ms = 0.0
    timeout_s = cfg.timeout_ms / 1000.0
    deadline = time.perf_counter() + timeout_s
    try:
        async for delta in _iter_chat_stream(
            chat,
            messages,
            temperature=cfg.temperature,
            max_tokens=cfg.max_tokens,
            thinking=False,
        ):
            if time.perf_counter() > deadline:
                break
            if not delta:
                continue
            if not parts:
                first_text_ms = max(0.0, (time.perf_counter() - started) * 1000)
            parts.append(delta)
            if on_delta:
                maybe = on_delta(delta)
                if asyncio.iscoroutine(maybe):
                    await maybe
    except Exception:
        parts = parts or []

    raw = "".join(parts).strip()
    if not raw:
        action = "silent_skip" if worker_required(heuristic) else heuristic
        complete_ms = max(0.0, (time.perf_counter() - started) * 1000)
        return FrontReply(
            action=action if action in FRONT_ACTIONS else "silent_skip",
            text="",
            model=model_id,
            complete_ms=complete_ms,
            skipped=True,
            max_tokens=cfg.max_tokens,
        )
    parsed_action, parsed_text = parse_front_payload(raw, fallback_action=heuristic)
    action, text, rejected = enforce_front_safety(
        parsed_action,
        parsed_text,
        user_text=user_text,
        heuristic=heuristic,
    )
    complete_ms = max(0.0, (time.perf_counter() - started) * 1000)
    skipped = action == "silent_skip" or not text
    if skipped and not text and worker_required(heuristic):
        action = "silent_skip"
    return FrontReply(
        action=action,
        text="" if action == "silent_skip" else text,
        model=model_id,
        first_text_ms=first_text_ms if text else 0.0,
        complete_ms=complete_ms,
        skipped=skipped,
        safety_rejected=rejected,
        thinking=False,
        tools_enabled=False,
        max_tokens=cfg.max_tokens,
        chunks=parts,
    )


async def run_two_lane_chat(
    user_text: str,
    *,
    history: list[ChatMessage] | None = None,
    settings: AppSettings | None = None,
    route: RequestRoute | None = None,
    turn_started: float | None = None,
    worker_stream: WorkerStream | None = None,
    on_delta: Callable[[str, str], Awaitable[None] | None] | None = None,
) -> AsyncIterator[dict[str, Any]]:
    """Yield front deltas first (or in parallel), then worker deltas, as one turn."""
    app = settings or load_settings()
    started = turn_started if turn_started is not None else time.perf_counter()
    router_started = time.perf_counter()
    resolved_route = route or route_request(user_text)
    heuristic = classify_front_action(user_text, route=resolved_route)
    router_ms = max(0.0, (time.perf_counter() - router_started) * 1000)
    queue_ms = max(0.0, (time.perf_counter() - started) * 1000)
    cfg = front_lane_config(app)
    model_id = resolve_front_model_id(app)
    timing = TwoLaneTiming(
        front_model=model_id,
        front_action=heuristic,
        queue_ms=queue_ms,
        router_ms=router_ms,
        router_complete_ms=router_ms,
    )

    async def _emit(lane: str, delta: str) -> None:
        if on_delta:
            maybe = on_delta(lane, delta)
            if asyncio.iscoroutine(maybe):
                await maybe

    distinct = _distinct_front_model(app, model_id)
    parallel = bool(app.front_responder.parallel_when_distinct_model and distinct and worker_required(heuristic))
    worker_task: asyncio.Task[tuple[list[str], float, float]] | None = None
    if parallel and worker_stream is not None:
        worker_task = asyncio.create_task(_collect_worker_stream(worker_stream, started, _emit))

    yield {"type": "front_response_started", "front_model": model_id, "front_action": heuristic}
    front = await generate_front_reply(
        user_text,
        history=history,
        settings=app,
        route=resolved_route,
        turn_started=started,
    )
    timing.front_model = front.model or model_id
    timing.front_action = front.action
    timing.front_first_text_ms = front.first_text_ms
    timing.front_complete_ms = front.complete_ms
    if front.skipped or front.action == "silent_skip":
        yield {"type": "front_response_skipped", "front_action": front.action, "reply": front}
    else:
        raw_front = "".join(front.chunks).strip()
        if front.safety_rejected or (raw_front and raw_front.lstrip().startswith("{")):
            stream_chunks = [front.text] if front.text else []
        else:
            stream_chunks = front.chunks or ([front.text] if front.text else [])
        for chunk in stream_chunks:
            if not chunk:
                continue
            await _emit("front", chunk)
            yield {"type": "delta", "lane": "front", "text": chunk}
        yield {"type": "front_response_completed", "reply": front}

    worker_parts: list[str] = []
    worker_first_ms = 0.0
    worker_complete_ms = 0.0
    need_worker = worker_required(front.action) and worker_stream is not None
    if worker_task is not None:
        if not need_worker:
            worker_task.cancel()
            try:
                await worker_task
            except (asyncio.CancelledError, Exception):
                pass
            worker_task = None
        else:
            yield {"type": "worker_response_started"}
            worker_parts, worker_first_ms, worker_complete_ms = await worker_task
            yield {"type": "worker_response_completed"}
    elif need_worker:
        yield {"type": "worker_response_started"}
        worker_parts, worker_first_ms, worker_complete_ms = await _collect_worker_stream(
            worker_stream, started, _emit
        )
        yield {"type": "worker_response_completed"}

    if (
        not front.skipped
        and front.action != "silent_skip"
        and worker_first_ms
        and front.first_text_ms
        and worker_first_ms + 40 < front.first_text_ms
        and not front.text
    ):
        front.action = "silent_skip"
        front.skipped = True
        front.text = ""
        timing.front_action = "silent_skip"

    merged = merge_front_and_worker(front.text, "".join(worker_parts).strip(), front.action)
    timing.worker_first_text_ms = worker_first_ms
    timing.worker_complete_ms = worker_complete_ms
    recorded = record_front_timing(timing.as_dict())
    yield {
        "type": "done",
        "text": merged,
        "front": front,
        "front_action": front.action,
        "front_text": front.text,
        "worker_text": "".join(worker_parts).strip(),
        "timing": recorded,
        "config": cfg.as_dict(),
    }


def note_front_audio(timing: dict[str, Any] | None, audio_ms: float) -> dict[str, Any]:
    payload = dict(timing or last_front_timing())
    if audio_ms and not payload.get("front_first_audio_ms"):
        payload["front_first_audio_ms"] = round(audio_ms, 1)
    if audio_ms and not payload.get("tts_first_audio_ms"):
        payload["tts_first_audio_ms"] = round(audio_ms, 1)
    return record_front_timing(payload)


def _is_trivial_chat(lowered: str) -> bool:
    text = (lowered or "").strip()
    if not text or len(text) > 180:
        return False
    if _LIVE_FACT_HINT.search(text):
        return False
    return bool(_TRIVIAL_CHAT.search(text))


def _substantively_same(left: str, right: str) -> bool:
    def _norm(value: str) -> str:
        return re.sub(r"\s+", " ", value.strip().lower())

    a, b = _norm(left), _norm(right)
    if not a or not b:
        return False
    if a == b:
        return True
    if a in b or b in a:
        return min(len(a), len(b)) >= 12
    return False


def _extract_json_object(raw: str) -> dict[str, Any] | None:
    text = (raw or "").strip()
    if not text:
        return None
    candidates = [text]
    fenced = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.DOTALL)
    if fenced:
        candidates.append(fenced.group(1))
    start = text.find("{")
    end = text.rfind("}")
    if start >= 0 and end > start:
        candidates.append(text[start : end + 1])
    for candidate in candidates:
        try:
            parsed = json.loads(candidate)
        except json.JSONDecodeError:
            continue
        if isinstance(parsed, dict):
            return parsed
    return None


def _distinct_front_model(settings: AppSettings, front_model: str) -> bool:
    configured = (settings.front_responder.model or "").strip()
    if not configured:
        return False
    loaded = str(getattr(MANAGER.provider, "model", "") or "").strip()
    return bool(front_model and loaded and front_model != loaded)


async def _iter_chat_stream(provider: Any, messages: list[ChatMessage], **kwargs: Any) -> AsyncIterator[str]:
    kwargs.setdefault("thinking", False)
    stream = provider.chat_stream(messages, **kwargs)
    if hasattr(stream, "__aiter__"):
        async for delta in stream:
            yield delta
        return
    streamed = await stream
    if hasattr(streamed, "__aiter__"):
        async for delta in streamed:
            yield delta
        return
    if isinstance(streamed, ChatResult) and streamed.content:
        yield streamed.content


async def _collect_worker_stream(
    worker_stream: WorkerStream,
    started: float,
    on_delta: Callable[[str, str], Awaitable[None]],
) -> tuple[list[str], float, float]:
    parts: list[str] = []
    first_ms = 0.0
    async for delta in worker_stream():
        if not delta:
            continue
        if not parts:
            first_ms = max(0.0, (time.perf_counter() - started) * 1000)
        parts.append(delta)
        await on_delta("worker", delta)
    complete_ms = max(0.0, (time.perf_counter() - started) * 1000)
    return parts, first_ms, complete_ms
