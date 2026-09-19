# RFC-0130: Selectable session personalities

**Status:** implemented  
**Author:** Cursor cloud worker  
**Date:** 2026-03-21

## Problem

Dialogue personality presets (RFC-0063) adjust tone rewriting, but they do not give the owner a **session mode** with distinct HUD cues and a dedicated system-prompt addendum for coding, research, or concise work. Owners need to say “start a coding session” and see Jarvis shift register and UI without merging Instagram persona trees (RFC-0104).

## Decision

1. Define **session personality packs** (`default`, `coding`, `research`, `concise`) with `id`, `display_name`, `system_prefix_addendum`, `hud_theme` token, and optional TTS voice hint.
2. Persist `active_id` in `AppSettings.session_personality` via `backend/app/persona/session_personality.py`.
3. Expose **GET/POST** `/api/personality` and optional `session_personality_active_id` on settings PUT.
4. **Intent hook** in owner chat: phrases like “start a coding session” / “switch to coding mode” auto-switch and return a spoken acknowledgement without invoking the worker model.
5. Inject the active addendum into `build_persona_instructions`, owner chat system prompt, and `front_responder` system prompt.
6. Portal: settings selector + `data-personality` on HUD root with CSS variable accents (Daybreak orange/black family).

**Not in this RFC:** full HUD layout redesign, per-personality avatar assets, or TTS voice auto-switch (hints only).

## Acceptance criteria

- [x] Packs listed and selectable via API and settings UI
- [x] Owner phrase switches personality and acknowledges
- [x] Prompt path includes session addendum
- [x] HUD shows light accent + top-bar cue when non-default
- [x] `tests/test_rfc0130_session_personalities.py` passes
- [x] `npm --prefix frontend run build` (portal touched)

## Likely files

| Area | Paths |
| --- | --- |
| Backend | `backend/app/persona/session_personality.py`, `backend/app/api/personality.py`, `backend/app/persona/pack.py`, `backend/app/persona/owner_chat.py`, `backend/app/agent/front_responder.py`, `backend/app/config.py` |
| Frontend | `frontend/src/personality/*`, `frontend/src/hud/HudShell.tsx`, `frontend/src/hud/hud.css`, `frontend/src/settings/AppearanceSettingsPane.tsx` |
| Tests | `tests/test_rfc0130_session_personalities.py` |

## Out of scope

- Instagram `persona_candidate` merge (RFC-0104)
- Full cinematic HUD reskin per mode
- Automatic TTS voice profile swap from `tts_voice_hint`

## Notes

**HUD theming is partial (by design for this ticket):** only CSS variable accents, a small top-bar label, and `data-personality` on `documentElement`, `#root`, and `.hud-app`. Presence renderers, Daybreak console chrome, and classic shell are unchanged. Voice-triggered switches update backend state immediately; the portal refreshes personality on load and when the user uses settings — owner-chat `done.personality` is returned for future live HUD sync but is not yet wired to every chat stream consumer.
