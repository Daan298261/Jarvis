# RFC-0073: HUD model hotswap selector

**Status:** implemented
**Queue item:** P0 — HUD model hotswap
**Author:** Jarvis Architect
**Date:** 2026-09-11
**Owner for implement:** Jarvis UX (`frontend/src`)

**Related (do not rewrite):** RFC-0003 runtime/model profiles; RFC-0043 LM Studio graded profiles; `frontend/src/pages/Model.tsx`, `RuntimeProfilesSection`, `LmStudioCatalogPicker` / `frontend/src/lmstudio/*`; `backend/app/api/model.py` (`GET /api/model`, `POST /api/model/load` with `{ profile }`); LM Studio catalog APIs.

## Problem

The owner wants fast model/runtime switching from the main HUD without drilling into Settings → Model. Load and profile controls live on the advanced Model page (`fast` / `balanced` / `quality` / `expert` plus RuntimeProfiles and the LM Studio catalog). HUD chrome (`HudTopChrome` in `HudShell.tsx`) has Admin and Legacy UI on the top-right, but no one-click hotswap. Health-rail Runtime is a status link to `/model`, not a switcher.

## Decision

Add a toolbar **ModelSelector** on the **main HUD chrome, top-right** (`HudTopChrome` / `.hud-top-right`):

1. **~6 configurable slots** for quick model/runtime profile hotswap — **one click**, no Settings drill-down.
2. Slots are **user-pinnable favorites** (persist preference) — **not** a hardcoded model list. Each slot points at an existing loadable target:
   - a `GET /api/model` inference profile `name` (`fast`, `balanced`, `quality`, `expert`, …), and/or
   - an RFC-0003 `RuntimeProfile` id (same ids `RuntimeProfilesSection` already lists), and/or
   - an LM Studio catalog entry already exposed (`runtime_profile_id` / `selectLmStudioProfile`).
3. **More** navigates to the existing advanced Model page (`/model` — `Model.tsx` / RuntimeProfiles / LM Studio catalog) for full management. Do not rebuild that page in the HUD.
4. Active slot / loaded profile must be visually obvious. Failed load surfaces a concise error on the HUD (reuse `GET /api/model` `last_error` / load HTTP error) without leaving chat.
5. **Persist** the pinned slot list + order in the same preference style RuntimeProfiles already uses: **localStorage**, sibling to `jarvis_selected_runtime_profile` (proposed key `jarvis_hud_model_slots`: ordered array of `{ kind, id }` targets). Do **not** add a parallel backend model registry. Active inference profile continues to persist via existing `POST /api/model/load` → `settings.inference.profile`. Active runtime preference continues via `jarvis_selected_runtime_profile` + `jarvis:runtime-profile-changed`. RFC-0043 catalog pin/favorite APIs stay as-is; HUD slots are a separate ordered favorite bar.
6. **Reuse existing APIs only.** Wire hotswap to `POST /api/model/load` `{ profile }` for inference profile names, and to the RuntimeProfile / LM Studio select path already used by RuntimeProfiles / `LmStudioCatalogPicker` when the slot is a runtime or catalog id. Refresh status with `GET /api/model`. Empty slots are pin affordances (pick from those existing lists), not dummy models.

**Will not:** redesign the full Model page; change AUTO router policy (RFC-0003); download/install new engines; add Android companion chrome; rewrite the LM Studio catalog backend.

## Acceptance criteria

- [x] HUD top-right ModelSelector with ~6 pin-configurable slots
- [x] One-click hotswap loads that profile via existing `/api/model` (or documented RuntimeProfile / LM Studio select) without opening Settings
- [x] Slots are user-configurable favorites (persist in `jarvis_hud_model_slots` or equivalent); not a hardcoded model list
- [x] More → existing advanced Model / Settings page (`/model`)
- [x] Active profile indicated; load errors visible on HUD without leaving chat
- [x] Specs-only PR (no product code here)
- [x] Implement follow-up: `npm --prefix frontend run build`; `python3 -m pytest` if backend prefs touched

## Likely files

| Area | Paths |
| --- | --- |
| Frontend | `frontend/src/hud/HudShell.tsx` (`HudTopChrome` / `.hud-top-right`), new `ModelSelector` component, localStorage prefs next to RuntimeProfiles keys |
| Reuse | `frontend/src/pages/Model.tsx`, `RuntimeProfiles.tsx`, `frontend/src/lmstudio/*`, `frontend/src/api.ts` (`getSelectedRuntimeProfileId`, `listRuntimeProfiles`, `selectLmStudioProfile`) |
| Backend | unchanged unless a tiny prefs endpoint is required — prefer localStorage; `backend/app/api/model.py` stays as-is |
| Tests | frontend unit/UI for slot persist, one-click load, active + error; pytest only if a settings API is added |
| Docs | this RFC; optional Architect §59 line after land |

## Out of scope

Presence/orb redesign; TTS; swarm routing rewrite; new inference backends; Android companion chrome; Model page redesign; AUTO policy changes; LM Studio catalog rewrite.

## Notes

Taco urgent 2026-09-11 via CoS. Keep this RFC short. Implement is a follow-up Jarvis UX ticket after this specs-only land — do not ship product code in the RFC PR.

## Implementation note

Landed via #180 (specs) + #181 (impl @ `0b9cfa1`); HUD ModelSelector top-right, pinnable slots, More → `/model`. Specs-only criterion satisfied by #180; implement build criterion satisfied by #181 land.
