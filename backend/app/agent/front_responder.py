"""RFC-0117 tiny front-chat responder lane.

Produces a fast first owner-facing reply with tools and thinking disabled.
The larger router/worker path remains responsible for non-trivial turns.
"""

from __future__ import annotations

import asyncio
import difflib
import json
import re
import time
from collections.abc import AsyncIterator, Awaitable, Callable
from dataclasses import asdict, dataclass, field
from typing import Any

from ..config import AppSettings, FrontResponderSettings, load_settings
from ..inference.manager import MANAGER
from ..providers.base import ChatMessage, ChatResult
from .planning import RequestRoute

RUNTIME_ROLE = "front_responder"
ANSWER_TIER = 1
FRONT_MAX_TOKENS_MIN = 96
FRONT_MAX_TOKENS_MAX = 160
FRONT_MAX_TOKENS_DEFAULT = 128
FRONT_USER_TEXT_SOFT_LIMIT = 1600
# Legacy transcripts inserted this heading between the front line and the worker.
# New merges never emit it. The pieces stay split so user-facing copy does not
# carry the heading as a literal label.
LEGACY_MERGE_HEADING = "Deeper" + " result"
DEEPER_RESULT_LABEL = LEGACY_MERGE_HEADING
DEEPER_RESULT_SEP = f"\n\n{DEEPER_RESULT_LABEL}\n"
# Hold ack_continue / handoff_notice this long. A worker sentence that lands
# first cancels the ack. final_basic and ask_clarification are not held.
ACK_HOLD_SECONDS = 1.2

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
def safe_hello(settings: AppSettings | None = None) -> str:
    """Greeting fallback that follows the address-style setting, including neutral."""
    from ..tts.persona_speech import address_vocative

    vocative = address_vocative(settings)
    if not vocative:
        return "Hello."
    return f"Hello, {vocative}."


# Neutral default. Spoken greetings go through safe_hello() so sir/name/neutral stay in one place.
SAFE_HELLO = "Hello."
CONTEXT_SWITCH_KEEP_BUSY = "Switching to a larger context model…"
CONTEXT_EXPAND_KEEP_BUSY = "One moment — expanding context for a fuller answer."

SAFE_PROGRESS_MODEL = "The main model is still loading; I shall update you shortly."
SAFE_PROGRESS_TOOLS = "I am still working through tools and verification."
SAFE_PROGRESS_GENERIC = "This is taking longer than usual; I am still on it."

PROGRESS_SYSTEM = """You are Jarvis giving the owner one brief progress update while deeper work continues.
Use a dry, understated British-inspired register. One or two short sentences only.
Explain why things are slow using only the situation hint (model load, tools, verification, context, hotswap).
Do not claim success, completion, or invented facts. Do not mention internal model names or routing scores.
Output only the spoken reply text."""

