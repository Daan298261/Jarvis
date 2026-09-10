from __future__ import annotations

import asyncio
import logging
import time
from typing import Any, Awaitable, Callable, TypeVar

from ..config import load_settings
from ..inference.manager import MANAGER
from ..inference.profiles import resolve_profile
from ..providers.base import ChatMessage
from .chat_delivery import publish_owner_text
from .pack import build_persona_instructions, load_persona_pack
from .quiet import should_speak_chat_reply

logger = logging.getLogger(__name__)

# RFC-0068: ~2–3s before first useful output
THINK_ALOUD_DELAY_SECONDS = 2.5
THINK_ALOUD_COOLDOWN_SECONDS = 90.0

THINK_ALOUD_SYSTEM = """You are Jarvis speaking one brief status line aloud while work continues in the background.
Use the persona register below. One short sentence only (at most 18 words).
Dry, understated British-inspired butler tone; light humour is optional.
Do not read plans, steps, acceptance criteria, END STATE, tool names, or internal traces.
Output only the spoken line — no quotes, labels, or markdown."""

_job_has_spoken: dict[str, bool] = {}
_last_spoken_monotonic: float = 0.0

T = TypeVar("T")


def reset_think_aloud_state() -> None:
    """Test helper — clear per-job and cooldown bookkeeping."""
    _job_has_spoken.clear()
    global _last_spoken_monotonic
    _last_spoken_monotonic = 0.0


def think_aloud_allowed(task_id: str, settings: Any | None = None) -> bool:
    current = settings or load_settings()
    if not should_speak_chat_reply(current):
        return False
    if _job_has_spoken.get(task_id):
        return False
    if _last_spoken_monotonic and (time.monotonic() - _last_spoken_monotonic) < THINK_ALOUD_COOLDOWN_SECONDS:
        return False
    return True


def _mark_spoken(task_id: str) -> None:
    _job_has_spoken[task_id] = True
    global _last_spoken_monotonic
    _last_spoken_monotonic = time.monotonic()


async def generate_think_aloud_line(context: str) -> str:
    """Persona-flavored one-liner; requires loaded inference."""
    cleaned = (context or "").strip() or "Work is taking a moment longer than usual."
    if not MANAGER.provider:
        return ""

    pack = load_persona_pack()
    persona = build_persona_instructions(pack)
    settings = load_settings()
    profile = resolve_profile(settings.inference.profile)
    messages = [
        ChatMessage(role="system", content=f"{THINK_ALOUD_SYSTEM}\n\n{persona}"),
        ChatMessage(
            role="user",
            content=f"Situation (do not repeat verbatim): {cleaned}\nSpeak one brief in-character status line.",
        ),
    ]
    try:
        result = await MANAGER.chat(
            messages,
            tools=None,
            temperature=min(0.9, profile.temperature + 0.15),
            top_p=profile.top_p,
            top_k=profile.top_k,
            thinking=False,
            max_tokens=48,
        )
    except Exception as exc:
        logger.debug("Think-aloud generation failed: %s", exc)
        return ""
    line = (result.content or "").strip().splitlines()[0].strip()
    if len(line) > 220:
        line = line[:217].rstrip() + "..."
    return line


async def maybe_emit_think_aloud(task_id: str, *, context: str) -> dict[str, Any] | None:
    """Emit at most one think-aloud line for this task when gates pass."""
    settings = load_settings()
    if not think_aloud_allowed(task_id, settings):
        return None
    line = await generate_think_aloud_line(context)
    if not line:
        return None
    _mark_spoken(task_id)
    delivery = await publish_owner_text(
        line,
        title="Jarvis",
        kind="assistant",
        source="think_aloud",
        speak=True,
    )
    logger.info("Think-aloud for task %s (%s chars)", task_id, len(line))
    return delivery


async def run_with_think_aloud(
    task_id: str,
    *,
    context: str,
    operation: Callable[[], Awaitable[T]],
    delay_seconds: float | None = None,
) -> T:
    """Run ``operation``; if it exceeds ``delay_seconds``, may speak once (RFC-0068)."""
    delay = THINK_ALOUD_DELAY_SECONDS if delay_seconds is None else delay_seconds
    if not think_aloud_allowed(task_id):
        return await operation()

    finished = asyncio.Event()

    async def _watch() -> None:
        try:
            await asyncio.wait_for(finished.wait(), timeout=delay)
        except TimeoutError:
            if not finished.is_set():
                await maybe_emit_think_aloud(task_id, context=context)

    watcher = asyncio.create_task(_watch())
    try:
        return await operation()
    finally:
        finished.set()
        watcher.cancel()
        try:
            await watcher
        except asyncio.CancelledError:
            pass
