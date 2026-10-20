# RFC-0227: Model chooser popup — responsive and rare; top-right model dropdown persists across updates

**Status:** accepted  
**Priority:** P1 (Taco bug batch 2026-10-17, bugs 3 and 4)  
**Queue item:** (none in this PR — Architect may add a master-plan line after land; do not edit `JARVIS_MASTER_PLAN.md` here)  
**Author:** Jarvis Architect  
**Date:** 2026-10-20

**Owner ask (verbatim intent, 2026-10-17):** "3. The 'Available local models' chooser popup is unresponsive and appears too often. Make it responsive and make it fire far less often. 4. The top-right model dropdown loses its selections on update. Persist them across updates."  
**Aligns with:** [`ANZU_PRODUCT_NORTH_STAR.md`](../../ANZU_PRODUCT_NORTH_STAR.md) §2 ("Finished is the target."), §7 ("ANZU should eliminate unnecessary approvals without eliminating meaningful control."), §19 ("Do not optimize benchmarks while damaging perceived responsiveness."; "Do not remove useful capability merely to simplify the codebase."), §20 Q10 ("Does it avoid unnecessary approval prompts and configuration?") and Q11 ("Does it feel responsive…").  
**Extends (do not rewrite):** [RFC-0210 running-model discovery](0210-running-model-discovery-and-owner-choice.md) (the popup), [RFC-0225](0225-local-engine-coexistence-and-resilient-api.md) (engine choices store, foreign/selected classification), the HUD model hot-swap slots (`frontend/src/hud/modelSlots.ts`, "HUD_MODEL_HOTSWAP").  
**Open implementation PRs that overlap (rebase gate):** #648 (RFC-0223: "ANZU could forget its selected model when an unrelated settings save completed" — backend inference selection; touches `running_models.py`, `api/model.py`, `api/runtime_profiles.py`, `frontend/src/hud/RunningModels.tsx`) and #649 (touches `frontend/src/api.ts`, `api/runtime_profiles.py`). #648 fixes the **backend** selected model; this RFC fixes the **HUD dropdown's slots/selection**, which live only in webview `localStorage`. S1 and S3 start after #648 is merged or closed.  
**Astra boundary:** Persona/presence/WebGL/appearance out of scope (Astra).

This PR is **specs-only**. No application code.

---

## Problem

Verified in `development` @ `3f17c3d8`:

**Bug 3 — chooser popup** (`frontend/src/hud/RunningModels.tsx`, mounted in `HudShell.tsx` on every page except `/model`; backend `backend/app/inference/running_models.py`):

1. **Appears too often.** The HUD card renders whenever any row has `choice == null`. Row identity is `sha256("port:model")`, so a new LM Studio instance id (e.g. `model:2`), a JIT reload, or a port change creates a "new" row and re-opens the card. The spoken notice dedupes only through an **in-memory** `_notified` set, so every ANZU restart re-announces. ANZU's own selected engine (e.g. Taco's LM Studio :1234) can itself appear as an offer row.
2. **Unresponsive.** `POST /api/model/running/{id}/choice` awaits `scan(force=True)` plus, for use/replace, `MANAGER.load(...)` under an exclusive request lease — tens of seconds — while the UI shows one global `busy` flag and the 5 s poll keeps re-rendering. Stop/replace also goes through `window.confirm`, which blocks the webview thread. A press can look like nothing happened.

**Bug 4 — top-right dropdown** (`frontend/src/hud/HudModelSelector.tsx`):

3. Slot assignments (`jarvis.hud.modelSlots.v1`) and the selected runtime profile (`jarvis_selected_runtime_profile`, mode, policy in `frontend/src/api.ts`) are stored **only in webview `localStorage`**. Candidates for loss on update (to be confirmed in S3): WebView2 user-data reset or origin change between builds (`tauri.localhost` vs `127.0.0.1:4780`), and slot `profileId`s that no longer resolve after runtime profiles are reseeded (user-created profiles use `uuid4`; LM Studio catalog `runtime_profile_id`s), which renders slots as "—".

## Decision

Ship **one RFC with three implement slices**, one named model each (**fast off**).

### Popup frequency rules (normative)

