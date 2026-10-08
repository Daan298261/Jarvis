# RFC-0203: Fast-path lane consolidation (terminal, progress, routing, verify-skip)

**Status:** accepted  
**Queue item:** (none — consolidation spec; implement waves follow senior `owner_chat` / `loop` reorder)  
**Author:** Jarvis Architect  
**Date:** 2026-10-08

**Aligns with:** [`ANZU_PRODUCT_NORTH_STAR.md`](../../ANZU_PRODUCT_NORTH_STAR.md) — one polished turn, no stubbed dual brains; conversational latency without the owner managing lanes.  
**Reconciles (does not edit):** [0085](0085-universal-task-fastpath.md), [0117](0117-tiny-front-chat-responder.md), [0127](0127-swift-initial-reply-and-progress.md), [0128](0128-progressive-answer-background-verify.md), [0171](0171-system-one-reflex-lane-jev-laya-priority.md), [0167](0167-quality-loop-critic-verifier-and-user-correction-learning.md), [0115](0115-ornith-orchestrator-router-complexity.md).  
**Companion (parallel amendment PR):** social ack held ~1.2 s and spoken only when the worker answer is late; `final_basic` / `ask_clarification` immediate; no double ack; context resize only at turn boundaries. This RFC assumes those UX rules; **call-site reorder in `owner_chat.py` / `loop.py` is owned by the senior 4.7 dev** — consolidation implement waves must not land before that reorder when it changes ack ordering.

**Numbering:** `0200`–`0201` on `development`; open PR #549 claims **0202**; PR #551 is product-only (no RFC). **This RFC is 0203.**

## Problem

Seven RFCs shipped overlapping fast-path behaviour. CoS audit (verified on `development` code, 2026-10-08) found **dual sources of truth** for: (1) when an owner turn is finished, (2) slow-turn progress emission, (3) routing among macro fast path / Reflex / Ornith complexity, and (4) when background verification is skipped. That produces duplicate acks, divergent skip rules, and hard-to-reason precedence — inconsistent with the north star (“tell ANZU what you want”) and with the companion ack-hold contract.

## Decision

**One canonical owner per overlap group.** Others become ordered inputs or are deleted. **No dual sources of truth.** Intended supersession (ledger ticks later): macro execution shortcut rules in 0085 fold into the terminal owner; 0127 slow progress folds into the unified progress loop; 0115/0171 routing calls only through the pipeline; 0128/0167 verify admission is single-gated.

### 1. Terminal turn (who may finish the owner turn)

| | |
| --- | --- |
| **Rule** | Exactly one function decides whether the **front lane alone** completes the turn vs the worker must run. |
| **Current RFCs** | 0085 `admit_fastpath`; 0117 `final_basic` / `ask_clarification`; 0128 publish-then-verify assumes worker answer. |
| **Current code** | `front_responder.terminal_front_completes_turn` (`backend/app/agent/front_responder.py`); early complete in `stream_owner_chat` (`backend/app/persona/owner_chat.py`); `admit_fastpath` + `AgentLoop` `_complete` on hit (`backend/app/agent/task_fastpath.py`, `backend/app/agent/loop.py` ~1289–1348). |
| **Canonical owner** | **`backend/app/agent/turn_outcome.py::resolve_owner_turn_terminal`** (new). Inputs: `route_kind`, `front_action`, `front_text`, `user_prompt`, `path` (`owner_chat` \| `task_loop`). Output: `terminal_complete` \| `require_worker` \| `fail_closed_worker` (empty/unsafe front). |
| **Precedence inside owner** | 1) managed_task → `require_worker`; 2) empty/unsafe front → `fail_closed_worker`; 3) `vault_ask_requires_working_set` → `require_worker`; 4) direct_lookup → never terminal via front text alone; 5) `final_basic` / `ask_clarification` on `direct_reply` + safe text → `terminal_complete`; 6) else `require_worker`. |
| **Fate of others** | `terminal_front_completes_turn` → thin wrapper or inlined into resolver; `admit_fastpath` → **stages-skipped list only** (calls resolver; no independent terminal logic); `owner_chat` / `loop` → call resolver only. |
| **Migration order** | 1) Add resolver + tests mirroring today’s matrix; 2) wire `loop.py` task conversation path; 3) wire `owner_chat.py` after senior reorder; 4) delete duplicate branches. |

