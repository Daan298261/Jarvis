from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

from .chat_delivery import publish_owner_text
from .session_state import load_owner_session_state, save_owner_session_state

logger = logging.getLogger(__name__)


def build_launch_greeting_text(*, now: datetime | None = None) -> str:
    """Short conversational greeting — not a plan or status dump."""
    moment = now or datetime.now(timezone.utc)
    hour = moment.hour
    if hour < 12:
        salutation = "Good morning"
    elif hour < 17:
        salutation = "Good afternoon"
    else:
        salutation = "Good evening"
    return (
        f"{salutation}. I'm at your service—ask me anything, or tell me what you'd like done on this machine."
    )


def _greeting_key(startup_id: str, *, day: str | None = None) -> str:
    utc_day = day or datetime.now(timezone.utc).date().isoformat()
    return f"{startup_id}:{utc_day}"


def should_send_greeting(startup_id: str) -> bool:
    state = load_owner_session_state()
    key = _greeting_key(startup_id)
    return state.get("last_greeting_key") != key


def mark_greeting_sent(startup_id: str) -> None:
    state = load_owner_session_state()
    state["last_greeting_key"] = _greeting_key(startup_id)
    state["last_greeting_at"] = datetime.now(timezone.utc).isoformat()
    save_owner_session_state(state)


async def maybe_send_launch_greeting(startup_id: str) -> dict[str, Any] | None:
    """Idempotent launch / first-owner-session greeting (once per cold start day)."""
    if not startup_id:
        return None
    if not should_send_greeting(startup_id):
        return None
    text = build_launch_greeting_text()
    delivery = await publish_owner_text(text, title="Greeting", kind="greeting", source="launch", speak=True)
    mark_greeting_sent(startup_id)
    logger.info("Enqueued launch greeting (%s chars)", len(text))
    return {"greeting": text, **delivery}
