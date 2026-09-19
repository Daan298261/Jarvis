from __future__ import annotations

import asyncio
import os
import re
from typing import Any

from ..config import load_settings
from ..events import BUS
from ..inference.manager import MANAGER
from ..providers.base import ChatMessage
from ..providers.completion_text import visible_completion_text
from ..persona.chat_delivery import OWNER_CHAT_CHANNEL, publish_owner_text

VERIFIED_OK_TOKEN = "VERIFIED_OK"
LEGACY_SAME_TOKEN = "SAME"
FOLLOWUP_PREFIX = "I double-checked and have an update: "

VERIFY_SYSTEM = """You are an independent verification pass for a conversational assistant.
Given the owner's question and the assistant's answer, decide whether the answer needs correction.
If the answer is accurate and complete enough for the question, reply EXACTLY: VERIFIED_OK
If correction is needed, reply with the corrected answer only — no preamble, labels, or markdown fences."""

_active_keys: set[str] = set()
_background_tasks: set[asyncio.Task[Any]] = set()


def _env_disabled() -> bool:
    raw = os.environ.get("JARVIS_BACKGROUND_VERIFY", "1").strip().lower()
    return raw in {"0", "false", "no", "off"}


def background_verify_enabled() -> bool:
    if _env_disabled():
        return False
    settings = load_settings()
    return bool(getattr(settings.dialogue, "background_verify", True))


def normalize_verification_reply(text: str) -> str:
    return (text or "").strip()


def is_verified_ok(text: str) -> bool:
    cleaned = normalize_verification_reply(text)
    if not cleaned:
        return True
    upper = cleaned.upper()
    if upper in {VERIFIED_OK_TOKEN, LEGACY_SAME_TOKEN}:
        return True
    if upper.startswith(VERIFIED_OK_TOKEN) and len(cleaned) <= len(VERIFIED_OK_TOKEN) + 4:
        return True
    return False


def answers_equivalent(left: str, right: str) -> bool:
    a = re.sub(r"\s+", " ", (left or "").strip().lower())
    b = re.sub(r"\s+", " ", (right or "").strip().lower())
    return bool(a) and a == b


def materially_different(initial: str, verified: str) -> bool:
    """True when the verifier returned a substantive correction (legacy helper)."""
    if is_verified_ok(verified):
        return False
    if answers_equivalent(initial, verified):
        return False
    body = normalize_verification_reply(verified)
    if not body:
        return False
    a = re.sub(r"\s+", " ", (initial or "").strip().lower())
    b = re.sub(r"\s+", " ", body.lower())
    if a == b:
        return False
    if a in b or b in a:
        shorter = min(len(a), len(b))
        if shorter >= 24:
            return False
    return True


def verification_applicable(*, user_prompt: str, answer: str) -> bool:
    prompt = (user_prompt or "").strip()
    body = (answer or "").strip()
    if len(prompt) < 2 or len(body) < 2:
        return False
    return True


def build_verification_messages(user_prompt: str, answer: str) -> list[ChatMessage]:
    user_block = (
        f"Owner question:\n{user_prompt.strip()}\n\n"
        f"Assistant answer:\n{answer.strip()}\n\n"
        "Does this answer need correction?"
    )
    return [
        ChatMessage(role="system", content=VERIFY_SYSTEM),
        ChatMessage(role="user", content=user_block),
    ]


def _dedupe_key(*, source: str, conversation_id: str | None, task_id: str | None, answer: str) -> str:
    anchor = task_id or conversation_id or "anon"
    digest = abs(hash((source, anchor, answer.strip()))) % (10**9)
    return f"{source}:{anchor}:{digest}"


async def verify_reply(user_text: str, draft: str) -> str:
    return await run_verification_model_call(user_text, draft)


async def run_verification_model_call(user_prompt: str, answer: str) -> str:
    if not MANAGER.provider or not MANAGER.state.loaded:
        return VERIFIED_OK_TOKEN
    messages = build_verification_messages(user_prompt, answer)
    result = await MANAGER.chat(
        messages,
        max_tokens=512,
        thinking=False,
    )
    if hasattr(result, "content"):
        return visible_completion_text(result.content, getattr(result, "reasoning", None))
    return visible_completion_text(result)


