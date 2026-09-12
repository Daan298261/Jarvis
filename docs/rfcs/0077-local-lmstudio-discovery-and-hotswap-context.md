# RFC-0077: Local LM Studio discovery + play/hotswap context

**Status:** accepted
**Author:** Jarvis Architect
**Date:** 2026-09-11
**Owner for implement:** D1 (scan/grade/load) + UX (ModelSelector chrome)

**Related (do not rewrite):** RFC-0043 LM Studio graded profiles; RFC-0073 HUD ModelSelector; `backend/app/inference/lmstudio_catalog.py`, `frontend/src/lmstudio/*`, `HudTopChrome` / `HudModelSelector`. Same specs-only PR as RFC-0074 / 0075 / 0076 (those stay intact).

## Problem

Taco wants every GGUF under the **current user’s** LM Studio models folder auto-discovered — not a hardcoded `C:\Users\daanv\...` path — graded, shown in the HUD ModelSelector as **local**, with a **play** control for one-click load. Conversation context must survive hotswap (same thread). When the selector opens, Admin / Legacy / top-right chrome must not overlap the menu.

RFC-0043 already grades and catalogs LM Studio GGUFs; its inventory notes used Taco’s `daanv` path. RFC-0073 shipped pinnable HUD slots + one-click hotswap, but not a full local catalog with a **local** mark, a distinct **play** load, conversation rebind, or chrome stacking when the menu is open.

## Decision

Discover, grade, and play local LM Studio models from the **runtime home** of the logged-in user. Hotswap keeps the running conversation. Selector chrome reflows so Admin/Legacy do not overlap.

### 1. Auto-discover current-user LM Studio root

Default scan root is the **current process user’s** home, resolved at runtime:

| OS | Root |
| --- | --- |
| Windows | `%USERPROFILE%\.lmstudio\models` |
| Other | `~/.lmstudio/models` (`Path.home() / ".lmstudio" / "models"`) |

Never hardcode a username (`daanv` or any other) in source, settings defaults, seed catalog paths, UI copy, or tests (fixtures may use a temp dir). Overrides stay `JARVIS_LMSTUDIO_MODELS_ROOT` and `settings.inference.lmstudio_models_root` — those must not ship a username either.

Scan all `.gguf` under that tree (skip `mmproj` sidecars). RFC-0043’s `C:\Users\daanv\.lmstudio\models` line remains **Taco desktop inventory**, not the runtime default. This RFC owns the home-relative contract.

### 2. Grade + surface as **local** in ModelSelector

Grade via RFC-0043 / `lmstudio_catalog` (seed match + ungraded remainder). HUD ModelSelector lists discovered locals with a visible **local** mark (privacy `local-only`). Rows remain pinnable into RFC-0073 slots (`jarvis_hud_model_slots`). Ungraded on-disk GGUFs still appear (filename + size), marked local, without inventing a fake overall rank.

Do not rebuild the Model page; **More** still goes to `/model`.

### 3. Play = one-click immediate load

**Play** loads that model **now** (not pin-only):

- Inference profile name → existing `POST /api/model/load` `{ profile }`
- LM Studio catalog / runtime id → existing select path (`POST /api/lmstudio/catalog/{id}/select` / `selectLmStudioProfile` / `applyRuntimeProfile`)

One click from ModelSelector; no Settings drill-down. Failed load stays a concise HUD error (`last_error` / HTTP), chat remains.

### 4. Hotswap preserves conversation context

On play / hotswap, **transfer the running conversation to the new model**. Same thread:

- Keep the same **conversation id** (do not mint a new one, do not clear HudChat / owner-chat transcript).
- Keep **recent turns** (user + assistant). If the new context window is smaller, truncate oldest turns only — never drop to an empty chat.
- Keep the **persona pack** as the first system segment (`inject_persona_messages` / RFC-0061 pack). Do not strip butler instructions on swap.

Backend conversation maps (`backend/app/persona/owner_chat.py` `_conversations`, agent/task thread ids) must survive `MANAGER.load` / provider swap. If a load currently resets in-memory history, the implement **rebinds**: same cid + persona + last N turns on the next request to the new provider.

### 5. No Admin / Legacy overlap when selector is open

When ModelSelector opens, **Admin**, **Legacy UI**, and the admin drawer must not sit under or over the menu. Reflow or stack `HudTopChrome` / `.hud-top-right` (close the admin drawer on selector open, or shift/stack so hit targets never overlap). Smoother than today’s absolute menu vs drawer both dropping from the same corner.

### Will not

- Hardcode `daanv` (or any username) paths
- Internet model download in this RFC
- Full Model page redesign
- Silent chat reset on hotswap
- Rewrite RFC-0043 grade axes or RFC-0073 slot persistence
- Change AUTO routing (RFC-0003)

## Acceptance criteria

- [ ] Discovers under current-user `~/.lmstudio/models` / `%USERPROFILE%\.lmstudio\models` without hardcoded usernames
- [ ] Graded + shown in ModelSelector marked **local**
- [ ] Play = one-click immediate load
- [ ] Hotswap/play preserves conversation context (same conversation id + recent turns + persona pack)
- [ ] No Admin/Legacy overlap when selector open
- [ ] Specs-only in this PR (no product code)
- [ ] Implement follow-up: `python3 -m pytest` (discovery root + no-username + context rebind); `npm --prefix frontend run build` when ModelSelector chrome lands

## Likely files

| Area | Paths |
| --- | --- |
| Backend | `backend/app/inference/lmstudio_catalog.py` (`default_models_root` / `discover_ggufs`), graded seed / catalog API, `backend/app/api/lmstudio.py`, `backend/app/api/model.py` (`POST /api/model/load`), conversation rebind on profile switch (`backend/app/persona/owner_chat.py`, persona pack inject) |
| Frontend | `frontend/src/hud/HudModelSelector.tsx`, `HudShell.tsx` (`HudTopChrome`), `frontend/src/hud/applyRuntimeProfile.ts`, `frontend/src/hud/hud-v2.css` (`.hud-top-right` / `.hud-model-menu` / `.hud-admin-drawer`), `frontend/src/lmstudio/*` |
| Tests | `tests/test_lmstudio_catalog.py` (home-relative root; reject hardcoded usernames), hotswap/conversation-rebind tests |
| Docs | this RFC; Architect §59 line |

## Out of scope

Product implementation in this PR. Downloading models from the internet. Full Model page redesign. RFC-0043 axis rewrite. RFC-0073 slot-store rewrite. Companion/Android chrome. AUTO policy. Pairing / speak / APK (RFC-0074–0076).

## Notes

Taco via CoS → Jarvis Architect (specs-only). Wants all local LM Studio models auto-discovered for the current user, graded, **local** in ModelSelector, play-to-load, context kept across hotswap, and no Admin/Legacy overlap.

RFC-0043 remains the grading/catalog contract; this RFC owns **home-relative discovery**, **local + play in the HUD selector**, **conversation rebind**, and **chrome stacking**. RFC-0073 remains the slot/hotswap chrome contract.

Linux cloud VMs cannot sign off live LM Studio load or HUD overlap on Windows; those are owner-desktop verification after implement.