FRONT_SYSTEM = """You are Jarvis speaking with the owner. Runtime role: front_responder. Answer tier: 1.
Reply immediately, naturally, and briefly in a British-inspired operations-assistant register.
Put the useful answer in the first sentence, ideally no more than twelve words.
Default to one to three short sentences. Do not think out loud.
This lane cannot use tools, write code, change files, or verify work.
Do not claim an action succeeded. Do not invent live facts, numbers, scores, weather, or repository state.
Do not mention routing scores, hidden reasoning, or internal model names.
If the hint action is final_basic, answer the greeting or basic chat directly.
When the hint is final_basic and the owner asked for a literal or terse reply, output that reply and nothing else. Do not prepend or append a holding sentence. Do not say you are checking details.
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
_front_lane_tasks: set[asyncio.Task[Any]] = set()


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
    """Record per-turn front timings, preserving earlier audio marks.

    Immediate TTS often notes ``front_first_audio_ms`` / ``tts_first_audio_ms``
    before the two-lane worker finishes. A later ``done`` write must not wipe
    those fields with zeros.
    """
    global _last_timing, _timings
    payload = dict(timing)
    previous = _last_timing or {}
    for key in ("front_first_audio_ms", "tts_first_audio_ms"):
        incoming = payload.get(key)
        if not incoming and previous.get(key):
            payload[key] = previous[key]
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
    """Configurable OpenAI-compat id on the front endpoint.

    An explicit ``model`` override wins. Otherwise a healthy dedicated front
    server (local CPU llama-server or a manual remote endpoint) advertises its
    profile alias. Empty settings with no dedicated server use the loaded
    worker alias. No vendor model name is hard-coded in this function.
    """
    app = settings or load_settings()
    configured = (app.front_responder.model or "").strip()
    if configured:
        return configured
    from ..inference.front_runtime import FRONT_RUNTIME

    dedicated = FRONT_RUNTIME.model_id(app)
    if dedicated:
        return dedicated
    advertised = list(getattr(MANAGER.state, "advertised_models", None) or [])
    return MANAGER.provider_model(app, advertised)


def worker_required(action: str) -> bool:
    return action in {"ack_continue", "handoff_notice", "silent_skip"}


def _fall_through_failed_self_status(
    action: str,
    text: str,
    *,
    reply_shape: str,
    rejected: bool,
) -> tuple[str, str]:
    """A failed self-status front must not become a canned terminal answer."""
    if (reply_shape or "").strip() != "self_status":
        return action, text
    if rejected or not (text or "").strip():
        return "ack_continue", ""
    return action, text


def terminal_front_completes_turn(action: str) -> bool:
    """True when the front lane alone finishes the owner turn (no worker)."""
    return action in {"final_basic", "ask_clarification"}


def is_unsafe_front_claim(
    text: str,
    *,
    snapshot: dict[str, Any] | None = None,
    reply_shape: str = "",
) -> bool:
    sample = (text or "").strip()
    if not sample:
        return False
    if _FAKE_DONE.search(sample) or _TOOL_CLAIM.search(sample):
        return True
    leak = _REASONING_LEAK.search(sample)
    invented = _INVENTED_FACTS.search(sample)
    if reply_shape == "self_status" and snapshot:
        from .self_knowledge import snapshot_blob

        blob = snapshot_blob(snapshot).lower()
        lowered = sample.lower()
        if leak:
            if any(
                marker in lowered
                for marker in ("hidden reasoning", "routing score", "chain of thought", "<think>")
            ):
                return True
            if "answer_tier" in lowered and "answer_tier" not in blob:
                return True
            if "runtime_role" in lowered and "runtime_role" not in blob:
                return True
            leak = None
        if invented:
            from .self_knowledge import snapshot_numeric_tokens

            numbers = re.findall(r"\d+(?:\.\d+)?", sample)
            allowed = snapshot_numeric_tokens(snapshot)
            if numbers and any(number not in allowed for number in numbers):
                return True
            invented = None
        return False
    return bool(invented or leak)


def is_safe_front_speech(action: str, text: str) -> bool:
    if action in {"silent_skip", ""}:
        return False
    cleaned = (text or "").strip()
    if not cleaned:
        return False
    if is_unsafe_front_claim(cleaned):
        return False
    return True


def _front_lane_user_text(user_text: str) -> str:
    """Keep the fast voice lane inside a small context envelope."""
    text = (user_text or "").strip()
    if len(text) <= FRONT_USER_TEXT_SOFT_LIMIT:
        return text
    head = text[: int(FRONT_USER_TEXT_SOFT_LIMIT * 0.55)].rstrip()
    tail = text[-int(FRONT_USER_TEXT_SOFT_LIMIT * 0.35) :].lstrip()
    return (
        f"{head}\n…\n[Owner spoke a long message ({len(text)} chars). "
        f"Acknowledge briefly; the worker lane has the full text.]\n…\n{tail}"
    )


def classify_front_action(
    user_text: str,
    *,
    route: RequestRoute | None = None,
    decision: Any | None = None,
) -> str:
    """Read an OwnerTurnDecision. Routing stays on the reflex turn decision."""
    if decision is not None:
        action = str(getattr(decision, "front_action", "") or "").strip()
        if action in FRONT_ACTIONS:
            return action
    text = (user_text or "").strip()
    if not text:
        return "silent_skip"
    from ..decision.owner_turn import rules_front_action

    return rules_front_action(text, baseline=route)


def fallback_text_for_action(
    action: str,
    settings: AppSettings | None = None,
    *,
    reply_shape: str = "",
    literal_text: str = "",
) -> str:
    shape = (reply_shape or "").strip()
    if shape == "literal" and (literal_text or "").strip():
        return literal_text.strip()
    if shape == "clarify" or action == "ask_clarification":
        return SAFE_CLARIFY
    if action == "silent_skip":
        return ""
    if shape == "self_status":
        # Never a canned holding line. A failed self-status front falls through
        # to the worker (see _fall_through_failed_self_status).
        return ""
    if shape == "social" or action == "final_basic":
        return safe_hello(settings)
    if action == "handoff_notice" or shape == "handoff":
        return SAFE_HANDOFF
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


def enforce_front_safety(
    action: str,
    text: str,
    *,
    user_text: str,
    heuristic: str,
    settings: AppSettings | None = None,
    reply_shape: str = "",
    literal_text: str = "",
    snapshot: dict[str, Any] | None = None,
) -> tuple[str, str, bool]:
    if (reply_shape or "").strip() == "literal" and (literal_text or "").strip():
        exact = literal_text.strip()
        cleaned_model = (text or "").strip()
        rejected = cleaned_model != exact
        return "final_basic", exact, rejected
    cleaned = (text or "").strip()
    resolved = action if action in FRONT_ACTIONS else heuristic
    rejected = False
    if heuristic != "final_basic" and resolved == "final_basic":
        resolved = "ack_continue" if heuristic != "ask_clarification" else heuristic
        rejected = True
    if is_unsafe_front_claim(cleaned, snapshot=snapshot, reply_shape=reply_shape):
        rejected = True
        if heuristic == "final_basic" and _is_trivial_chat(user_text.lower()):
            resolved = "final_basic"
            cleaned = safe_hello(settings)
        else:
            resolved = heuristic if heuristic in FRONT_ACTIONS else "ack_continue"
            if resolved == "final_basic" and reply_shape not in {"social", "self_status", "literal"}:
                resolved = "ack_continue"
            cleaned = fallback_text_for_action(
                resolved,
                settings,
                reply_shape=reply_shape,
                literal_text=literal_text,
            )
    if rejected and not cleaned and resolved != "silent_skip":
        cleaned = fallback_text_for_action(
            resolved,
            settings,
            reply_shape=reply_shape,
            literal_text=literal_text,
        )
    resolved, cleaned = _fall_through_failed_self_status(
        resolved, cleaned, reply_shape=reply_shape, rejected=rejected
    )
    return resolved, cleaned, rejected


def live_text_update(shown: str, reply: str) -> tuple[str, str] | None:
    """How a consolidated reply should update a quick line already on screen.

    ``append`` is the new tail when the reply still starts with that line.
    ``replace`` is the full reply when a correction replaces it. ``None`` means
    nothing new to show. An empty ``shown`` is a first line, returned as append.
    """
    previous = (shown or "").strip()
    text = (reply or "").strip()
    if not text:
        return None
    if previous and text.startswith(previous):
        tail = text[len(previous) :].strip()
        if not tail:
            return None
        return ("append", tail)
    if previous and text != previous:
        return ("replace", text)
    if not previous:
        return ("append", text)
    return None


def _early_merge_result(
    front: str,
    worker: str,
    action: str,
) -> str | None:
    if action == "silent_skip":
        return worker or front
    if action == "final_basic" and not worker:
        return front or worker
    if action == "ask_clarification" and not worker:
        return front
    if not front:
        return worker
    if not worker:
        return front
    return None


def _apply_arbitration_result(
    result: Any | None,
    front: str,
    worker: str,
    action: str,
    reply_shape: str,
) -> str:
    from ..decision.surfaces import answer_value

    disposition = ""
    if result is not None:
        disposition = str(answer_value(result, "disposition") or "")
    if disposition not in {"keep_front", "keep_worker", "append_novel"}:
        disposition = infer_arbitration_disposition(
            front,
            worker,
            front_action=action,
            reply_shape=reply_shape,
        )
    if reply_shape == "literal" or (
        action == "final_basic" and front and not is_unsafe_front_claim(front)
    ):
        disposition = "keep_front"
    return apply_disposition(disposition, front, worker)


def merge_front_and_worker(
    front_text: str,
    worker_text: str,
    action: str,
    *,
    user_message: str = "",
    reply_shape: str = "",
    front_spoken: bool = False,
    decision_tier: str = "local",
) -> str:
    """One owner-facing turn via Reflex arbitration + string executor.

    One side empty: return the other side and do not call a provider.
    Empty / synthetic ``user_message``: rules disposition only (no provider).
    """
    front = _strip_legacy_merge_heading(front_text or "").strip()
    worker = _strip_legacy_merge_heading(worker_text or "").strip()
    early = _early_merge_result(front, worker, action)
    if early is not None:
        return early
    result = None
    if (user_message or "").strip():
        from ..decision.surfaces import arbitrate_front_and_worker

        result = arbitrate_front_and_worker(
            user_message=user_message,
            front_text=front,
            worker_text=worker,
            front_action=action,
            front_spoken=front_spoken,
            reply_shape=reply_shape,
            decision_tier=decision_tier,
        )
    return _apply_arbitration_result(result, front, worker, action, reply_shape)


async def merge_front_and_worker_async(
    front_text: str,
    worker_text: str,
    action: str,
    *,
    user_message: str = "",
    reply_shape: str = "",
    front_spoken: bool = False,
    decision_tier: str = "local",
) -> str:
    """Bounded arbitration (50 ms, off the event loop) then the string executor."""
    front = _strip_legacy_merge_heading(front_text or "").strip()
    worker = _strip_legacy_merge_heading(worker_text or "").strip()
    early = _early_merge_result(front, worker, action)
    if early is not None:
        return early
    if not (user_message or "").strip():
        return _apply_arbitration_result(None, front, worker, action, reply_shape)
    from ..decision.surfaces import arbitrate_front_and_worker_bounded

    result = await arbitrate_front_and_worker_bounded(
        user_message=user_message,
        front_text=front,
        worker_text=worker,
        front_action=action,
        front_spoken=front_spoken,
        reply_shape=reply_shape,
        decision_tier=decision_tier,
    )
    return _apply_arbitration_result(result, front, worker, action, reply_shape)


def speakable_worker_remainder(merged: str, spoken_through: int) -> str:
    """Slice TTS text after an already-spoken prefix, never speaking merge labels.

    Early front TTS advances the stream cursor by ``len(front)``. A merged
    reply is ``{front}\\n\\n{novel worker}`` with no section heading. Strip a
    legacy merge heading if an older transcript still contains one, so speech
    is only the owner-facing remainder.
    """
    text = merged or ""
    if spoken_through <= 0:
        fragment = text
    elif spoken_through >= len(text):
        return ""
    else:
        fragment = text[spoken_through:]
    return _strip_merge_label_from_tts(fragment).strip()


def _strip_merge_label_from_tts(fragment: str) -> str:
    if not fragment:
        return ""
    if fragment.startswith(DEEPER_RESULT_SEP):
        return fragment[len(DEEPER_RESULT_SEP) :]
    if DEEPER_RESULT_SEP in fragment:
        before, after = fragment.split(DEEPER_RESULT_SEP, 1)
        before = before.rstrip()
        after = after.lstrip()
        if before and after:
            return f"{before}\n\n{after}"
        return before or after
    leading = re.match(
        rf"^\s*{re.escape(DEEPER_RESULT_LABEL)}\s*\n?",
        fragment,
        flags=re.IGNORECASE,
    )
    if leading:
        return fragment[leading.end() :]
    return fragment


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
            merged[-1]["content"] = apply_disposition(
                infer_arbitration_disposition(previous, content, front_action="ack_continue"),
                previous,
                content,
            )
            continue
        merged.append(dict(turn))
        merged[-1]["content"] = content
    return merged


def front_system_prompt() -> str:
    """FRONT_SYSTEM plus active session personality addendum (RFC-0130)."""
    try:
        from ..persona.session_personality import session_personality_system_addendum

        addendum = session_personality_system_addendum()
    except Exception:
        addendum = ""
    if addendum:
        return f"{FRONT_SYSTEM}\n\n{addendum}"
    return FRONT_SYSTEM


def small_context_envelope(
    user_text: str,
    history: list[ChatMessage] | None = None,
    *,
    action_hint: str,
    context_turns: int = 4,
    snapshot: dict[str, Any] | None = None,
    reply_shape: str = "",
) -> list[ChatMessage]:
    hint = action_hint if action_hint in FRONT_ACTIONS else "ack_continue"
    messages = [
        ChatMessage(role="system", content=front_system_prompt()),
        ChatMessage(role="system", content=f"Hint front_action: {hint}. Keep the reply spoken-ready."),
    ]
    if (reply_shape or "").strip() == "self_status" and snapshot:
        from .self_knowledge import snapshot_prompt_addendum

        messages.append(ChatMessage(role="system", content=snapshot_prompt_addendum(snapshot)))
    keep = max(0, int(context_turns or 0))
    prior = [
        message
        for message in (history or [])
        if message.role in {"user", "assistant"} and str(message.content or "").strip()
    ]
    if keep:
        messages.extend(prior[-keep * 2 :])
    messages.append(ChatMessage(role="user", content=_front_lane_user_text(user_text)))
    return messages


def front_provider(settings: AppSettings | None = None):
    app = settings or load_settings()
    from ..inference.front_runtime import FRONT_RUNTIME

    dedicated = FRONT_RUNTIME.provider(app)
    if dedicated is not None:
        return dedicated
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
    if not MANAGER.state.loaded:
        return None
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
    turn_decision: Any | None = None,
    turn_started: float | None = None,
    provider: Any | None = None,
    on_delta: Callable[[str], Awaitable[None] | None] | None = None,
) -> FrontReply:
    app = settings or load_settings()
    cfg = front_lane_config(app)
    started = turn_started if turn_started is not None else time.perf_counter()
    decision = turn_decision
    if decision is None:
        from .request_routing import evaluate_request_route

        decision = await evaluate_request_route(
            user_text,
            route,
            settings=app,
            decision_tier=str(getattr(getattr(app, "decision", None), "tier", "") or "local"),
        )
    heuristic = classify_front_action(user_text, route=route, decision=decision)
    reply_shape = str(getattr(decision, "reply_shape", "") or "")
    literal_text = str(getattr(decision, "literal_text", "") or "")
    snapshot: dict[str, Any] | None = None
    if reply_shape == "self_status":
        from .self_knowledge import build_self_knowledge_snapshot

        snapshot = build_self_knowledge_snapshot(app)
    model_id = resolve_front_model_id(app)
    if not app.front_responder.enabled:
        return FrontReply(action="silent_skip", text="", model=model_id, skipped=True, max_tokens=cfg.max_tokens)
    if reply_shape == "literal" and literal_text:
        elapsed_ms = max(0.0, (time.perf_counter() - started) * 1000)
        action, text, rejected = enforce_front_safety(
            "final_basic",
            literal_text,
            user_text=user_text,
            heuristic="final_basic",
            settings=app,
            reply_shape=reply_shape,
            literal_text=literal_text,
            snapshot=snapshot,
        )
        return FrontReply(
            action=action,
            text=text,
            model=model_id,
            skipped=False,
            safety_rejected=rejected,
            max_tokens=cfg.max_tokens,
            first_text_ms=elapsed_ms,
            complete_ms=elapsed_ms,
        )
    chat = provider or front_provider(app)
    if chat is None or not hasattr(chat, "chat_stream"):
        action, text, rejected = enforce_front_safety(
            heuristic,
            fallback_text_for_action(
                heuristic, app, reply_shape=reply_shape, literal_text=literal_text
            ),
            user_text=user_text,
            heuristic=heuristic,
            settings=app,
            reply_shape=reply_shape,
            literal_text=literal_text,
            snapshot=snapshot,
        )
        action, text = _fall_through_failed_self_status(
            action, text, reply_shape=reply_shape, rejected=rejected
        )
        if heuristic == "silent_skip":
            return FrontReply(
                action="silent_skip",
                text="",
                model=model_id,
                skipped=True,
                safety_rejected=rejected,
                max_tokens=cfg.max_tokens,
            )
        elapsed_ms = max(0.0, (time.perf_counter() - started) * 1000)
        return FrontReply(
            action=action,
            text=text,
            model=model_id,
            skipped=True,
            safety_rejected=rejected,
            max_tokens=cfg.max_tokens,
            first_text_ms=elapsed_ms,
            complete_ms=elapsed_ms,
        )

    messages = small_context_envelope(
        user_text,
        history,
        action_hint=heuristic,
        context_turns=cfg.context_turns,
        snapshot=snapshot,
        reply_shape=reply_shape,
    )
    parts: list[str] = []
    first_text_ms = 0.0
    timeout_s = cfg.timeout_ms / 1000.0
    deadline = time.perf_counter() + timeout_s
    try:
        async for delta in _deadline_stream(_iter_chat_stream(
            chat,
            messages,
            temperature=cfg.temperature,
            max_tokens=cfg.max_tokens,
            thinking=False,
            first_token_deadline_ms=cfg.timeout_ms,
            idle_deadline_ms=cfg.timeout_ms,
            stream_lane="front",
        ), timeout_s):
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
        complete_ms = max(0.0, (time.perf_counter() - started) * 1000)
        if heuristic == "silent_skip":
            return FrontReply(
                action="silent_skip",
                text="",
                model=model_id,
                complete_ms=complete_ms,
                skipped=True,
                max_tokens=cfg.max_tokens,
            )
        fb = fallback_text_for_action(
            heuristic, app, reply_shape=reply_shape, literal_text=literal_text
        )
        action, text, rejected = enforce_front_safety(
            heuristic,
            fb,
            user_text=user_text,
            heuristic=heuristic,
            settings=app,
            reply_shape=reply_shape,
            literal_text=literal_text,
            snapshot=snapshot,
        )
        action, text = _fall_through_failed_self_status(
            action, text, reply_shape=reply_shape, rejected=rejected
        )
        return FrontReply(
            action=action,
            text=text,
            model=model_id,
            complete_ms=complete_ms,
            skipped=True,
            safety_rejected=rejected,
            max_tokens=cfg.max_tokens,
            first_text_ms=complete_ms,
        )
    parsed_action, parsed_text = parse_front_payload(raw, fallback_action=heuristic)
    action, text, rejected = enforce_front_safety(
        parsed_action,
        parsed_text,
        user_text=user_text,
        heuristic=heuristic,
        settings=app,
        reply_shape=reply_shape,
        literal_text=literal_text,
        snapshot=snapshot,
    )
    action, text = _fall_through_failed_self_status(
        action, text, reply_shape=reply_shape, rejected=rejected
    )
    complete_ms = max(0.0, (time.perf_counter() - started) * 1000)
    skipped = action == "silent_skip" or not text
    if skipped and not text and worker_required(heuristic) and action != "ack_continue":
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


def progress_template_for_context(context: str) -> str:
    lowered = (context or "").lower()
    if "model" in lowered or "context" in lowered or "load" in lowered:
        return SAFE_PROGRESS_MODEL
    if "tool" in lowered or "verif" in lowered or "pytest" in lowered:
        return SAFE_PROGRESS_TOOLS
    return SAFE_PROGRESS_GENERIC


async def generate_progress_update(
    context: str,
    *,
    settings: AppSettings | None = None,
    provider: Any | None = None,
) -> str:
    app = settings or load_settings()
    situation = (context or "").strip() or "Work is taking longer than usual."
    if not app.front_responder.enabled:
        return progress_template_for_context(situation)
    cfg = front_lane_config(app)
    chat = provider or front_provider(app)
    if chat is None or not hasattr(chat, "chat_stream"):
        return progress_template_for_context(situation)
    messages = [
        ChatMessage(role="system", content=PROGRESS_SYSTEM),
        ChatMessage(
            role="user",
            content=f"Situation: {situation}\nGive one brief progress line for the owner.",
        ),
    ]
    parts: list[str] = []
    deadline = time.perf_counter() + max(1.0, cfg.timeout_ms / 1000.0)
    try:
        async for delta in _iter_chat_stream(
            chat,
            messages,
            temperature=cfg.temperature,
            max_tokens=min(cfg.max_tokens, 256),
            thinking=False,
            first_token_deadline_ms=cfg.timeout_ms,
            idle_deadline_ms=cfg.timeout_ms,
            stream_lane="front",
        ):
            if time.perf_counter() > deadline:
                break
            if delta:
                parts.append(delta)
    except Exception:
        parts = parts or []
    line = "".join(parts).strip().splitlines()[0].strip() if parts else ""
    if not line or is_unsafe_front_claim(line):
        return progress_template_for_context(situation)
    return line


async def run_two_lane_chat(
    user_text: str,
    *,
    history: list[ChatMessage] | None = None,
    settings: AppSettings | None = None,
    route: RequestRoute | None = None,
    turn_decision: Any | None = None,
    turn_started: float | None = None,
    worker_stream: WorkerStream | None = None,
    on_delta: Callable[[str, str], Awaitable[None] | None] | None = None,
    prefetched_front: FrontReply | None = None,
    suppress_front: bool = False,
) -> AsyncIterator[dict[str, Any]]:
    """Yield front deltas first (or in parallel), then worker deltas, as one turn."""
    app = settings or load_settings()
    started = turn_started if turn_started is not None else time.perf_counter()
    router_started = time.perf_counter()
    decision = turn_decision
    if decision is None:
        from .request_routing import evaluate_request_route

        decision = await evaluate_request_route(
            user_text,
            route,
            settings=app,
            decision_tier=str(getattr(getattr(app, "decision", None), "tier", "") or "local"),
        )
    resolved_route = decision.route
    heuristic = classify_front_action(user_text, route=resolved_route, decision=decision)
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
    if prefetched_front is not None:
        front = prefetched_front
    else:
        front = await generate_front_reply(
            user_text,
            history=history,
            settings=app,
            route=resolved_route,
            turn_decision=decision,
            turn_started=started,
        )
    timing.front_model = front.model or model_id
    timing.front_action = front.action
    timing.front_first_text_ms = front.first_text_ms
    timing.front_complete_ms = front.complete_ms
    if front.first_audio_ms:
        timing.front_first_audio_ms = front.first_audio_ms
        timing.tts_first_audio_ms = front.first_audio_ms
    elif last_front_timing().get("front_first_audio_ms"):
        # Early speak may have noted audio before this lane finished.
        prior_audio = float(last_front_timing().get("front_first_audio_ms") or 0.0)
        if prior_audio:
            timing.front_first_audio_ms = prior_audio
            timing.tts_first_audio_ms = float(
                last_front_timing().get("tts_first_audio_ms") or prior_audio
            )
    if suppress_front or front.action == "silent_skip" or (not front.text and front.skipped):
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

    merge_front = "" if suppress_front else front.text
    merged = await merge_front_and_worker_async(
        merge_front,
        "".join(worker_parts).strip(),
        front.action,
        user_message=user_text,
        reply_shape=str(getattr(decision, "reply_shape", "") or ""),
        front_spoken=bool(merge_front) and not suppress_front,
        decision_tier=str(getattr(getattr(app, "decision", None), "tier", "") or "local"),
    )
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


_COMPARE_STOPWORDS = frozenset(
    {
        "a", "an", "the", "of", "to", "and", "or", "if", "it", "is", "are", "was",
        "were", "be", "been", "being", "just", "my", "your", "you", "youre",
        "seeing", "those", "that", "this", "them", "they", "me", "i", "we", "our",
        "sir", "please", "will", "ill", "its", "for", "on", "in", "at", "with",
    }
)
_CORRECTION_CUE = re.compile(
    r"(?i)\b(not|no longer|isn'?t|wasn'?t|aren'?t|actually|instead|rather|"
    r"moved|changed|corrected|wrong|updated)\b"
)


def _strip_legacy_merge_heading(text: str) -> str:
    """Drop a legacy section heading without treating it as spoken content."""
    if not text or LEGACY_MERGE_HEADING.lower() not in text.lower():
        return text or ""
    pattern = re.compile(rf"\n*{re.escape(LEGACY_MERGE_HEADING)}\n*", re.IGNORECASE)
    cleaned = pattern.sub("\n\n", text)
    return re.sub(r"\n{3,}", "\n\n", cleaned).strip()


def _normalize_compare(text: str) -> str:
    lowered = (text or "").lower().replace("'", "").replace("’", "")
    cleaned = re.sub(r"[^a-z0-9\s]", " ", lowered)
    return re.sub(r"\s+", " ", cleaned).strip()


def _content_tokens(text: str) -> list[str]:
    return [
        token
        for token in _normalize_compare(text).split()
        if token not in _COMPARE_STOPWORDS and len(token) > 2
    ]


def _split_sentences(text: str) -> list[str]:
    parts = re.split(r"(?<=[.!?])\s+", (text or "").strip())
    return [part.strip() for part in parts if part.strip()]


def _sequence_ratio(left: str, right: str) -> float:
    a = _normalize_compare(left)
    b = _normalize_compare(right)
    if not a or not b:
        return 0.0
    if a == b:
        return 1.0
    return difflib.SequenceMatcher(None, a, b).ratio()


def _number_tokens(text: str) -> set[str]:
    return set(re.findall(r"\d+(?:\.\d+)?", text or ""))


def _sentence_restates_front(sentence: str, front: str, front_sentences: list[str]) -> bool:
    """True when a worker sentence adds nothing beyond the front line."""
    if _CORRECTION_CUE.search(sentence) and not _CORRECTION_CUE.search(front):
        return False
    sentence_numbers = _number_tokens(sentence)
    front_numbers = _number_tokens(front)
    if sentence_numbers and front_numbers and sentence_numbers != front_numbers:
        return False
    best = max(_sequence_ratio(sentence, candidate) for candidate in (*front_sentences, front))
    worker_tokens = _content_tokens(sentence)
    known = set(_content_tokens(front))
    novel = [token for token in worker_tokens if token not in known]
    coverage = 1.0 if not worker_tokens else 1.0 - (len(novel) / len(worker_tokens))
    if best >= 0.72:
        return True
    if best >= 0.58 and len(novel) <= 2:
        return True
    if coverage >= 0.72 and len(novel) <= 2:
        return True
    return _substantively_same(front, sentence)


def infer_arbitration_disposition(
    front: str,
    worker: str,
    *,
    front_action: str = "",
    reply_shape: str = "",
) -> str:
    """Rules adapter for ``arbitration``: today's merge outcome as a typed choice."""
    left = _strip_legacy_merge_heading(front or "").strip()
    right = _strip_legacy_merge_heading(worker or "").strip()
    if reply_shape == "literal" or (
        front_action == "final_basic" and left and not is_unsafe_front_claim(left)
    ):
        return "keep_front"
    if not left:
        return "keep_worker"
    if not right:
        return "keep_front"
    if _substantively_same(left, right):
        return "keep_front"
    if right.startswith(left):
        tail = right[len(left) :].strip()
        if not tail or _sentence_restates_front(tail, left, _split_sentences(left)):
            return "keep_front"
        return "keep_worker"
    if left.startswith(right):
        return "keep_front"
    front_sentences = _split_sentences(left)
    novel = [
        sentence
        for sentence in _split_sentences(right)
        if not _sentence_restates_front(sentence, left, front_sentences)
    ]
    if not novel:
        return "keep_front"
    novel_text = " ".join(novel).strip()
    corrects = bool(_CORRECTION_CUE.search(novel_text)) or bool(
        _number_tokens(novel_text)
        and _number_tokens(left)
        and _number_tokens(novel_text) != _number_tokens(left)
    )
    if corrects:
        return "keep_worker"
    return "append_novel"