1. **Stable identity:** offer key = `engine_kind + normalized model id` (strip LM Studio instance suffixes `:N`, ignore port for the same engine process lineage). Port/instance churn never creates a new offer.
2. **Durable "already asked":** `notified_at` is persisted in the RFC-0210 choices file; restart does not re-announce.
3. **Never offer what ANZU already uses** (`selected` / `anzu_owned` from RFC-0225 S3).
4. **Cooldown:** an unanswered offer is shown/announced at most once per 24 h per key; the card collapses to a small "1 local model available" chip after 60 s untouched (chip opens the full card). Dismissing the card = "Ask later" (cooldown), not a choice.
5. **Aggregate:** several new rows → one card and at most one spoken line.
6. **Ask again only on a genuinely new model id** (RFC-0210's rule, now on the stable key).

### Responsiveness rules (normative)

1. Choice endpoint returns within 300 ms with a `job_id`; load/stop runs in the background; `GET /api/model/running/jobs/{job_id}` reports `queued / running / done / failed` with message.
2. Per-row pending state (spinner + elapsed seconds) instead of a global `busy`; other rows stay usable; polling pauses for rows with a job in flight.
3. Stop/replace confirmation is an in-card inline confirm (two-step button), not `window.confirm`.
4. Every press gives feedback in ≤100 ms (pressed/working state).

### Dropdown persistence rules (normative)

1. **Server-side source of truth:** HUD slots + selected runtime profile id/mode/policy are persisted by the backend in `data_dir()/hud/model-selector.json` (custom data — kept by Upgrade/Repair/Update per the installer contract, wiped only by clean/semi-clean reinstall as already documented).
2. **One-time migration:** on first load the frontend uploads existing `localStorage` values if the server has none; afterwards `localStorage` is a write-through cache only.
3. **Stable references:** each slot stores `profileId` **and** a resolvable fingerprint (`provider`, `model`, `name`); if the id no longer exists after an update, the slot re-binds to the profile matching the fingerprint; if none matches, the slot shows the stored label with "Not installed" (never "—" silently).
4. Updates of the selected profile on the server emit the existing `jarvis:runtime-profile-changed` window event so all listeners keep working.

### Live-UI add-alongside reasoning pass (2026-10-14 standing order)

| Current live behaviour | Preserved? | Added alongside |
| --- | --- | --- |
| RFC-0210 card: Use model / Leave alone / Stop model / Use ANZU's model per row; busy-client hints; "Stop this server in its own app…" hint | **Yes**, all four buttons and all hints | Per-row pending, inline confirm, collapse-to-chip, "Ask later" |
| Model page `RunningModels showAll` with "Scan running servers" and "No other local model servers found." | **Yes**, unchanged (full list, no cooldown on the Model page) | Job status per row |
| Spoken "I found another local model server…" line | **Yes**, same text | Rate-limited per the rules |
| Dropdown: 6 slots, assign/move/clear, labels, configure mode, LM Studio graded/ungraded catalog rows, discovered GGUF play, HexStrike suite entry, load elapsed timer, headline/subline | **Yes**, every control kept | Server persistence, fingerprint re-bind, "Not installed" state |
| `jarvis:runtime-profile-changed` event contract | **Yes** | Also fired on server-side restore |

Nothing is deleted; `window.confirm` is replaced by an inline confirm that keeps the same explicit confirmation step (behaviour preserved, mechanism made non-blocking). Each implement PR carries the preserved-behaviour section with verification.

### Stub rule

No stubs or soft-fails. A job endpoint that always says `done`, or a persistence file that is written but never read on startup, is a fail.

---

## Slices (one ticket each)

Assign order: **S1 → S2; S3 independent** (S3 after #648).

### S1 — Offer frequency + async choice jobs (backend)

**Model:** Grok 4.5 (fast off) · **Lane:** D1 · **Depends:** RFC-0225 S3 (sequential owner of `running_models.py` / `api/model.py`), #648 resolved

| Path | Why |
| --- | --- |
| `backend/app/inference/running_models.py` | Stable offer key; persisted `notified_at`; cooldown; exclude selected/ANZU-owned; aggregated notice; `decide()` → background job |
| `backend/app/api/model.py` | Choice returns `{job_id}`; `GET /api/model/running/jobs/{job_id}`; snapshot includes `offer_key`, `cooldown_until`, `job` |
| `tests/test_rfc0227_offer_frequency.py` (new) | Below |
| `tests/test_rfc0210_running_models.py` | Update fixtures for the stable key (assertions on behaviour kept) |

- [ ] Same model reappearing with instance suffix `:2` or after a port change → no new offer, no new spoken line.
- [ ] Restart with an unanswered offer inside cooldown → no announcement; after 24 h → one announcement.
- [ ] ANZU's selected engine/model never appears as an offer.
- [ ] Three new models at once → one card, one spoken line.
- [ ] Choice endpoint returns ≤300 ms with `job_id`; job reaches `done` or `failed` with message; stale/busy rejections still enforced (RFC-0210 rules).
- [ ] RFC-0210 suite green.

### S2 — Responsive chooser card (UI)

**Model:** Composer 2.5 (fast off) · **Lane:** UX · **Depends:** S1

| Path | Why |
| --- | --- |
| `frontend/src/hud/RunningModels.tsx` | Per-row pending + elapsed, job polling, inline two-step confirm, collapse-to-chip after 60 s, "Ask later", pause polling during jobs |
| `frontend/src/hud/hud-v2.css` | Chip + pending styles (existing classes untouched) |
| `frontend/running-models-card.test.mjs` (new) + `package.json` script | Below |

- [ ] Press → visible pressed/working state within 100 ms; other rows remain clickable.
- [ ] Stop/replace require the inline second click; no `window.confirm` call remains in this component.
- [ ] Job failure shows the backend message on that row; success updates the row without a full-card flash.
- [ ] Untouched card collapses to the chip after 60 s; chip re-opens it; Model page (`showAll`) never collapses.
- [ ] All four actions and hints present (snapshot test); build + lint pass.

### S3 — Dropdown selections persist across updates

**Model:** Grok 4.5 (fast off) · **Lane:** D2 · **Depends:** #648 resolved (and #649 for `api.ts` / `runtime_profiles.py`)

| Path | Why |
| --- | --- |
| `backend/app/api/runtime_profiles.py` | `GET/PUT /api/runtime-profiles/hud-selection` (slots with fingerprints, selected id, mode, policy); atomic write to `data_dir()/hud/model-selector.json` |
| `frontend/src/hud/modelSlots.ts` | Fingerprint in `HudModelSlotEntry`; server load/save; one-time localStorage migration; fingerprint re-bind |
| `frontend/src/hud/HudModelSelector.tsx` | Load from server on mount; "Not installed" slot state; fire `jarvis:runtime-profile-changed` on restore |
| `frontend/src/api.ts` | `getSelectedRuntimeProfileId` / `setSelectedRuntimeProfileId` / mode / policy helpers write-through to the server endpoint (hunk limited to these helpers) |
| `docs/audits/2026-10-20-hud-dropdown-persistence.md` (new) | Confirmed loss mechanism with evidence (before/after update on Taco's PC) |
| `tests/test_rfc0227_hud_selection.py` (new); `frontend/hud-model-slots.test.mjs` (new) + `package.json` script | Below |

- [ ] Audit records the confirmed cause of the loss on update.
- [ ] Simulated update (cleared localStorage) → slots and selection restored from the server.
- [ ] Runtime profile id changed but fingerprint matches → slot re-binds; no match → stored label + "Not installed", not "—".
- [ ] First run with only localStorage data → migrated to server once; second run reads server.
- [ ] `apply-runtime-profile.test.mjs` and existing dropdown behaviour unchanged; build + lint pass.

---

## Overall acceptance

- [ ] On Taco's PC over a day of use with LM Studio + Ollama running: the HUD card appears at most once per new model, never for ANZU's own engine, and every button responds visibly.
- [ ] Run the installer Update/Upgrade path: dropdown slots and selection are identical before and after.
- [ ] All Live-UI rows preserved; RFC-0210 suite and frontend build/lint green.

## Ticket cards

| ID | Title | Model | Lane | Depends |
| --- | --- | --- | --- | --- |
| 0227-S1 | Offer frequency + async choice jobs | Grok 4.5 | D1 | 0225-S3, #648 |
| 0227-S2 | Responsive chooser card | Composer 2.5 | UX | S1 |
| 0227-S3 | Dropdown selections persist across updates | Grok 4.5 | D2 | #648, #649 |

## Likely files

See ownership tables. `running_models.py` / `api/model.py` are taken over from RFC-0225 S3 after it merges (sequential, never concurrent).

`frontend/package.json` is shared by every frontend ticket in the 2026-10-17 batch: each ticket adds exactly one `test:*` script line (append-only hunk, trivial rebase) and touches nothing else in that file.

## Out of scope

- Persona/presence/WebGL/appearance (Astra).
- Backend "forgot selected model after settings save" (#648 / RFC-0223).
- Startup foreign-engine prompt (RFC-0225 S4).

## Risks

- **Stable key merges two genuinely different deployments of the same model id** — acceptable; the Model page still lists every row.
- **Server persistence vs multiple portal windows** — last write wins with `updated_at`; windows refresh on the change event.
