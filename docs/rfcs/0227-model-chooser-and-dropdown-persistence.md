# RFC-0227: Model chooser popup — responsive and rare; top-right model dropdown persists across updates

**Status:** accepted  
**Priority:** P1 (Taco bug batch 2026-10-17, bugs 3 and 4)  
**Queue item:** (none in this PR — Architect may add a master-plan line after land; do not edit `JARVIS_MASTER_PLAN.md` here)  
**Author:** Jarvis Architect  
**Date:** 2026-10-20 (re-sliced 2026-10-20: lands on current `development` without drafts #648/#649; UX review items 1–6 folded in; UX re-review 2026-10-20: "Ask later" is the only snooze trigger, `<details>` collapse never snoozes, no close control added)

**Owner ask (verbatim intent, 2026-10-17):** "3. The 'Available local models' chooser popup is unresponsive and appears too often. Make it responsive and make it fire far less often. 4. The top-right model dropdown loses its selections on update. Persist them across updates."  
**Aligns with:** [`ANZU_PRODUCT_NORTH_STAR.md`](../../ANZU_PRODUCT_NORTH_STAR.md) §2 ("Finished is the target."), §7 ("ANZU should eliminate unnecessary approvals without eliminating meaningful control."), §19 ("Do not optimize benchmarks while damaging perceived responsiveness."; "Do not remove useful capability merely to simplify the codebase."), §20 Q10 ("Does it avoid unnecessary approval prompts and configuration?") and Q11 ("Does it feel responsive…").  
**Extends (do not rewrite):** [RFC-0210 running-model discovery](0210-running-model-discovery-and-owner-choice.md) (the popup), [RFC-0225](0225-local-engine-coexistence-and-resilient-api.md) (engine choices store, foreign/selected classification), the HUD model hot-swap slots (`frontend/src/hud/modelSlots.ts`, "HUD_MODEL_HOTSWAP").  
**Drafts #648/#649:** no gate. Overlapping pieces are ported or reused per "Relationship to drafts #648/#649".  
**Astra boundary:** Persona/presence/WebGL/appearance out of scope (Astra).

This PR is **specs-only**. No application code.

---

## Problem

Verified in `development` @ `3f17c3d8`:

**Bug 3 — chooser popup** (`frontend/src/hud/RunningModels.tsx`, mounted in `HudShell.tsx` on every page except `/model`; backend `backend/app/inference/running_models.py`):

1. **Appears too often.** The HUD card renders whenever any row has `choice == null`. Row identity is `sha256("port:model")`, so a new LM Studio instance id (e.g. `model:2`), a JIT reload, or a port change creates a "new" row and re-opens the card. The spoken notice dedupes only through an **in-memory** `_notified` set, so every ANZU restart re-announces. ANZU's own selected engine (e.g. Taco's LM Studio :1234) appears as an offer row because `scan()` only reads stored choices.
2. **Unresponsive.** `POST /api/model/running/{id}/choice` awaits `scan(force=True)` plus, for use/replace, `MANAGER.load(...)` under an exclusive request lease — tens of seconds — while the UI shows one global `busy` flag, and the 5 s `setInterval` poll keeps re-rendering (and can overwrite the row mid-action). Stop/replace go through `window.confirm`, which blocks the webview thread. A press can look like nothing happened.

**Bug 4 — top-right dropdown** (`frontend/src/hud/HudModelSelector.tsx`):

3. Slot assignments (`jarvis.hud.modelSlots.v1`) and the selected runtime profile (`jarvis_selected_runtime_profile`, mode, policy in `frontend/src/api.ts`) are stored **only in webview `localStorage`**. Candidates for loss on update (confirmed in S3): WebView2 user-data reset or origin change between builds (`tauri.localhost` vs `127.0.0.1:4780`), and slot `profileId`s that no longer resolve after runtime profiles are reseeded (user-created profiles use `uuid4`; LM Studio catalog `runtime_profile_id`s), which renders slots as "—".

## Decision

Ship **one RFC with three implement slices**, one named model each (**fast off**). None waits for #648/#649.