def apply_disposition(disposition: str, front_text: str, worker_text: str) -> str:
    """String executor for a typed arbitration disposition. Never emits a merge heading."""
    front = _strip_legacy_merge_heading(front_text or "").strip()
    worker = _strip_legacy_merge_heading(worker_text or "").strip()
    choice = (disposition or "").strip()
    if choice == "keep_front":
        return front or worker
    if choice == "keep_worker":
        return worker or front
    if not front:
        return worker
    if not worker:
        return front
    front_sentences = _split_sentences(front)
    novel = [
        sentence
        for sentence in _split_sentences(worker)
        if not _sentence_restates_front(sentence, front, front_sentences)
    ]
    if not novel:
        return front
    return f"{front}\n\n{' '.join(novel).strip()}"


def ack_is_held(action: str) -> bool:
    """ack_continue and handoff_notice wait; final answers do not."""
    return action in {"ack_continue", "handoff_notice"}


def should_prefetch_turn_retrieval(
    user_text: str,
    *,
    vault_required: bool,
    action: str = "",
    decision: Any | None = None,
) -> bool:
    """Terminal greetings skip retrieval. Vault-relevant asks still compose."""
    resolved = action or classify_front_action(user_text, decision=decision)
    if terminal_front_completes_turn(resolved) and not vault_required:
        return False
    return True


