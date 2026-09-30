from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import threading
import time
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from ..config import data_dir, load_settings
from ..events import BUS
from ..inference.manager import MANAGER
from ..providers.base import ChatMessage
from ..providers.completion_text import visible_completion_text
from ..persona.chat_delivery import OWNER_CHAT_CHANNEL, publish_owner_text

log = logging.getLogger(__name__)

VERIFIED_OK_TOKEN = "VERIFIED_OK"
LEGACY_SAME_TOKEN = "SAME"
FOLLOWUP_PREFIX = "I double-checked and have an update: "
OWNER_SCOPE = "owner"
CORRECTIONS_FILENAME = "verified_corrections.jsonl"

VERIFY_SYSTEM = """You are an independent verification pass for a conversational assistant.
Given the owner's question and the assistant's answer, decide whether the answer needs correction.
If the answer is accurate and complete enough for the question, reply EXACTLY: VERIFIED_OK
If correction is needed, reply with the corrected answer only — no preamble, labels, or markdown fences."""

# RFC-0167: admit research / coding / planning / consequential workflows — not universal chat.
_ADMIT_TASK_CLASSES = frozenset(
    {
        "research",
        "software engineering",
        "browser automation",
        "system administration",
        "data processing",
        "document processing",
        "office",
        "windows gui",
        "filesystem",
        "shell",
        "multimodal",
        "long-horizon autonomous",
        "mixed",
    }
)

_GREETING_OR_ACK = re.compile(
    r"(?i)^\s*("
    r"hi|hello|hey|yo|sup|thanks|thank you|thx|"
    r"good\s+(morning|afternoon|evening)|"
    r"how are you(?:\s+doing)?|"
    r"nice to (?:meet|see) you"
    r")\s*[!.?]*\s*$"
)

_CONSEQUENTIAL_HINTS = re.compile(
    r"(?i)\b("
    r"research|compare|summarize|summary|plan|planning|roadmap|"
    r"implement|refactor|debug|pytest|compile|deploy|architecture|"
    r"security|investigate|analyze|analysis|design|review|"
    r"write (?:the |some )?code|fix (?:the|this|my)|"
    r"acceptance criteria|trade-?offs?"
    r")\b"
)

_SUBSTANTIAL_ANSWER_CHARS = 120

_active_keys: set[str] = set()
_background_tasks: set[asyncio.Task[Any]] = set()
_STATS_LOCK = threading.Lock()
_STATS: dict[str, Any] = {
    "hit": 0,
    "skip": 0,
    "verified_ok": 0,
    "correct": 0,
    "error": 0,
    "unhelpful": 0,
    "by_reason": {},
    "last": None,
}


class VerificationUnavailable(RuntimeError):
    """Raised when a required verify pass cannot run (fail closed)."""


@dataclass(frozen=True)
class VerificationAdmission:
    admitted: bool
    reason: str

    def as_dict(self) -> dict[str, Any]:
        return {"admitted": self.admitted, "reason": self.reason}


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
    """True only for an explicit VERIFIED_OK / SAME token — empty is not success."""
    cleaned = normalize_verification_reply(text)
    if not cleaned:
        return False
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


def _resolve_route_kind(user_prompt: str, route_kind: str | None) -> str:
    kind = (route_kind or "").strip()
    if kind:
        return kind
    try:
        from .planning import route_request

        return route_request(user_prompt).kind
    except Exception:
        return ""


def _resolve_task_class(user_prompt: str, task_class: str | None, route_kind: str) -> str:
    klass = (task_class or "").strip().lower()
    if klass:
        return klass
    try:
        from .planning import CONVERSATION_CLASS, classify_task, route_request

        if route_kind:
            return classify_task(user_prompt) if route_kind == "managed_task" else CONVERSATION_CLASS
        return route_request(user_prompt).task_class
    except Exception:
        return ""