### Popup frequency rules (normative)

1. **Stable identity:** offer key = `engine_kind + normalized model id` (strip LM Studio instance suffixes `:N`, ignore port for the same engine process lineage). Port/instance churn never creates a new offer.
2. **Durable "already asked":** `notified_at` is persisted in the RFC-0210 choices file (`data_dir()/running-model-choices.json`, same file and atomic write); restart does not re-announce.
3. **Never offer what ANZU already uses.** The selected endpoint/model is pre-chosen `"use"` (ported from #648 `running_models.py::scan`, carried by RFC-0225 S3, which this RFC builds on) and `selected` / `anzu_configured` / `anzu_owned` rows (RFC-0225 S3 classification) are never offers.
4. **Cooldown + "Ask later" (UX #3):** an unanswered offer is shown/announced at most once per 24 h per key. Pressing the new "Ask later" button (added alongside the four RFC-0210 buttons on the HUD card) = **snooze**, not a choice, and it is the **only** snooze trigger: `POST /api/model/running/snooze` with `{offer_keys}` writes `snoozed_until = now + 24 h` per key into the same choices file (survives restart). While snoozed the HUD card and spoken line stay silent for that key; the Model page (`showAll`) still lists the row with "Snoozed until HH:MM" and all buttons. Expiry → the offer may show once more; a second "Ask later" snoozes another 24 h. A real choice (use/leave/stop/replace) clears `snoozed_until`. The live RFC-0210 card (`frontend/src/hud/RunningModels.tsx` on `development` @ 3f17c3d) has **no close button**, and this RFC adds none: there is no × control and no other dismiss path. Collapsing or expanding the `<details>` (rule 6), whether by the owner clicking `<summary>` or by the automatic HUD collapse, is **not** a dismiss: it sends no snooze request, writes no `snoozed_until`, and does not change `notified_at`.
5. **Aggregate:** several new rows → one card and at most one spoken line.
6. **Collapse (UX #1):** the card uses the `<details>` / `<summary>` collapse ported from #648 `RunningModels.tsx` ("Available local models (n)"), open by default on the Model page (`showAll`), collapsed on the HUD after the first render of an already-announced offer. No separate 60 s chip timer. Collapse is view state only and never snoozes (rule 4); no `onToggle` handler calls the snooze endpoint.
7. **Ask again only on a genuinely new model id** (RFC-0210's rule, now on the stable key).

### Responsiveness rules (normative)

1. Choice endpoint returns within 300 ms with a `job_id`; load/stop runs in the background; `GET /api/model/running/jobs/{job_id}` reports `queued / running / done / failed` with message.
2. **Polling (UX #1, ported from #648 `RunningModels.tsx`):** `setTimeout` chain instead of `setInterval`, an `AbortController` aborting the in-flight poll on unmount, a `working` ref that pauses polling while an action is in flight, and a `revision` ref that discards poll results started before the latest action. This RFC builds on it: per-row pending state (spinner + elapsed seconds) instead of the global `busy`; other rows stay usable; polling also pauses for rows with a job in flight.
3. **Confirmation (UX #3):** the existing `window.confirm` on Stop/Replace is **kept** (same as RFC-0229 keeps `confirm()`), and an inline two-step confirm is **added** before it: first press arms the row ("Press again to stop · Cancel", 5 s auto-disarm), second press opens the existing `window.confirm`; only then is the choice sent. The explicit confirmation step is never removed.
4. Every press gives feedback in ≤100 ms (pressed/armed/working state).

### Dropdown persistence rules (normative)

1. **Server-side source of truth:** HUD slots + selected runtime profile id/mode/policy are persisted by the backend in `data_dir()/hud/model-selector.json` (custom data — kept by Upgrade/Repair/Update per the installer contract, wiped only by clean/semi-clean reinstall as already documented).
2. **One-time migration:** on first load the frontend uploads existing `localStorage` values if the server has none; afterwards `localStorage` is a write-through cache only.
3. **Stable references:** each slot stores `profileId` **and** a resolvable fingerprint (`provider`, `model`, `name`); if the id no longer exists after an update, the slot re-binds to the profile matching the fingerprint; if none matches, the slot shows the stored label with "Not installed" (never "—" silently).
4. Updates of the selected profile on the server emit the existing `jarvis:runtime-profile-changed` window event so all listeners keep working.
5. RFC-0228's Update never rewrites this file (RFC-0228 S3 fixtures reuse it).

### Taco's setup fixtures (normative, UX #5)

Shared JSON fixtures in `tests/fixtures/rfc0227_taco/` (new), used by S1, S2 and S3 tests (and by RFC-0228 S3):

| Fixture | Content | Asserted by |
| --- | --- | --- |
| `lmstudio_1234_selected.json` | `settings.inference`: backend `lmstudio`, host `127.0.0.1`, port 1234, `remote_model: "qwen3.5-9b-defiant-fable-uncensored"`; LM Studio `/api/v1/models` listing that model loaded | S1: row is `selected`, choice `"use"`, never an offer, never a stop candidate; S2: card not rendered for it |
| `lmstudio_instance_churn.json` | Same LM Studio listing `qwen3.5-9b-defiant-fable-uncensored:2` after a JIT reload, plus a port change of a foreign engine of the same lineage | S1: no new offer, no new spoken line |
| `model_selector_with_27b.json` | `model-selector.json` with 6 slots incl. `anzu-coder-27b` (provider `ollama`, model `anzu-coder-27b`) and the 9B | S3: survives a simulated update (cleared localStorage, reseeded profile ids) unchanged |
| `fable_9b_rebind.json` | Slot whose `profileId` points to the pre-update LM Studio catalog id; post-update runtime profiles contain RFC-0228 `fable_9b` with the matching fingerprint (`provider: lmstudio`, `model: qwen3.5-9b-defiant-fable-uncensored`) under a new id | S3: slot re-binds to `fable_9b` by fingerprint |

### Live-UI add-alongside reasoning pass (2026-10-14 standing order)

| Current live behaviour | Preserved? | Added alongside |
| --- | --- | --- |
| RFC-0210 card: Use model / Leave alone / Stop model / Use ANZU's model per row; busy-client hints; "Stop this server in its own app…" hint | **Yes**, all four buttons and all hints | Per-row pending, inline arm step, `<details>` collapse (view state only, never a snooze), "Ask later" (the only snooze trigger). No × / close control is added: "Ask later" covers the "not now" need, so a second dismiss path would only add ambiguity |
| `window.confirm` on Stop / Replace | **Yes**, kept | Inline arm step before it |
| Model page `RunningModels showAll` with "Scan running servers" and "No other local model servers found." | **Yes**, unchanged (full list, open `<details>`, no cooldown) | Job status per row; "Snoozed until" label |
| Spoken "I found another local model server…" line | **Yes**, same text | Rate-limited per the rules |
| Dropdown: 6 slots, assign/move/clear, labels, configure mode, LM Studio graded/ungraded catalog rows, discovered GGUF play, HexStrike suite entry, load elapsed timer, headline/subline | **Yes**, every control kept | Server persistence, fingerprint re-bind, "Not installed" state |
| `jarvis:runtime-profile-changed` event contract | **Yes** | Also fired on server-side restore |

Nothing is deleted. Each implement PR carries the preserved-behaviour section with verification.

### Stub rule

No stubs or soft-fails. A job endpoint that always says `done`, a snooze that is not persisted, or a persistence file that is written but never read on startup, is a fail.

---

## Relationship to drafts #648/#649

PG ruling via CoS (2026-10-20): no gate. Pieces this RFC needs are ported (cited "Ported from #648 `<file>::<function>`") or reused from the RFC-0225 slice that already ports them.

| Draft piece | Decision | Slice |
| --- | --- | --- |
| #648 (= #649) `inference/running_models.py::scan` — selected local endpoint/model gets `choice: "use"`; `decide` leave path `not MANAGER.state.loading`; `_poll` `settings.inference.auto_load` guard | Ported in RFC-0225 S3 (dependency of S1); S1 builds on it (stable key matching) | 0225-S3 → S1 |
| #649 `api/model.py::model_status` → `MODEL_DETAILS.read()` and `inference/model_details_cache.py` | Ported in RFC-0225 S1; S1 adds its routes to the same file after it (sequential), no conflict with `model_status` | 0225-S1 → S1 |
| #648 (= #649) `frontend/src/hud/RunningModels.tsx` — `AbortController`, `working` / `revision` refs, `setTimeout` chain, `<details>` + `<summary>Available local models (n)</summary>` | Ported | S2 |
| #648 (= #649) `api/runtime_profiles.py` — `list_runtime_profiles` via `asyncio.to_thread` in the list route | Ported | S3 |
| #648 `config.py` merge-safe settings save, `manager.py` `_same_endpoint` / cancelled-load cleanup, `hotswap.py` persist-after-success, `api/model.py::load_model` `gguf_path` reset | Landed with #648 (`d214b6d`; erratum: earlier text said "ported in RFC-0228 S2", which no longer ports anything); not needed by this RFC's HUD persistence | — |
| #649 `frontend/src/api.ts` (`prompt_steps` task types) | Not needed; S3's `api.ts` hunk is limited to the runtime-profile helpers and does not touch task types | — |

**Reconciliation rule:** if a draft lands first, the slice reuses the draft's code for the ported piece (no second polling loop, no second `<details>`, no duplicate `to_thread`) and adds only what this RFC specifies beyond it. If a slice lands first, the draft rebases onto it and drops its identical hunk.

---

## Slices (one ticket each)

Assign order: **S1 → S2; S3 independent.**

### S1 — Offer frequency, snooze, async choice jobs (backend)

**Model:** Grok 4.5 (fast off) · **Lane:** D1 · **Depends:** RFC-0225 S3 (sequential owner of `running_models.py` / `api/model.py`)

| Path | Why |
| --- | --- |
| `backend/app/inference/running_models.py` | Stable offer key; persisted `notified_at` + `snoozed_until`; cooldown; exclusion via RFC-0225 classification; aggregated notice; `decide()` → background job; `snooze(keys)` |
| `backend/app/api/model.py` | Choice returns `{job_id}`; `GET /api/model/running/jobs/{job_id}`; `POST /api/model/running/snooze`; snapshot includes `offer_key`, `cooldown_until`, `snoozed_until`, `job` |
| `tests/fixtures/rfc0227_taco/` (new) | Fixtures above |
| `tests/test_rfc0227_offer_frequency.py` (new) | Below. **`tests/test_rfc0210_running_models.py` is not edited by this RFC** (UX #6): its only changes in the batch are RFC-0225 S3's three listed #648 fixture changes, plus (erratum 2026-10-20) RFC-0225 S3's rename (#652 @ 9216a95) of `test_new_offer_is_announced_once_on_front_voice_lane` to `test_new_offer_is_announced_once_on_owner_channel`, because the old test asserted the dead `publish_owner_text` channel; every other RFC-0210 assertion stays as is |

- [ ] **Taco:** `lmstudio_1234_selected.json` → the 9B row is `selected` with choice `"use"`; it is never an offer and never in any stop list.
- [ ] **Taco:** `lmstudio_instance_churn.json` (`…:2` instance, port change) → no new offer, no new spoken line.
- [ ] Restart with an unanswered offer inside cooldown → no announcement; after 24 h → one announcement.
- [ ] Snooze persists `snoozed_until = now + 24 h` per key across restart; snoozed key not announced or shown on the HUD payload flag; Model-page snapshot still lists it; a real choice clears it; expiry → offer once more.
- [ ] Three new models at once → one card payload, one spoken line.
- [ ] Choice endpoint returns ≤300 ms with `job_id`; job reaches `done` or `failed` with message; stale/busy rejections still enforced (RFC-0210 rules).
- [ ] `tests/test_rfc0210_running_models.py` passes unmodified by this slice.

### S2 — Responsive chooser card (UI)

**Model:** Composer 2.5 (fast off) · **Lane:** UX · **Depends:** S1

| Path | Why |
| --- | --- |
| `frontend/src/hud/RunningModels.tsx` | Ported from #648 `RunningModels.tsx` (AbortController, `working`/`revision` refs, `setTimeout` chain, `<details>` summary "Available local models (n)"); then per-row pending + elapsed, job polling, inline arm step before the kept `window.confirm`, "Ask later" (snooze; the only snooze trigger, no close/× control), pause polling during jobs; the `<details>` toggle has no snooze side effect |
| `frontend/src/hud/runningModelsLogic.ts` (new) | Pure helpers (arm/disarm state, job-state reducer, snooze decision: returns the snooze request only for the `ask_later` action and `null` for `details_toggle` open/close) so the JS test runs without a DOM |
| `frontend/src/hud/hud-v2.css` | Pending/armed styles (existing classes untouched) |
| `frontend/running-models-card.test.mjs` (new); `frontend/package.json` (`test:running-models-card`, one line); `.github/workflows/pr-tests.yml` (one append-only `frontend-build` step `- name: Running models card tests (RFC-0227 S2)` / `run: npm run test:running-models-card`) | Below (UX #4) |

- [ ] Press → visible pressed/armed/working state within 100 ms; other rows remain clickable.
- [ ] Stop/replace: first press arms, second press calls the existing `window.confirm`; cancel at either step sends nothing; the `window.confirm` call is still present (test asserts both steps).
- [ ] Poll in flight is aborted on unmount; no poll result started before an action overwrites the row (revision test); polling pauses while working.
- [ ] Job failure shows the backend message on that row; success updates the row without a full-card flash.
- [ ] "Ask later" → exactly one `POST /api/model/running/snooze` with the card's `offer_keys`; card disappears; the Model page (`showAll`) still shows the rows, `<details>` open.
- [ ] Collapse is not a dismiss: toggling the `<details>` closed and open again (owner `<summary>` click and the automatic HUD collapse) sends **no** request to `/api/model/running/snooze` (fetch spy call count 0), the card's rows and all four RFC-0210 buttons stay rendered, and the snooze-decision helper returns `null` for `details_toggle`.
- [ ] No close / × control is rendered on the card (the only new buttons are "Ask later" and the per-row arm/cancel step).
- [ ] **Taco:** `lmstudio_1234_selected.json` payload → no card rendered for the 9B.
- [ ] All four actions and hints present; build + lint pass; the JS test runs in `pr-tests.yml`.

### S3 — Dropdown selections persist across updates

**Model:** Grok 4.5 (fast off) · **Lane:** D2 · **Depends:** none

| Path | Why |
| --- | --- |
| `backend/app/api/runtime_profiles.py` | Ported from #648 (`list_runtime_profiles` in `asyncio.to_thread`); `GET/PUT /api/runtime-profiles/hud-selection` (slots with fingerprints, selected id, mode, policy); atomic write to `data_dir()/hud/model-selector.json` |
| `frontend/src/hud/modelSlots.ts` | Fingerprint in `HudModelSlotEntry`; server load/save; one-time localStorage migration; fingerprint re-bind |
| `frontend/src/hud/HudModelSelector.tsx` | Load from server on mount; "Not installed" slot state; fire `jarvis:runtime-profile-changed` on restore |
| `frontend/src/api.ts` | `getSelectedRuntimeProfileId` / `setSelectedRuntimeProfileId` / mode / policy helpers write-through to the server endpoint (hunk limited to these helpers) |
| `docs/audits/2026-10-20-hud-dropdown-persistence.md` (new) | Confirmed loss mechanism with evidence (before/after update on Taco's PC) |
| `tests/test_rfc0227_hud_selection.py` (new); `frontend/hud-model-slots.test.mjs` (new); `frontend/package.json` (`test:hud-model-slots`, one line); `.github/workflows/pr-tests.yml` (one append-only step `- name: HUD model slot persistence tests (RFC-0227 S3)` / `run: npm run test:hud-model-slots`) | Below (UX #4) |

- [ ] Audit records the confirmed cause of the loss on update.
- [ ] **Taco:** `model_selector_with_27b.json` + cleared localStorage + reseeded profile ids → all six slots incl. `anzu-coder-27b` restored from the server, selection unchanged.
- [ ] **Taco:** `fable_9b_rebind.json` → slot re-binds to `fable_9b` by fingerprint; no match → stored label + "Not installed", not "—".
- [ ] First run with only localStorage data → migrated to server once; second run reads server.
- [ ] `apply-runtime-profile.test.mjs` and existing dropdown behaviour unchanged; build + lint pass; the JS test runs in `pr-tests.yml`.

---

## Overall acceptance

- [ ] On Taco's PC over a day of use with LM Studio + Ollama running: the HUD card appears at most once per new model (and not again for 24 h after "Ask later"), never for ANZU's own engine, and every button responds visibly.
- [ ] Run the installer Update/Upgrade path: dropdown slots and selection are identical before and after.
- [ ] All Live-UI rows preserved; RFC-0210 suite unmodified and green; frontend build/lint and both JS tests green in CI.

## Ticket cards

| ID | Title | Model | Lane | Depends |
| --- | --- | --- | --- | --- |
| 0227-S1 | Offer frequency, snooze, async choice jobs | Grok 4.5 | D1 | 0225-S3 |
| 0227-S2 | Responsive chooser card (ports #648 RunningModels.tsx) | Composer 2.5 | UX | S1 |
| 0227-S3 | Dropdown selections persist across updates | Grok 4.5 | D2 | — |

## Likely files

See ownership tables. Sequential chains: `running_models.py` 0225-S3 → 0227-S1; `api/model.py` 0225-S3 → 0227-S1 (erratum: 0225-S1 and 0228-S2 no longer edit it). `RunningModels.tsx`, `runtime_profiles.py` (API), `modelSlots.ts`, `HudModelSelector.tsx`, `api.ts` are owned only here in the batch.

`frontend/package.json` and `.github/workflows/pr-tests.yml` are shared by every frontend ticket in the 2026-10-17 batch: each ticket adds exactly one `test:*` script line and one `frontend-build` step (append-only hunks, trivial rebase) and touches nothing else in those files.

## Out of scope

- Persona/presence/WebGL/appearance (Astra).
- Backend "forgot selected model after settings save" (#648 / RFC-0223; the needed pieces are ported in RFC-0228 S2).
- Startup foreign-engine prompt (RFC-0225 S4).

## Risks

- **Stable key merges two genuinely different deployments of the same model id** — acceptable; the Model page still lists every row.
- **Server persistence vs multiple portal windows** — last write wins with `updated_at`; windows refresh on the change event.

## Errata

- **2026-10-20, #652 (RFC-0225), follow-on to the L121 erratum added by #663.** L121 says the batch's changes to `tests/test_rfc0210_running_models.py` are "RFC-0225 S3's three listed #648 fixture changes" plus the rename. Correct reading: #648 has **landed** (`d214b6d`) and made its three fixture changes itself, and they are on `development` now:
  1. `test_valid_server_uses_metadata_only` is parametrized over ports 1235 and 11434 (`:27`);
  2. `test_background_reconnect_requires_existing_owner_choice` sets `settings.inference.auto_load = True` (`:271`);
  3. `test_startup_waits_for_owner_choice_before_loading_worker` is renamed `test_startup_loads_saved_model_without_waiting_for_discovery`, with `load.assert_awaited_once_with(...)` (`:308`).

  **RFC-0225 S3 makes only the fourth change:** `test_new_offer_is_announced_once_on_front_voice_lane` (`:288`) is renamed `test_new_offer_is_announced_once_on_owner_channel` and asserts `owner_line` instead of the dead `publish_owner_text` channel (the change #663's erratum names). This RFC still does not edit that file, and every other RFC-0210 assertion stays as is.