### 2. Progress / ack emission (slow-turn loops)

| | |
| --- | --- |
| **Rule** | One slow-progress loop per turn; initial social ack policy comes from companion amendment + `generate_front_reply`, not a second timer. |
| **Current RFCs** | 0117 two-lane ack; 0127 swift ack + 60 s watchdog; 0068 think-aloud. |
| **Current code** | `SlowTurnNudger` 60 s / 45 s repeat (`backend/app/persona/slow_turn_feedback.py`); `run_worker_progress_watchdog` 60 s / 50 s (`backend/app/agent/worker_progress.py`); `emit_worker_progress_update` → `generate_progress_update` (`front_responder.py`); `owner_chat` starts nudger (`owner_chat.py` ~683); `loop.py` starts watchdog (~1430, ~2121). |
| **Canonical owner** | **`backend/app/agent/worker_progress.py::run_owner_slow_progress_loop`** (rename/alias of watchdog + emit path). Parameters: `task_id` or `conversation_id`, `turn_started`, `should_continue`. |
| **Precedence** | Initial visible/audible line: `front_responder.generate_front_reply` (held ack per companion). **Only** `run_owner_slow_progress_loop` may emit further owner-facing slow progress (think-aloud template fallback inside `emit_worker_progress_update`). |
| **Fate of others** | Delete `SlowTurnNudger` / `slow_turn_feedback.py`; remove nudger from `owner_chat`; `loop` and `owner_chat` share the same helper. Ingress “processing” speech (0122) stays a **one-shot** stage event, not a loop. |
| **Migration order** | 1) Unify timers (60 s first, single cooldown constant); 2) switch `owner_chat` to shared loop after reorder; 3) remove `SlowTurnNudger`. **Depends on** senior `owner_chat` ack-hold reorder. |

### 3. Routing (macro lane vs Reflex vs Ornith complexity)

| | |
| --- | --- |
| **Rule** | Ordered pipeline: macro lane first; worker model/tier second; Reflex only refines among eligible options — never overrides macro lane or policy. |
| **Current RFCs** | 0085 `route_request`; 0115 `resolve_router_decision`; 0171 Reflex `decide` / `route_persona_model`. |
| **Current code** | `planning.route_request` (`backend/app/agent/planning.py`); `task_fastpath.resolve_route_kind` (`task_fastpath.py`); `orchestrator_router.resolve_router_decision` + `merge_router_output` (`backend/app/inference/orchestrator_router.py`); `prepare_answer_route` (`backend/app/inference/answer_routing.py`); Reflex `route_persona_model` inside `select_runtime_for_decision` (`answer_routing.py` ~74–117); `ingress_gate` complexity hint (`ingress_gate.py`) — **signal only**. |
| **Canonical owner** | **`backend/app/agent/routing_pipeline.py::resolve_owner_turn_routing`**. Returns `TurnRouting`: `route_kind`, `RouterDecision` (nullable on terminal complete), `fastpath_stages_skipped`, `reflex_trace`. |
| **Precedence** | 1) `resolve_route_kind` / `route_request` (durable `response_route` wins); 2) if `terminal_complete` from §1 → skip `prepare_answer_route`; 3) else `resolve_router_decision` + `prepare_answer_route` side effects on `WorkingState`; 4) Reflex (`decision.surfaces`) only inside profile pick / bounded classes per 0171; 5) `ingress_gate` / Reflex complexity **may raise** `minimum_answer_tier`, never lower hard rules. |
| **Fate of others** | Call sites (`loop.py`, `owner_chat` worker arm) call **only** `resolve_owner_turn_routing`; `admit_fastpath` demoted to helper reading `TurnRouting`; direct `prepare_answer_route` from overlap workers forbidden without pipeline. |
| **Migration order** | 1) Extract pipeline with tests; 2) `loop` conversation + managed entry; 3) `owner_chat` worker path post-reorder; 4) collapse duplicate `route_request` calls in verify path to cached `route_kind`. |

### 4. Verify-skip (background verification / critic admission)