def first_sentence_ready(text: str) -> bool:
    """True once owner-facing text contains a finished sentence."""
    stripped = (text or "").strip()
    if len(stripped) < 4:
        return False
    for index, char in enumerate(stripped):
        if char not in ".!?":
            continue
        end = index + 1
        if end >= len(stripped) or stripped[end] in " \t\n\"'":
            return True
    return False


async def wait_for_late_ack(
    action: str,
    *,
    turn_started: float,
    worker_ready: asyncio.Event,
    hold_s: float | None = None,
) -> bool:
    """Return True when the ack should be shown and spoken.

    ``final_basic`` and ``ask_clarification`` return immediately. Held acks
    return False when ``worker_ready`` is set before the hold deadline,
    measured from ``turn_started``.
    """
    if not ack_is_held(action):
        return True
    if worker_ready.is_set():
        return False
    hold = ACK_HOLD_SECONDS if hold_s is None else max(0.0, float(hold_s))
    remaining = (turn_started + hold) - time.perf_counter()
    if remaining <= 0:
        return not worker_ready.is_set()
    try:
        await asyncio.wait_for(worker_ready.wait(), timeout=remaining)
    except asyncio.TimeoutError:
        pass
    return not worker_ready.is_set()


_worker_sentence_events: dict[str, asyncio.Event] = {}


