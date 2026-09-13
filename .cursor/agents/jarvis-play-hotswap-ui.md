---
name: jarvis-play-hotswap-ui
description: RFC-0077 Play auto-load and HUD hotswap frontend plus inference activate backend. Use when Play button must start runtime and wait for loaded model.
---

You implement **Stream C** from `docs/spec.md`.

**Own these paths only:**
- `backend/app/inference/hotswap.py`
- `backend/app/inference/manager.py` (load/wait helpers only)
- `backend/app/api/lmstudio.py`
- `backend/app/api/runtime_profiles.py`
- `backend/app/api/model.py` (status fields if needed)
- `frontend/src/hud/HudModelSelector.tsx`
- `frontend/src/hud/applyRuntimeProfile.ts`
- `frontend/src/hud/hud-v2.css` (hotswap UI only)
- `frontend/src/chat/OwnerChatTranscript.tsx` (Show work default collapsed — RFC-0075 UI slice)
- `frontend/src/chat/ownerChatView.ts`
- `tests/test_runtime_activate.py`
- `tests/test_owner_chat_hotswap.py`
- `tests/test_lmstudio_catalog.py`

**Do not touch:** `android/**`, `backend/app/persona/**`, pairing files.

**Done when:** Play waits until `/api/model` reports loaded or error; HUD shows loading state; pytest owned tests pass; `npm --prefix frontend run build`.

Branch: `cursor/play-hotswap-1009` from latest `development`. One PR to `development`.
