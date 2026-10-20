# RFC-0218: Persona UI surfaces A/B/C + intent-driven auto persona switch

**Status:** accepted  
**Queue item:** (none in this PR — Architect may add a master-plan line after land; do not edit `JARVIS_MASTER_PLAN.md` here)  
**Author:** Jarvis Architect  
**Date:** 2026-10-14  
**Amended:** 2026-10-20 — S3b backend amendment (auto-switch lock write + tasks-path persona switch), CoS option (a). See [S3b](#s3b--backend-amendment-auto-switch-lock-write--tasks-path-persona-switch).

**Owner:** Taco explicitly owns this persona-surface change (owner-authorized persona work, ask of 2026-10-14). Astra still owns WebGL / renderer internals and fills the morph hook (S5).  
**Aligns with:** [`ANZU_PRODUCT_NORTH_STAR.md`](../../ANZU_PRODUCT_NORTH_STAR.md) §3 (ANZU should have presence), §4 (voice is a primary interface), §5 (one assistant, many specialists — specialists auto-chosen), §6 (fast when simple — reflex chain), §19 (rules for interpreting specifications).  
**Extends (do not rewrite):** [RFC-0069](0069-presence-shape-catalog-and-morph-api.md) (morph API), [RFC-0137](0137-persona-presence-shape-and-voice-binding.md) (roster + voice binding), [RFC-0171](0171-system-one-reflex-lane-jev-laya-priority.md) (reflex lane), [RFC-0195](0195-visual-acceptance-and-presence-stage.md) (one stage), [RFC-0206](0206-jev-laya-every-turn-arbitration.md) (every-turn `decide_owner_turn`), [RFC-0209](0209-autonomous-memory-capture.md) (decision-class precedent), [RFC-0210](0210-restore-volumetric-persona-avatars.md) + PR #623 (A–E variants restored), [RFC-0214](0214-performance-compass.md) (per-class thresholds).  
**Astra boundary:** No edits to WebGL shaders, `MorphablePresenceStage` / `morphableOrbCloud` internals, presence art, or the morph animation body. Architect specs surface, routing, wiring, and the typed hook only.

This PR is **specs-only**. No application code.

---

## Problem

1. **One persona surface layout only.** Taco wants several owner-selectable persona UI layouts (A/B/C), each offering avatar choices.
2. **Persona switching is manual.** "Anzu, write me a script" stays on Anzu. North star §5 says ANZU "should normally determine when specialist capability is useful without forcing the user to route every task manually." The reflex lane already has `persona_model_routing` (model pick) but nothing chooses the *persona* from intent.
3. **No switch feedback.** A switch must be heard (TTS in the new persona's voice) and work must start immediately, with no confirmation wait.
4. **No backend→UI persona event channel exists.** The backend can change persona (`named_persona._activate`) but the UI only learns about persona changes it initiated (`activateNamedPersona`).
5. **No named seam for the cloud→persona morph.** Astra needs a typed hook to fill.

## Decision

Ship **one RFC with six implement slices** (S1–S5, plus the S3b backend amendment of 2026-10-20), each a single CoS-assignable ticket with one named model (**fast off**).

### North-star justification

- **§3:** "> **ANZU should have presence.**" / "Morphing should feel organic. Status changes should be understandable." — the switch is a visible, spoken state change through one stage; the morph is a named seam (S5).
- **§4:** "ANZU should acknowledge simple requests almost immediately… continue heavier work without creating the impression that the entire system has frozen." and "The voice should belong to the selected ANZU personality and visual presence." — switch line is spoken in the **new** persona's voice, fire-and-forget, work starts the same turn.
- **§5:** "Specialists can be manually selected where desirable, but ANZU should normally determine when specialist capability is useful…" — auto-switch (S1/S2), manual pin keeps working and wins.
- **§6:** "deterministic rule → tiny/reflex decision system → normal code/tool execution → normal model → specialist/expert reasoning only when required" — intent is a reflex decision class answered inside `decide_owner_turn`, rules first, Laya/Jev next, deadline fallback = stay.
- **§19:** "Do not create several interfaces where one adaptive interface can work." — **A/B/C are owner-selectable layouts of ONE adaptive persona surface**, sharing one persona state, one activation path (`activateNamedPersona`), one stage, one voice binding. They are not separate apps or forks. "Do not remove useful capability merely to simplify the codebase." — live UI is additive (below). "Do not mark something finished merely because its backend exists." — S2 is not done without S3 consuming its event, and S3 is not done until S3b emits that event on the transport the live UI actually uses (`/api/tasks`).

### Terms

| Name | Meaning in this RFC |
| --- | --- |
| **Persona UI layout A/B/C** (new) | Whole persona-surface layouts. **A = the current live layout, unchanged, default.** B and C are new layouts. Each offers avatar choices. Stored as `personaLayout: "A" \| "B" \| "C"`. |
| **Avatar variant A–E** (existing, RFC-0210 / #623) | Per-persona avatar versions in `frontend/src/presence/mythicPersonaVariant.ts`. **Distinct from layouts.** Stay intact and are reused as the avatar choices inside every layout. |
| **Auto switch** | Backend-initiated persona change from intent (`persona_intent_switch`). |
| **Manual pin / lock** | Owner's explicit persona selection with the lock setting on. Disables auto-switch. |

### Live-UI rule: additive only

Per the 2026-10-14 standing order and PR #623 regressions, every slice is **add, never delete**. Must remain present and working:

- Per-persona A–E variant buttons.
- Selected variant persists across persona switches (manual and auto).
- Both humanoid paths (production + muscular/original procedural).
- The 14-persona roster (no roster changes).
- Appearance brightness/density sliders with live preview.
- `PinnedPersonaDock`.
- Every existing persona button, message, preview, and highlight.

Every implement PR includes a **reviewer reasoning pass**: a short section listing each preserved item and how it was verified (test or screenshot). A preservation snapshot test (S3) guards the list.

### Stub rule

**Single exception:** `onCloudToPersonaMorph` (S5) — typed, exported, no-op body, doc comment citing Taco's 2026-10-14 authorization. Everything else is fully wired. No other stubs, scaffolding, TODO bodies, or soft-fails.

### Switch behaviour (normative)

1. Precedence: explicit persona name in the utterance ("Enki, …") > manual pin/lock > intent decision > stay.
2. Lock setting on → no auto-switch, ever.
3. Confidence floor per class (RFC-0214 tunable); below floor → stay.
4. Hysteresis: chit-chat / social / acknowledgement turns never flip back to the previous persona; only a new task intent changes persona.
5. Order: `_activate(new)` **before** `speak_text` so voice resolves to the new persona.
6. Speech is fire-and-forget; failure is logged and never blocks the turn.
7. Work starts in the same turn on the new persona. No confirmation.
8. First owner-visible text is not delayed beyond the reflex budget (RFC-0206, < 50 ms default).
9. Approvals, `harm_veto`, and policy are unaffected by a switch.

---

## Slices (one ticket each)

Assign order: **S1 ∥ S5 → S2 → S3b → S3 → S4.** (S3b, added 2026-10-20, is assigned before S3; S3 frontend is a consumer only.)

### S1 — Decision class `persona_intent_switch`

**Model:** Grok 4.5 (fast off) · **Depends:** none

| Path | Why |
| --- | --- |
| `backend/app/decision/types.py` | Add `"persona_intent_switch"` to `REFLEX_DECISION_CLASSES`. **Not** in `POLICY_HARDENED_CLASSES`. |
| `backend/app/decision/surfaces.py` | `route_persona_intent(user_message, *, current_persona, pinned, locked, settings) -> PersonaIntentDecision` (`to`, `reason`, `decision_source`, `confidence`). Pattern: `route_persona_model` / `arbitrate_front_and_worker_bounded`. |
| `backend/app/decision/adapters/rules.py` | Rules branch: explicit roster name → that persona (confidence 1.0); lock → stay; intent→persona map from roster roles (coding/engineering → `enki`, etc., derived from RFC-0137 roster, not a second roster). |
| `backend/app/decision/owner_turn.py` | Evaluate inside `decide_owner_turn` — still the only routing call. Result on the owner-turn decision object. |
| `backend/app/decision/__init__.py` | Export. |
| Tests (`tests/test_decision_persona_intent.py`) | Below. |

- [ ] "Anzu, write me a script" → `enki`.
- [ ] Chit-chat ("thanks", "how are you") → stays on current persona (incl. after a switch — hysteresis).
- [ ] "Enki, …" / any roster name → that persona regardless of intent.
- [ ] Lock on → stays for every fixture.
- [ ] Below confidence floor → stays.
- [ ] Fixture provider returning a persona is respected over rules baseline (non-explicit, non-locked).
- [ ] Decision within reflex budget; deadline fallback = stay.
- [ ] Class is in `REFLEX_DECISION_CLASSES`, not in `POLICY_HARDENED_CLASSES`.

### S2 — Backend switch + speak + start

**Model:** Grok 4.6 (fast off) · **Depends:** S1

**No backend→UI persona event channel exists today; S2 adds one** by extending the existing owner-chat stream (`stream_owner_chat`, `backend/app/persona/owner_chat.py`) with a typed event:

`persona_switched { from: PersonaId, to: PersonaId, reason: "intent" | "explicit_name", decision_source: DecisionSource, confidence: number }`

| Path | Why |
| --- | --- |
| `backend/app/persona/owner_chat.py` | On switch decision: `named_persona._activate(to)` → emit `persona_switched` → schedule speech (not awaited) → run the turn on the new persona. |
| `backend/app/persona/named_persona.py` | Reuse `_activate` / `resolve_persona_id`; no second activation path. |
| `backend/app/tts/persona_speech.py` | Short switch line via `speak_text` (lane `front`), same pattern as `announce_stream_stall`. |
| Stream event typing (backend schema + `frontend` stream types) | Typed `persona_switched`. |
| Tests (`tests/test_persona_intent_switch_turn.py`) | Below. |

- [ ] `_activate` is called before `speak_text`; test asserts `resolve_speaking_voice` returns the **new** persona's voice.
- [ ] `persona_switched` emitted once with correct `from/to/reason/decision_source/confidence`.
- [ ] `speak_text` raising (incl. `SpeechRefused`) does not block or fail the turn.
- [ ] Work starts in the same turn on the new persona; no confirmation prompt.
- [ ] First owner-visible text not delayed beyond reflex budget.
- [ ] No switch → no event, no speech.
- [ ] Approval-required tools still require approval after a switch; `harm_veto` unaffected.

### S3b — Backend amendment: auto-switch lock write + tasks-path persona switch

**Model:** Grok 4.6 (fast off) · **Lane:** D1 · **Depends:** S1, S2 · **Added:** 2026-10-20 (CoS option (a); gaps found by UX on S3, confirmed by D1)

**Why this slice exists.** Two gaps block S3 on `development` at `3f17c3d`:

1. **Nothing writes `named_personas.auto_switch_locked`.** S1 reads it (`backend/app/decision/owner_turn.py`, `store.auto_switch_locked`) and the field exists on `NamedPersonaSettings` (`backend/app/config.py`), but neither `PUT /api/settings` (`SettingsUpdate` / `update_settings`) nor `PUT /api/named-personas` (`NamedPersonaPut` / `put_named_personas`) accepts it, and `GET /api/named-personas` (`public_state()`) does not return it. The S3 lock toggle has nothing to write to.
2. **`persona_switched` only fires on a transport no frontend uses.** S2 calls `apply_persona_switch` only in `stream_owner_chat` (`POST /api/owner/chat/messages/stream`, `backend/app/persona/owner_chat.py`). HUD chat (`frontend/src/hud/HudChat.tsx`), Chat (`frontend/src/pages/Chat.tsx`) and Phone (`frontend/src/pages/Phone.tsx`) all `POST /api/tasks` → `AGENT.create_task` (`backend/app/agent/loop.py`) → front lane (`backend/app/agent/front_responder.py`), and that path never calls `apply_persona_switch`. The tasks path already computes `turn.persona_intent` in its one `evaluate_request_route` → `decide_owner_turn` call and then drops it.

**Fix (add-only).** Expose the lock on both write endpoints, and run the existing S2 `apply_persona_switch` on the tasks path from the `turn` that path already decides, publishing the same event shape on the task event stream the frontend already subscribes to (`GET /api/tasks/{task_id}/events`, SSE via `BUS.stream`, consumed by `frontend/src/chat/ownerChatView.ts` and `frontend/src/tts/useTaskSpeech.ts`).

#### Part 1 — lock write

- `PUT /api/settings` (`backend/app/api/settings.py`, `update_settings`): add `named_personas_auto_switch_locked: StrictBool | None = None` to `SettingsUpdate` (flat name, same convention as `tts_*` / `front_responder_*`). When not `None`, set `settings.named_personas.auto_switch_locked` before the existing `save_settings(settings)`. The response (`settings.model_dump()`) and `GET /api/settings` already serialise `named_personas`, so the round-trip needs no new code beyond the write.
- `PUT /api/named-personas` (`backend/app/api/named_personas.py`, `put_named_personas`): add `auto_switch_locked: StrictBool | None = None` to `NamedPersonaPut`. When not `None`, persist it through a new helper `set_auto_switch_locked(locked: bool)` in `backend/app/persona/named_persona.py` (same `_load()` → mutate → `save_settings` pattern as `persist_persona_preferences`), applied before the existing `as_specialist` / `apply` branches. A lock-only write is `{"id": <active id>, "apply": false, "auto_switch_locked": true}`, which uses the existing request shape: `id` stays required, and `apply: false` with no appearance patch already returns `public_state()` without activating anything.
- `GET /api/named-personas`: `public_state()` gains one key, `"auto_switch_locked": bool`. All existing keys keep their names and values.
- Validation: `StrictBool`, so `"yes"`, `1` and `"true"` are rejected with 422 and nothing is written. Omitting the field changes nothing.
- No other field, default or behaviour of either endpoint changes.

#### Part 2 — tasks-path persona switch

- **Where:** `AgentRuntime.create_task` in `backend/app/agent/loop.py` (this is where the tasks path makes its decision; `api/tasks.py::create_task` only delegates). Insert the call after the new `Task` row is committed, because `BUS.publish` persists a `TaskEvent` with a task FK. It must come before the `acknowledgement` publish and before `_start_runner`, so nothing on the task is spoken or run before activation:
  ```python
  from ..persona.owner_chat import apply_persona_switch          # S2 function, reused, no copy
  from ..tts.persona_speech import schedule_persona_switch_announcement
  persona_event = apply_persona_switch(turn.persona_intent, task.id)
  if persona_event is not None:
      await BUS.publish(task.id, persona_event["type"], <title>, json.dumps(persona_event), stage="queued")
      if persona_event["type"] == "persona_switched":
          schedule_persona_switch_announcement(persona_event["to"])   # fire-and-forget, as S2
  ```
  The task-stream event is `kind: "persona_switched"`, and its `detail` is the S2 `PersonaSwitchedEvent` serialised as JSON: `{type, conversation_id (= task id), from, to, reason, decision_source, confidence}`. A bind failure publishes `kind: "persona_switch_failed"` with the S2 `PersonaSwitchFailedEvent` JSON, and the previous persona stays.
- **Follow-up turns** (`POST /api/tasks/{id}/continue`): the follow-up decision already made in `_run` (`follow_turn`, stored with `_remember_owner_turn`) gets the same call, placed after `_remember_owner_turn(task_id, follow_turn)` and before `_run_conversation` or the managed run, so "Anzu, now write me a script" inside an existing chat task also switches.
- **Exactly one decide per turn.** No new `evaluate_request_route` / `decide_owner_turn` call. The switch reads `turn.persona_intent` from the decision `create_task` (or `_run` for follow-ups) already made. `front_responder.generate_front_reply` / `run_two_lane_chat` keep receiving that same remembered turn as `turn_decision`, so their `if decision is None:` fallback decide never runs on this path. `backend/app/agent/front_responder.py` needs no change unless a test shows a path that reaches it with `turn_decision=None` from `/api/tasks`; in that case pass the remembered turn through, and add no second decide.
- **Budget:** the decision stays inside the RFC-0206 / S1 50 ms reflex budget (unchanged). `apply_persona_switch` is synchronous local work. The speech is scheduled, never awaited, and the persona-brain model hotswap is not triggered on this path, so the acknowledgement is not delayed past the reflex budget.
- **Order:** `apply_main_persona(to)` (inside `apply_persona_switch`) → publish `persona_switched` → schedule switch line → `acknowledgement` / `chat_tts` / runner. Every line spoken for the task therefore resolves to the new persona's voice.
- **Same turn, no confirmation:** the task runs immediately on the new persona. No prompt, no pause, no extra event to wait for.
- **Not moved:** chat sends stay on `/api/tasks`. No frontend send is moved to `/api/owner/chat/messages/stream`, because moving them is a live-UI transport risk. `stream_owner_chat` keeps its S2 call, unchanged.
- **Policy:** approvals, `harm_veto` and the task's tool exposure are computed exactly as before, and a switch does not alter them (S2 rule 9).

#### Ownership (S3b)

| Path | Change |
| --- | --- |
| `backend/app/api/settings.py` | `SettingsUpdate.named_personas_auto_switch_locked: StrictBool \| None`; write in `update_settings`. Add-only. *(#649 file)* |
| `backend/app/api/named_personas.py` | `NamedPersonaPut.auto_switch_locked: StrictBool \| None`; write via `set_auto_switch_locked` in `put_named_personas`. Add-only. *(#649 file)* |
| `backend/app/persona/named_persona.py` | New `set_auto_switch_locked(locked)`; `public_state()` adds the `auto_switch_locked` key. Add-only. |
| `backend/app/agent/loop.py` | `create_task` and the `_run` follow-up branch call S2 `apply_persona_switch` on the existing `turn` / `follow_turn` and publish on `BUS`. Add-only. *(#649 file)* |
| `backend/app/agent/front_responder.py` | Read-only for this slice, unless the one-decide test finds a `/api/tasks` path that reaches it with `turn_decision=None`; then pass the remembered turn through, add-only. *(#649 file)* |
| `backend/app/api/tasks.py` | No change expected: `POST /api/tasks` delegates to `AGENT.create_task`, and `GET /api/tasks/{id}/events` already streams every `BUS` kind. Listed so reviewers can see it was checked. *(#649 file)* |
| `backend/app/persona/owner_chat.py` | **Not edited.** `apply_persona_switch`, the event TypedDicts and the `stream_owner_chat` call stay as S2 landed them. *(#649 file)* |
| `tests/test_rfc0218_s3b_lock_and_tasks_switch.py` (new) | All S3b acceptance below. |

#### Relationship to draft #649

`backend/app/api/settings.py`, `backend/app/api/named_personas.py`, `backend/app/api/tasks.py`, `backend/app/agent/loop.py`, `backend/app/agent/front_responder.py` and `backend/app/persona/owner_chat.py` are also touched by Taco's draft PR #649 (RFC-0224, `cursor/task-latency-and-quality-99ea`). As of its current head, #649 does not touch `auto_switch_locked`, `apply_persona_switch`, `persona_intent`, or the `create_task` decision block. Its edits are elsewhere in the same files: the front reconfigure task and `large_task_reviews` in `settings.py`, a sync `get_named_personas` in `named_personas.py`, `prompt_steps` in `tasks.py`, workflow gating around the follow-up branch in `loop.py`, and owner-chat sequential intake rerouted to `AGENT.create_task` in `owner_chat.py`.

- **No gate.** S3b lands on `development` without #648 or #649.
- **If #649 lands first:** S3b rebases onto it and reuses its code. Use #649's `get_named_personas` signature. Put the follow-up call after #649's `stored_workflow` / `needs_workflow` computation and `_remember_owner_turn`, and do not duplicate its workflow gating. With #649, owner-chat sequential intake goes through `AGENT.create_task`, so those turns switch through S3b's `create_task` call, and that call is still the turn's only decision because `stream_owner_chat` returns before its own decide on the sequential path.
- **If S3b lands first:** #649 rebases onto S3b. Every S3b hunk is additive (new optional request fields, one new helper, one new `public_state` key, inserted lines in `create_task` and the follow-up branch), so the rebase is mechanical and keeps both sets of changes.

#### Acceptance (S3b)

- [ ] `PUT /api/settings {"named_personas_auto_switch_locked": true}` persists the lock; the response and a following `GET /api/settings` return `named_personas.auto_switch_locked == true`; `false` round-trips back.
- [ ] `PUT /api/named-personas {"id": <active>, "apply": false, "auto_switch_locked": true}` persists the lock without activating or changing any persona; the response and a following `GET /api/named-personas` return `auto_switch_locked == true`; `false` round-trips back.
- [ ] A non-bool value (`"yes"`, `1`) is rejected with 422 on both endpoints and nothing is written. Omitting the field leaves the stored value unchanged.
- [ ] Existing fields and behaviour of both endpoints are unchanged: the current `test_*settings*` / named-persona API tests pass unmodified, and every existing `public_state()` key is still present with the same value.
- [ ] With the lock written through either endpoint, S1 does not switch: "Anzu, write me a script" via `/api/tasks` keeps the current persona and publishes no `persona_switched`.
- [ ] "Anzu, write me a script" sent via `POST /api/tasks` (lock off) publishes exactly one `persona_switched` on `GET /api/tasks/{id}/events`, whose `detail` JSON has `from: "anzu"`, `to: "enki"`, `reason: "intent"`, and the `decision_source` and `confidence` from the S1 decision. The task then runs on `enki`: `active_persona_id() == "enki"`, and `resolve_speaking_voice` returns Enki's voice for the task's `chat_tts` lines.
- [ ] Order on the task stream: `persona_switched` comes before `acknowledgement` and before any `chat_tts`. `apply_main_persona` is called before `speak_text`.
- [ ] Exactly one `decide_owner_turn` call per turn is asserted on `/api/tasks` (spy on `decide_owner_turn` / `evaluate_request_route`, count == 1 for `create_task` plus the full front-lane turn, and count == 1 for a `/continue` follow-up).
- [ ] Latency budget test: with the reflex fixture, the decision stays within the 50 ms budget (existing S1 budget tests stay green), and the time from `create_task` entry to the `persona_switched` publish is within the reflex budget plus a fixed activation allowance named in the test. The switch line is scheduled, not awaited (a `speak_text` that blocks for 5 s does not delay the `acknowledgement`).
- [ ] `speak_text` raising (including `SpeechRefused`) does not fail the task; the bind failure path publishes `persona_switch_failed` and keeps the previous persona.
- [ ] A "/continue" follow-up with a coding intent switches the same way (one event, one decide).
- [ ] Chit-chat via `/api/tasks` publishes no `persona_switched` and does not speak a switch line (hysteresis, as in S1).
- [ ] The owner-chat stream path is unchanged and still emits: `tests/test_persona_intent_switch_turn.py` passes unmodified, and `stream_owner_chat` still yields `persona_switched` exactly once.
- [ ] HUD chat, Chat and Phone transports are unchanged: they still `POST /api/tasks` and subscribe to `/api/tasks/{id}/events`, no request or SSE shape is removed or renamed, and no frontend file is edited by this slice.
- [ ] Approval-required tools still need approval after a tasks-path switch; `harm_veto` is unaffected.
- [ ] `python3 -m pytest` passes.

### S3 — Frontend auto-switch wiring

**Model:** Composer 2.5 (fast off) · **Lane:** UX · **Depends:** S3b (and S2, S5) · **Consumer only:** no backend edits. Every backend write and event this slice needs comes from S2 + S3b.

| Path | Why |
| --- | --- |
| Task event stream consumer (`GET /api/tasks/{id}/events`, `kind: "persona_switched"`, `detail` = S3b JSON) — the live HUD chat / Chat / Phone transport — plus the owner-chat stream consumer where it exists | Handle `persona_switched` → `activateNamedPersona(to)` (shared manual/auto path; backend already active, so no duplicate PUT side-effects beyond idempotent state sync). Typed task-event kind in the frontend stream types. No transport change. |
| `frontend/src/persona/activateNamedPersona.ts` | Accept `reason: "manual" \| "intent"`; keep selected A–E variant (`mythicAvatarForSelection`); invoke `onCloudToPersonaMorph` (S5) on every switch. |
| `NamedPersonaControls.tsx`, `PinnedPersonaDock.tsx` | Highlight updates to new persona; lock toggle surfaced, writing `auto_switch_locked` through S3b's `PUT /api/named-personas` field and reading it from `GET /api/named-personas`. Additive only. |
| Tests | Below. |

- [ ] `frontend/presence-lifecycle.test.mjs` and all #623 tests pass unchanged.
- [ ] Preservation snapshot: every item in the Live-UI list is present before and after an auto switch.
- [ ] Selected A–E variant persists across auto and manual switch.
- [ ] Dock + controls highlight the new persona.
- [ ] Morph hook called once per switch with correct ids and `reason`.
- [ ] A `persona_switched` task event (S3b) received during a HUD chat / Chat / Phone turn updates the active persona, highlight and morph hook, with no change to how those pages send.
- [ ] Lock toggle round-trips through `PUT`/`GET /api/named-personas` `auto_switch_locked`.
- [ ] `npm --prefix frontend run build` + lint pass.

### S4 — Persona UI layouts A/B/C

**Model:** Grok 4.6 (fast off) · **Depends:** S3

| Path | Why |
| --- | --- |
| `frontend/src/presence/presentationSettings.ts` (+ backend presentation settings model) | Persist `personaLayout` (`"A"` default). |
| `frontend/src/settings/AppearanceSettingsPane.tsx` / `AppearancePresenceControls.tsx` | Layout picker with preview. Additive. |
| New layout components for B and C under `frontend/src/persona/` | Each offers avatar choices (A–E variants + humanoids). Same persona state, same `activateNamedPersona`, same stage. Layout A = current live layout, untouched. |
| Tests | Below. |

- [ ] Preservation snapshot passes for layout A (identical to pre-RFC live UI).
- [ ] Select B/C → persisted across reload.
- [ ] Layout switch mid-session loses no persona, variant, slider, or chat state.
- [ ] Auto-switch works in A, B and C (highlight + morph hook + voice).
- [ ] Build + lint + pytest pass.

### S5 — Morph hook `onCloudToPersonaMorph`

**Model:** Composer 2.5 (fast off) · **Depends:** none

| Path | Why |
| --- | --- |
| New `frontend/src/presence/personaMorphHook.ts` (beside `presenceLifecycle.ts`) | Exported typed hook, no-op body. |
| Call site wiring (consumed by S3) | Awaited with a timeout (e.g. 1500 ms) so a slow Astra fill cannot block activation. |
| Test | Below. |

```ts
/**
 * Cloud → persona morph seam. Astra fills the body.
 * Taco explicitly authorized this no-op body (2026-10-14) as the single
 * exception to the no-stub rule (RFC-0218). Do not add other stubs.
 */
export type PersonaMorphContext = {
  reason: "manual" | "intent"
  layout: "A" | "B" | "C"
  variant: string
}
export function onCloudToPersonaMorph(
  from: PersonaId,
  to: PersonaId,
  ctx: PersonaMorphContext,
): void | Promise<void> {}
```

- [ ] Hook exported and typed as above.
- [ ] Invoked on every switch (manual and intent) with correct `from`, `to`, `ctx`.
- [ ] A hook that never resolves does not block activation past the timeout.
- [ ] This is the only no-op body introduced by RFC-0218.

---

## Ticket cards

| Ticket | Title | Lane | Model | Depends | Assign order |
| --- | --- | --- | --- | --- | --- |
| RFC-0218 S1 | Decision class `persona_intent_switch` | backend | Grok 4.5 (fast off) | — | 1 (∥ S5) |
| RFC-0218 S5 | Morph hook `onCloudToPersonaMorph` | frontend | Composer 2.5 (fast off) | — | 1 (∥ S1) |
| RFC-0218 S2 | Backend switch + speak + start (owner-chat stream) | backend | Grok 4.6 (fast off) | S1 | 2 |
| RFC-0218 S3b | Backend amendment: auto-switch lock write + tasks-path persona switch | D1 | Grok 4.6 (fast off) | S1, S2 | 3 |
| RFC-0218 S3 | Frontend auto-switch wiring (consumer only) | UX | Composer 2.5 (fast off) | S3b (+ S2, S5) | 4 |
| RFC-0218 S4 | Persona UI layouts A/B/C | frontend | Grok 4.6 (fast off) | S3 | 5 |

No ticket is gated on draft PRs #648 / #649 (see S3b, *Relationship to draft #649*).

## Acceptance criteria (RFC-level)

- [ ] All slice checkboxes above.
- [ ] Every implement PR has the reviewer reasoning pass for the Live-UI list.
- [ ] Unit tests pass (`python3 -m pytest`); `npm --prefix frontend run build`.

## Likely files

| Area | Paths |
| --- | --- |
| Backend | `backend/app/decision/{types,surfaces,owner_turn,__init__}.py`, `backend/app/decision/adapters/rules.py`, `backend/app/persona/{owner_chat,named_persona}.py`, `backend/app/tts/persona_speech.py`; S3b: `backend/app/api/{settings,named_personas}.py`, `backend/app/agent/loop.py` (`backend/app/agent/front_responder.py`, `backend/app/api/tasks.py` checked, not expected to change) |
| Frontend | `frontend/src/persona/*`, `frontend/src/presence/{presentationSettings,presenceLifecycle,personaMorphHook}.ts`, `frontend/src/settings/AppearanceSettingsPane.tsx` |
| Tests | `tests/test_decision_persona_intent.py`, `tests/test_persona_intent_switch_turn.py`, `tests/test_rfc0218_s3b_lock_and_tasks_switch.py`, `frontend/presence-lifecycle.test.mjs` + new frontend tests |
| Docs | `docs/rfcs/README.md` |

## Out of scope

WebGL / renderer internals; the morph animation body (Astra); roster changes (no new persona rows); RFC-0069 morph API rewrite; new voice packs; Android companion visuals.

## Notes

- PR #623 (RFC-0210 follow-up) is the regression reference for the Live-UI list.
- RFC-0217 is taken by open PR #627; this RFC takes 0218.
- 2026-10-20 amendment: S3b added from UX's S3 gap report, confirmed by D1; CoS picked option (a), which keeps chat sends on `/api/tasks` and does not move them to the owner-chat stream.
