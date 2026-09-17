from __future__ import annotations

from typing import Any

BROWSER_USE_WORKER_ID = "browser-use"


def _state_fields(state: Any) -> tuple[str, str]:
    url = ""
    title = ""
    if state is None:
        return url, title
    if hasattr(state, "url") and getattr(state, "url", None):
        url = str(getattr(state, "url"))
    if hasattr(state, "title") and getattr(state, "title", None):
        title = str(getattr(state, "title"))
    if hasattr(state, "to_dict"):
        try:
            state_dict = state.to_dict()
        except Exception:
            state_dict = {}
        if isinstance(state_dict, dict):
            if state_dict.get("url"):
                url = str(state_dict["url"])
            if state_dict.get("title"):
                title = str(state_dict["title"])
    return url, title


def structured_payload_from_history(history: Any, *, start_url: str | None = None) -> dict[str, Any]:
    """Map a browser-use AgentHistoryList into Jarvis ingest-friendly fields."""
    final_text = ""
    if history is not None and hasattr(history, "final_result"):
        try:
            final_text = str(history.final_result() or "")
        except Exception:
            final_text = ""

    structured_obj: Any = None
    if history is not None and hasattr(history, "structured_output"):
        try:
            structured_obj = history.structured_output
        except Exception:
            structured_obj = None
    if structured_obj is not None and hasattr(structured_obj, "model_dump"):
        try:
            dump = structured_obj.model_dump(mode="json")
            if isinstance(dump, dict):
                for key in ("text", "content", "extracted_text", "body"):
                    if dump.get(key) and not final_text:
                        final_text = str(dump[key])
        except Exception:
            pass

    resolved_url = (start_url or "").strip()
    title = ""
    if structured_obj is not None and hasattr(structured_obj, "model_dump"):
        try:
            dump = structured_obj.model_dump(mode="json")
            if isinstance(dump, dict) and dump.get("title"):
                title = str(dump["title"])
        except Exception:
            pass

    action_trace: list[dict[str, Any]] = []
    extracted_chunks: list[str] = []

    items = getattr(history, "history", None) or []
    for index, item in enumerate(items):
        step: dict[str, Any] = {"step": index + 1}
        state_url, state_title = _state_fields(getattr(item, "state", None))
        if state_url:
            resolved_url = state_url
        if state_title:
            title = state_title

        model_output = getattr(item, "model_output", None)
        actions = getattr(model_output, "action", None) if model_output is not None else None
        if actions:
            serialized: list[Any] = []
            for action in actions[:5]:
                if hasattr(action, "model_dump"):
                    serialized.append(action.model_dump(exclude_none=True, mode="json"))
                else:
                    serialized.append(str(action))
            step["actions"] = serialized
        next_goal = getattr(model_output, "next_goal", None) if model_output is not None else None
        if next_goal:
            step["next_goal"] = str(next_goal)[:240]

        for result in getattr(item, "result", None) or []:
            content = getattr(result, "extracted_content", None)
            if content:
                text = str(content).strip()
                if text:
                    extracted_chunks.append(text[:800])
                    step.setdefault("extracted", []).append(text[:400])
            err = getattr(result, "error", None)
            if err:
                step.setdefault("errors", []).append(str(err)[:240])

        if len(step) > 1:
            action_trace.append(step)
        if len(action_trace) >= 32:
            break

    if not action_trace and history is not None and hasattr(history, "agent_steps"):
        try:
            for index, summary in enumerate(history.agent_steps()[:12]):
                action_trace.append({"step": index + 1, "summary": str(summary)[:700]})
        except Exception:
            pass

    extracted_text = final_text.strip()
    if not extracted_text and extracted_chunks:
        extracted_text = "\n\n".join(dict.fromkeys(extracted_chunks))

    return {
        "url": resolved_url,
        "title": title,
        "extracted_text": extracted_text,
        "action_trace": action_trace,
        "steps": len(items) if hasattr(items, "__len__") else 0,
    }


def format_browser_use_output(payload: dict[str, Any]) -> str:
    parts: list[str] = []
    if payload.get("title"):
        parts.append(f"Title: {payload['title']}")
    if payload.get("url"):
        parts.append(f"URL: {payload['url']}")
    body = str(payload.get("extracted_text") or "").strip()
    if body:
        parts.append(body)
    trace = payload.get("action_trace")
    if isinstance(trace, list) and trace:
        parts.append(f"Action trace: {len(trace)} step(s) recorded in tool data.")
    return "\n".join(parts).strip() or "Browser Use finished."


def browser_use_tool_result_data(
    *,
    goal: str,
    structured: dict[str, Any],
    start_url: str | None,
    session_reused: bool,
) -> dict[str, Any]:
    return {
        "backend": BROWSER_USE_WORKER_ID,
        "goal": goal,
        "url": structured.get("url") or start_url or "",
        "title": structured.get("title") or "",
        "extracted_text": structured.get("extracted_text") or "",
        "action_trace": structured.get("action_trace") or [],
        "steps": structured.get("steps") or 0,
        "session_reused": session_reused,
    }


def browser_use_ingest_payload(*, data: dict[str, Any] | None, output: str = "") -> dict[str, Any]:
    """Normalize browser_use tool data for ingest fallbacks."""
    payload = data if isinstance(data, dict) else {}
    text = str(payload.get("extracted_text") or "").strip()
    if not text:
        text = (output or "").strip()
    trace = payload.get("action_trace")
    return {
        "url": str(payload.get("url") or "").strip(),
        "title": str(payload.get("title") or "").strip(),
        "text": text,
        "action_trace": trace if isinstance(trace, list) else [],
        "steps": int(payload.get("steps") or 0),
        "session_reused": bool(payload.get("session_reused")),
    }
