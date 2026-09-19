"""Deliver initial answers quickly, verify in the background, notify on material diffs."""

from __future__ import annotations

import asyncio
import re
from typing import Any

from ..config import load_settings
from ..inference.manager import MANAGER
from ..inference.profiles import resolve_profile
from ..providers.base import ChatMessage
from .chat_delivery import OWNER_CHAT_CHANNEL, publish_owner_text
from ..events import BUS

VERIFY_SYSTEM = """You double-check a draft assistant reply to the owner.
Return ONLY the corrected final answer if something material was wrong or missing.
If the draft is substantively fine, return exactly: SAME
Do not add preamble. No markdown fences."""

_background_tasks: set[asyncio.Task[Any]] = set()


def _normalize(text: str) -> str:
    return re.sub(r"\s+", " ", (text or "").strip().lower())


def materially_different(initial: str, verified: str) -> bool:
    a, b = _normalize(initial), _normalize(verified)
    if not b or b == "same":
        return False
    if a == b:
        return False
    if a in b or b in a:
        shorter = min(len(a), len(b))
        if shorter >= 24:
            return False
    return True


async def verify_reply(user_text: str, draft: str) -> str:
    settings = load_settings()
    if not MANAGER.provider:
        return ""
    profile = resolve_profile(settings.inference.profile)
    messages = [
        ChatMessage(role="system", content=VERIFY_SYSTEM),
        ChatMessage(
            role="user",
            content=f"Owner question:\n{user_text[:2000]}\n\nDraft reply:\n{draft[:4000]}",
        ),
    ]
    result = await MANAGER.chat(
        messages,
        temperature=min(0.35, profile.temperature),
        top_p=profile.top_p,
        top_k=profile.top_k,
        max_tokens=min(512, profile.max_tokens or 512),
        thinking=False,
    )
    return (getattr(result, "content", "") or "").strip()


async def _run_verify_and_notify(
    user_text: str,
    draft: str,
    *,
    source: str,
    speak: bool,
) -> None:
    try:
        checked = await verify_reply(user_text, draft)
        if not materially_different(draft, checked):
            await BUS.publish_ephemeral(
                OWNER_CHAT_CHANNEL,
                "verification",
                "Background check",
                "No material change after verification.",
                stage="verify",
            )
            return
        note = (
            "I've rechecked that answer in the background and have a refinement.\n\n"
            f"{checked}"
        )
        await publish_owner_text(note, source=source, speak=speak, user_prompt=user_text)
        await BUS.publish_ephemeral(
            OWNER_CHAT_CHANNEL,
            "verification",
            "Background check",
            checked[:2000],
            stage="verify",
        )
    except Exception as exc:
        await BUS.publish_ephemeral(
            OWNER_CHAT_CHANNEL,
            "verification",
            "Background check skipped",
            str(exc)[:400],
            stage="verify",
        )


def schedule_background_verification(
    user_text: str,
    draft: str,
    *,
    source: str = "owner_chat",
    speak: bool = True,
) -> None:
    cleaned = (draft or "").strip()
    if len(cleaned) < 40:
        return
    task = asyncio.create_task(
        _run_verify_and_notify(user_text, cleaned, source=source, speak=speak)
    )
    _background_tasks.add(task)
    task.add_done_callback(_background_tasks.discard)