def decide_verification_admission(
    *,
    user_prompt: str,
    answer: str,
    route_kind: str | None = None,
    task_class: str | None = None,
) -> VerificationAdmission:
    """RFC-0167 risk/task/quality gate — verification is not universal."""
    prompt = (user_prompt or "").strip()
    body = (answer or "").strip()
    if len(prompt) < 2 or len(body) < 2:
        return VerificationAdmission(False, "too_short")

    # Cheap social turns skip before route classification (RFC-0167 low-risk).
    if _GREETING_OR_ACK.match(prompt):
        return VerificationAdmission(False, "greeting")

    kind = _resolve_route_kind(prompt, route_kind)
    from .planning import DIRECT_LOOKUP, DIRECT_REPLY, MANAGED_TASK

    if kind in {DIRECT_REPLY, DIRECT_LOOKUP}:
        return VerificationAdmission(False, "direct_route")

    klass = _resolve_task_class(prompt, task_class, kind)
    if kind == MANAGED_TASK:
        return VerificationAdmission(True, "managed_task")
    if klass in _ADMIT_TASK_CLASSES:
        return VerificationAdmission(True, f"task_class:{klass}")
    if _CONSEQUENTIAL_HINTS.search(prompt):
        return VerificationAdmission(True, "consequential")
    if len(body) >= _SUBSTANTIAL_ANSWER_CHARS and not _GREETING_OR_ACK.match(body):
        return VerificationAdmission(True, "substantial_answer")
    return VerificationAdmission(False, "low_risk")


def verification_applicable(
    *,
    user_prompt: str,
    answer: str,
    route_kind: str | None = None,
    task_class: str | None = None,
) -> bool:
    return decide_verification_admission(
        user_prompt=user_prompt,
        answer=answer,
        route_kind=route_kind,
        task_class=task_class,
    ).admitted


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


def _note_stat(label: str, *, reason: str = "", extra: dict[str, Any] | None = None) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "label": label,
        "reason": reason,
        "ts": round(time.time(), 3),
    }
    if extra:
        payload.update(extra)
    with _STATS_LOCK:
        if label in _STATS and isinstance(_STATS[label], int):
            _STATS[label] = int(_STATS[label]) + 1
        reasons: dict[str, int] = _STATS["by_reason"]  # type: ignore[assignment]
        key = f"{label}:{reason}" if reason else label
        reasons[key] = int(reasons.get(key, 0)) + 1
        _STATS["last"] = payload
    return payload


def background_verify_stats() -> dict[str, Any]:
    with _STATS_LOCK:
        return {
            "hit": int(_STATS["hit"]),
            "skip": int(_STATS["skip"]),
            "verified_ok": int(_STATS["verified_ok"]),
            "correct": int(_STATS["correct"]),
            "error": int(_STATS["error"]),
            "unhelpful": int(_STATS["unhelpful"]),
            "by_reason": dict(_STATS["by_reason"] or {}),
            "last": dict(_STATS["last"] or {}) if _STATS["last"] else None,
        }


def reset_background_verify_stats() -> None:
    with _STATS_LOCK:
        _STATS["hit"] = 0
        _STATS["skip"] = 0
        _STATS["verified_ok"] = 0
        _STATS["correct"] = 0
        _STATS["error"] = 0
        _STATS["unhelpful"] = 0
        _STATS["by_reason"] = {}
        _STATS["last"] = None


def corrections_path() -> Path:
    return data_dir() / CORRECTIONS_FILENAME