def open_worker_sentence_watch(key: str) -> asyncio.Event:
    event = asyncio.Event()
    _worker_sentence_events[key] = event
    return event


def note_worker_first_sentence(key: str) -> None:
    event = _worker_sentence_events.get((key or "").strip())
    if event is not None and not event.is_set():
        event.set()


def close_worker_sentence_watch(key: str) -> None:
    _worker_sentence_events.pop((key or "").strip(), None)


class QueueSentenceWatch:
    """Buffer a worker queue and flag when the first sentence arrives."""

    def __init__(self, queue: asyncio.Queue) -> None:
        self.queue = queue
        self.ready = asyncio.Event()
        self.buffered: list[Any] = []
        self._task: asyncio.Task[None] | None = None

    def start(self) -> asyncio.Task[None]:
        self._task = asyncio.create_task(self._run())
        return self._task

    async def _run(self) -> None:
        while True:
            item = await self.queue.get()
            self.buffered.append(item)
            if item is None:
                joined = "".join(part for part in self.buffered if isinstance(part, str)).strip()
                if joined:
                    self.ready.set()
                return
            joined = "".join(part for part in self.buffered if isinstance(part, str))
            if first_sentence_ready(joined):
                self.ready.set()
                return

    def stop(self) -> None:
        task = self._task
        if task is not None and not task.done():
            task.cancel()

    async def finish(self) -> list[Any]:
        """Stop the watch and return every item it already pulled off the queue."""
        self.stop()
        task = self._task
        if task is not None:
            try:
                await task
            except asyncio.CancelledError:
                pass
        return list(self.buffered)


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


