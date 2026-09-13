# RFC-0084: Social weather stays conversational (live forecast, no scripts)

**Status:** implemented  
**Queue item:** Spoken/social factual asks must not enter the tool loop  
**Author:** Taco report via Cursor  
**Date:** 2026-09-13

## Problem

Asking “what is the weather in dinteloord, tomorrow” (no question mark, voice or typed) is classified as a mixed **task**. The agent loop then writes a retrieval **script** instead of answering. There is no meteorological tool loaded; Open-Meteo / KNMI is not consulted. Android Chat has a model picker but not a voice picker, does not show whether the conversation model is loaded, and realtime voice always submits with profile `auto`.

## Decision

1. Treat weather / short social factual asks as `conversation` even without `?`, unless the owner clearly asks for a file/script/install job.
2. On the conversation path, fetch a live Open-Meteo forecast (geocode + daily) and inject it as a briefing. Jarvis speaks one or two sentences. **Never** generate a retrieval script.
3. Companion `/models` reports whether the inference profile is actually loaded. Android Chat and Home show model + voice pickers and that loaded status. Realtime voice hello passes the selected UI model into `submit`.

**Will not:** add a weather *tool* to the agent registry (that would keep tempting script-writing); clone Marvel TTS; edit Architect spec docs.

## Acceptance criteria

- [x] `what is the weather in dinteloord, tomorrow` classifies as `conversation`
- [x] Conversation path receives an Open-Meteo briefing (or a clear lookup-failed note), not a coding plan
- [x] `create a weather script` still classifies as a tool task
- [x] Companion `/models` includes `inference.loaded` / active profile
- [x] Android Chat and Home expose model + voice pickers and loaded-model status
- [x] Realtime companion turns submit the selected inference profile
- [x] Unit tests pass (`python -m pytest`)

## Likely files

| Area | Paths |
| --- | --- |
| Backend | `backend/app/agent/planning.py`, `backend/app/agent/loop.py`, `backend/app/persona/weather.py`, `backend/app/persona/owner_chat.py`, `backend/app/mobile/service.py`, `backend/app/mobile/realtime_voice.py` |
| Android | `android/app/src/main/java/com/jarvis/companion/MainActivity.kt`, `CompanionModel.kt`, `RealtimeVoiceSession.kt` |
| Tests | `tests/test_planning.py`, `tests/test_owner_chat_greeting.py`, `tests/test_weather_briefing.py`, `tests/test_mobile_companion.py`, `tests/test_mobile_realtime_voice.py` |

## Out of scope

KNMI-specific credentials; Home IoT; installer; offensive tooling; HUD listen crash (D1).

## Notes

Open-Meteo is public, no API key. Desktop sign-off: speak the Dinteloord line with the 9B loaded and confirm a spoken forecast, not a Python file.
