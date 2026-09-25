"""RFC-0115 model handoff package (no hidden chain-of-thought)."""

from __future__ import annotations

from dataclasses import dataclass, field

from ..agent.compaction import compact_history, SUMMARY_MARKER
from ..providers.base import ChatMessage
from ..providers.completion_text import strip_think_blocks
from .inference_prompt import inference_message_text, strip_inference_only_lines


@dataclass
class ModelHandoff:
    user_request: str
    conversation_summary: str
    recent_turns: list[ChatMessage]
    working_state: str
    relevant_observations: list[str] = field(default_factory=list)
    failed_attempts: list[str] = field(default_factory=list)

    def as_dict(self) -> dict:
        return {
            "user_request": self.user_request,
            "conversation_summary": self.conversation_summary,
            "recent_turns": [{"role": m.role, "content": inference_message_text(m)} for m in self.recent_turns],
            "working_state": self.working_state,
            "relevant_observations": list(self.relevant_observations),
            "failed_attempts": list(self.failed_attempts),
        }


def _public_turn(message: ChatMessage) -> ChatMessage | None:
    if message.role not in {"user", "assistant"}:
        return None
    text = inference_message_text(message)
    text = strip_think_blocks(text, trim=False)
    if message.role == "assistant":
        text = strip_inference_only_lines(text)
    if not text.strip():
        return None
    if message.reasoning_content:
        # Hidden reasoning must not transfer (RFC-0083 / RFC-0115).
        pass
    return ChatMessage(role=message.role, content=text.strip())


def build_model_handoff(
    *,
    user_request: str,
    history: list[ChatMessage],
    working_state_block: str = "",
    observations: list[str] | None = None,
    failed_attempts: list[str] | None = None,
    keep_recent: int = 8,
) -> ModelHandoff:
    dialog = [m for m in history if m.role in {"user", "assistant", "tool"}]
    summary = ""
    if len(dialog) > keep_recent:
        keep = min(keep_recent, len(dialog))
        compacted = compact_history(dialog, keep_last=keep, working_state_block=working_state_block)
        for message in compacted:
            if message.role == "system" and isinstance(message.content, str) and SUMMARY_MARKER in message.content:
                summary = message.content
                break
    tail_start = max(0, len(dialog) - keep_recent)
    recent_raw = dialog[tail_start:]
    recent: list[ChatMessage] = []
    for message in recent_raw:
        cleaned = _public_turn(message)
        if cleaned:
            recent.append(cleaned)
    return ModelHandoff(
        user_request=user_request,
        conversation_summary=summary,
        recent_turns=recent,
        working_state=working_state_block,
        relevant_observations=list(observations or [])[-8:],
        failed_attempts=list(failed_attempts or [])[-8:],
    )


def handoff_system_message(handoff: ModelHandoff) -> str:
    turns = "\n".join(
        f"{m.role}: {m.content}" for m in handoff.recent_turns[-10:]
    )
    obs = "\n".join(f"- {o}" for o in handoff.relevant_observations) or "- none"
    failed = "\n".join(f"- {f}" for f in handoff.failed_attempts) or "- none"
    parts = [
        "Model handoff (continue the same owner conversation; do not repeat failed approaches).",
        f"Current user request (verbatim):\n{handoff.user_request}",
    ]
    if handoff.conversation_summary:
        parts.append(handoff.conversation_summary)
    if turns:
        parts.append(f"Recent turns:\n{turns}")
    if handoff.working_state:
        parts.append(handoff.working_state)
    parts.append(f"Relevant observations:\n{obs}")
    parts.append(f"Failed attempts:\n{failed}")
    return "\n\n".join(parts)