def record_verified_correction(
    *,
    user_prompt: str,
    initial_answer: str,
    correction: str,
    conversation_id: str | None = None,
    task_id: str | None = None,
    source: str = "owner_chat",
    route_kind: str | None = None,
    task_class: str | None = None,
) -> dict[str, Any]:
    """Durable before/after/provenance correction (owner scope). No prompt rewrite / fine-tune."""
    now = datetime.now(timezone.utc).isoformat()
    record_id = uuid.uuid4().hex
    record: dict[str, Any] = {
        "id": record_id,
        "owner_scope": OWNER_SCOPE,
        "source": source,
        "source_type": "background_verify",
        "conversation_id": conversation_id or "",
        "task_id": task_id or "",
        "user_prompt": (user_prompt or "").strip()[:4000],
        "before": (initial_answer or "").strip()[:4000],
        "after": (correction or "").strip()[:4000],
        "route_kind": (route_kind or "").strip(),
        "task_class": (task_class or "").strip(),
        "created_at": now,
        "provenance": {
            "source_type": "background_verify",
            "source_id": record_id,
            "owner_scope": OWNER_SCOPE,
            "conversation_id": conversation_id or "",
            "task_id": task_id or "",
            "created_at": now,
            "note": "RFC-0128/0167 verified correction — store only; never auto-rewrites prompts",
        },
    }
    path = corrections_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(record, ensure_ascii=False) + "\n")

    vault_result: dict[str, Any] | None = None
    vault_error: str | None = None
    try:
        from ..memory.obsidian_vault import persist_verified_correction

        vault_result = persist_verified_correction(
            user_prompt=user_prompt,
            initial_answer=initial_answer,
            correction=correction,
            conversation_id=conversation_id,
            provenance=record["provenance"],
        )
        if isinstance(vault_result, dict) and vault_result.get("ok") is False:
            vault_error = str(vault_result.get("error") or "vault_persist_failed")[:400]
            log.warning("Obsidian verified-correction persist failed: %s", vault_error)
    except Exception as exc:
        vault_error = str(exc)[:400]
        log.exception("Obsidian verified-correction persist raised")
        vault_result = {"ok": False, "error": vault_error}

    return {
        "ok": True,
        "record": record,
        "path": str(path),
        "vault": vault_result,
        "vault_error": vault_error,
    }


async def verify_reply(user_text: str, draft: str) -> str:
    return await run_verification_model_call(user_text, draft)


async def run_verification_model_call(user_prompt: str, answer: str) -> str:
    if not MANAGER.provider or not MANAGER.state.loaded:
        raise VerificationUnavailable("model_unloaded")
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
) -> dict[str, Any]:
    from ..persona.owner_chat import append_owner_assistant_message

    followup = f"{FOLLOWUP_PREFIX}{correction.strip()}"
    append_owner_assistant_message(conversation_id, followup)
    persist: dict[str, Any] = {"ok": True}
    try:
        from ..persona.owner_chat import get_conversation
        from ..projects.portal_store import save_owner_conversation

        if conversation_id:
            await save_owner_conversation(conversation_id, get_conversation(conversation_id))
    except Exception as exc:
        persist = {"ok": False, "error": str(exc)[:400]}
        log.warning("Owner conversation persist after verify correction failed: %s", persist["error"])
    await publish_owner_text(
        followup,
        source="owner_chat",
        speak=speak,
        user_prompt=user_prompt,
    )
    return persist


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


