# RFC-0218: Persona UI surfaces A/B/C + intent-driven auto persona switch

**Status:** accepted  
**Queue item:** (none in this PR — Architect may add a master-plan line after land; do not edit `JARVIS_MASTER_PLAN.md` here)  
**Author:** Jarvis Architect  
**Date:** 2026-10-14  
**Amended:** 2026-10-20 — S3b backend amendment (auto-switch lock write + tasks-path persona switch), CoS option (a). See [S3b](#s3b--backend-amendment-auto-switch-lock-write--tasks-path-persona-switch). Revised the same day after UX's review of 4425603: S3 gets a separate auto-switch path, `switch_id` dedupe with session and storage guards, a failure consumer, readable rendering, exact ownership and a CI step. S2 payload gains `switch_id` (D1), the morph has a single entry (D2), and #649 is pinned at `b5c3640`.

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
4. **No backend→UI persona event channel exists.** The backend can change persona (`named_persona._activate`) but the UI only learns about persona changes it initiated (`activateNamedPersona`). The live pages read task events by polling `GET /api/tasks/{id}` (all three) and through SSE replay (HUD chat, Chat), so any persisted event is seen many times.
5. **No named seam for the cloud→persona morph.** Astra needs a typed hook to fill.

## Decision

Ship **one RFC with six implement slices** (S1–S5, plus the S3b backend amendment of 2026-10-20), each a single CoS-assignable ticket with one named model (**fast off**).

### North-star justification

- **§3:** "> **ANZU should have presence.**" / "Morphing should feel organic. Status changes should be understandable." — the switch is a visible, spoken state change through one stage; the morph is a named seam (S5).
- **§4:** "ANZU should acknowledge simple requests almost immediately… continue heavier work without creating the impression that the entire system has frozen." and "The voice should belong to the selected ANZU personality and visual presence." — switch line is spoken in the **new** persona's voice, fire-and-forget, work starts the same turn.
- **§5:** "Specialists can be manually selected where desirable, but ANZU should normally determine when specialist capability is useful…" — auto-switch (S1/S2), manual pin keeps working and wins.
- **§6:** "deterministic rule → tiny/reflex decision system → normal code/tool execution → normal model → specialist/expert reasoning only when required" — intent is a reflex decision class answered inside `decide_owner_turn`, rules first, Laya/Jev next, deadline fallback = stay.
- **§19:** "Do not create several interfaces where one adaptive interface can work." — **A/B/C are owner-selectable layouts of ONE adaptive persona surface**, sharing one persona state, one activation module (`activateNamedPersona.ts`: the manual `activateNamedPersona` plus the auto `applyAutoPersonaSwitch` beside it, both morphing through the one `awaitPersonaMorphWithTimeout` entry), one stage, one voice binding. They are not separate apps or forks. "Do not remove useful capability merely to simplify the codebase." — live UI is additive (below). "Do not mark something finished merely because its backend exists." — S2 is not done without S3 consuming its event, and S3 is not done until S3b emits that event on the transport the live UI actually uses (`/api/tasks`).

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

Every implement PR includes a **reviewer reasoning pass**: a short section listing each preserved item and how it was verified (test or screenshot). The S3 tests (`frontend/persona-auto-switch.test.mjs`) pin the manual path's source and prove the auto path writes no presentation, variant or persona setting.

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

`persona_switched { switch_id: string, from: PersonaId, to: PersonaId, reason: "intent" | "explicit_name", decision_source: DecisionSource, confidence: number }`

`persona_switch_failed { switch_id: string, to: PersonaId, error: string, detail: string }`

Both events also carry `type` and `conversation_id`, as S2 landed them.

**`switch_id` (additive amendment, 2026-10-20, carried by the S3b ticket).** This is a stable id for one switch attempt. It is the key S3 uses to apply each switch at most once. `apply_persona_switch(intent, conversation_id, *, switch_seq: int | None = None)` sets `switch_id = f"{conversation_id}:{switch_seq}"` when the caller passes a sequence number. The tasks path (S3b) always passes one. With no sequence number, it sets `switch_id = f"{conversation_id}:{uuid4().hex}"`. That covers `stream_owner_chat`, which persists no events and so has nothing to count. The key is added to both TypedDicts (`PersonaSwitchedEvent`, `PersonaSwitchFailedEvent`). No existing key is renamed or removed, and the existing positional call `apply_persona_switch(turn.persona_intent, cid)` in `stream_owner_chat` stays as it is.

| Path | Why |
| --- | --- |
| `backend/app/persona/owner_chat.py` | On switch decision: `named_persona._activate(to)` → emit `persona_switched` → schedule speech (not awaited) → run the turn on the new persona. *(2026-10-20: `switch_id` key + keyword-only `switch_seq`, edited by the S3b ticket.)* |
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
- [ ] *(2026-10-20, added by the S3b ticket to the same file; existing tests unmodified)* `test_switch_event_carries_switch_id`: `persona_switched.switch_id` is a non-empty string that starts with `f"{conversation_id}:"`. `test_switch_failed_event_carries_switch_id`: the same holds for `persona_switch_failed`. `test_switch_ids_unique_per_turn`: two switching turns in one conversation have different `switch_id`s. `test_apply_persona_switch_explicit_seq`: `apply_persona_switch(intent, "t1", switch_seq=3)["switch_id"] == "t1:3"`.

### S3b — Backend amendment: auto-switch lock write + tasks-path persona switch

**Model:** Grok 4.6 (fast off) · **Lane:** D1 · **Depends:** S1, S2 · **Added:** 2026-10-20 (CoS option (a); gaps found by UX on S3, confirmed by D1). **Revised 2026-10-20** after UX's review of 4425603 (12 items), D1's `switch_id` item and D2's single-morph-entry item.

**Why this slice exists.** Two gaps block S3 on `development` at `3f17c3d`:

1. **Nothing writes `named_personas.auto_switch_locked`.** S1 reads it (`backend/app/decision/owner_turn.py`, `store.auto_switch_locked`) and the field exists on `NamedPersonaSettings` (`backend/app/config.py`), but neither `PUT /api/settings` (`SettingsUpdate` / `update_settings`) nor `PUT /api/named-personas` (`NamedPersonaPut` / `put_named_personas`) accepts it, and `GET /api/named-personas` (`public_state()`) does not return it. The S3 lock toggle has nothing to write to.
2. **`persona_switched` only fires on a transport no frontend uses.** S2 calls `apply_persona_switch` only in `stream_owner_chat` (`POST /api/owner/chat/messages/stream`, `backend/app/persona/owner_chat.py`). No client calls that endpoint (`frontend/` has no reference to `messages/stream`). HUD chat (`frontend/src/hud/HudChat.tsx`), Chat (`frontend/src/pages/Chat.tsx`) and Phone (`frontend/src/pages/Phone.tsx`) all send with `POST /api/tasks` (and `POST /api/tasks/{id}/continue`) → `AGENT.create_task` (`backend/app/agent/loop.py`) → front lane (`backend/app/agent/front_responder.py`). That path never calls `apply_persona_switch`. It already computes `turn.persona_intent` in its one `evaluate_request_route` → `decide_owner_turn` call, then drops it.

**How the live pages read task events (verified on `3f17c3d`).**

- HUD chat and Chat poll `GET /api/tasks/{id}` every 400 ms and read `task.events`. They also open `GET /api/tasks/{id}/events` (SSE) through `useTaskSpeech` and `useLiveAssistantPreview`.
- Phone opens **no** EventSource. It polls `GET /api/tasks/{id}` every 2 s and lists `event.title` for the last 8 of `task.events`.
- `BUS.stream` replays every persisted `TaskEvent` row on each subscribe, and `GET /api/tasks/{id}` returns every row. A persisted event is therefore seen again on every poll, reconnect, reopen and reload. Neither payload carries a row id or seq, so S3's dedupe key is `switch_id`, not a transport position.

**Fix (add-only).** Expose the lock on both write endpoints. Run the existing S2 `apply_persona_switch` on the tasks path from the `turn` that path already decides. Publish the result as a persisted `TaskEvent` with a human title. Because the event is persisted, it reaches HUD chat and Chat through both the SSE stream and the poll, and reaches Phone through the poll.

#### Part 1 — lock write

- `PUT /api/settings` (`backend/app/api/settings.py`, `update_settings`): add `named_personas_auto_switch_locked: StrictBool | None = None` to `SettingsUpdate` (flat name, same convention as `tts_*` / `front_responder_*`). When not `None`, set `settings.named_personas.auto_switch_locked` before the existing `save_settings(settings)`. The response (`settings.model_dump()`) and `GET /api/settings` already serialise `named_personas`, so the round-trip needs no new code beyond the write.
- `PUT /api/named-personas` (`backend/app/api/named_personas.py`, `put_named_personas`): add `auto_switch_locked: StrictBool | None = None` to `NamedPersonaPut`. When not `None`, persist it through a new helper `set_auto_switch_locked(locked: bool)` in `backend/app/persona/named_persona.py` (same `_load()` → mutate → `save_settings` pattern as `persist_persona_preferences`), applied before the existing `as_specialist` / `apply` branches. A lock-only write is `{"id": <active id>, "apply": false, "auto_switch_locked": true}`, which uses the existing request shape: `id` stays required, and `apply: false` with no appearance patch already returns `public_state()` without activating anything (no `apply_main_persona`, no `_maybe_activate_persona_brain`).
- `GET /api/named-personas`: `public_state()` gains one key, `"auto_switch_locked": bool`. All existing keys keep their names and values.
- Validation: `StrictBool`, so `"yes"`, `1` and `"true"` are rejected with 422 and nothing is written. Omitting the field changes nothing.
- No other field, default or behaviour of either endpoint changes. S3b adds no settings merge and no write lock of its own (see *Relationship to draft #649*, `config.py`).

#### Part 2 — tasks-path persona switch

- **Where:** `AgentRuntime.create_task` in `backend/app/agent/loop.py` (this is where the tasks path decides; `api/tasks.py::create_task` only delegates). Insert the call after the new `Task` row is committed, because `BUS.publish` persists a `TaskEvent` with a task FK. It must come before the `acknowledgement` publish and before `_start_runner`, so nothing on the task is spoken or run before activation:
  ```python
  from ..persona.owner_chat import apply_persona_switch          # S2 function, reused, no copy
  from ..tts.persona_speech import schedule_persona_switch_announcement
  seq = await _next_persona_switch_seq(task.id)                  # new helper in loop.py, below
  persona_event = apply_persona_switch(turn.persona_intent, task.id, switch_seq=seq)
  if persona_event is not None:
      await BUS.publish(task.id, persona_event["type"], persona_event_title(persona_event),
                        json.dumps(persona_event), stage="queued")
      if persona_event["type"] == "persona_switched":
          schedule_persona_switch_announcement(persona_event["to"])   # fire-and-forget, as S2
  ```
- **`_next_persona_switch_seq(task_id) -> int`** (new, `loop.py`): `1 + COUNT(TaskEvent)` for that `task_id` with `kind IN ("persona_switched", "persona_switch_failed")`. The first switch on a task is `"<task_id>:1"` and a `/continue` switch on the same task is `"<task_id>:2"`. The id is in the persisted `detail`, so SSE replay, reconnect, reload and Phone's poll all return the identical `switch_id`. `apply_persona_switch` returns `None` for a stay, so a counted number is only ever used for an event that is actually published.
- **Titles (`persona_event_title(event) -> str`, new, `loop.py`):** `persona_switched` → `"Persona switched to <Label>"`. `persona_switch_failed` → `"Persona switch failed"`. `<Label>` is `CATALOG[to].label` from `backend/app/persona/named_persona.py`, for example `"Persona switched to Enki"`. There is no placeholder title. Phone lists `event.title`, so Phone shows these strings as they are.
- **Payload:** the task-stream event is `kind: "persona_switched"`, and its `detail` is the S2 `PersonaSwitchedEvent` as JSON: `{type, conversation_id (= task id), switch_id, from, to, reason, decision_source, confidence}`. A bind failure publishes `kind: "persona_switch_failed"` with the S2 `PersonaSwitchFailedEvent` JSON, `{type, conversation_id, switch_id, to, error, detail}`, and the previous persona stays. `detail` remains machine JSON for S3. Owner-facing surfaces render it through S3's formatter and never show the raw JSON (S3, *Rendering*).
- **Follow-up turns** (`POST /api/tasks/{id}/continue`): `_run` already makes the follow-up decision (`follow_turn`, stored with `_remember_owner_turn`). It gets the same block, with `seq` from `_next_persona_switch_seq(task_id)`, placed after `_remember_owner_turn(task_id, follow_turn)` and before `_run_conversation` or the managed run. "Anzu, now write me a script" inside an existing chat task therefore also switches.
- **Exactly one decide per turn.** No new `evaluate_request_route` / `decide_owner_turn` call. The switch reads `turn.persona_intent` from the decision `create_task` (or `_run` for follow-ups) already made. `front_responder.generate_front_reply` / `run_two_lane_chat` keep receiving that same remembered turn as `turn_decision` (loop.py passes it through), so their `if decision is None:` fallback decide never runs on this path. `backend/app/agent/front_responder.py` is not edited.
- **Budget:** the decision stays inside the RFC-0206 / S1 reflex budget (`OWNER_TURN_DEADLINE_MS = 50.0`, unchanged). `apply_persona_switch` is synchronous local work (`apply_main_persona` only; no `_maybe_activate_persona_brain`, so no model hotswap on this path). `_next_persona_switch_seq` is one indexed count. The speech is scheduled and never awaited. The hard limit is in Acceptance.
- **Order:** `apply_main_persona(to)` (inside `apply_persona_switch`) → publish `persona_switched` → schedule switch line → `acknowledgement` / `chat_tts` / runner. Every line spoken for the task therefore resolves to the new persona's voice.
- **Same turn, no confirmation:** the task runs immediately on the new persona. No prompt, no pause, no extra event to wait for.
- **Not moved:** chat sends stay on `/api/tasks`. No frontend send is moved to `/api/owner/chat/messages/stream`, because moving them is a live-UI transport risk. `stream_owner_chat` keeps its S2 call (positional, uuid `switch_id`). That endpoint has no client today and is kept for API parity. Any future client of it must route its `persona_switched` / `persona_switch_failed` events through S3's handler (`frontend/src/persona/personaSwitchEvents.ts`) and add no second consumer.
- **Policy:** approvals, `harm_veto` and the task's tool exposure are computed exactly as before, and a switch does not alter them (S2 rule 9).

#### Ownership (S3b)

| Path | Change |
| --- | --- |
| `backend/app/api/settings.py` | `SettingsUpdate.named_personas_auto_switch_locked: StrictBool \| None`; write in `update_settings`. Add-only. *(#649 file)* |
| `backend/app/api/named_personas.py` | `NamedPersonaPut.auto_switch_locked: StrictBool \| None`; write via `set_auto_switch_locked` in `put_named_personas`. Add-only. *(#649 file)* |
| `backend/app/persona/named_persona.py` | New `set_auto_switch_locked(locked)`; `public_state()` adds the `auto_switch_locked` key. Add-only. |
| `backend/app/persona/owner_chat.py` | S2 amendment only: `switch_id` key on both TypedDicts and keyword-only `switch_seq` on `apply_persona_switch`. `stream_owner_chat` is not edited. Add-only. *(#649 file)* |
| `backend/app/agent/loop.py` | `create_task` and the `_run` follow-up branch call S2 `apply_persona_switch` on the existing `turn` / `follow_turn` and publish on `BUS`. New helpers `_next_persona_switch_seq` and `persona_event_title`. Add-only. *(#649 file)* |
| `backend/app/decision/owner_turn.py` | Only in the order "#649 lands first": the `basic_qa` stay guard (see *Relationship to draft #649*). Not edited otherwise. *(#649 file)* |
| `backend/app/agent/front_responder.py` | **Not edited.** Checked: the tasks path always passes the remembered turn. *(#649 file)* |
| `backend/app/api/tasks.py` | **Not edited.** `POST /api/tasks` delegates to `AGENT.create_task`, and `GET /api/tasks/{id}` and `GET /api/tasks/{id}/events` already return every persisted kind. *(#649 file)* |
| `backend/app/config.py` | **Not edited.** *(#649 file)* |
| `tests/test_rfc0218_s3b_lock_and_tasks_switch.py` (new) | All S3b acceptance below. |
| `tests/test_persona_intent_switch_turn.py` | Append-only: the four S2 `switch_id` tests. Existing tests unmodified. |

#### Relationship to draft #649

Pinned at **#649 head `b5c3640`** (RFC-0223/0224, branch `cursor/task-latency-and-quality-99ea`). As of that head, #649 does not touch `auto_switch_locked`, `apply_persona_switch`, the S2 event TypedDicts, `persona_intent`, or the `create_task` decision block. The overlap, file by file:

| File | What #649 changes at `b5c3640` | How S3b / S3 reconcile, either order |
| --- | --- | --- |
| `backend/app/api/settings.py` | Front reconfigure task; `large_task_reviews`. | Different fields and lines. S3b's field is appended to `SettingsUpdate`. Mechanical rebase. |
| `backend/app/api/named_personas.py` | `get_named_personas` becomes sync (`def`, not `async def`). | Use whichever signature is on the base. S3b does not touch `get_named_personas`. |
| `backend/app/api/tasks.py` | `prompt_steps` in the task payload. | S3b does not edit it. Persona events stay in `payload["events"]`. |
| `backend/app/agent/loop.py` | Workflow gating (`stored_workflow` / `needs_workflow`) around the follow-up branch. | Put the follow-up block after #649's workflow computation and `_remember_owner_turn`, before the conversation or managed run. Do not duplicate the gating. |
| `backend/app/persona/owner_chat.py` | Sequential intake in `stream_owner_chat` goes through `AGENT.create_task` instead of `start_sequential_chain`. | The S3b hunk (TypedDicts + `apply_persona_switch`, lines ~70–130) is separate from #649's hunk (~376–415). With #649, sequential-intake turns switch through S3b's `create_task` block, and that block is still the turn's only decision, because `stream_owner_chat` returns before its own decide on the sequential path. |
| `backend/app/agent/front_responder.py` | `basic_qa` fall-through: `_fall_through_failed_self_status` and `fallback_text_for_action` treat `basic_qa` like `self_status`. `small_context_envelope` folds the action hint and snapshot into **one** leading system message (Qwen template). | S3b does not edit this file and adds no system message. The persona voice and prompt come from `apply_main_persona` before the front runs, so the single-system-message rule holds. |
| `backend/app/config.py` | `save_settings` becomes merge-safe: a `_saved_snapshot` PrivateAttr, `_merge_settings_changes`, `_SETTINGS_WRITE_LOCK` and an atomic temp-file replace. | S3b adds **no** merge or lock of its own. Both lock writes go through `save_settings`. If #649 is on the base, a stale `AppSettings` saved by an unrelated writer does not revert the lock, because the lock is not in that writer's diff. Tests are below. |
| `backend/app/decision/owner_turn.py` | Adds `basic_qa` to `REPLY_SHAPES`, plus `is_quick_knowledge_question`, `infer_rules_reply_shape` → `basic_qa`, and a `_apply_floors` guard. | **Decision:** a `basic_qa` turn is a short knowledge answer on the front, not a new task intent, so it never auto-switches (hysteresis, Switch behaviour 4). An explicit name of a *different* persona still wins (S1 precheck). The guard goes in `decide_owner_turn` after `_apply_floors`: if the final `reply_shape == "basic_qa"` and `persona_intent.reason == "intent"`, replace it with `persona_intent_stay(current, reason="no_intent", source=<same>)`. Whichever of S3b / #649 lands **second** adds this guard and the two `basic_qa` tests below, because `basic_qa` does not exist on `development` without #649. |
| `frontend/src/api.ts` | `Task.prompt_steps` and `TaskObservability.prompt_steps`. | S3's additions (new exported types after the `Task` block) do not touch `Task`'s fields. Whichever lands second keeps both. |
| `frontend/src/App.tsx` | Chat, Phone (and other pages) become `lazy()` imports. | S3 does **not** edit `App.tsx`. The handler is imported by the pages themselves, and its state lives in `sessionStorage` / `localStorage`, so lazy loading does not change behaviour in either order. |

- **No gate.** S3b and S3 land on `development` without #648 or #649.
- **If #649 lands first:** S3b rebases onto it, follows the table, and adds the `basic_qa` guard and tests plus `test_lock_not_reverted_by_stale_settings_save`.
- **If S3b lands first:** #649 rebases onto S3b. Every S3b hunk is additive, so the rebase is mechanical. #649's rebase adds the `basic_qa` guard, the two `basic_qa` tests and `test_lock_not_reverted_by_stale_settings_save` into `tests/test_rfc0218_s3b_lock_and_tasks_switch.py`.

#### Acceptance (S3b)

All in `tests/test_rfc0218_s3b_lock_and_tasks_switch.py` unless another file is named.

- [ ] `test_settings_put_lock_round_trip`: `PUT /api/settings {"named_personas_auto_switch_locked": true}` persists the lock; the response and a following `GET /api/settings` return `named_personas.auto_switch_locked == true`; `false` round-trips back.
- [ ] `test_named_personas_put_lock_round_trip`: `PUT /api/named-personas {"id": <active>, "apply": false, "auto_switch_locked": true}` persists the lock without activating or changing any persona (no `apply_main_persona`, no `_maybe_activate_persona_brain` call); the response and a following `GET /api/named-personas` return `auto_switch_locked == true`; `false` round-trips back.
- [ ] `test_lock_rejects_non_bool` (parametrised over both endpoints × `"yes"`, `1`, `"true"`): 422 and nothing is written. `test_lock_omitted_unchanged`: omitting the field leaves the stored value unchanged.
- [ ] Existing behaviour unchanged. These pass unmodified: `tests/test_named_personas_api.py`, `tests/test_rfc0137_named_persona.py`, `tests/test_inference_stack_settings.py`, `tests/test_presentation_settings.py`. `test_public_state_keys_superset`: every pre-existing `public_state()` key is still present with the same value.
- [ ] `test_lock_not_reverted_by_unrelated_settings_put`: lock on via `PUT /api/named-personas`, then an unrelated `PUT /api/settings` (e.g. a `tts_*` field). The lock is still `true`. Runs in both orders.
- [ ] `test_lock_not_reverted_by_stale_settings_save` (only once #649's merge-safe `save_settings` is on the base; added by whichever lands second): load `AppSettings` A, write the lock through `PUT /api/named-personas`, then `save_settings(A)` with an unrelated change. The lock is still `true`.
- [ ] `test_lock_blocks_intent_switch_on_tasks`: with the lock written through either endpoint, "Anzu, write me a script" via `POST /api/tasks` keeps the current persona and publishes no `persona_switched`.
- [ ] `test_explicit_name_overrides_lock_create` and `test_explicit_name_overrides_lock_continue`: with the lock on and `anzu` active, "Enki, write me a script" via `POST /api/tasks` produces exactly one `persona_switched` with `reason: "explicit_name"`, `to: "enki"`. The same holds for a `POST /api/tasks/{id}/continue` follow-up.
- [ ] `test_tasks_intent_switch_event`: "Anzu, write me a script" sent via `POST /api/tasks` (lock off) publishes exactly one `persona_switched`. Its title is `"Persona switched to Enki"`, and its `detail` JSON has `switch_id == f"{task_id}:1"`, `from: "anzu"`, `to: "enki"`, `reason: "intent"`, and the `decision_source` and `confidence` from the S1 decision. The task then runs on `enki`: `active_persona_id() == "enki"`, and `resolve_speaking_voice` returns Enki's voice for the task's `chat_tts` lines.
- [ ] `test_switch_event_in_task_poll_and_stream`: the same event, with the same `title`, `detail` and `switch_id`, appears in `GET /api/tasks/{id}` `events` (the poll Phone uses) and in a fresh `GET /api/tasks/{id}/events` subscription (replay). Two subscriptions and two polls return the identical `switch_id`.
- [ ] `test_continue_switch_id_increments`: a `/continue` follow-up that switches publishes `switch_id == f"{task_id}:2"`, after a `create_task` that switched with `:1`.
- [ ] `test_switch_order_on_task_stream`: `persona_switched` comes before `acknowledgement` and before any `chat_tts`; `apply_main_persona` is called before `speak_text`.
- [ ] `test_one_decide_per_turn_create` and `test_one_decide_per_turn_continue`: a spy on `decide_owner_turn` and `evaluate_request_route` counts exactly 1 call for `create_task` plus the full front-lane turn, and exactly 1 for a `/continue` follow-up.
- [ ] `test_tasks_first_text_not_delayed_by_switch` (mirrors S2's `test_first_text_not_delayed_by_switch`). `BUS.publish` is wrapped to record `time.perf_counter()` per event, and the front model is stubbed to return immediately, as in the S2 fixture. Managed route ("Anzu, write me a script"): `t(acknowledgement) − t(persona_switched) < OWNER_TURN_DEADLINE_MS` (50.0 ms). Conversation route ("Enki, how are you?" with `anzu` active): `t(first chat_tts) − t(persona_switched) < OWNER_TURN_DEADLINE_MS`. The test imports the constant and asserts it equals 50.0, so the limit cannot drift silently.
- [ ] `test_switch_line_not_awaited`: a `speak_text` that blocks for 5 s does not move the `acknowledgement` publish; the limit above still holds.
- [ ] `test_speech_failure_does_not_fail_task`: `speak_text` raising (including `SpeechRefused`) does not fail the task.
- [ ] `test_bind_failure_publishes_failed`: a bind failure publishes one `persona_switch_failed` with title `"Persona switch failed"` and a `detail` JSON carrying `switch_id`, `to`, `error`, `detail`. The previous persona stays and no switch line is spoken.
- [ ] `test_chit_chat_no_switch`: "thanks" via `/api/tasks` publishes no persona event and speaks no switch line (hysteresis, as in S1).
- [ ] `test_basic_qa_addressing_current_stays` (both orders): with `anzu` active, "Anzu, what is a closure?" publishes no persona event, and the reply comes from Anzu.
- [ ] `test_basic_qa_with_intent_cue_stays` (added by whichever of S3b / #649 lands second): with `anzu` active, "what is a python function?" is decided as `reply_shape == "basic_qa"`, publishes no `persona_switched`, and `persona_intent.reason == "no_intent"`. "Enki, what is a python function?" still switches with `reason: "explicit_name"`.
- [ ] The owner-chat stream path is unchanged and still emits: the existing tests in `tests/test_persona_intent_switch_turn.py` pass unmodified, and `stream_owner_chat` still yields `persona_switched` exactly once (now with a `switch_id`).
- [ ] `test_transports_unchanged`: HUD chat, Chat and Phone still `POST /api/tasks` / `/continue`. No request, poll or SSE shape is removed or renamed, and no frontend file is edited by this slice.
- [ ] `test_policy_unchanged_after_switch`: approval-required tools still need approval after a tasks-path switch; `harm_veto` is unaffected.
- [ ] `python3 -m pytest` passes. The PR checks "Run full backend suite" step in `.github/workflows/pr-tests.yml` already runs this file; no CI edit is needed.

### S3 — Frontend auto-switch wiring

**Model:** Composer 2.5 (fast off) · **Lane:** UX · **Depends:** S3b (and S2, S5) · **Consumer only:** no backend edits. Every backend write and event this slice needs comes from S2 + S3b.

#### Why the manual path cannot be reused (verified on `3f17c3d`)

`activateNamedPersona` does three things:

1. It calls `updatePresentation({shell: "hud", requestedPresence: "particle_bust", avatarId})`, which forces the HUD shell.
2. It calls `selectNamedPersona(id)`, which sends `PUT /api/named-personas {id}`. On the server that means `apply=true, activate_brain=true` by default, so `apply_main_persona` runs a second time and `_maybe_activate_persona_brain` is scheduled, which can hotswap the model mid-task.
3. It runs the morph through `awaitPersonaMorphWithTimeout`.

For an auto-switch the backend has already activated the persona (S3b), so steps 1 and 2 would be harmful: a classic-shell Chat page would flip to HUD, and a brain hotswap would land in the middle of the task. Only the morph (step 3) and a state refresh are wanted.

#### Add-alongside reasoning (live-UI rule)

- **Manual path: unchanged.** `activateNamedPersona` and `activatePersonaVoice` in `frontend/src/persona/activateNamedPersona.ts` keep their current bodies byte for byte. Every manual caller (`NamedPersonaControls.tsx`, `PinnedPersonaDock.tsx`, layout B/C later) keeps the PUT, the HUD presentation update, the voice-pack install retry and the morph exactly as today. The `reason?` option S5 added stays, and manual callers keep passing nothing (that is, `"manual"`).
- **Auto path: added next to it.** A new export `applyAutoPersonaSwitch(sw, options)` goes in the same file, below `activateNamedPersona`. It does exactly three things, in order:
  1. Read the displayed persona: `displayed = currentActivePersonaId()`.
  2. `await loadNamedPersonas()`. This is a GET only, and it publishes the server state, so the active persona, Dock highlight and Controls highlight update through the existing `namedPersonas` listeners. Its existing `selectionRevision` guard keeps a later manual pick from being overwritten.
  3. Run the morph through **the same entry** the manual path uses: `awaitPersonaMorphWithTimeout(displayed, sw.to, {reason: "intent", layout: "A", variant: mythicAvatarForSelection(readPresentationBootstrap().avatarId)}, undefined, options.morphHook)`. That is the same default hook `onCloudToPersonaMorph` (the typed no-op), the same `PERSONA_MORPH_TIMEOUT_MS` (1500 ms) and the same never-throw behaviour. There is no second morph call path, no second hook and no second timeout (D2). It uses the same gate as the manual path: the morph runs only when `displayed` and `sw.to` are both roster ids and `displayed !== sw.to`. **Server-truth gate (added after UX re-peer at bfb9136):** the morph also runs only when the active persona in the GET response from step 2 (`state.active.id`) equals `sw.to`. If it differs (a manual pick made in this tab before or after a reload, in another tab or on another device), there is no morph and no highlight change toward `sw.to`. The highlight shows the server's active persona, which the GET already published, and the `switch_id` stays recorded as applied (it was marked before `applyAutoPersonaSwitch` ran).
- **What the auto path never does:** no `PUT /api/named-personas`, no `selectNamedPersona`, no `updatePresentation` (shell, presence and `avatarId` untouched), no voice-pack install, and no brain activation. The selected A–E variant persists because nothing writes `avatarId`.
- **Once per switch, across both routes (D2).** The morph runs at most once per on-screen persona change. On the auto route, `switch_id` dedupe (below) means a switch is handled once. Both routes use the `displayed !== to` gate, so a manual pick of Enki followed by an auto `persona_switched` to Enki morphs once (the manual one), and an auto switch to Enki followed by a manual click on Enki also morphs once.
- **Preserved items** (Live-UI list) are checked in the implement PR's reviewer reasoning pass and by the `persona-auto-switch` tests below.

#### Handler, guards and storage (`frontend/src/persona/personaSwitchEvents.ts`, new)

One handler serves every page: `handlePersonaTaskEvents(taskId, events, deps?)`. `events` is any array of task events, from a poll (`task.events`) or an SSE message. `deps` lets the tests inject storage, clock, `applyAutoPersonaSwitch` and the notice sink. It parses only `kind === "persona_switched" | "persona_switch_failed"`, reads `switch_id` from `detail` JSON, and applies a switch only when **all** guards pass:

1. **Sent in this session.** `taskId` is in the sent-task registry.
2. **Not already applied.** `switch_id` is not in the applied-switch store.
3. **Not pre-existing.** It was not already on the task when this client registered a `/continue` on it (that registration marks those ids applied without applying them).

The guards run in that order. The `switch_id` is written to the applied store **before** `applyAutoPersonaSwitch` runs (mark-then-apply), so a poll and an SSE message that deliver the same event in the same tick apply it once. Events with no `switch_id` or unparsable `detail` are ignored, with one `console.warn`.

**Sent-task registry (guard i).**

- **Key:** `anzu.persona.sentTasks.v1` in `sessionStorage`.
- **Scope:** one browser tab session. It survives a reload of the same tab, and a new tab or a closed tab starts empty. Another tab, another device, or a task opened from history or Phone's task list is therefore never "sent in this session".
- **Value:** a JSON array of `{taskId: string, sentAt: number /* Date.now() */}`.
- **Write:** `registerSentTask(taskId, knownEvents)`, called by each page right after its own successful `POST /api/tasks` (with `created.id`) and after its own successful `POST /api/tasks/{id}/continue`. For `/continue`, every `switch_id` already present in the page's current `task.events` is first marked applied without applying (guard iii).
- **Cap and eviction:** keep the 50 newest by `sentAt`. On insert beyond 50, the oldest is dropped. Re-registering an existing `taskId` updates its `sentAt`.

**Applied-switch store (guard ii).**

- **Key:** `anzu.persona.appliedSwitches.v1` in `localStorage`.
- **Scope:** per origin, so per device and browser profile. It survives reload and tab close.
- **Value:** a JSON object `{[taskId]: {ids: string[], lastAt: number}}`.
- **Write:** add the `switch_id` under its task and set `lastAt = Date.now()`.
- **Retention and eviction:** on every read and write, first drop tasks whose `lastAt` is older than **30 days**, then, if more than **100 tasks** remain, drop the oldest by `lastAt` until 100 remain. Ids are only evicted per task, never one at a time. **A task that is in the current tab's sent-task registry is never evicted**, so an id can't be forgotten while its task can still pass guard (i).
- **Storage unavailable** (private mode, quota, or the storage API throws): both registries fall back to in-memory maps for the page lifetime. A reload then starts with an empty sent-task registry, so guard (i) alone prevents re-applying. Nothing is applied by guesswork.

**Manual pick after send.** If the owner picked a persona manually (any `activateNamedPersona` call with `reason` `"manual"` or unset, recorded as `lastManualPickAt`) after the task's `sentAt`, a later-arriving `persona_switched` for that task is marked applied but **not** applied. The server already reflects the manual pick, and the auto path must not morph away from it. The handler records the pick through an `onManualPersonaPick()` call that the S3 mounts make next to their existing manual activation calls. `activateNamedPersona` itself is not edited.

- **Key:** `anzu.persona.lastManualPickAt.v1` in `sessionStorage`.
- **Scope:** one browser tab session, so it survives a reload of the same tab, like `sentTasks`.
- **Value:** a single number (`Date.now()` at the pick), overwritten on each manual pick; there is nothing to evict.
- **Storage unavailable:** an in-memory value for the page lifetime. A reload then loses it, and the server-truth gate in `applyAutoPersonaSwitch` still prevents a morph away from the manual pick.

**Failure consumer (`persona_switch_failed`).** The failure event goes through the same guards and dedupe. On a fresh failure:

- The highlight stays on the previous persona (no GET is needed, and none is made).
- The new component `frontend/src/persona/PersonaSwitchNotice.tsx` shows an owner-visible notice: `"Couldn't switch to <Label>: <detail>"`, where `<Label>` comes from `PERSONA_LABELS[to]` and `<detail>` is the event's `detail` field.
- The notice has `role="status"`, `aria-live="polite"` and a Dismiss button. It stays until it is dismissed or a later switch on that page succeeds.
- It is mounted additively in HUD chat, Chat and Phone.

#### Rendering: readable text, never raw JSON

`formatPersonaSwitchEvent(event): string | null` (pure, in `personaSwitchEvents.ts`) returns:

- `persona_switched`, `reason: "intent"` → `"Switched from <From> to <To> for this request"`
- `persona_switched`, `reason: "explicit_name"` → `"Switched from <From> to <To> — you asked for <To>"`
- `persona_switch_failed` → `"Couldn't switch to <To>: <detail>"`
- any other kind → `null`

Labels come from `PERSONA_LABELS`. When it returns `null`, callers keep their existing rendering.

- **Show work** (`frontend/src/chat/ownerChatView.ts` + `frontend/src/chat/OwnerChatTranscript.tsx`): add `workEventDetailText(event)` to `ownerChatView.ts`, which returns `formatPersonaSwitchEvent(event) ?? event.detail`. `OwnerChatTranscript.tsx` uses it in place of `event.detail` at its three detail lines (the `.slice(0, 400)` / `.slice(0, 800)` truncation stays). For every other kind the output is byte-identical. `filterWorkEvents` is unchanged, so persona events stay visible in the work panel.
- **Ops rail** (`frontend/src/hud/HudOpsRail.tsx`): the event row's detail uses `workEventDetailText(event).slice(0, 80)` instead of `event.detail.slice(0, 80)`. The label is the S3b title. The output is unchanged for other kinds.
- **Phone** (`frontend/src/pages/Phone.tsx`): the list shows `event.title`, which S3b makes human (`"Persona switched to Enki"`, `"Persona switch failed"`), so the list needs no rendering change. The failure detail reaches the owner through `PersonaSwitchNotice`.

#### Mounts (additive)

- **HUD chat** (`frontend/src/hud/HudChat.tsx`) and **Chat** (`frontend/src/pages/Chat.tsx`):
  - Call `registerSentTask` after their existing `POST /api/tasks` and `/continue` calls succeed.
  - Call `usePersonaSwitchEvents(task)` (a hook exported by `personaSwitchEvents.ts`) on the `task` they already poll every 400 ms, which feeds `task.events` to `handlePersonaTaskEvents`.
  - Render `<PersonaSwitchNotice />`.
  - No new EventSource is opened. The existing SSE readers (`useTaskSpeech`, `useLiveAssistantPreview`) ignore the new kinds and are not edited.
- **Phone** (`frontend/src/pages/Phone.tsx`): same three additions. `usePersonaSwitchEvents(active)` consumes the `task.events` from its existing 2 s `GET /api/tasks/{id}` poll. No EventSource is added to Phone and the poll interval is unchanged.
- **Latency:** the highlight and morph follow within one poll (≤ 400 ms on HUD chat and Chat, ≤ 2 s on Phone). The switch line is already spoken by the backend at switch time, so voice feedback does not wait for the poll.

#### Ownership (S3)

| Path | Change |
| --- | --- |
| `frontend/src/persona/personaSwitchEvents.ts` (new) | `handlePersonaTaskEvents`, `usePersonaSwitchEvents`, `registerSentTask`, `onManualPersonaPick`, `formatPersonaSwitchEvent`, both storage registries, the `anzu.persona.lastManualPickAt.v1` sessionStorage value (in-memory fallback). |
| `frontend/src/persona/PersonaSwitchNotice.tsx` (new) | Owner-visible failure notice. |
| `frontend/src/persona/activateNamedPersona.ts` | **Add-only:** new export `applyAutoPersonaSwitch` (morphs only when the GET's active persona equals `sw.to`). `activateNamedPersona` / `activatePersonaVoice` bodies unchanged. |
| `frontend/src/api.ts` | **Add-only:** `export type TaskEvent = NonNullable<Task["events"]>[number]`, `PersonaSwitchedDetail`, `PersonaSwitchFailedDetail`, `PersonaTaskEventKind = "persona_switched" \| "persona_switch_failed"`. These go after the `Task` type, and `Task["events"]` keeps `kind: string`. |
| `frontend/src/hud/HudChat.tsx`, `frontend/src/pages/Chat.tsx`, `frontend/src/pages/Phone.tsx` | **Add-only mounts:** `registerSentTask` after their own sends, `usePersonaSwitchEvents`, `<PersonaSwitchNotice />`. (None of the three calls `activateNamedPersona` today.) |
| `frontend/src/chat/ownerChatView.ts` | **Add-only:** `workEventDetailText`. |
| `frontend/src/chat/OwnerChatTranscript.tsx` | The three `event.detail` reads become `workEventDetailText(event)`. Output is unchanged for other kinds. |
| `frontend/src/hud/HudOpsRail.tsx` | The event-row detail goes through `workEventDetailText`. Output is unchanged for other kinds. |
| `frontend/src/persona/NamedPersonaControls.tsx`, `frontend/src/persona/PinnedPersonaDock.tsx` | Lock toggle (writes `auto_switch_locked` through S3b's `PUT /api/named-personas` field and reads it from `GET /api/named-personas`), and `onManualPersonaPick()` next to their existing `activateNamedPersona` calls. Highlight comes from the existing listeners. Additive only. |
| `frontend/persona-auto-switch.test.mjs` (new) | All S3 tests below. |
| `frontend/persona-auto-switch-test-loader.mjs`, `frontend/persona-auto-switch-test-stubs.mjs` (new) | Module stubs that count PUT, `updatePresentation`, `selectNamedPersona` and GET calls. S5's `persona-morph-test-loader.mjs` / `persona-morph-test-stubs.mjs` are not edited. |
| `frontend/package.json` | **Add-only:** `"test:persona-auto-switch": "node --experimental-strip-types --test persona-auto-switch.test.mjs"`. |
| `.github/workflows/pr-tests.yml` | **Add-only, one step, owned by this S3 ticket.** It is a single additive step in the `frontend-build` job, after "Persona morph hook tests (RFC-0218 S5)": `- name: Persona auto-switch tests (RFC-0218 S3)` / `run: npm run test:persona-auto-switch`. Precedent: S5 (#635, also a frontend Composer ticket) added its own step the same way. No other line of the workflow changes. |

#### Acceptance (S3)

All in `frontend/persona-auto-switch.test.mjs` (CI: "Persona auto-switch tests (RFC-0218 S3)") unless another file is named.

- [ ] `frontend/presence-lifecycle.test.mjs`, `frontend/persona-morph-hook.test.mjs` and all #623 tests pass unchanged.
- [ ] `manual path unchanged`: the source text of `activateNamedPersona` and `activatePersonaVoice` in `src/persona/activateNamedPersona.ts` hashes to the value pinned from `development@3f17c3d`, and an existing manual activation still sends one `PUT /api/named-personas {id}` and one `updatePresentation({shell: "hud", …})`.
- [ ] `auto switch makes no PUT and no presentation change`: on `persona_switched` there are zero `PUT /api/named-personas` calls, zero `selectNamedPersona` calls, zero `updatePresentation` calls and exactly one `GET /api/named-personas`. Shell, presence and `avatarId` are unchanged (the A–E variant persists), and the published active persona is `to`.
- [ ] `auto switch morphs through the shared entry`: the morph hook is called once, through `awaitPersonaMorphWithTimeout`, with `(displayed, to, {reason: "intent", layout: "A", variant})`. A hook that never resolves releases after `PERSONA_MORPH_TIMEOUT_MS`.
- [ ] `manual then auto to same persona morphs once` and `auto then manual to same persona morphs once`.
- [ ] `no re-apply on replay`: the same `persona_switched` delivered twice in one `events` array, and then again in a second call, applies once (one GET, one morph).
- [ ] `no re-apply on reconnect`: an SSE-shaped redelivery of every persisted event after the switch was applied applies nothing.
- [ ] `no re-apply on reload`: apply a switch, then clear module memory while keeping `sessionStorage` / `localStorage` (simulated reload), and feed the same `task.events`. Nothing is applied. With `localStorage` unavailable and `sessionStorage` cleared, nothing is applied either.
- [ ] `no re-apply on Phone poll`: five consecutive polled `task.events` arrays containing the same switch apply once.
- [ ] `not sent in this session`: events of a task opened from history or Phone's task list (never registered) apply nothing.
- [ ] `continue does not resurrect old switches`: registering a `/continue` on a task whose `events` already hold `"<id>:1"` does not apply `:1`, and a new `"<id>:2"` is applied once.
- [ ] `manual pick after send wins`: `onManualPersonaPick()` after `registerSentTask`, followed by the task's `persona_switched`, gives no morph and no GET-driven change, and the id is marked applied.
- [ ] `manual pick survives reload and late auto switch does not morph`: `registerSentTask`, then `onManualPersonaPick()` (manual pick of Odin), then a simulated reload (module memory cleared, `sessionStorage` / `localStorage` kept). The task's `persona_switched` to Enki then arrives. `anzu.persona.lastManualPickAt.v1` is still set after the reload, there is no morph and no GET-driven change, and the `switch_id` is marked applied.
- [ ] `GET active persona differs from sw.to so no morph`: a sent task's fresh `persona_switched` to Enki, with the stubbed `GET /api/named-personas` returning active Odin, gives zero morph-hook calls, no highlight change toward Enki (the published active persona is Odin), and the `switch_id` marked applied.
- [ ] `eviction`: with 101 tasks and one of them older than 30 days, the store keeps ≤ 100 and drops the expired and oldest first. A task in the sent-task registry is never evicted. `sentTasks` keeps the newest 50.
- [ ] `failure notice`: `persona_switch_failed` renders `"Couldn't switch to Enki: <detail>"` once (also deduped by `switch_id`), the highlight stays on the previous persona, and no PUT or GET is made.
- [ ] `readable rendering`: `formatPersonaSwitchEvent` and `workEventDetailText` return the three readable strings and never a string starting with `{`. For a non-persona event, `workEventDetailText(event) === event.detail`.
- [ ] `lock toggle round-trips`: it writes `auto_switch_locked` through `PUT /api/named-personas` with `apply: false` and reads it from `GET /api/named-personas`.
- [ ] Preservation (Live-UI list): the implement PR's reviewer reasoning pass lists each preserved item with a screenshot, and the tests above show that the auto path writes no presentation, variant or persona setting.
- [ ] `npm --prefix frontend run build` passes (the `frontend-build` "Build frontend" step, which includes `tsc -b`). Lint (`oxlint`) is not a CI gate and is not part of this acceptance.

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
- [ ] `npm --prefix frontend run build` + the `frontend-build` named test steps + `python3 -m pytest` pass (oxlint is not a CI gate).

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
| RFC-0218 S3b | Backend amendment: auto-switch lock write + tasks-path persona switch (+ S2 `switch_id`) | D1 | Grok 4.6 (fast off) | S1, S2 | 3 |
| RFC-0218 S3 | Frontend auto-switch wiring (consumer only; owns one `pr-tests.yml` step) | UX | Composer 2.5 (fast off) | S3b (+ S2, S5) | 4 |
| RFC-0218 S4 | Persona UI layouts A/B/C | frontend | Grok 4.6 (fast off) | S3 | 5 |

No ticket is gated on draft PRs #648 / #649 (see S3b, *Relationship to draft #649*).

## Acceptance criteria (RFC-level)

- [ ] All slice checkboxes above.
- [ ] Every implement PR has the reviewer reasoning pass for the Live-UI list.
- [ ] Unit tests pass (`python3 -m pytest`); `npm --prefix frontend run build`; `npm --prefix frontend run test:persona-morph-hook` and `test:persona-auto-switch`.

## Likely files

| Area | Paths |
| --- | --- |
| Backend | `backend/app/decision/{types,surfaces,owner_turn,__init__}.py`, `backend/app/decision/adapters/rules.py`, `backend/app/persona/{owner_chat,named_persona}.py`, `backend/app/tts/persona_speech.py`; S3b: `backend/app/api/{settings,named_personas}.py`, `backend/app/persona/{owner_chat,named_persona}.py`, `backend/app/agent/loop.py`, `backend/app/decision/owner_turn.py` (only the `basic_qa` guard, per the #649 table); checked and not edited: `backend/app/agent/front_responder.py`, `backend/app/api/tasks.py`, `backend/app/config.py` |
| Frontend | S3: `frontend/src/persona/{personaSwitchEvents.ts,PersonaSwitchNotice.tsx,activateNamedPersona.ts,NamedPersonaControls.tsx,PinnedPersonaDock.tsx}`, `frontend/src/api.ts`, `frontend/src/hud/{HudChat,HudOpsRail}.tsx`, `frontend/src/pages/{Chat,Phone}.tsx`, `frontend/src/chat/{ownerChatView.ts,OwnerChatTranscript.tsx}`, `frontend/package.json`; S4/S5: `frontend/src/persona/*`, `frontend/src/presence/{presentationSettings,presenceLifecycle,personaMorphHook}.ts`, `frontend/src/settings/AppearanceSettingsPane.tsx` |
| CI | `.github/workflows/pr-tests.yml` — one add-only step owned by S3 (`npm run test:persona-auto-switch`) |
| Tests | `tests/test_decision_persona_intent.py`, `tests/test_persona_intent_switch_turn.py`, `tests/test_rfc0218_s3b_lock_and_tasks_switch.py`, `frontend/presence-lifecycle.test.mjs`, `frontend/persona-morph-hook.test.mjs`, `frontend/persona-auto-switch.test.mjs` (+ `frontend/persona-auto-switch-test-{loader,stubs}.mjs`) |
| Docs | `docs/rfcs/README.md` |

## Out of scope

WebGL / renderer internals; the morph animation body (Astra); roster changes (no new persona rows); RFC-0069 morph API rewrite; new voice packs; Android companion visuals.

## Notes

- PR #623 (RFC-0210 follow-up) is the regression reference for the Live-UI list.
- RFC-0217 is taken by open PR #627; this RFC takes 0218.
- 2026-10-20 amendment: S3b added from UX's S3 gap report, confirmed by D1; CoS picked option (a), which keeps chat sends on `/api/tasks` and does not move them to the owner-chat stream.
- 2026-10-20 revision (after UX REQUEST CHANGES on 4425603, plus D1 and D2 items): the tasks-path design is kept as is (the `create_task` and `/continue` insertion points, `apply_persona_switch` imported, the payload matching S2, the lock 422). Added `switch_id`, the human titles, the separate auto-switch path with a single morph entry, the session and storage dedupe guards, the failure notice, readable rendering, exact S3 ownership and CI step, the hard 50 ms limit, named test files, and #649 pinned at `b5c3640` with a file-by-file reconciliation.