def front_worker_should_overlap(
    settings: AppSettings,
    user_text: str,
    *,
    strategy: str = "direct",
    action: str = "",
    decision: Any | None = None,
) -> bool:
    """Start worker prep while the front reply is still generating.

    Only when the front endpoint is a different server, the heuristic needs a
    worker, and intake is a single direct turn. Terminal heuristics stay
    serial so they never call ``MANAGER.load``.
    """
    cfg = settings.front_responder
    if not cfg.enabled or not cfg.parallel_when_distinct_model:
        return False
    if (strategy or "direct") != "direct":
        return False
    heuristic = action or classify_front_action(user_text, decision=decision)
    if heuristic not in {"ack_continue", "handoff_notice"}:
        return False
    return _distinct_front_model(settings, resolve_front_model_id(settings))


def _distinct_front_model(settings: AppSettings, front_model: str) -> bool:
    from ..inference.front_runtime import FRONT_RUNTIME

    if FRONT_RUNTIME.is_distinct(settings):
        return True
    configured = (settings.front_responder.model or "").strip()
    if not configured:
        return False
    loaded = str(getattr(MANAGER.provider, "model", "") or "").strip()
    return bool(front_model and loaded and front_model != loaded)


async def _deadline_stream(stream: AsyncIterator[str], timeout_s: float) -> AsyncIterator[str]:
    """Bound even a provider that never yields its first token."""
    try:
        async with asyncio.timeout(timeout_s):
            async for delta in stream:
                yield delta
    finally:
        await stream.aclose()


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