async def _emit_verify_failure(*, channel: str, reason: str, detail: str = "") -> None:
    body = reason if not detail else f"{reason}: {detail}"[:400]
    await BUS.publish_ephemeral(
        channel,
        "background_verify",
        "Background verify failed closed",
        body,
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
    route_kind: str | None = None,
    task_class: str | None = None,
) -> dict[str, Any]:
    if not background_verify_enabled():
        _note_stat("skip", reason="disabled")
        return {"skipped": True, "reason": "disabled"}

    admission = decide_verification_admission(
        user_prompt=user_prompt,
        answer=answer,
        route_kind=route_kind,
        task_class=task_class,
    )
    if not admission.admitted:
        _note_stat("skip", reason=admission.reason, extra={"route_kind": route_kind or "", "task_class": task_class or ""})
        return {"skipped": True, "reason": admission.reason, "admission": admission.as_dict()}

    key = _dedupe_key(
        source=source,
        conversation_id=conversation_id,
        task_id=task_id,
        answer=answer,
    )
    if key in _active_keys:
        _note_stat("skip", reason="duplicate")
        return {"skipped": True, "reason": "duplicate"}
    _active_keys.add(key)
    channel = task_id or OWNER_CHAT_CHANNEL
    _note_stat(
        "hit",
        reason=admission.reason,
        extra={"source": source, "route_kind": route_kind or "", "task_class": task_class or ""},
    )
    try:
        raw = await run_verification_model_call(user_prompt, answer)
        cleaned = normalize_verification_reply(raw)
        if not cleaned:
            _note_stat("error", reason="empty_verifier_output")
            await _emit_verify_failure(channel=channel, reason="empty_verifier_output")
            return {"error": "empty_verifier_output", "fail_closed": True}

        if is_verified_ok(cleaned):
            await _emit_verified_debug(channel=channel)
            _note_stat("verified_ok", reason=admission.reason)
            return {"verified_ok": True}

        if answers_equivalent(cleaned, answer):
            # Echoed the draft instead of VERIFIED_OK — silent to owner, surfaced for tuning.
            await _emit_verified_debug(channel=channel)
            _note_stat("unhelpful", reason="echoed_answer")
            return {"verified_ok": True, "unhelpful": True, "reason": "echoed_answer"}

        correction = cleaned
        if not materially_different(answer, correction):
            await _emit_verified_debug(channel=channel)
            _note_stat("unhelpful", reason="not_material")
            return {"verified_ok": True, "unhelpful": True, "reason": "not_material"}

        correction_meta: dict[str, Any] | None = None
        if source == "owner_chat":
            persist = await publish_owner_correction(
                correction,
                user_prompt=user_prompt,
                conversation_id=conversation_id,
                speak=speak,
            )
            correction_meta = record_verified_correction(
                user_prompt=user_prompt,
                initial_answer=answer,
                correction=correction,
                conversation_id=conversation_id,
                source=source,
                route_kind=route_kind,
                task_class=task_class,
            )
            if not persist.get("ok"):
                correction_meta["conversation_persist_error"] = persist.get("error")
            if correction_meta.get("vault_error"):
                log.warning(
                    "Verified correction stored locally; vault mirror failed: %s",
                    correction_meta["vault_error"],
                )
        elif task_id:
            await publish_task_correction(task_id, correction, user_prompt=user_prompt)
            correction_meta = record_verified_correction(
                user_prompt=user_prompt,
                initial_answer=answer,
                correction=correction,
                task_id=task_id,
                source=source,
                route_kind=route_kind,
                task_class=task_class,
            )
        _note_stat("correct", reason=admission.reason)
        return {
            "corrected": True,
            "text": correction,
            "correction_record": correction_meta,
        }
    except VerificationUnavailable as exc:
        reason = str(exc)[:400] or "verification_unavailable"
        _note_stat("error", reason=reason)
        await _emit_verify_failure(channel=channel, reason=reason)
        return {"error": reason, "fail_closed": True}
    except Exception as exc:
        detail = str(exc)[:400]
        _note_stat("error", reason="inference_error")
        await _emit_verify_failure(channel=channel, reason="inference_error", detail=detail)
        return {"error": detail, "fail_closed": True}
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
    route_kind: str | None = None,
    task_class: str | None = None,
) -> bool:
    """Schedule async verify when enabled and admitted. Returns True if a task was created."""
    answer = (draft or "").strip()
    if not background_verify_enabled():
        _note_stat("skip", reason="disabled")
        return False
    admission = decide_verification_admission(
        user_prompt=user_prompt,
        answer=answer,
        route_kind=route_kind,
        task_class=task_class,
    )
    if not admission.admitted:
        _note_stat("skip", reason=admission.reason)
        return False
    task = asyncio.create_task(
        execute_background_verification(
            user_prompt=user_prompt,
            answer=answer,
            source=source,
            conversation_id=conversation_id,
            task_id=task_id,
            speak=speak,
            route_kind=route_kind,
            task_class=task_class,
        ),
        name=f"jarvis-bg-verify:{source}:{task_id or conversation_id or 'chat'}",
    )
    _background_tasks.add(task)
    task.add_done_callback(_background_tasks.discard)
    return True


def reset_background_verify_state() -> None:
    _active_keys.clear()
    reset_background_verify_stats()
