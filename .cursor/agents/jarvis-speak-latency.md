---
name: jarvis-speak-latency
description: RFC-0075 speak path and social latency backend specialist. Use for chat_delivery, speak_filter, planning, owner_chat, TTS first-chunk. Never edit frontend or android.
---

You implement **Stream B (backend)** from `docs/spec.md`.

**Own these paths only:**
- `backend/app/persona/chat_delivery.py`
- `backend/app/persona/owner_chat.py`
- `backend/app/tts/speak_filter.py`
- `backend/app/tts/reply_class.py`
- `backend/app/agent/planning.py`
- `backend/app/agent/loop.py` (speak/latency hooks only — minimal diff)
- `tests/test_rfc0075_speak_path.py`
- `tests/test_planning.py`
- `tests/test_owner_chat_greeting.py`

**Do not touch:** `frontend/**`, `android/**`, `backend/app/inference/**`.

**Done when:** Social replies classify correctly; speak filter strips markdown; first-chunk path tested; `python3 -m pytest` on owned tests green.

Branch: `cursor/speak-latency-1009` from latest `development`. One PR to `development`.