SpokenCallback = Callable[[str], Awaitable[None] | None]


async def emit_context_switch_keep_busy(
    *,
    settings: AppSettings | None = None,
    user_text: str = "",
    on_spoken: SpokenCallback | None = None,
) -> str:
    """Owner-facing keep-busy while the worker model hotswaps (dedicated front lane)."""
    app = settings or load_settings()
    text = CONTEXT_SWITCH_KEEP_BUSY
    if app.front_responder.enabled:
        try:
            front = await generate_front_reply(
                user_text or "Please wait while I switch models.",
                settings=app,
                turn_started=time.perf_counter(),
            )
            if front.text and is_safe_front_speech(front.action, front.text):
                text = front.text
        except Exception:
            # Keep the static handoff line; never invent a success claim.
            text = CONTEXT_SWITCH_KEEP_BUSY
    if on_spoken:
        maybe = on_spoken(text)
        if asyncio.iscoroutine(maybe):
            await maybe
    return text


def spawn_context_switch_keep_busy(
    *,
    settings: AppSettings | None = None,
    user_text: str = "",
    on_spoken: SpokenCallback | None = None,
) -> asyncio.Task[str]:
    """Fire-and-forget keep-busy on the front lane so worker hotswap does not block it."""

    async def _runner() -> str:
        return await emit_context_switch_keep_busy(
            settings=settings,
            user_text=user_text,
            on_spoken=on_spoken,
        )

    task = asyncio.create_task(_runner())
    _front_lane_tasks.add(task)
    task.add_done_callback(_front_lane_tasks.discard)
    return task


async def emit_context_expand_keep_busy(
    *,
    on_spoken: SpokenCallback | None = None,
) -> str:
    """Static keep-busy while context expands — never regenerates a front reply."""
    text = CONTEXT_EXPAND_KEEP_BUSY
    if on_spoken:
        maybe = on_spoken(text)
        if asyncio.iscoroutine(maybe):
            await maybe
    return text


def spawn_context_expand_keep_busy(
    *,
    on_spoken: SpokenCallback | None = None,
) -> asyncio.Task[str]:
    """Fire-and-forget keep-busy so context expand does not block the worker path."""

    async def _runner() -> str:
        return await emit_context_expand_keep_busy(on_spoken=on_spoken)

    task = asyncio.create_task(_runner())
    _front_lane_tasks.add(task)
    task.add_done_callback(_front_lane_tasks.discard)
    return task


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