async def publish_owner_correction(
    correction: str,
    *,
    user_prompt: str,
    conversation_id: str | None,
    speak: bool = True,
) -> None:
    from ..persona.owner_chat import append_owner_assistant_message

    followup = f"{FOLLOWUP_PREFIX}{correction.strip()}"
    append_owner_assistant_message(conversation_id, followup)
    try:
        from ..persona.owner_chat import get_conversation
        from ..projects.portal_store import save_owner_conversation

        if conversation_id:
            await save_owner_conversation(conversation_id, get_conversation(conversation_id))
    except Exception:
        pass
    await publish_owner_text(
        followup,
        source="owner_chat",
        speak=speak,
        user_prompt=user_prompt,
    )


async def publish_task_correction(
    task_id: str,
    correction: str,
    *,
    user_prompt: str,
) -> None:
    from ..agent.compaction import deserialize_messages, serialize_messages
    from ..db.models import Task
    from ..db.session import SessionLocal

    followup = f"{FOLLOWUP_PREFIX}{correction.strip()}"
    async with SessionLocal() as session:
        task = await session.get(Task, task_id)
        if not task:
            return
        messages = deserialize_messages(task.conversation_json or "[]")
        messages.append(ChatMessage(role="assistant", content=followup))
        task.conversation_json = serialize_messages(messages)
        task.result = followup
        await session.commit()

    await publish_owner_text(
        followup,
        source="task_chat",
        speak=True,
        user_prompt=user_prompt,
    )
    await BUS.publish(
        task_id,
        "chat_tts",
        "Verification update",
        followup,
        stage="verify",
    )
    await BUS.publish(
        task_id,
        "assistant",
        "Verification update",
        followup,
        stage="verify",
    )


async def _emit_verified_debug(*, channel: str) -> None:
    await BUS.publish_ephemeral(
        channel,
        "background_verify",
        "Background verify",
        VERIFIED_OK_TOKEN,
        stage="verify",
    )


async def execute_background_verification(
    *,
    user_prompt: str,
    answer: str,
    source: str,
    conversation_id: str | None = None,
    task_id: str | None = None,
    speak: bool = True,
) -> dict[str, Any]:
    if not background_verify_enabled() or not verification_applicable(user_prompt=user_prompt, answer=answer):
        return {"skipped": True}

    key = _dedupe_key(
        source=source,
        conversation_id=conversation_id,
        task_id=task_id,
        answer=answer,
    )
    if key in _active_keys:
        return {"skipped": True, "reason": "duplicate"}
    _active_keys.add(key)
    try:
        raw = await run_verification_model_call(user_prompt, answer)
        if is_verified_ok(raw) or answers_equivalent(raw, answer):
            channel = task_id or OWNER_CHAT_CHANNEL
            await _emit_verified_debug(channel=channel)
            return {"verified_ok": True}

        correction = normalize_verification_reply(raw)
        if not correction or not materially_different(answer, correction):
            channel = task_id or OWNER_CHAT_CHANNEL
            await _emit_verified_debug(channel=channel)
            return {"verified_ok": True}

        if source == "owner_chat":
            await publish_owner_correction(
                correction,
                user_prompt=user_prompt,
                conversation_id=conversation_id,
                speak=speak,
            )
        elif task_id:
            await publish_task_correction(task_id, correction, user_prompt=user_prompt)
        return {"corrected": True, "text": correction}
    except Exception as exc:
        channel = task_id or OWNER_CHAT_CHANNEL
        await BUS.publish_ephemeral(
            channel,
            "background_verify",
            "Background verify skipped",
            str(exc)[:400],
            stage="verify",
        )
        return {"error": str(exc)[:400]}
    finally:
        _active_keys.discard(key)


def schedule_background_verification(
    user_prompt: str,
    draft: str,
    *,
    source: str = "owner_chat",
    speak: bool = True,
    conversation_id: str | None = None,
    task_id: str | None = None,
) -> None:
    answer = (draft or "").strip()
    if not background_verify_enabled() or not verification_applicable(user_prompt=user_prompt, answer=answer):
        return
    task = asyncio.create_task(
        execute_background_verification(
            user_prompt=user_prompt,
            answer=answer,
            source=source,
            conversation_id=conversation_id,
            task_id=task_id,
            speak=speak,
        ),
        name=f"jarvis-bg-verify:{source}:{task_id or conversation_id or 'chat'}",
    )
    _background_tasks.add(task)
    task.add_done_callback(_background_tasks.discard)


def reset_background_verify_state() -> None:
    _active_keys.clear()