| | |
| --- | --- |
| **Rule** | One admission function for RFC-0128 background verify; terminal front and direct routes are skip **reasons**, not parallel gates. |
| **Current RFCs** | 0128 progressive verify; 0167 risk/task policy; 0085 skip on direct routes. |
| **Current code** | `decide_verification_admission` (`backend/app/agent/background_verify.py`); `schedule_background_verification` (same); `should_skip_background_verify` (`task_fastpath.py`); `loop.py` ~1704 uses `should_skip_*` then schedule; `owner_chat.py` ~793–808 skips via `terminal_front_completes_turn` then schedules with fresh `route_request`. |
| **Canonical owner** | **`backend/app/agent/background_verify.py::decide_verification_admission`** (unchanged name). `schedule_background_verification` must always consult it. |
| **Precedence** | Skip reasons (first match): `disabled` → `terminal_front` → `direct_route` (0085 kinds) → `greeting` / `too_short` → else 0167 admit rules. |
| **Fate of others** | **Delete** `should_skip_background_verify`; `loop` passes `route_kind` + `front_terminal` flag into admission; `owner_chat` stops pre-skipping — pass `front_action` into admission. Fastpath `stages_skipped` lists `background_verify` when admission would skip. |
| **Migration order** | 1) Extend admission with `terminal_front` reason; 2) remove `should_skip_background_verify` + fix call sites; 3) align tests in `test_rfc0128_*` and 0167 fixtures. |

## Acceptance criteria

**Specs (this PR)**

- [x] RFC-0203 merged with four canonical owners and migration order documented.
- [x] `docs/rfcs/README.md` index line + next-free bump.

**Implement (follow-on waves — unchecked)**

- [ ] `resolve_owner_turn_terminal` is the only terminal-turn decision; pytest proves `owner_chat` and `loop` paths match for the same fixtures.
- [ ] `run_owner_slow_progress_loop` is the only slow progress loop; no `SlowTurnNudger` remains; no double ack with companion hold policy.
- [ ] `resolve_owner_turn_routing` is the only routing entry from `loop` / `owner_chat` worker arms; one macro + one tier decision per turn in traces.
- [ ] `decide_verification_admission` is the only verify-skip gate; `should_skip_background_verify` removed; schedule path always uses admission.
- [ ] No regressions on 0085 hard bypass, 0117 front actions, 0127/0128 contracts, 0115 tier floors, 0171 fail-closed Reflex timeout.
- [ ] `python3 -m pytest` passes.
- [ ] `npm --prefix frontend run build` passes if any portal touch (expected none).

## Likely files

| Area | Paths |
| --- | --- |
| New | `backend/app/agent/turn_outcome.py`, `backend/app/agent/routing_pipeline.py` |
| Backend | `backend/app/agent/front_responder.py`, `task_fastpath.py`, `loop.py`, `worker_progress.py`, `background_verify.py`, `backend/app/inference/answer_routing.py`, `orchestrator_router.py`, `backend/app/persona/owner_chat.py` |
| Remove | `backend/app/persona/slow_turn_feedback.py` (after migration) |
| Tests | `tests/test_rfc0203_fastpath_consolidation.py`, extend `test_rfc0085_*`, `test_rfc0127_*`, `test_rfc0128_*` |

## Out of scope

- Editing RFC files 0117, 0127, 0131 (parallel amendment PR).
- Astra / persona / WebGL / presence / morph / voice UI surfaces.
- `JARVIS_MASTER_PLAN.md` ledger ticks (Architect after implement).
- Replacing managed-task in-loop critic / `verify_code` (0167 long-running path).
- New model providers or Reflex provider additions beyond wiring through the pipeline.

## Notes

- **PR implement model:** `composer-2.5` (fast=off). CoS: undraft+squash consolidation PRs; land implement waves **after** senior-dev `owner_chat` / `loop` reorder for ack-hold.
- **Intended supersession (ledger later):** 0085 terminal rules → 0203 §1; 0127 watchdog duplication → 0203 §2; ad-hoc triple routing → 0203 §3; `should_skip_background_verify` → 0203 §4.
- Desktop live-model / TTS soak remains sign-off on owner paths; cloud ships unit tests only.
