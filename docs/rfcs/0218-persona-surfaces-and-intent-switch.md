# RFC-0218: Persona UI surfaces A/B/C + intent-driven auto persona switch

**Status:** accepted  
**Queue item:** (none in this PR — Architect may add a master-plan line after land; do not edit `JARVIS_MASTER_PLAN.md` here)  
**Author:** Jarvis Architect  
**Date:** 2026-10-14

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

Ship **one RFC with five implement slices**, each a single CoS-assignable ticket with one named model (**fast off**).

### North-star justification

- **§3:** "> **ANZU should have presence.**" / "Morphing should feel organic. Status changes should be understandable." — the switch is a visible, spoken state change through one stage; the morph is a named seam (S5).
- **§4:** "ANZU should acknowledge simple requests almost immediately… continue heavier work without creating the impression that the entire system has frozen." and "The voice should belong to the selected ANZU personality and visual presence." — switch line is spoken in the **new** persona's voice, fire-and-forget, work starts the same turn.
- **§5:** "Specialists can be manually selected where desirable, but ANZU should normally determine when specialist capability is useful…" — auto-switch (S1/S2), manual pin keeps working and wins.
- **§6:** "deterministic rule → tiny/reflex decision system → normal code/tool execution → normal model → specialist/expert reasoning only when required" — intent is a reflex decision class answered inside `decide_owner_turn`, rules first, Laya/Jev next, deadline fallback = stay.
- **§19:** "Do not create several interfaces where one adaptive interface can work." — **A/B/C are owner-selectable layouts of ONE adaptive persona surface**, sharing one persona state, one activation path (`activateNamedPersona`), one stage, one voice binding. They are not separate apps or forks. "Do not remove useful capability merely to simplify the codebase." — live UI is additive (below). "Do not mark something finished merely because its backend exists." — S2 is not done without S3 consuming its event.

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

Assign order: **S1 ∥ S5 → S2 → S3 → S4.**

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

### S3 — Frontend auto-switch wiring

**Model:** Composer 2.5 (fast off) · **Depends:** S2, S5

| Path | Why |
| --- | --- |
| Owner-chat stream consumer | Handle `persona_switched` → `activateNamedPersona(to)` (shared manual/auto path; backend already active, so no duplicate PUT side-effects beyond idempotent state sync). |
| `frontend/src/persona/activateNamedPersona.ts` | Accept `reason: "manual" \| "intent"`; keep selected A–E variant (`mythicAvatarForSelection`); invoke `onCloudToPersonaMorph` (S5) on every switch. |
| `NamedPersonaControls.tsx`, `PinnedPersonaDock.tsx` | Highlight updates to new persona; lock toggle surfaced (writes the setting S1 reads). Additive only. |
| Tests | Below. |

- [ ] `frontend/presence-lifecycle.test.mjs` and all #623 tests pass unchanged.
- [ ] Preservation snapshot: every item in the Live-UI list is present before and after an auto switch.
- [ ] Selected A–E variant persists across auto and manual switch.
- [ ] Dock + controls highlight the new persona.
- [ ] Morph hook called once per switch with correct ids and `reason`.
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

## Acceptance criteria (RFC-level)

- [ ] All slice checkboxes above.
- [ ] Every implement PR has the reviewer reasoning pass for the Live-UI list.
- [ ] Unit tests pass (`python3 -m pytest`); `npm --prefix frontend run build`.

## Likely files

| Area | Paths |
| --- | --- |
| Backend | `backend/app/decision/{types,surfaces,owner_turn,__init__}.py`, `backend/app/decision/adapters/rules.py`, `backend/app/persona/{owner_chat,named_persona}.py`, `backend/app/tts/persona_speech.py` |
| Frontend | `frontend/src/persona/*`, `frontend/src/presence/{presentationSettings,presenceLifecycle,personaMorphHook}.ts`, `frontend/src/settings/AppearanceSettingsPane.tsx` |
| Tests | `tests/test_decision_persona_intent.py`, `tests/test_persona_intent_switch_turn.py`, `frontend/presence-lifecycle.test.mjs` + new frontend tests |
| Docs | `docs/rfcs/README.md` |

## Out of scope

WebGL / renderer internals; the morph animation body (Astra); roster changes (no new persona rows); RFC-0069 morph API rewrite; new voice packs; Android companion visuals.

## Notes

- PR #623 (RFC-0210 follow-up) is the regression reference for the Live-UI list.
- RFC-0217 is taken by open PR #627; this RFC takes 0218.
