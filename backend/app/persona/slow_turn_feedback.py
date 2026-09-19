"""Keep the owner informed when worker turns exceed latency budgets."""

from __future__ import annotations

import asyncio
import time
from typing import Any, Awaitable, Callable

from ..config import AppSettings, load_settings
from ..providers.base import ChatMessage
from .chat_delivery import publish_owner_text

NUDGE_AFTER_SECONDS = 60.0
REPEAT_EVERY_SECONDS = 45.0

SLOW_NUDGE_SYSTEM = """You are Jarvis updating the owner while a larger model is still working.
One or two short sentences. Explain briefly why the turn may take longer (context size, tools, verification).
Do not claim success. Do not invent results. British-inspired, calm tone."""

ExplainFn = Callable[[str, float], Awaitable[str] | str]


async def default_slow_explanation(user_text: str, elapsed_s: float) -> str:
    from ..agent.front_responder import generate_front_reply

    settings = load_settings()
    prompt = (
        f"The owner asked: {user_text[:400]}\n"
        f"Elapsed seconds: {int(elapsed_s)}.\n"
        "Give a brief status line."
    )
    front = await generate_front_reply(
        prompt,
        history=[ChatMessage(role="system", content=SLOW_NUDGE_SYSTEM)],
        settings=settings,
    )
    if front.text:
        return front.text.strip()
    if elapsed_s >= 120:
        return "Still working through a heavier pass — nearly there."
    return "Still on it — the larger model is chewing through the details."


class SlowTurnNudger:
    def __init__(
        self,
        user_text: str,
        *,
        started: float | None = None,
        explain: ExplainFn | None = None,
        speak: bool = True,
        source: str = "owner_chat",
    ) -> None:
        self.user_text = (user_text or "").strip()
        self.started = started if started is not None else time.perf_counter()
        self.explain = explain or default_slow_explanation
        self.speak = speak
        self.source = source
        self._task: asyncio.Task[None] | None = None
        self._nudges = 0

    async def _loop(self) -> None:
        try:
            await asyncio.sleep(NUDGE_AFTER_SECONDS)
            while True:
                elapsed = time.perf_counter() - self.started
                maybe = self.explain(self.user_text, elapsed)
                text = await maybe if asyncio.iscoroutine(maybe) else maybe
                text = (text or "").strip()
                if text:
                    self._nudges += 1
                    await publish_owner_text(
                        text,
                        source=self.source,
                        speak=self.speak,
                        user_prompt=self.user_text,
                    )
                await asyncio.sleep(REPEAT_EVERY_SECONDS)
        except asyncio.CancelledError:
            return

    def start(self) -> None:
        if self._task is None:
            self._task = asyncio.create_task(self._loop())

    async def stop(self) -> dict[str, Any]:
        if self._task is None:
            return {"nudges": self._nudges}
        self._task.cancel()
        try:
            await self._task
        except asyncio.CancelledError:
            pass
        self._task = None
        return {"nudges": self._nudges}
