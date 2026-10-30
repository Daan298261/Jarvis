# RFC-0245: Large-prompt pipeline (reflex detect, gated large-model preload, spoken ack, split, completeness, durable sequential prompts)

**Status:** accepted
**Priority:** P1 (Taco ask B, relayed by Chief of Staff 2026-10-20)
**Author:** Jarvis Architect
**Date:** 2026-10-20
**Traced on:** `development` @ `ce78fe7d` (every cited symbol re-resolved there; previously traced on `e56740c`, where no cited file differed from `d85c9d4`; #660 and #661 landed as `90a0010` and `bd2558bd`; #669 changed only `mcp/package.json`, `mcp/package-lock.json` and `frontend/package-lock.json`). Open batch PRs cited: #652 (RFC-0225; final head in this PR's body), #655 (RFC-0228; final head in this PR's body), #664 (RFC-0232; final head in this PR's body), #666 (RFC-0230, landed as `94a62fa0`; `docs/rfcs/0230-pc-first-response-latency.md` on `development`), #668 (RFC-0233; final head in this PR's body), #670 (RFC-0211, supersedes #585; final head in this PR's body). Originally traced on `11b264a7` with #649 @ `edb4685` (identical to `b5c3640` for every file cited here), #652 (RFC-0225; final head in this PR's body), #655 (RFC-0228; final head in this PR's body), #585 (RFC-0211; final head in this PR's body), #663 (RFC-0218 delivery fix; since landed as `781004c`).
**Amended 2026-10-20 (#649 landed):** #649 merged into `development` as `ee786dc`, so S2 no longer ports it. S2 now cites the landed engine and adds only what #649 lacks: `seed_workflow`, the two pipeline tables, and `LargePromptSettings`. Every #649 reference in §4-§6 and S1-S6 is re-traced on `development` @ `d85c9d4`, and so is every `loop.py`, `owner_turn.py`, `api/tasks.py` and `App.tsx` line number (#648 and #649 shifted them).
**Amended 2026-10-20 (UX round 3, N1-N9; CoS):** sync `AGENT.cancel` hands `on_parent_cancel` to the main loop thread-safely (`request_parent_cancel`, `cancelling` flag) so voice stop, media, self-dev and the live agent suite reach a running pipeline, one test per caller; `started` re-taken after the precheck, which has its own bound `LARGE_PRECHECK_BOUND_MS = 30`; D2's two explicit-wording negatives tested; keep-alive refreshed every `idle_unload_seconds / 2` while leased (ANZU-loaded only), with no-churn tests; the refuse test and the live audit follow the VRAM-aware rule; `/continue` sets `waiting → running` and recovery re-runs `preparing`; the preload names `anzu-coder-27b`, resolves `profile_name` without the private helper and defines that no owner rebind runs; no reference to the saving hotswap entry point remains; `last_free_vram` added to #652's second-owner row; `loop.py` and `main.py` chains end with 0233; re-pinned (header). **Then (CoS, pin removal):** open batch PRs are cited by number and RFC only (final heads in the PR body); the `main.py` chain ends at #670 (RFC-0211), which supersedes #585; #670 doesn't edit `loop.py`. **Then (UX round 4, CoS):** cross-PR refs cited by section or function name, never by line (#670 by function, #655 §"Out of scope", #652/#655/#666 by section); RFC-0230 cited as landed (`94a62fa0`); the S5 table carries `bind_loop` (in `main.py`, before `recover_on_startup`), the `request_parent_cancel` call in `AGENT.cancel` and the queue functions, with cancel-before-`bind_loop` defined and two tests; `started` is re-taken after the last owner-turn precheck (#668's `gap_precheck` goes before the re-take). The `rules.py`, `db/models.py`, `api/settings.py`, `api/tasks.py` and `api.ts` chains now include RFC-0233's slices (S1, S3, S1, S3 → S4 and S6).
**Amended 2026-10-20 (UX re-peer, 9 items; D2 + CoS):** cancel endpoint awaits `on_parent_cancel` then calls the sync `AGENT.cancel` (`api/tasks.py::cancel_task`); total `large_precheck` inside the `try` at `owner_turn.py::decide_owner_turn` and passed to `_apply_floors` at all three call sites (no deadline helper); 0245 adds no RE detection and relies on #664's admit-first probe, settings allow-list and explicit-wording rule; 0230-S3's prewarm skips while a 27B lease is held; in `waiting` the 27B is released after `idle_unload_seconds` (only if ANZU loaded it; reload on `/continue`) and is never pinned; **0245 edits neither `hotswap.py` (0225-S3 only) nor `rewarm.py` (0228-S2 only)**; lease tracked in `large_prompt._leases` keyed by task id (load via the existing `apply_runtime_profile_to_settings(persist=False)` + `MANAGER.load(task_id=)`); `refuse` outlook only on a fresh free-VRAM reading below requirement + 1 GB; a *Statuses* table with one setter and reader per value. Re-traced on `development` @ `e56740c` (`bd2558bd` with #661 landed, plus #669's `mcp/` lockfile only). Cross-checked with #652 (RFC-0225; final head in this PR's body), #655 (RFC-0228; final head in this PR's body), #664, #666 and #668 at the heads of this joint push (PR body).
**Amended 2026-10-20 (cross-citation pass):** #664 (RFC-0232; final head in this PR's body) re-cited with its final helper `planning.re_intent_match(prompt, *, allowed=None) -> ReIntent | None` (cached per turn) and probe `planning.probe_dump_target`; 0218-S3b (not landed) added to the `owner_turn.py` chain.
**Amended 2026-10-20 (UX peer, 17 blockers; CoS rulings 1-6; D2 + CoS floor change):** RFC-0232 precedence (verbatim CoS text, §1) with 0232's RE helper consumed in the precheck and its RE floor in `_apply_floors`, one `decide()` per turn; size rules on the full prompt, outside the 50 ms window, also on deadline/exception fallbacks; candidate from the baseline route plus the final gate after floors; #649's planner skipped for a marked parent; one spoken ack on the parent's front lane, worded from the RFC-0225 gate outlook and never claiming a load; Taco's default (LM Studio 9B owner-loaded, managed off, 16 GB) runs the parts on the 9B; request lease holds the target for the whole parent, and the large-task load is never persisted, with the owner's selection restored; breaker bind, cancel races, idempotent vault, L4 length floor, S0 outlook/lease/late-reconcile; S6 extends the live "Saved plan" rows; complete ownership chains with lanes. Re-traced on `development` @ `3007696` (`d85c9d4` plus #660, #667 and #662; only `pr-tests.yml` lines moved: "Build frontend", "Persona morph hook tests" `step "Persona morph hook tests (RFC-0218 S5)"`). Cross-checked with #666 (RFC-0230, landed as `94a62fa0`; `docs/rfcs/0230-pc-first-response-latency.md` on `development`), #664 (RFC-0232; final head in this PR's body), #652 (RFC-0225; final head in this PR's body).
**Amended 2026-10-20 (CoS, #665 peer):** the large target `anzu-coder-27b` was assumed to exist as a runtime profile. It does not (see *Target profile: `anzu-coder-27b`*), so new slice **0245-S0** adds it and 0245-S4 hard-depends on it. Re-traced for S0 and for the `hotswap.py`, `config.py` and `main.py` citations on `development` @ `d214b6d` (#648 landed; #663 landed at `781004c`), #652 (RFC-0225; final head in this PR's body), #655 (RFC-0228; final head in this PR's body), #649 @ `edb4685`.
**Amended 2026-10-30 (CoS, line-number removal; `development` @ `ce78fe7d`):** every code citation is by file and symbol (function, class or constant name); no line numbers remain anywhere in this spec. Symbols were re-resolved on `development` @ `ce78fe7d`, and a cited symbol that is missing there is drift to fix, not a stale line. **Renumbered 0231 → 0245:** #674 landed a different RFC-0231 (Android voice and desktop projects), so this spec is RFC-0245 and every former `0231-Sn` / `RFC-0231` reference that meant it is now `0245-Sn` / `RFC-0245`. **Engine modes (RFC-0244) added** to §1, S4 and S5.

**Owner ask (Taco, ask B, intent as relayed):** when Taco speaks or types a large or complex task, Jev/Laya decide that it is complex. Then:
1. ANZU immediately loads the large model (anzu-coder-27b or whichever large model applies). `anzu-coder-27b` is the 0245-S0 runtime profile.
2. In parallel, the small front model says something short, such as "This is a large task, I'm loading the larger model." (as relayed; per CoS ruling 4 the shipped ack is worded from the RFC-0225 gate and never claims a load, §2)
3. The prompt is split into sections, or into single questions if it asks several.
4. Each section is checked for completeness, with iteration.
5. Each section becomes one detailed prompt.
6. The prompts are saved in the DB or Obsidian.
7. The prompts are queued one after another through the scheduled-task system.
8. Every prompt always includes deeper sub-tasks and quantitative sub-tasks.

**Aligns with:** [`ANZU_PRODUCT_NORTH_STAR.md`](../../ANZU_PRODUCT_NORTH_STAR.md):
- §4: "ANZU should acknowledge simple requests almost immediately … and continue heavier work without creating the impression that the entire system has frozen."
- §6: "**deterministic rule → tiny/reflex decision system → normal code/tool execution → normal model → specialist/expert reasoning only when required**"
- §7: "Important decisions should be surfaced clearly."
- §8: "Every major autonomous workflow should have a concept of acceptance criteria." and "Confidence should come from evidence rather than cheerful completion messages."
- §9: "ANZU chooses infrastructure."

**Extends (do not rewrite):**
- [RFC-0171](0171-system-one-reflex-lane-jev-laya-priority.md) / [RFC-0206](0206-jev-laya-every-turn-arbitration.md): the reflex lane, one decide per turn, arbitration.
- [RFC-0026](0026-execution-phase-and-verifier-observability.md) / [RFC-0029](0029-transactional-durable-execution.md): the durable task API, `AgentRuntime.create_task` and `/continue`.
- [RFC-0224](0224-responsive-conversation-and-durable-task-prompts.md) (#649, landed `ee786dc`): persisted prompt stages. Its landed engine is reused as-is.
- [RFC-0225](0225-local-engine-coexistence-and-resilient-api.md) (#652): `prepare_engine_for` and the VRAM gate.
- [RFC-0228](0228-installer-update-default-9b-idle-unload.md) (#655): the `NINE_B_REWARM` coordinator.
- [RFC-0218](0218-persona-surfaces-and-intent-switch.md) S3b, as amended by #663: tasks-path persona switch, `switch_id`, switch line delivered as `chat_tts`.
- [RFC-0211](0211-ollama-self-development-scheduler.md) (#670 draft, which supersedes #585): the scheduler.
- [RFC-0071](0071-automation-failure-circuit-breaker.md): breaker admission.

Some of these links point at RFC files that live only on their open PRs. They resolve once those PRs land.

**#649 and #670 (RFC-0211; supersedes #585, which it ports onto `development`; cited by section and function name only, since it is a draft and will move):** #649 has landed and S2 builds on it (see *Relationship to #649 and #670*). #670 is still a draft and does not gate this RFC.

**Astra boundary:** persona, WebGL, presence, morph and appearance are out of scope (Astra). This RFC emits no persona events and edits no persona or presence component.

This PR is **specs-only**. It contains no application code.

---

## Problem

Verified on `development` @ `e56740c` (originally `11b264a7`; the cited lines are unchanged).

1. **"Large" is not a decision.** The single owner-turn decide (`decision/owner_turn.py::decide_owner_turn` on `development` @ `d85c9d4`, via `agent/request_routing.py::evaluate_request_route`) yields route, tier and `persona_intent` (`OwnerTurnDecision`). Nothing decides "this prompt is a multi-part large task". The only related signals are:
   - `policy.local_complexity_tier` (`decision/policy.py`): tier 4 for expert hints or more than 4000 chars, tier 3 for complex hints or more than 1200 chars.
   - The separate `complexity_escalation` surface (`decision/surfaces.py::complexity_and_escalate`).
   - #649's regex `is_large_request` (`agent/task_workflow.py`, landed), which is not a reflex decision. It only triggers #649's model planner inside `_run` (`loop.py`).
2. **No immediate load of the large model.** `prepare_answer_route` only runs when the loaded model is an orchestrator, or tier ≤ 1 (`agent/loop.py`), and it runs inside `_run`, after the front lane. A large prompt starts on whatever model is loaded. The swap to the large model happens later, if it happens at all, through `execute_visible_model_switch` (`inference/model_escalation.py`).
3. **No large-task ack.** `create_task` publishes the generic `task_acknowledgement(prompt)` as an `acknowledgement` event (`loop.py`), and it is not spoken. As #663 found, `publish_owner_text` goes to `OWNER_CHAT_CHANNEL` (`persona/chat_delivery.py`), and no client reads that channel. The only path the live UI speaks is a `chat_tts` event on the task stream: `useTaskSpeech.ts::useTaskSpeech` → `queueChatSpeech`, mounted in HUD chat and Chat.
4. **The prompt is split only for a dead endpoint.** `agent/intake.py` has a sequential chain:
   - `MAX_SEQUENTIAL_PARTS = 8`, `part_prompt`, `advance_chain`.
   - Chains are stored as JSON files under `data/intake_chains`.
   - Its only caller is `persona/owner_chat.py`, the `stream_owner_chat` endpoint, which has no client.
   - Chat sends go to `/api/tasks`. Since #649, `_run` asks the loaded model for a 1-8 step plan when `is_large_request` fires (`loop.py`, `task_workflow.py::prepare_workflow`). That plan is model-generated, so it isn't a split of the owner's text. It runs on whatever model is loaded, with no completeness check, and a planner failure fails the task (`task_workflow.py::prepare_workflow`).
5. **No completeness check.** No section-level check or bounded iteration exists anywhere.
6. **Durable prompt stages exist (landed #649), but only one task at a time.** `TaskPromptPlan` / `TaskPromptStep` (`db/models.py`) are executed one stored prompt at a time inside one task (`loop.py::AgentRuntime._run`, completion guard `AgentRuntime._update`). Its planner asks the model for the plan (`PLAN_SYSTEM`, `task_workflow.py`), which needs a capable model already loaded. It has no notion of a parent with one child task per section, no section completeness, and no mandatory deeper/quantitative steps.
7. **No queue that runs owner prompts one after another.**
   - `mobile/scheduler.py::tick` runs periodic automations. It skips while the previous run is non-terminal and is admitted by `automation/breaker.admit_automatic_trigger`.
   - `agent/queue_watcher.py` is a file drop queue.
   - #670's `DevelopmentScheduler` (`agent/development_scheduler.py`, `class DevelopmentScheduler` and its `tick()`, whose `resource_hold` dispatch gate is in `tick()`) is a draft and reserves Ollama for Grokbot work.
   - None of them takes N owner sub-prompts and runs them in order.
8. **No guaranteed deeper or quantitative work.** #649's steps are `work` plus `REVIEW_STEPS` (bugfix, fact_check, quality_control; #649 `task_workflow.py`). Nothing requires a deeper-analysis or quantitative sub-task, and nothing validates one.

## Decision

Ship **one RFC with seven implement slices (S0-S6)**, one named model per slice and fast mode off. Nothing waits for #670. #649 has landed and is reused.

**Pipeline at a glance.** A large owner turn becomes one **parent task** (the one the HUD is already following) and N **child tasks**, one per section, run strictly one after another.

```
owner turn ─► decide_owner_turn: large-prompt precheck on the FULL raw prompt (outside the 50 ms window)
   │           ─► _decide_sync: one decide (riders large_prompt / large_prompt_split only when 0232's RE helper did not match)
   │           ─► _apply_floors: 0232 RE floor, then 0245 large floor
   │ large (and not RE)
   ├─► create_task: 0230 prewarm_worker + route decision ─► 0232 RE dispatch (not taken) ─► Task row ─► 0218 S3b persona block
   ├─► 0245 large branch: cancel 0230's pending 9B prewarm; read the RFC-0225 gate outlook (in memory, no probe)
   ├─► ONE spoken ack: the parent's front-lane line (fixed text, chat_tts, 0230-S0 mark lane "front"), worded from the gate outlook
   ├─► preload task started (not awaited), only when the outlook allows: request lease → apply_runtime_profile_to_settings(persist=False) + MANAGER.load(task_id=parent) → warm
   └─► parent runner (after the ack): split → completeness rounds (≤ 3) → compile → persist → await preload (≤ 180 s, defined fallback)
          → dispatch part 1 as a child task (breaker admit + bind)
child terminal hook ─► completed: dispatch next │ failed: stop, parent fails visibly │ needs_owner: parent waits (27B released after idle_unload_seconds)
last part done ─► parent completes with the combined result ─► release lease ─► restore the owner's saved selection ─► schedule_orchestrator_restore (NINE_B_REWARM, public API)
```

Between the ack and the parent's terminal outcome the parent speaks nothing (CoS ruling 5): progress, gate and needs_owner lines are visible events only.

### Terms

| Term | Meaning |
| --- | --- |
| **Large turn** | An owner turn whose decision has `large_prompt == "large"`. |
| **Pipeline** | One `large_prompt_pipelines` row, keyed by the parent task id. |
| **Section / part** | One `large_prompt_sections` row. Its child task runs one detailed prompt. |
| **Target** | The large runtime profile that is preloaded and used by every child. |
| **Mode** | `sections` or `questions`, chosen by the `large_prompt_split` rider. |

### 1. Detection: one decide, two riders (S1)

Detection follows the RFC-0218 pattern: rider questions on the existing decide, no second decide.

**Precedence (CoS ruling, normative, verbatim):** A turn whose prompt contains an absolute filesystem path together with RE intent (RFC-0232's narrowed dump/extraction detection) routes to reverse engineering and is never split by RFC-0245; a path with a plain or coding question routes normally.

Mechanically (D2 + CoS ruling 2026-10-20): RFC-0232 S2's precedence is a **floor in `_apply_floors`** (`owner_turn.py`), not an early return. Every turn keeps the persona precheck (`_decide_sync`) and **exactly one `decide()`**. **0245 adds no RE detection of its own.** RE intent is decided only by RFC-0232 S2's helper `planning.re_intent_match(prompt, *, allowed=None) -> ReIntent | None` (memoised per turn) and its on-disk probe `planning.probe_dump_target`, specified in #664 and not restated here. What 0245 relies on, as #664 guarantees it:
- the probe is admit-first through `store.admit_allowed_target` (#661, landed `bd2558bd`, `reverse_engineering/store.py`), which runs before any stat of the target or a marker, so an outside path makes zero filesystem calls;
- the helper and the probe always read the owner's allow-list from settings (`load_settings().allowed_directories`) and never pass `None` to the gate (`admit_allowed_target(target, None)` is the deliberate trusted-in-process bypass, `store.py`, and is not changed); an empty list admits nothing;
- explicit owner wording skips **only** the dump-marker requirement, never the allow-list check or the source-tree veto.

0245 consumes the result in exactly one place, the precheck, and the floor order:
- **Precheck (one place only):** `large_prompt.precheck(text, settings)` runs in `decide_owner_turn`, **inside** the `try` at `owner_turn.py` and before the worker is submitted, i.e. outside the 50 ms `wait_for`. It calls `planning.re_intent_match(text)` once (the per-turn memo means 0232's own floor reuses the same result) and stores `re_match`. When it matches there is **no candidate**: no rider is appended to the one `decide()`, and `large_prompt_floor` is not set. The local is named **`large_precheck`** so it never collides with the persona `precheck` inside `_decide_sync`. #664 states the same placement. **Timing (N2):** `started = now()` (today `owner_turn.py::decide_owner_turn`) is re-taken **after the last owner-turn precheck**, so no precheck counts against the 50 ms decide budget on the real or the injected clock. Today, with 0245-S1 alone, that is `large_precheck`. RFC-0233-S1 (#668, §1 "Detection", its precheck paragraph) inserts `gap_precheck` after `large_precheck` and **before** the re-take, so the re-take stays the last statement before the decide worker is submitted. 0245-S1 writes it with that comment (`# re-taken after the last owner-turn precheck`). The large precheck has its own bound, **`LARGE_PRECHECK_BOUND_MS = 30`** (`decision/large_prompt.py`): ≤ 20 ms for the rules on a 100 KB paste plus #664's ≤ 10 ms probe wait. It bounds `large_precheck` only; #668's `gap_precheck` keeps its own < 1 ms bound, and neither is charged to the decide budget. It is synchronous and cannot be interrupted; an overrun is logged once with the measured ms and the result is still used (`test_precheck_within_own_bound`).
- **Total:** the precheck never raises. Any exception (its own or the probe's) yields `LargePromptPrecheck(floor="standard", re_match=None, rules_fired=(), mode="sections", error=repr(exc))` and one log line, so `decide_owner_turn` never falls through to `request_routing.py::evaluate_request_route`'s bare decision and today's route plus 0232's floor still apply.
- **Floors:** `_apply_floors(user_message, baseline, literal, result, *, large_precheck=None)` gains one keyword, passed at all three call sites (normal, timeout and exception tails). 0232's RE floor runs first and 0245's large-prompt floor after it; when the RE floor applied, `large_prompt` stays `None`. The verdict is set in `_apply_floors` only; there is no separate deadline helper.

RFC-0232 S2 owns the RE-side test `test_path_plus_re_intent_routes_to_re_before_large_prompt_split` (`tests/test_rfc0232_intent_and_alias.py`). 0245-S1 adds its side of the contract (S1 tests), and `test_one_decide_per_turn` (S1) asserts exactly one `decide()` for a large turn and for a path-plus-RE turn.

- **Precheck on the full prompt (rules, sync).** Reflex runs the rules adapter on `compact_state(raw_state)` (`reflex.py::decide`), which cuts every string over 800 chars to 800 (`decision/types.py`). So size rules are **never** evaluated inside `decide()`. `large_precheck` is computed on the raw `user_message` (placement above) and carries L1-L5, the split mode, `rules_fired`, `floor` (`large` | `standard`), `mode` and `re_match`. It is passed as the keyword `large_precheck` to `_decide_sync`, `_deadline_rules_result` and `_apply_floors`. Cost is linear in the prompt with one regex pass per rule: `test_precheck_bounded_on_100kb_prompt` bounds it.
- **Candidate (inside `_decide_sync`, before the one `decide()`).** A candidate exists only when **all** of these hold:
  - `large_precheck.re_match` is not set (RFC-0232 S2's helper did not match);
  - the baseline route is managed (`baseline.kind == MANAGED_TASK`), and `infer_rules_reply_shape(text)` is none of literal, clarify, self_status, basic_qa or social (all in `REPLY_SHAPES`, `owner_turn.py`);
  - `security_role == ""`;
  - `settings.large_prompts.enabled` is true;
  - `large_precheck.floor == "large"` (at least one rule below fires).

  Without a candidate, no rider is appended and the decision is unchanged byte for byte.
- **Riders (appended to `OWNER_TURN_QUESTIONS` for that call only):**
  - `large_prompt`: choice `standard` | `large`, `decision_class="complexity_escalation"`.
  - `large_prompt_split`: choice `sections` | `questions`, `decision_class="workflow_branch"`.

  Both classes are already in `REFLEX_DECISION_CLASSES` (`decision/types.py`), so the unlisted-class check at `reflex.py::decide` passes. The rules adapter's rider branches (`decision/adapters/rules.py`, next) read only the scalar state keys `large_prompt_floor` and `large_prompt_rules` that `_decide_sync` sets from `large_precheck`; they never measure text.
- **Rules (computed by the precheck on the raw text).** `large` fires if any of these holds:
  - **L1:** `len(prompt) ≥ 4000`.
  - **L2:** at least 3 list items (`^\s*(\d+[.)]|[-*•])\s+`) and `len ≥ 600`.
  - **L3:** at least 3 question sentences (ending in `?`, or starting with an interrogative word in en/nl) and `len ≥ 200`. This also sets split `questions`.
  - **L4:** `task_workflow.is_large_request(prompt)` (landed #649, `agent/task_workflow.py`), imported and called as is, **counted only when `len ≥ 600` or another rule also fires**. "Make a quick snake game" is therefore not large.
  - **L5:** `local_complexity_tier(prompt) == 4`.

  Split mode: `questions` when L3 fired and fewer than 3 list items exist, otherwise `sections`.
- **Floor semantics** (the rule at `reflex.py::decide`: providers may raise a tier but never lower it):
  - `_apply_floors` (`decide`) applies `large_precheck.floor`. A typed provider may raise `standard → large` only at confidence ≥ 0.75, and may never lower `large → standard`.
  - **Deadline and exception fallbacks keep the verdict and the full question.** `_deadline_rules_result(..., large_precheck=...)` asks `OWNER_TURN_QUESTIONS` plus the riders when a candidate exists, and the `TimeoutError` / `Exception` tails reach the verdict through `_apply_floors(..., large_precheck=large_precheck)`. The owner's full text reaches `create_task` unchanged (it is the `prompt` argument, never rebuilt from the projection), so `Task.prompt` holds the whole question.
  - A provider's split answer wins only when L3 did not fire.
- **Final gate after the floors.** The verdict is nulled when 0232's RE floor applied, and unless the final route is `managed_task` and the final reply shape is not in {literal, clarify, self_status, basic_qa, social}. A provider that answers `direct_reply` at ≥ 0.75 on a 4500-char prompt therefore leaves `large_prompt is None`, as today.
- **Engine modes (RFC-0244 "Decision"; landed `engine_mode.py`).** The mode is read from the same settings snapshot the decide uses and applies at request entry; 0245 never forces a resident model out. `reflex_only` (`not model_enabled(settings)`): **no large-prompt pipeline of any kind.** `precheck` returns before any rule or probe call, so `large_prompt is None` with no rider and no candidate; the `create_task` large branch is not taken (no pipeline row, no `gate_outlook`, no preload, no lease, no ack, no vault note, no split); the turn then follows RFC-0244's own path, `_run`'s early return for a disabled model (`reflex_only_reply`), which 0245 leaves unchanged. 0232's RE floor and every other floor behave as RFC-0244 and 0232 define. `model_only` (`not decision_engines_enabled(settings)`): the pipeline runs normally **without the reflex lane**. The precheck uses only the deterministic rules L1-L5 and 0232's RE helper (no typed-provider rider, no JEV or Laya call, so a prompt only a provider would have raised to `large` stays `None`); the split mode is `sections` unless L3 fired; the ack, preload, split, completeness and queue are unchanged, because they are front and large-model work, not reflex decisions. The mode is re-read at every child dispatch and at `/continue` and recovery (§5): under `reflex_only` those steps dispatch nothing and preload nothing, and the parent shows one non-spoken event until the mode allows models again. Tests: `test_engine_mode_reflex_only_runs_no_pipeline_no_preload_no_ack` and `test_engine_mode_model_only_runs_pipeline_without_jev_laya` (S4), `test_engine_mode_reflex_only_parks_recovered_pipeline` (S5).
- **Output.** New field `OwnerTurnDecision.large_prompt: LargePromptIntent | None` (`OwnerTurnDecision`; `_apply_policy_guard` carries it through), with fields `verdict`, `mode`, `rules_fired: tuple[str, ...]`, `decision_source`, `confidence`. `request_routing` passes the field through unchanged.
- **#649's planner is not a second decision.** The landed auto-planner (`loop.py::AgentRuntime._run` `needs_workflow` `prepare_workflow(..., planner=MANAGER.chat)`) never runs for a pipeline parent or child (S4/S5 mark and skip, §2). When `large_prompts.enabled` is false or the verdict is `None`, #649 behaves exactly as landed.
- **Arbitration class.** The large ack is a front notice, not an answer. The parent's final result is the combined child outcome, which matches `keep_worker` semantics (`surfaces.py`). `arbitrate_front_and_worker` is not called for the ack.

### 2. Ack and preload (S4)

**Order inside `AgentRuntime.create_task`** (`loop.py`), matching #666 and #664:
1. RFC-0230 S3's `prewarm_worker("turn")` and the route decision (RFC-0230 owns that position);
2. RFC-0232's RE dispatch (an RE turn never reaches step 4, and its decision has `large_prompt=None`, §1);
3. the `Task` commit and RFC-0218 S3b's persona block (unchanged, including `publish_persona_switch_line` per #663);
4. **this RFC's large branch**, which replaces only the generic ack at `AgentRuntime.create_task` for a large turn.

**Marking the parent.** The large branch inserts the `large_prompt_pipelines` row (§4) in the same session as the `Task` commit, before `_start_runner`. That row is the mark: `large_prompt_queue.is_pipeline_parent(task_id)` reads it, and `_run` returns into the parent runner **before** `loop.py` (#649's `needs_workflow`), so #649's planner never plans a 0245 parent (CoS ruling 2). Children are seeded (§4), so `load_workflow` finds a stored plan and #649 never auto-plans them either.

**The large branch, step by step** (all in-memory, no I/O probe, so the ack stays inside its budget):
1. **Cancel 0230's 9B prewarm** when a target resolves and the gate outlook is not `refuse`: `turn_prewarm.cancel_prewarm(turn_id)` (RFC-0230 S3 exposes it; #666 S3). A prewarm that has not yet called `prepare_engine_for` is cancelled. One already inside `prepare_engine_for` finishes under its single-flight, and the preload's own gate call queues behind it. With the outlook `refuse`, the prewarm is left alone (the parts will run on the 9B).
2. **Resolve the target** (`large_prompt.resolve_target`, below) and **ask the RFC-0225 gate before wording the ack** (CoS ruling 4): `engine_coexistence.gate_outlook(target) -> GateOutlook(verdict: "resident" | "allow" | "refuse", reason: str)`, added by 0245-S0 (§2a). It reads only RFC-0225's in-memory state:
   - `resident`: the target is in `anzu_loaded_instances()` or the last `/api/ps` snapshot RFC-0225 keeps;
   - `refuse`: **all** of: the resident worker is owner-loaded (not in `anzu_loads`, e.g. Taco's LM Studio `127.0.0.1:1234` `qwen3.5-9b-defiant-fable-uncensored`), `is_managed(<its engine>)` is false, **and** RFC-0225's last free-VRAM reading is known, fresh (≤ 60 s) and below the target's requirement + 1 GB headroom (`anzu_coder.vram_requirement_gb(target)` + 1 = 13 GB). That is the refusal in #652 §"Engine preparation path" step 5 (owner-loaded 9B, managed mode off), predicted without a probe. RFC-0225 measures free VRAM inside step 5 (#652 §"Engine preparation path" step 5, "VRAM gate for large models") but keeps no reading, so 0245-S0 adds `engine_coexistence.last_free_vram() -> VramReading | None`, recorded by every step-5 measurement (§2a);
   - `allow` otherwise, including an unknown or stale reading and any card where the 27B fits beside the resident 9B (e.g. 18 GB free on a 24 GB card): the preload runs and the real step-5 gate decides, with its refusal fallback below.
3. **Speak the one ack** (CoS ruling 5). The text is a module constant chosen from the outlook. **No variant says the larger model is loading**, so the ack can never claim a load the gate has not allowed:

   | Outlook | Text |
   | --- | --- |
   | `resident` | "This is a large task. I'll split it into parts and work through them one by one with the larger model." |
   | `allow` | "This is a large task. I'll split it into parts and work through them one by one." |
   | `refuse` | "This is a large task. I'll split it into parts and work through them on the model you have loaded." |
   | no target | "This is a large task. I'll split it into parts and work through them on the current model." |

   **Delivery is the parent's front lane (RFC-0230 rule 1, #666 §3 "Decisions", rule 1).** For a pipeline parent `_run` skips `_run_managed_front_lane` and the front-off fallback (`chat_tts` plus `publish_owner_text`). The ack **is** the parent's front-lane line, published as `BUS.publish(task.id, "acknowledgement", "Acknowledged", text, stage="queued")` (the event the 0218 S3b latency test measures) plus `BUS.publish(task.id, "chat_tts", "Large task", text, stage="large_prompt_ack")`, and stamped with RFC-0230 S0's `mark(turn_id, "tts_enqueued", lane="front", source="large_prompt_ack")`. The client's `first_audio` mark (`chatTtsPlayer.ts`, 0230-S0) closes the clock. The title is not `"Speak reply"`, so the ack never joins the reply prefix (`useTaskSpeech.ts::useTaskSpeech`). The ack never goes through `publish_owner_text` (no client, #663). It is a fixed text, not a front-model generation, because a generation could claim a load the gate refuses (ruling 4).
   **Nothing else on the parent is spoken until its terminal outcome.** The gate line, preload status, "Part n of N done", needs_owner and vault lines are `BUS.publish(parent, "large_prompt", …)` events only (visible in Show work and the panel). RFC-0225 owner lines raised by the preload carry `task_id=parent` and `speak=False` (§2a), so they show as a chip and a task event but are not spoken. The terminal outcome (combined result or failure text) is the task's answer, spoken by the existing outcome path once.
4. **Start the preload** with `asyncio.create_task(large_prompt.preload(task.id, target, outlook))` only when a target resolved and the outlook is `resident` or `allow`. It is not awaited, and the handle is stored on the runtime so cancel can reach it. With `refuse`, no preload runs, no model is touched, and the parent shows one event: "Running on <loaded model>: the larger model needs about 12 GB and would need the 9B unloaded, which ANZU only does in managed mode (Settings → Local engines → Let ANZU manage this engine)."
5. Record `ack_ms` on the pipeline row, then `_start_runner(task.id, self._run(task.id, continue_existing=False))`, unchanged.

**Splitting runs after the ack (normative).** No split, completeness or compile work runs in `create_task`; it all runs in the parent runner, which starts after the ack is published. `test_ack_not_delayed_by_split` holds this with a split fake that blocks for 5 s.

**Latency budget (normative), on RFC-0230's clock.**
- **CI:** the ack `chat_tts` is persisted ≤ 150 ms after `evaluate_request_route` returns, with a preload fake that blocks for 5 s and a split fake that blocks for 5 s.
- **Owner-visible target:** the large turn is held to RFC-0230's target, **first audible word ≤ 1.5 s at p50 and ≤ 2.0 s at p95 from end of owner input** (#666 §2 "Target", hard target), measured with 0230-S0's marks. 0245-S4 adds three large-turn cases (`tests/fixtures/rfc0245/latency_cases.json`, from the S3 fixtures: 5-item list, 4 questions, 6000-char spec) through 0230-S0's `--cases` hook in `scripts/anzu-latency-repro.ps1`. The headline is 0230's client-clock `first_audio − input_end`, closed by the browser's `playing` event. There is no separate 0245 clock.

**Target resolution** (`agent/large_prompt.py::resolve_target(settings) -> TargetResolution`, sync, in-memory):
1. `settings.large_prompts.target_runtime` (default `"anzu-coder-27b"`, the 0245-S0 profile), matched against **enabled** runtime profiles (`list_runtime_profiles()`, `enabled is True`) by `name`, then `model_profile`, then the provider model id. A disabled row never matches (`runtime_router.py::_filter_candidates`).
2. Otherwise `route_runtime` (`runtime_router.py`) with `minimum_answer_tier=3`, `task_specialization="coding"` when `task_class` is code/build/debug and `"reasoning"` otherwise, and `preferred_profiles=("expert", "ornith_35b")` (ported from `answer_routing.py::select_runtime_for_decision`).
3. Otherwise no target, with `reason` = S0's last reconcile outcome (`anzu_coder.last_outcome()`). The parent event names it: `ollama_unreachable` → "Ollama isn't running, so the larger model isn't available; running on the current model."; `not_advertised` → "Ollama doesn't list anzu-coder-27b; running on the current model."; `owner_disabled` → "anzu-coder-27b is turned off in your runtime profiles; running on the current model." When the outcome was `ollama_unreachable` and the template is disabled, the **preload task** (never the ack path) first runs one bounded reconcile, `reconcile_anzu_coder_profile(attempts=1, timeout_s=3.0)`. If that enables the row, it re-resolves and continues with the preload, and the event says "Found anzu-coder-27b in Ollama; using it for the parts."

**Preload** (`large_prompt.preload`). No new loader, and **0245 does not edit `hotswap.py`**; it uses RFC-0225's public gate API plus existing, unedited calls:
1. **Request lease first.** `token = engine_coexistence.hold_request_lease(engine_id, model, reason=f"large-prompt:{parent}")` (§2a), held while the parent is `running` (CoS ruling 3); for `waiting`, see below.
2. **Load without persisting.** `settings = await hotswap.apply_runtime_profile_to_settings(target, persist=False)` (`hotswap.py`, existing keyword, not edited), then `await MANAGER.load(settings, profile_name, context_size=target.context_limit, task_id=parent)`. The target is the runtime profile named exactly **`anzu-coder-27b`** (`target.name`, §2a), and `apply_runtime_profile_to_settings` sets the Ollama backend and model `anzu-coder-27b` on the in-memory settings. `profile_name = target.model_profile or settings.inference.profile`; the S0 row has `model_profile = None`, so the saved profile key is kept (the same result `hotswap._resolve_builtin_profile_name` gives for this row, without calling that private helper). **Owner rebind (defined):** `rebind_owner_conversations_after_hotswap` (`hotswap.py::activate_runtime_profile`) is **not** run, because the parts are fresh child tasks bound to the target per task, and the owner's conversations keep the saved selection and its context limit (`test_preload_does_not_rebind_owner_conversations`). After RFC-0225 S3, `MANAGER.load(..., task_id=...)` forwards to `engine_coexistence.prepare_engine_for` (#652 Owner-line surfaces, item 1): single-flight, revive or respawn, identity check, step-5 VRAM gate and owner lines. `save_settings` is never called, so **a large-task load never becomes the owner's saved selection** (ruling 3).
3. Warm with `gpu_prefer.ensure_ollama_gpu` (`apply_runtime_profile_to_settings`) or `ensure_lmstudio_gpu` (`local_lmstudio_fallback_settings`), by provider. For an Ollama target the preload first reads `GET /api/ps`:
   - already listed → no warm call (an owner-loaded model's `keep_alive` is never touched), not recorded in `anzu_loads`, `preload_status = "already_loaded"`;
   - not listed → warm with RFC-0228's normal `keep_alive: "<idle_unload_seconds>s"` (#655 §"Idle unload + reload", Ollama keep-alive bullet; never pinned), then `GET /api/ps` again; listed → `engine_coexistence.record_anzu_load(engine_id="ollama@127.0.0.1:11434", model="anzu-coder-27b")`, `preload_status = "loaded"`; not listed → `failed:warm_not_resident`.
4. Set `preload_status` (see *Statuses*). On any non-loaded status the lease is released at once.

**While the parent is `running`** (parts executing, and the gaps between them):
- RFC-0225 step 6 sees the held request lease and never unloads the target; step 7 never unloads during a lease (#652 §"Engine preparation path", step 5's ANZU-loaded-heavy bullet and step 7).
- **Keep-alive while leased (N4).** Ollama's `keep_alive` is Ollama-side, and the ANZU lease does not stop it, so a long tool step with no model request could let it expire mid-part, fire #655's 27B-idle (§"Orchestrator default + one 9B re-warm path") `NINE_B_REWARM`, and ping-pong both models. While a lease is held on an ANZU-loaded target, `large_prompt` refreshes it every `idle_unload_seconds / 2` (450 s by default) with `POST /api/generate {"model": "anzu-coder-27b", "keep_alive": "<idle_unload_seconds>s"}` (no prompt). The refresh stops when the lease is released (the `waiting` timer, terminal, cancel). An owner-loaded target is never refreshed. Part requests also refresh it. So the 27B is never idle longer than `idle_unload_seconds` after the lease ends, in line with #655 §"Orchestrator default + one 9B re-warm path" ("The 27B is still never held longer than `idle_unload_seconds`").
- `NINE_B_REWARM` (RFC-0228 S2, used only through its public API; 0245 does not edit `rewarm.py`) never swaps the worker between parts: 0245 calls `schedule_orchestrator_restore` only at parent terminal (restore step 3), the 27B-idle trigger fires only once the 27B has left VRAM (#655 §"Orchestrator default + one 9B re-warm path"), and any rewarm reload goes through `prepare_engine_for`, whose steps 6 and 7 never unload a target holding a request lease (#652 §"Engine preparation path", steps 6 and 7) and whose last VRAM guard skips a 9B reload that does not fit (#655 §"Orchestrator default + one 9B re-warm path", "Last guard").
- **Chat turns during a pipeline** route to the loaded target: `prepare_answer_route` uses the loaded runtime (`loop.py::AgentRuntime._run`), and the front lane still speaks first per RFC-0230. RFC-0230 S3's per-turn prewarm skips while the lease is held: 0245-S4 registers `large_prompt.active_target() -> RuntimeProfile | None` (any pipeline holding a lease) through 0230-S3's `turn_prewarm.register_lease_probe` (#666 S3), so a chat turn never issues a 9B `prepare_engine_for` against the lease and never touches the 27B. A chat turn that explicitly needs the 9B (persona brain, explicit switch) waits on the lease under RFC-0225 step 7 and gets that step's visible line.

**While the parent is `waiting`** (a `needs_owner` part; CoS ruling, same rule as #668): when the parent enters `waiting`, `large_prompt` starts an `idle_unload_seconds` timer (RFC-0228 S2's setting, default 900 s). The keep-alive refresh above keeps running while the lease is held and stops when this timer releases it. When it fires, the lease is released and, **only if ANZU loaded the target** (it is in `anzu_loads`), the target is left to RFC-0228's normal expiry and RFC-0225's reverse gate; an owner-loaded target is never touched. The 9B comes back through `NINE_B_REWARM` as usual. `/continue` cancels the timer if it has not fired, otherwise it re-preloads (below) before the next dispatch.

**Preload outcomes (defined, never silent):**

| Outcome | Behaviour |
| --- | --- |
| loaded / already_loaded | Children run on the target. |
| outlook `refuse` (no preload) | The parts run on the loaded 9B. Nothing is unloaded (ANZU never unloads a model it did not load). One event, as in step 4 above. The task does not fail. |
| real gate refuses (step 5) | RFC-0225's owner line (with `task_id=parent`, `speak=False`) names the reason. The lease is released and the parts run on the current model, with one event "Running on <current>: <reason>". The task does not fail. |
| load error | The same fallback, with the error text in the event. |
| not loaded within `PRELOAD_DEADLINE_S = 180` | The preload task is cancelled, then the same fallback with "The larger model took too long to load". |
| owner cancels the parent during preload | The preload task is cancelled, the lease is released, and the restore runs. |

**Re-preload on resume.** `/continue` on the parent and `recover_on_startup` (§5) check `MANAGER.state` and Ollama `/api/ps`. When the target is no longer resident or the lease was released (the `waiting` timer fired, backend restart, owner unloaded it), they re-run `preload` (new lease, same outcomes) before the next dispatch.

**Restore at pipeline end** (any terminal parent status):
1. Release the request lease (if still held). The target's `keep_alive` is already RFC-0228's normal value, so nothing else is sent.
2. **Restore the owner's selection.** Because the preload never persisted, `load_settings().inference` is still the owner's selection. If `MANAGER.state` still points at the target the pipeline loaded, the restore calls `MANAGER.load(load_settings(), <saved profile>, task_id=parent)`, which goes through `prepare_engine_for`, i.e. RFC-0225 step 6 unloads the ANZU-loaded target when the 9B needs the room, and never unloads an owner-loaded one. If the owner changed the model meanwhile (through settings, which merge via `_merge_settings_changes`, `config.py`, used at `save_settings._write`), `MANAGER.state` no longer points at the target and nothing is restored.
3. Call `schedule_orchestrator_restore` (`model_escalation.py`; after RFC-0228 S2 that is `NINE_B_REWARM`).

**Lease bookkeeping (0245 side, keyed by task id).** 0245-S4 edits neither `hotswap.py` (0225-S3 is its only owner) nor `rewarm.py` (0228-S2 is its only owner), and adds no keyword to any `hotswap.py` function. The lease is tracked in `agent/large_prompt.py`: `_leases: dict[str, LeaseRecord]` keyed by the parent task id (`LeaseRecord(token, engine_id, model, anzu_loaded, wait_timer)`), filled by `preload` from `engine_coexistence.hold_request_lease` (0245-S0, #652's file table) and cleared by `release_lease(parent)`. `active_target()` reads it. Leases are in-memory; startup recovery (§5) re-takes them for every pipeline still `running` or `waiting`. The `waiting` timer is exposed as `large_prompt.start_wait_timer(task_id)` / `cancel_wait_timer(task_id)` so RFC-0233 (#668) reuses it unchanged.

### 2a. Target profile: `anzu-coder-27b` (S0)

**Source trace (normative).** `anzu-coder-27b` is an Ollama model on Taco's PC, not something ANZU ships:
- `development` @ `d214b6d`: no runtime profile, model profile, specialist catalogue entry or installer asset defines it. `rg anzu-coder` over `backend/`, `config/`, `installer/` and `tests/` returns nothing. `installer/windows/model-catalog.json` does not exist yet (RFC-0228 S1/S4 create it). `config/default.json` has no runtime profiles; the registry defaults are `runtime_profiles.py::_reject_generic_security_enable` (`PROFILES` + `model_stack.recommended_specialist_runtime_profiles()`), and neither contains it.
- The only mentions on `development` are observations and fixtures: `docs/audits/2026-10-09-model-reuse-scheduler-manager.md::section "Running model reuse"` ("Ollama exposed `anzu-coder-27b:latest` at 11434") and RFC-0227 `docs/rfcs/0227-model-chooser-and-dropdown-persistence.md::section "Taco's setup fixtures (normative, UX #5)"` (HUD slot fixture, provider `ollama`, model `anzu-coder-27b`).
- RFC-0228 (#655, RFC-0228; final head in this PR's body): the header's "Owner context" ("`anzu-coder-27b` (Ollama, ~12 GB GPU) is for coding"), §"Idle unload + reload" "VRAM yielding for `anzu-coder-27b`", and §"Out of scope" ("Changing the 27B coder or its Ollama model configuration"). 0228-S1 owns the Fable 9B default and `fable_9b` (§"Default model"), not the coder, and `dl_expert27b` (§"Problem", item 7) is the separate Qwen3.5-27B GGUF for `expert`. **0228-S1 is therefore not the owner; #655 is not amended.**
- RFC-0225 (#652, RFC-0225; final head in this PR's body): uses the model only in the gate and in owner lines (§"Engine preparation path" steps 2 and 5, including "`anzu-coder-27b` ≈ 12 GB"; §"S3" acceptance "27B request, free VRAM < 13 GB"). It adds no profile.
- Taco's drafts #648 (landed as `d214b6d`) and #649 @ `edb4685`: no hunk names `anzu-coder` (`gh pr diff` searched).

**Owner: 0245-S0.** It adds one shipped runtime-profile template in the existing schema (`RuntimeProfile`, `runtime_profiles.py`, produced by `SpecialistModel.runtime_profile()`, `model_stack.py`), so no schema field is added:

| `RuntimeProfile` field | Value | Why |
| --- | --- | --- |
| `id` | `recommended-anzu-coder-27b` | `model_stack.py::SpecialistModel.runtime_profile` pattern |
| `name` | `anzu-coder-27b` | `large_prompts.target_runtime` default; equals `create_runtime_profile`'s normalisation (`runtime_profiles.py`) |
| `label` (display name) | `ANZU Coder 27B (Ollama)` | |
| `model` (model key) | `anzu-coder-27b` | Ollama tag; `anzu-coder-27b:latest` resolves through the existing `resolve_advertised_model` substring match in `apply_runtime_profile_to_settings` |
| `provider` | `ollama` | as in the RFC-0227 fixture and RFC-0228's header "Owner context" |
| `endpoint` (runtime) | `127.0.0.1:11434` | Ollama loopback, same form as the Umi entry (`model_stack.py::MODEL_CATALOG`). LM Studio `http://127.0.0.1:1234/v1` keeps serving the 9B `qwen3.5-9b-defiant-fable-uncensored`, and nothing here changes it. |
| `context_limit` | `16384` | `RuntimeProfile.from_dict` default. A compiled part is ≤ 6000 chars plus ≤ 1800 chars carry-over, so 16k leaves room for the tool loop and keeps the footprint inside the 12 GB estimate. |
| `quantization` | `ollama` | the Umi convention (`model_stack.py::MODEL_CATALOG`); the quant is inside Taco's Ollama model |
| `privacy_class` | `local-only` | |
| `cost_ceiling_usd` | `0.0` | local (`model_stack.py::SpecialistModel.runtime_profile`) |
| `capability_tags` | `("llm_inference", "text", "coding", "agentic", "tool-use")` | no `high-quality`, so `_quality_score` (`runtime_router.py`) does not lift it over the preferred `expert` in answer routing |
| `specialization_tags` | `("coding",)` | no `reasoning`, so answer routing's `task_specialization="reasoning"` bonus (`answer_routing.py::select_runtime_for_decision`) does not go to it |
| `model_profile` | `None` | an Ollama runtime has no `PROFILES` entry; the preload's `MANAGER.load` then keeps `settings.inference.profile` (§2 step 2) |
| `is_local` | `True` | |
| `description` | `Taco's 27B coding model in Ollama (~12 GB GPU). ANZU enables it only when Ollama lists it.` | |
| `enabled` | `False` as shipped; set to `True` by the S0 reconcile below | specialist templates ship disabled (`tests/test_model_stack.py::test_specialist_runtime_templates_are_disabled_by_default`), so installs without the model route exactly as today |
| `runtime_role`, `answer_tier` | `expert`, `4` | `SpecialistModel.role = "leader"` (`model_stack.py::SpecialistModel.runtime_profile`); `profile_roles.py` is not edited (0228-S2 owns it) |
| `gguf_path` | `""` | not a GGUF ANZU loads |

The `SpecialistModel` entry is `MODEL_CATALOG["anzu-coder-27b"]` with `key`/`runtime_profile_name` `anzu-coder-27b`, `role="leader"`, `enabled_by_default=False`, `ship_runtime_template=True`, `manual_gate=False`, `inference_profile=None`, and the values above. `ROLE_SPECS["leader"].preferred_profiles` is **not** changed (`tests/test_model_stack.py::test_leader_role_prefers_qwen38_then_local_fallbacks` keeps passing).

**Values outside `RuntimeProfile` (no new schema field):**
- **VRAM estimate:** `anzu_coder.VRAM_ESTIMATE_GB = 12.0`, the total requirement at `context_limit` 16384 (Taco's figure; #652 §"Engine preparation path" step 5). `anzu_coder.vram_requirement_gb(target) -> float | None` returns `12.0` when the target provider is `ollama` and its model is `anzu-coder-27b` or `anzu-coder-27b:<tag>`, otherwise `None`. S0 adds one hunk to RFC-0225's `engine_coexistence.prepare_engine_for` step-5 requirement lookup: consult `vram_requirement_gb` first, then the existing catalogue / graded `weight_gb` lookup unchanged. A second one-line hunk in step 5 records the measured free VRAM for `last_free_vram()` (§2 outlook). With the 1 GB headroom the gate acts below 13 GB free, which is #652's test threshold (§"S3" acceptance, "free VRAM < 13 GB").
- **`idle_unload_seconds`:** not per profile. ANZU-originated Ollama loads use RFC-0228 S2's `settings.inference.idle_unload_seconds` (default 900, so `keep_alive: "900s"`; `0` means `"-1"`, pinned; #655 §"Idle unload + reload", Ollama keep-alive bullet). This profile inherits it.
- **ANZU-loaded vs owner-loaded (RFC-0225, #652 §"Terms" *Engine ledger* / *ANZU-loaded instance* and #652 §"Engine preparation path" step 5's bullets):**
  - *ANZU-loaded:* ANZU's preload warmed it and `/api/ps` did not list it before (§2 preload step 3). It is recorded in `anzu_loads`, and the reverse gate (step 6) may unload it with `keep_alive: 0` when the 9B needs the VRAM back.
  - *Owner-loaded:* listed by `/api/ps` before ANZU asked (e.g. Taco ran it from his shell). Not recorded, never unloaded by ANZU, and the reverse gate gives its "which you loaded" error line instead.
  - With the profile enabled, Ollama on 11434 counts as `anzu_configured` under RFC-0225 S3's classification ("Ollama referenced by an enabled runtime profile"), so it is never offered for stopping.
- **Installer catalogue size / sha256:** none. The model is Taco's own Ollama build, so it is not an installer asset: `installer/windows/model-catalog.json` (RFC-0228) gets no entry, and S0 changes no installer file. #655 §"Out of scope" already excludes it.

**Enable reconcile** (`backend/app/inference/anzu_coder.py::reconcile_anzu_coder_profile() -> dict`, new). It runs once per backend start as `_start_optional_step("anzu_coder_profile", reconcile_anzu_coder_profile)` in `main.py` startup, next to the existing optional steps (`main.py`), so startup never waits on it:
1. `probe_remote_server("127.0.0.1", 11434, timeout=3.0)` (`backends.py`). If Ollama is unreachable, it retries every 60 s, at most 10 attempts, then stops with outcome `ollama_unreachable`.
2. Ollama answers but doesn't list `anzu-coder-27b` / `anzu-coder-27b:<tag>` → `not_advertised`. Nothing changes.
3. A registry row named `anzu-coder-27b` whose id is not `recommended-anzu-coder-27b` (an owner-created row) → `owner_row`. That row is left alone and resolution uses it (`_merge_missing_defaults`, `runtime_profiles.py`, never adds the template over it).
4. The template row is already enabled → `already_enabled`.
5. The template row is disabled and `runtime_profiles_root()/anzu-coder-profile.json` has `auto_enabled_at` → `owner_disabled`. The owner turned it off after an earlier auto-enable, so it is not re-enabled.
6. Otherwise → `update_runtime_profile("recommended-anzu-coder-27b", enabled=True)`, write `{"auto_enabled_at": <ISO-8601 UTC>}` to that file, outcome `enabled`.

Each outcome is logged once as `anzu_coder_profile outcome=<outcome>` and returned, so `startup_health` records it. This follows the existing rule that a discovered local model becomes an enabled runtime row (`model_discovery.py::register_discovered_paths`). If the model is removed from Ollama later, the next preload fails visibly through `MANAGER.load` (the Ollama probe's "Model 'anzu-coder-27b' is not loaded in Ollama…") and takes the "load error" fallback in §2; the parts then run on the current model and the task does not fail.

**Taco's 16 GB card (normative statement).** `anzu-coder-27b` needs about 12 GB (`VRAM_ESTIMATE_GB`), and the resident 9B needs about 7 GB (#652 §"Engine preparation path" step 5, owner-loaded heavy-model bullet). 12 + 7 = 19 GB exceeds a 16 GB card, so on Taco's PC the step-5 gate **always** takes either the unload path (the 9B is ANZU-loaded, or managed mode is on) or the refuse path (the 9B is owner-loaded and managed mode is off, which is Taco's default: LM Studio `127.0.0.1:1234`, `qwen3.5-9b-defiant-fable-uncensored`, #652 §"Terms"). The S4 live audit records which path ran, once with managed mode off and once with it on.

**Late Ollama start.** `reconcile_anzu_coder_profile(*, attempts: int = 10, timeout_s: float = 3.0)` keeps the startup behaviour above with its defaults. The last outcome is kept in memory and returned by `anzu_coder.last_outcome() -> str | None`. When RFC-0225 S3 starts `ollama serve` after the 10 attempts ran out, the next large turn's preload task runs one bounded reconcile (`attempts=1`, ≤ 3 s, never on the ack path; §2 target resolution step 3).

**RFC-0225 additions owned by 0245-S0** (`engine_coexistence.py`, second owner after 0225-S3; #652 lists it):
- `gate_outlook(target) -> GateOutlook` (§2 step 2): pure, in-memory only (`is_managed`, `anzu_loaded_instances()`, the last `/api/ps` snapshot, the selected engine's owner/ANZU classification, `last_free_vram()`). No probe, no I/O. `refuse` requires a known, fresh (≤ 60 s) reading below requirement + 1 GB; otherwise `allow`.
- `last_free_vram() -> VramReading(free_gb: float, at: float) | None`: step 5 (#652 §"Engine preparation path" step 5) already measures free VRAM before every gated load; 0245-S0 adds one line there that records the value and its monotonic time in memory. Nothing else reads or measures VRAM.
- `hold_request_lease(engine_id, model, *, reason) -> str` and `release_request_lease(token) -> None`. A held token counts as a request lease in steps 6 and 7 (#652 §"Engine preparation path"), exactly like a turn's lease. Release of an unknown token is a no-op. `held_leases()` lists them for diagnostics.
- `owner_line(..., speak: bool = True)`: with `speak=False` and a `task_id`, (b) publishes the `engine_notice` task event but not the task `chat_tts`. Every existing call keeps the default, so RFC-0225 and RFC-0228 lines are unchanged. The ephemeral (a) frame carries the `task_id`, so `EngineNotices` does not speak it while that task is open (#652 "unless `task_id` equals `openTaskId`").

### 3. Split, completeness, compile (S3)

All of this lives in `agent/large_prompt_intake.py` (new). It runs in the parent runner, deterministically, on CPU, and does not wait for the preload.

**Split** (`split_prompt(text, mode) -> SplitResult`):
- **sections mode:**
  - Split boundaries are, in priority order: Markdown headings, top-level numbered or bulleted items, then blank-line paragraphs. This reuses `decision/intake.py split_segments` for paragraph segmentation.
  - Text before the first boundary is the **shared context** (preamble). A trailing paragraph that begins "Constraints", "Requirements", "Note", "Let op" or "Eisen", or that contains no boundary marker after the last item, is the **shared constraints** block (trailer).
- **questions mode:** one section per question sentence. Non-question sentences that sit between questions attach to the following question as context.
- **Bounds:**
  - 1 ≤ N ≤ `MAX_SECTIONS = 8`, the same value as `intake.MAX_SEQUENTIAL_PARTS`.
  - When N > 8, the two smallest adjacent sections are merged repeatedly.
  - A section under 40 chars is merged into its predecessor.
  - N == 1 is valid: the pipeline still runs one detailed prompt with sub-tasks.
- **Ingress.** A prompt over 6000 chars stores the original once with `memory/ingress_spill.store_ingress_blob` (`count_tokens`). Every section then carries the blob reference so the child can `read_ingress`. The `maybe_mirror_to_vault` swallow is not used.

**Completeness** (`check_section(section, ctx) -> Completeness`):
- Deterministic criteria:
  - **C1, actionable:** at least 3 words and at least one verb or question.
  - **C2, no dangling reference:** "it", "that", "the above", "dit", "dat" or "hierboven" as the subject, without a referent in the section or the shared context.
  - **C3, deliverable inferable:** an imperative verb or a question exists.
  - **C4 (questions mode):** the section is interrogative.
- A Reflex decide scores each section per round: `decision_class="verifier_score"`, the 50 ms deadline, and `choice complete | incomplete` with a `missing` rationale. Rules are the fallback.
- A section is **complete** when C1-C4 pass and the score is not `incomplete` at confidence ≥ 0.75.
- **Deterministic repairs, one per round, in this order:**
  1. merge into the predecessor (fixes C2 or C1);
  2. merge with the next section;
  3. attach the previous section's text as context (fixes C2).

  Each repair is recorded in `repairs_json`.
- **Hard bound: `MAX_COMPLETENESS_ROUNDS = 3`.** At the bound the outcome is **defined**:
  - The section status becomes `needs_owner` and `missing_json` lists the failed criteria.
  - One parent event (not spoken; CoS ruling 5): `Part N isn't clear enough to start: <missing, ≤ 120 chars>. Tell me what you mean, or say "skip part N".` The parent's `waiting` status shows it in the panel and the task list.
  - The queue runs every part **before** the blocked one, then the parent goes to `waiting`.
  - An owner reply via `/continue` on the parent sets that part's `source_text` to the original text plus the reply, and grants exactly **one** more round. Failing that round re-asks once with the same line. "skip part N" marks the part `skipped`.
  - Nothing proceeds on an incomplete section. Nothing soft-fails.

**Compile** (`compile_prompt(section, ctx) -> str`, deterministic template, ≤ 6000 chars; #649's brief budget at `task_workflow.py::prepare_workflow`):

```
Part {n} of {N}: {title}
Goal: {one-line goal, the first sentence of the section}
Shared context: {preamble, ≤ 1200 chars, or "read_ingress <blob>" reference}
Constraints: {trailer, verbatim}
Section (verbatim): {source_text}
Deliverable: {inferred deliverable, or "a direct, complete answer to the question"}
Acceptance: {the section's own success criteria if stated, else "every point in the section is addressed"}
Rules: do only this part; earlier parts' results are given below when relevant; report what could not be verified.
```

At dispatch, the child gets `Previous part result (≤ 1800 chars)`, which is intake's `CARRYOVER_CHARS`. No model rewrites the section text. The detailed prompt is reproducible from the row.

**Mandatory sub-tasks (every prompt, always).** The child's workflow steps are:
1. `work`;
2. `deeper`;
3. `quantitative`;
4. then #649's `REVIEW_STEPS` when `large_task_reviews` is on.

`deeper` and `quantitative` are not toggleable.

- **deeper** step prompt: analyse the part's result beyond the direct answer. The result **must** contain these Markdown headings:
  - `Root cause / mechanism`;
  - `Alternatives considered`, with at least 2 items;
  - `Assumptions checked`;
  - `Edge cases`.
- **quantitative** step prompt: put numbers on it. The result **must** contain:
  - a Markdown table with header `Metric | Value | Unit | Source/Method`;
  - at least 1 row with a numeric Value;
  - in every row, either a source (file, command, URL or measurement) or `estimate: <method>`;
  - a line beginning `Acceptance:` that states the target against the measured or estimated value.

  When the part is genuinely non-numeric, the row is `Measurable criteria | <count> | items | enumerated above`, which still holds a number.
- **Validators** (`validate_deeper`, `validate_quantitative`, pure): a failed validation re-runs the step with the validator's message appended, at most **2 retries**. After that the step fails, and the part fails visibly with "Part n of N: quantitative sub-task did not meet its format after 3 attempts". No validator is skipped.

**Persist.**
- SQLite is **always** authoritative: `large_prompt_pipelines` plus `large_prompt_sections` (§4).
- **Vault mirror:** applies when `public_binding_status` (`memory/obsidian_vault.py`) is bound and `large_prompts.store == "db_and_vault"`. It is **idempotent, keyed on the section's `vault_rel_path`** (`_Temporal/LargePrompts/<parent_id>/part-NN.md`):
  - **get-or-create:** when the row already has `vault_rel_path` and the note exists, it is reused; only otherwise `create_note` writes it with frontmatter (parent, ordinal, status) and the detailed prompt. `create_note` raises `FileExistsError` on an existing file, so a recovery re-dispatch or a follow-up recompile never calls it twice; an existing file without a row path is adopted and its path stored.
  - **append, not replace:** `edit_note` replaces the body, so at part terminal the pipeline reads the current body, composes `<existing body>\n\n## Result\n<summary>` and passes that to `edit_note`. A recompile appends `## Prompt (revised)` the same way.
- **Owner-edit conflict:** `edit_note` reports a conflict without `force`. The pipeline does not force. It records `vault_conflict` on the row and shows one parent event (not spoken), "Part n note was edited in Obsidian; ANZU left your edit and kept the result in ANZU".
- **Mirror failure:** produces a visible parent event (not spoken). DB persistence and the run continue.
- `large_prompts.store` takes the values `"db"` (default) or `"db_and_vault"`.

### 4. Storage: landed #649 engine plus seeding (S2)

#649 landed as `ee786dc`. S2 **reuses** its engine unchanged and ports nothing. Every citation below is `development` @ `d85c9d4`:

| Landed #649 piece | Where | Used by 0245 as |
| --- | --- | --- |
| `TaskPromptPlan` (goal, source_ref, followups_json), `TaskPromptStep` (uq `task_id`+`ordinal`, kind, prompt, status, result) | `db/models.py` | child prompt storage, unchanged |
| `REVIEW_STEPS` | `agent/task_workflow.py` | appended to every child when `large_task_reviews` is on |
| `TaskWorkflow` (`prompt()` with bounded predecessor summaries, `owns_history`, `finish_current`, `mark_running`) | `task_workflow.py` | runs the child's seeded steps |
| `load_workflow` | `task_workflow.py` | child `_run` finds its seeded plan |
| `workflow_payload`, `prompt_steps` in `GET /api/tasks/{id}` and observability | `task_workflow.py`, `api/tasks.py::get_task`, `get_task_observability` | child payload, unchanged |
| stored-workflow load and the `needs_workflow` flag | `agent/loop.py::AgentRuntime._run` | a child with seeded steps takes the workflow path |
| stored-workflow execution (`mark_running`, prompt, `max_steps = min(320, policy.max_steps × steps)`) | `loop.py` | unchanged |
| per-prompt step limit | `loop.py::AgentRuntime._run` | unchanged |
| advance to the next stored prompt with fresh context | `loop.py::AgentRuntime._run` | unchanged, plus the S5 validator gate before (§3) |
| completion guard (no completion while more than one stored prompt is open) | `loop.py::AgentRuntime._update` | unchanged |
| `large_task_reviews` setting | `config.py::AppSettings`; `api/settings.py::SettingsUpdate`, `update_settings` | unchanged |
| prompt-steps rows in the panel, status label, types | `TaskActivity.tsx::TaskActivityPanel`, `taskStatus.ts::mergeObservability`, `api.ts::TaskObservability` | child panel, unchanged (S6 adds no prompt-steps UI) |
| tests | `tests/test_rfc0224_task_workflow.py` (24 tests, `pytest` "Run full backend suite") | stays #649's; S2 doesn't edit it, and it must keep passing |

**Not used by the pipeline (left exactly as landed):** `PLAN_SYSTEM` / `prepare_workflow` (`task_workflow.py`), the auto-plan branch (`loop.py::AgentRuntime._run`) and `append_followup` (`task_workflow.py`, `loop.py::AgentRuntime._run`):
- A pipeline **parent** never reaches them: S4's parent-runner entry returns before `loop.py::AgentRuntime._run`.
- A **child** has seeded steps, so `workflow is not None` and the auto-plan branch is skipped (`loop.py::AgentRuntime._run`).
- Child `/continue` goes to the parent (§5), so `append_followup` never runs for a child.
- Every other task, including any large request when `large_prompts.enabled=false` or the precheck excludes the turn, keeps #649's behaviour unchanged.

**Added by S2 (what #649 does not provide):**
- `task_workflow.seed_workflow(session, task_id, *, goal: str, source_ref: str, steps: list[StepSpec]) -> None`, appended to `task_workflow.py` after `workflow_payload`. `StepSpec = tuple[str, str]` is (kind, prompt). It runs in the caller's session, before `_start_runner`. It writes one `TaskPromptPlan` and one `TaskPromptStep` per spec (ordinal 1..n, status `pending`) and sets `task.plan_json` the way `prepare_workflow` does . It is idempotent: if a plan already exists for `task_id`, it returns without writing. Bounds are 1 ≤ len(steps) ≤ 12 and `len(goal) ≤ 16000`, the same ceiling `append_followup` enforces . Anything over raises `ValueError`, and the child is never created.
- **What a child's seeded rows contain:**
  - `goal`: the section's `detailed_prompt` (≤ 6000 chars), plus `Previous part result` (≤ 1800 chars) when there is one;
  - `source_ref`: `large_prompt_sections id=<id>`, plus `; read_ingress blob_id=<blob>` when the pipeline has a blob;
  - steps: `("work", "Deliver this part as specified in the goal.")`, `("deeper", <deeper prompt, §3>)`, `("quantitative", <quantitative prompt, §3>)`, then `REVIEW_STEPS` when `large_task_reviews` is on.
- The two pipeline tables below and `LargePromptSettings` (§Settings).

**Statuses: every value has one setter and one reader (normative).**

| Field | Value | Set by | Read by |
| --- | --- | --- | --- |
| `pipelines.status` | `preparing` | large branch in `create_task` (row insert) | panel (`payload`), `recover_on_startup` (re-runs the parent runner) |
| | `running` | parent runner after compile + persist | `dispatch_next`, `on_child_terminal`, panel, recovery |
| | `waiting` | `dispatch_next` when the next part is `needs_owner` (from `on_child_terminal` or the first dispatch) | `/continue` (§5), the `waiting` idle timer (§2), panel, recovery |
| | `running` (again) | the `/continue` handler, after the answered `needs_owner` part is re-checked `complete` (§5); also cancels the `waiting` timer | `dispatch_next`, panel |
| | `completed` / `failed` | `on_child_terminal` on the last part / a failed part | restore, panel, `_update`'s terminal hook (parent terminal) |
| | `cancelled` | `on_parent_cancel` | `on_child_terminal` (never dispatches), panel |
| `pipelines.preload_status` | `pending` | row insert | panel |
| | `loaded` / `already_loaded` | `preload` (after `/api/ps`) | `dispatch_next` (child runs on target), restore (`loaded` ⇒ ANZU loaded it), panel |
| | `skipped:refuse` / `skipped:no_target` | large branch (no preload started) | `dispatch_next` (child on current model), panel |
| | `gate_refused:<reason>` / `failed:<reason>` / `timeout` | `preload` | `dispatch_next` (current model), panel |
| | `released:waiting_idle` | the `waiting` idle timer | `/continue` and recovery (re-preload), panel |
| `sections.status` | `pending` | parent runner (persist) | `dispatch_next` |
| | `queued` / `running` | `dispatch_next` / the child's `_run` start | recovery (re-dispatch / resume), panel |
| | `needs_owner` | S3 intake at the round bound (§3) | `dispatch_next` (parent → `waiting`), `/continue` (answers it), panel |
| | `completed` / `failed` / `skipped` / `cancelled` | `on_child_terminal` / `on_child_cancel_api` and the skip-part follow-up / `on_parent_cancel` | parent completion (combined result), panel |
| `sections.completeness` | `complete` / `incomplete` | S3 completeness rounds | S3 intake (`incomplete` at the bound ⇒ `needs_owner`; only `complete` sections are compiled), panel |

`test_every_status_has_setter_and_reader` walks this table: for every value it drives the named setter and asserts the named reader branches on it.

**New tables** (`db/models.py`; created by `create_all`, no ALTER needed):

`large_prompt_pipelines`:
- `parent_task_id` (PK, FK tasks);
- `mode`;
- `status`: preparing | running | waiting | completed | failed | cancelled;
- `target_profile`;
- `preload_status`;
- `previous_selection_json` (audit only: the owner's saved selection at preload time; the preload never persists, so the restore reads the saved settings, §2);
- `ack_ms`;
- `store`;
- `blob_ref`;
- `created_at`, `updated_at`.

`large_prompt_sections`:
- `id`;
- `parent_task_id` (index);
- `ordinal`, with uq(`parent_task_id`, `ordinal`);
- `title`;
- `source_text`;
- `completeness`;
- `rounds`;
- `missing_json`;
- `repairs_json`;
- `detailed_prompt`;
- `child_task_id`, nullable, unique;
- `status`: pending | needs_owner | queued | running | completed | failed | skipped | cancelled;
- `result_summary`;
- `vault_rel_path`;
- `vault_conflict`;
- `content_hash`;
- timestamps.

### 5. Queue and lifecycle (S5)

This reuses the semantics of `agent/intake.py`'s chain (stable ids, advance on terminal, stop on failure; `part_request_id, start_sequential_chain, advance_chain`), moved from JSON files to the DB, and admits each child through the same breaker scheduled runs use.

- **Dispatch** (`large_prompt_queue.dispatch_next(parent_id)`):
  - Under a per-parent `asyncio.Lock`, pick the lowest-ordinal `pending` or `queued` section.
  - Call `admit_automatic_trigger` (`automation/breaker.py`) with automation id `large-prompt:<parent>`, `ensure_automation` first. When the kill switch is engaged or the breaker is open, the parent fails visibly with the breaker reason. No retry loop.
  - Call `AGENT.create_task(child_prompt, request_id=uuid5(NS, f"large-prompt:{parent}:{ordinal}"), pipeline_section=section_id, profile=target)`.
  - The id is stable, so a re-dispatch after a crash reuses the same child (`loop.py::AgentRuntime.create_task` request_id reuse).
  - **Bind the admitted run to the child:** `bind_run_to_task(run_id, child.id)` (`automation/breaker.py`) right after `create_task` returns, the same call the scheduler makes (`mobile/scheduler.py::tick`). Without it the admitted run stays in flight and eats the failure budget (`breaker.py::_in_flight_run_count`, `admit_automatic_trigger`). A re-dispatch that reuses the child id re-binds the same run id.
- **`create_task(..., pipeline_section: str | None = None)`**, keyword-only, default `None`, so every existing call is unchanged. When it is set:
  - The route is fixed to MANAGED with the parent's task class and **no decide** (the parent turn already decided; still exactly one decide per owner turn).
  - No persona block, no large branch (no recursion) and no generic ack.
  - `seed_workflow` with `work, deeper, quantitative, *REVIEW_STEPS?` runs in the same session as the Task commit, before `_start_runner`.
  - The title is `Part n of N · <section title ≤ 60 chars>`.
- **`_run` for a child:** skip the managed front lane and its `chat_tts`. Children never speak, because the HUD follows the parent. Run the seeded workflow on the target profile. Per-child `speak_outcome` in the terminal hook is suppressed.
- **Terminal hook** (`_update`), placed next to `advance_intake_chain`, as `large_prompt_queue.on_child_terminal(child_id, status, result)`. **First check:** when `pipeline.status == "cancelled"` (the parent was cancelled), the hook records the child's section as `cancelled` and returns; it never dispatches. Otherwise:

| Child status | Effect |
| --- | --- |
| completed | Section `completed` with `result_summary`; vault append (§3); parent event "Part n of N done" (not spoken); dispatch the next part. If the next part is `needs_owner`, the parent goes to `waiting` and shows the line once as an event; the request lease stays held. If there is no next part, the parent completes. |
| cancelled by the owner (child cancel, pipeline not cancelled) | Section `skipped`; parent event "Part n skipped"; dispatch the next part. |
| failed | Section `failed`; remaining sections `cancelled`. The parent **fails** with "Part n of N failed: <error ≤ 200>. Parts n+1–N were not started." That text is spoken by the existing outcome path. |
| kill switch / breaker | Same as failed, with the breaker reason. |

- **Parent completion:**
  - `result` is the per-part Markdown sections ("## Part n: title" plus result).
  - `verification` has one line per part: the part's own verification, plus "deeper ✓ quantitative ✓".
  - Status is `completed`. The existing `speak_outcome` and the `useTaskSpeech` final speech run unchanged: that is the task's answer, the only parent speech after the ack.
  - Then the restore (§2).
- **Parent runner:**
  1. Run intake (§3).
  2. Await the preload up to its deadline.
  3. Set parent status `running` with `current_action` "Part 1 of N".
  4. Dispatch.
  5. **Return without a terminal status.** The parent stays `running` (or `waiting`), driven by the hook.

  `_update`'s terminal hook therefore never sees a parent until the pipeline itself sets it terminal.
- **Cancel:**
  - `AGENT.cancel` (`loop.py`) is **sync** and stays sync. S5 adds one call in it: `large_prompt_queue.request_parent_cancel(task_id)` (sync, a no-op for a non-pipeline task). It sets an in-memory `cancelling` flag that `on_child_terminal` and `dispatch_next` treat exactly like `pipeline.status == "cancelled"`, then hands `on_parent_cancel(task_id)` to the event loop **thread-safely**: on the loop thread with `loop.call_soon(loop.create_task, …)`, from any other thread with `asyncio.run_coroutine_threadsafe(…, loop)`, where `loop` is the backend's main loop captured by `large_prompt_queue.bind_loop()` in `main.py`'s startup, **immediately before** `recover_on_startup`. **Before `bind_loop` has run** (a startup-time cancel, or a test that never binds a loop) `request_parent_cancel` only sets the `cancelling` flag and logs one line `large_prompt cancel_before_bind task=<id>`. It never raises and schedules nothing. `dispatch_next` honours the flag (no dispatch; it runs `on_parent_cancel` itself, which marks the pipeline `cancelled`), and `recover_on_startup` honours it the same way for a pipeline it would otherwise resume. This works whether or not the parent runner is still alive (it returns after the first dispatch, so its handler cannot be relied on). Every sync caller therefore reaches a running pipeline: the cancel endpoint (`api/tasks.py::cancel_task`), voice stop (`mobile/realtime_voice.py::interrupt_turn`), media (`mobile/media.py::VoiceBridge.accept_audio`), self-dev (`agent/self_dev.py::activate_kill_switch`) and the live agent suite (`inference/live_agent_suite.py::_run_live_suite`). `POST /api/tasks/{id}/cancel` (`async def cancel_task`, `api/tasks.py`) for a pipeline parent additionally **`await`s `large_prompt_queue.on_parent_cancel(parent)`** first, then calls `AGENT.cancel(parent)` and commits the row as today. `on_parent_cancel`, under the per-parent lock, sets `pipeline.status = "cancelled"` **first**, then cancels the running child and the preload task, marks the rest `cancelled`, cancels the `waiting` timer and the keep-alive refresh, releases the lease and runs the restore. It is idempotent, so the scheduled call after the endpoint's awaited one is a no-op. The running child's later terminal hook sees the cancelled pipeline (or the flag) and never dispatches.
  - For a pipeline **child**, `cancel_task` keeps its order (sync `AGENT.cancel`, then the `status = "cancelled"` commit without `_update`, so the terminal hook would never fire for a queued child with no runner) and S5 adds one call after that commit: `await large_prompt_queue.on_child_cancel_api(child_id)`, which runs `on_child_terminal(child_id, "cancelled", None)` (skip that part, dispatch the next).
- **Follow-ups:**
  - `/continue` on a **child** is redirected to the parent, in `continue_task`.
  - `/continue` on the **parent** is handled in `_run`'s follow-up path, after S3b's follow-up persona block. It first re-preloads when the target is no longer resident (§2). If a part is `needs_owner`, the reply answers it (§3). Otherwise the text is appended as a new last part (content-hash dedupe, the same rule as landed `append_followup`, `task_workflow.py`; the parent has no stored workflow, so `append_followup` itself is not called) and goes through completeness and compile.
- **Startup recovery** (`main.py`, after `reconcile_execution_on_startup`). A pipeline in **`preparing`** (the parent runner died before compile/persist) re-runs the parent runner from intake: split, completeness, compile and persist are idempotent (§3, uq(`parent_task_id`, `ordinal`)), then the preload if no lease is held. For each pipeline in `running` or `waiting`:
  - re-take the request lease (`large_prompt._leases`);
  - when the target is not resident, re-run `preload` (§2 "Re-preload on resume");
  - if the current child is terminal, run `on_child_terminal` (a missed advance);
  - if it is `queued` without a runner, dispatch it again (same id);
  - if it is `running` without a runner, call `continue_task(child)`, which resumes the durable run (RFC-0029).
- **Visibility:** `get_task` (`api/tasks.py`) **and** `get_task_observability` (`api/tasks.py`, which `TaskActivity.tsx::TaskActivityPanel` fetches once, only while `phase_history` is empty; live parent updates come from `GET /api/tasks/{id}`) both gain the same `large_prompt` object (one builder, `large_prompt_queue.payload(task_id)`), containing:
  - mode;
  - status;
  - target;
  - preload_status;
  - ack_ms;
  - sections (`ordinal`, `title`, `status`, `completeness`, `rounds`, `missing`, `child_task_id`, `vault_rel_path`, `vault_conflict`).

  Parent events are plain human text, so Show work (`OwnerChatTranscript.tsx::OwnerChatTranscript`, which renders `title` and `detail`) shows the progress without an edit.
- **Recents:** children appear in `/api/tasks` (polled by `App.tsx::OwnerPortal`) with their "Part n of N" titles. The list endpoint is unchanged.

### 6. Owner UI (S6)

The live panel already has #649's "Saved plan and task prompts" block (`TaskActivity.tsx::TaskActivityPanel` on `d85c9d4`, `mergeObservability` carrying `prompt_steps` at `taskStatus.ts`, `prompt_steps` types at `api.ts::TaskObservability`). S6 **extends those rows add-only** and does not build a second plan list (CoS ruling 2).

- **Data.** `large_prompt` arrives on both `GET /api/tasks/{id}` and `GET /api/tasks/{id}/observability` (§5). `mergeObservability` (`taskStatus.ts`) gains one line, `large_prompt: obs.large_prompt ?? task.large_prompt`, next to `prompt_steps`. `TaskObservability`'s field list gains `"large_prompt"`.
- **View model, pure TS:** `frontend/src/components/largePromptSectionsView.ts` (new). `largePromptSectionsView(task: Task): LargePromptView | null` returns `null` when `task.large_prompt` is absent. Otherwise it returns:
  - for a **parent**: one row per section (ordinal, title, status chip label and tone, completeness, rounds, missing text), each with actions `{label: "Open", taskId: child_task_id}`, `{label: "Cancel part", method: "POST", path: "/api/tasks/<child>/cancel"}` (only when queued or running) and the vault path when mirrored; one `{label: "Cancel remaining", method: "POST", path: "/api/tasks/<parent>/cancel"}`; and a status line built from target, preload_status and ack_ms;
  - for a **child**: one line, "Part n of N of <parent title>", with an Open action to the parent.
  Step labels come from the existing `humanizeToken` (`taskStatus.ts`): `deeper` → "Deeper", `quantitative` → "Quantitative". No new label table.
- **Render (thin, add-only)** in `TaskActivity.tsx`:
  - the existing condition `{!!view.prompt_steps?.length && (` (`TaskActivityPanel`) becomes `{(!!view.prompt_steps?.length || !!largeView) && (`; the `<summary>Saved plan and task prompts</summary>` and the existing `<ol>` of prompt steps stay byte-identical, and the `<ol>` still renders only when `prompt_steps` has rows;
  - after that `<ol>`, inside the same `<details>`, one added mount `{largeView && <LargePromptSections view={largeView} />}`;
  - `frontend/src/components/LargePromptSections.tsx` (new) renders the view model and wires buttons to `api()` with the view model's method and path.
  A pipeline child (which has seeded `prompt_steps`) therefore shows the live rows exactly as today plus the "Part n of N" line; a parent (no prompt steps) shows the sections list inside the same block.
- **Tests run on the pure file.** `frontend/large-prompt-sections.test.mjs` imports `largePromptSectionsView.ts` and `taskStatus.ts` under `node --experimental-strip-types` (no `.tsx` import, like `avatar-motion.test.mjs`). `npm run build` (`pr-tests.yml`, "Build frontend") is the TSX type gate for `TaskActivity.tsx` and `LargePromptSections.tsx`.
- **Not edited:** OwnerChatTranscript, HudChat, Chat, Phone, `useTaskSpeech` and every persona component.

### Live-UI add-alongside reasoning pass (2026-10-14 standing order)

Touched live UI: the TaskActivity panel (HudChat, Chat, Phone), task speech, Show work, the front lane.

| Surface | Existing behaviour kept? | Addition and reasoning |
| --- | --- | --- |
| "Saved plan and task prompts" (`TaskActivity.tsx::TaskActivityPanel`) | **Yes.** Summary text, `<ol>`, rows, `humanizeToken` labels and the nested "Stage result" details are byte-identical. For a task without `large_prompt` the condition evaluates exactly as today (`largeView` is `null`). | One `||` in the condition and one mount after the `<ol>`. Reasoning: a non-pipeline task cannot see any change; a pipeline child gains one line; a parent gains the sections list where the owner already looks for "the plan". |
| Rest of `TaskActivityPanel` (`ChildExecution`, `VerificationPanel`, `PhaseHistory`, buttons) | **Yes**, untouched | None. |
| `mergeObservability` | **Yes**: every existing field still merged the same way | One added field. A test asserts all existing fields are unchanged. |
| `useTaskSpeech` | **Yes**, unchanged | The ack is an ordinary `chat_tts` with title "Large task" (≠ "Speak reply"). Nothing else on the parent is spoken until its outcome. |
| Parent front lane (`_run_managed_front_lane`, front-off fallback) | **Changed only for a pipeline parent**: skipped, because the ack is its front-lane line. Every other task runs the front lane as today. | Reasoning: two front lines (ack plus a model reply) would break ruling 5, and a model line could claim a load. Children already skip it. |
| Show work (`OwnerChatTranscript.tsx::OwnerChatTranscript`) | **Yes**, unchanged | Parent events are human-readable text, so no formatter is needed. |
| `EngineNotices` (RFC-0225) | **Yes** | Preload lines carry `task_id=parent` and `speak=False`: chip and task event, no speech. |
| RFC-0218 persona switch line, highlight, morph | **Yes** | Parent switch per S3b, before the ack. Children emit no persona events. |
| Phone | **Yes** | Shows the parent's events and panel via its existing poll. No speech is added. |
| Task recents (`App.tsx::OwnerPortal`) | **Yes** | Part children are listed with "Part n of N" titles. |

### Stub rule

Every function named here ships complete, with tests. The following are not allowed:
- `TODO` or `NotImplementedError`;
- `except Exception: pass` around pipeline steps;
- a toggle without an implementation;
- a step or validator that always passes;
- a section status that nothing sets;
- a UI button whose endpoint is missing.

`large_prompts.enabled=false` restores today's behaviour exactly. A test proves the decision and `create_task` are byte-identical in that case.

### Settings (S2 adds the block; owned in `config.py`)

```python
class LargePromptSettings(BaseModel):
    enabled: bool = True
    target_runtime: str = "anzu-coder-27b"  # the 0245-S0 runtime profile name
    store: Literal["db", "db_and_vault"] = "db"
```

`AppSettings.large_prompts` is added next to `decision` (`config.py` on `d85c9d4`). `api/settings.py` exposes it on the existing settings GET and PUT. No new settings UI is part of this RFC; the setting is editable through the existing advanced settings JSON.

---

## Reconciliation

| With | Rule |
| --- | --- |
| **RFC-0224 / #649 (landed `ee786dc`)** | Its engine is reused unchanged (§4). S2 adds `seed_workflow`, the pipeline tables and `LargePromptSettings`, and copies no #649 code. Pipeline parents are marked by their `large_prompt_pipelines` row and bypass #649's model planner (S4 entry before `loop.py::AgentRuntime._run`; `test_649_planner_not_called_for_pipeline_parent_or_child`). Children are seeded, so they never auto-plan. Every other task keeps #649's behaviour. `tests/test_rfc0224_task_workflow.py` is not edited and must stay green. |
| **RFC-0211 / #670** | Sections are rows a future scheduler can list as "upcoming tasks". When `DevelopmentScheduler` lands, its `resource_hold` (checked in `DevelopmentScheduler.tick()`) is respected: dispatch defers while a hold names Ollama, with the parent event "Waiting for the scheduler's model hold". Nothing here waits on #670. |
| **RFC-0026 / 0029** | Children are ordinary durable tasks created through `AgentRuntime.create_task`. Follow-ups use `/continue`, and recovery uses `continue_task`. There is no second task system. |
| **Reflex arbitration** | One decide per owner turn, with two riders only when a candidate exists. The ack is a fixed front notice worded from the gate outlook, so `keep_worker` semantics apply to the parent result (§1). |
| **RFC-0218 S3b (+ #663)** | The parent turn's persona block runs first, unchanged. `switch_id = task_id:seq` is counted on the parent only. Children never call `apply_persona_switch`, so they publish no `persona_switched` or `persona_switch_failed`, and their `seq` counter stays empty. The 0218 test `t(acknowledgement) − t(persona_switched) < 50 ms` still holds, because the large branch publishes the `acknowledgement` event in the same position. |
| **RFC-0225 S3** | The preload loads through `MANAGER.load(..., task_id=parent)`, which 0225-S3 routes through `prepare_engine_for`; settings come from the existing `hotswap.apply_runtime_profile_to_settings(target, persist=False)`. There is no separate VRAM gate, loader or owner-line channel, and 0245 does not edit `hotswap.py` (0225-S3 is its only owner in this batch, #652 (RFC-0225; final head in this PR's body)). 0245 uses 0225's own gate inputs for the ack outlook (plus the last step-5 free-VRAM reading, which 0245-S0 records), holds a 0225 request lease on the target while the parent runs (steps 6 and 7 respect it), and never unloads a model ANZU did not load. 0245-S0 is the second owner of `engine_coexistence.py`; #652's file table names it. |
| **RFC-0228 S1 / S4** | Not the owner of `anzu-coder-27b`: 0228-S1 is the Fable 9B default and 0228 §"Out of scope" excludes the coder ("Changing the 27B coder or its Ollama model configuration"). No `model-catalog.json` entry is added (not an installer asset). |
| **RFC-0225 S3 (gate requirement)** | 0245-S0 adds the `anzu-coder-27b` requirement (12 GB) as the first lookup in the step-5 gate. The gate logic, ledger and owner lines stay 0225's. |
| **RFC-0228 S2** | An ANZU-loaded target is warmed with RFC-0228's normal `keep_alive: "<idle_unload_seconds>s"` and is never pinned, so #655 §"Orchestrator default + one 9B re-warm path" ("never held longer than `idle_unload_seconds`") holds: part requests refresh it while the parent runs, and in `waiting` the lease is released after `idle_unload_seconds` (only an ANZU-loaded target is then left to expire; reload on `/continue`). The restore goes through the owner's unchanged saved selection and `schedule_orchestrator_restore` → `NINE_B_REWARM`. 0245 does not edit `rewarm.py` (0228-S2 is its only owner) or `hotswap.py` (0225-S3 is its only owner); both are used through their public API only. |
| **`agent/intake.py`** | Left in place for `stream_owner_chat`. The large pipeline replaces its use only on the tasks path. Merging the two is out of scope. |
| **RFC-0232 (#664)** | **Precedence (CoS, verbatim):** A turn whose prompt contains an absolute filesystem path together with RE intent (RFC-0232's narrowed dump/extraction detection) routes to reverse engineering and is never split by RFC-0245; a path with a plain or coding question routes normally. 0232-S2's RE helper (two-stage, specified in #664) is called by 0245's precheck and suppresses the riders; 0232's RE floor in `_apply_floors` runs before 0245's; one `decide()` per turn (§1). Tests: 0232's `test_path_plus_re_intent_routes_to_re_before_large_prompt_split` (`tests/test_rfc0232_intent_and_alias.py`); 0245's `test_path_plus_re_intent_routes_to_re_not_split`, `test_plain_path_question_not_routed_to_re`, `test_ffs_word_coding_question_not_routed_to_re`, `test_one_decide_per_turn`. Files: 0232-S2 (`owner_turn.py`) before 0245-S1; 0232-S3 → S4 → S5 (`loop.py`) before 0245-S4 and -S5. |
| **RFC-0230 (#666)** | Its slices go **first** on the shared turn files: `loop.py` (0230-S0 → S2 → S3, after 0218-S3b), `owner_turn.py` (0230-S5, after 0218-S3b), `api.ts` (0230-S0). Then RFC-0232, then 0245. On `main.py` RFC-0225 goes first (0225-S2 → S3 → 0230-S0 → S5 → 0245-S0 → S5; 0225-S1 does not edit `main.py`, #652 (RFC-0225; final head in this PR's body)). On a held 27B lease, 0230-S3's per-turn prewarm skips via `register_lease_probe` and never touches the 27B. The large ack is the parent's front-lane line (rule 1), marked with 0230-S0's `mark`, and is held to 0230's ≤ 1.5 s p50 / ≤ 2.0 s p95 through three large cases appended to `scripts/anzu-latency-repro.ps1`. On a large verdict 0245 calls 0230-S3's `turn_prewarm.cancel_prewarm(turn_id)`. Row 6 (the two-system-message HTTP 500) is fixed in code by landed #649 (#666). |
| **RFC-0244 (landed engine modes)** | Cited by section ("Decision", "Acceptance criteria"). `reflex_only` runs no large-prompt pipeline, no preload and no ack; `model_only` runs the pipeline without the reflex lane (rules-only precheck, no JEV or Laya); `hybrid` is as specified above. 0245 reuses `engine_mode.model_enabled` and `decision_engines_enabled` and adds no mode of its own. See §1 "Engine modes". |

## Relationship to #649 and #670

| Draft hunk | Taken? | Where |
| --- | --- | --- |
| #649 models, `TaskWorkflow` engine, loop workflow execution, `prompt_steps`, `large_task_reviews`, UI steps | **Landed; reused unchanged** (`db/models.py::TaskPromptPlan`, `task_workflow.py::REVIEW_STEPS`, `workflow_payload`, `loop.py::AgentRuntime._run`, `AgentRuntime._update`, `TaskActivity.tsx::TaskActivityPanel`) | S2 (seeding only), S5, S6 |
| #649 `is_large_request` | **Landed; imported** as rules L4 (`task_workflow.py`) | S1 |
| #649 `PLAN_SYSTEM` / `prepare_workflow` / auto-plan branch / `append_followup` | Landed; **not used by the pipeline** and left unchanged for every other task (§4) | — |
| #649 `basic_qa` reply shape | Landed (`owner_turn.py::REPLY_SHAPES`); the S1 precheck excludes it | S1 |
| #670 scheduler | Not ported (respected when it lands) | S5 |

---

## Slices (one ticket each, one developer each, fast off)

### S0: `anzu-coder-27b` runtime profile, VRAM requirement, enable reconcile, gate outlook and leases

**Model:** Grok 4.5 · **Lane:** D1 · **Depends:** RFC-0225 S3 (creates `engine_coexistence.py` with `prepare_engine_for`, `owner_line`, `anzu_loads`; `main.py` chain)

| File | Change |
| --- | --- |
| `backend/app/inference/model_stack.py` | `MODEL_CATALOG["anzu-coder-27b"]` `SpecialistModel` (§2a values); only owner in the batch |
| `backend/app/inference/anzu_coder.py` (new) | `VRAM_ESTIMATE_GB`, `vram_requirement_gb`, `reconcile_anzu_coder_profile(*, attempts=10, timeout_s=3.0)`, `last_outcome()` |
| `backend/app/inference/engine_coexistence.py` | Second owner after 0225-S3 (listed in #652's S3 file table): the step-5 requirement lookup consults `anzu_coder.vram_requirement_gb(target)` first, and step 5 records its free-VRAM measurement for `last_free_vram()`; `gate_outlook` (VRAM-aware `refuse`); `hold_request_lease` / `release_request_lease` / `held_leases` counted as request leases in steps 6 and 7; `owner_line(..., speak=True)` keyword (§2a) |
| `backend/app/main.py` | One line: `_start_optional_step("anzu_coder_profile", reconcile_anzu_coder_profile)` plus its import |
| `tests/test_rfc0245_anzu_coder_profile.py` (new) | Below |

Tests (CI: `pytest` job, step "Run full backend suite", `.github/workflows/pr-tests.yml`):
- `test_template_fields_exact`: `default_runtime_profiles()` contains a row equal, field by field, to the §2a table (id, name, label, model, provider, endpoint, context_limit, quantization, privacy_class, cost_ceiling_usd, capability_tags, specialization_tags, model_profile, is_local, description, enabled=False, runtime_role, answer_tier, gguf_path).
- `test_existing_routes_unchanged_when_template_disabled`: `route_runtime` and `prepare_answer_route` give the same result with and without the template, for the leader, orchestrator and tier-2/3/4 answer preference sets.
- `test_enabled_profile_does_not_outrank_expert_for_reasoning_answers`: template enabled, tier-4 reasoning answer route → `expert`.
- `test_reconcile_enables_when_ollama_lists_model` (`anzu-coder-27b:latest` advertised) → `enabled`, row enabled, `auto_enabled_at` written.
- `test_reconcile_not_advertised_leaves_disabled`.
- `test_reconcile_unreachable_retries_bounded`: fake clock, 10 attempts 60 s apart, then `ollama_unreachable`, and `last_outcome() == "ollama_unreachable"`.
- `test_reconcile_respects_owner_row_and_owner_disable`: owner-created `anzu-coder-27b` row → `owner_row`, untouched; template disabled after `auto_enabled_at` → `owner_disabled`, stays disabled.
- `test_reconcile_runs_as_optional_startup_step`: startup reaches `/api/health` without awaiting the probe; the step name is in `startup_health.report()`.
- `test_vram_requirement_12gb_for_coder_only`: `anzu-coder-27b` and `anzu-coder-27b:latest` on Ollama → 12.0; other models → `None`.
- `test_gate_uses_coder_requirement`: with 12.5 GB free and an ANZU-loaded 9B, `prepare_engine_for(<S0 profile>)` takes the gate's unload path (12.0 + 1 GB > 12.5); with 13.5 GB free nothing is unloaded.
- `test_gate_outlook_refuse_for_owner_loaded_9b_managed_off`: LM Studio `127.0.0.1:1234` 9B owner-loaded, `is_managed` false, `last_free_vram()` 8.0 GB recorded 10 s ago → `refuse`; no HTTP or NVML call is made (fakes assert zero calls).
- `test_gate_outlook_allows_when_vram_fits_or_unknown`: same owner-loaded 9B with managed off, but `last_free_vram()` 18.0 GB (24 GB card) → `allow`; reading `None` → `allow`; reading 8.0 GB but 90 s old → `allow`. The preload then runs and the real step-5 gate decides.
- `test_step5_records_last_free_vram`: one gated `prepare_engine_for` with an NVML fake returning 9.5 GB → `last_free_vram().free_gb == 9.5`.
- `test_gate_outlook_resident_and_allow`: target in `anzu_loaded_instances()` → `resident`; ANZU-loaded 9B → `allow`.
- `test_request_lease_blocks_step6_unload`: an ANZU-loaded `anzu-coder-27b` with a held `hold_request_lease` token is not unloaded when a 9B `prepare_engine_for` runs; after `release_request_lease` it is.
- `test_owner_line_speak_false_publishes_event_not_tts`: `owner_line(..., task_id=t, speak=False)` publishes the `engine_notice` task event and the ephemeral frame, and no task `chat_tts`; the default still publishes `chat_tts`.

### S1: Large-prompt detection riders

**Model:** Grok 4.5 · **Lane:** D2 · **Depends:** RFC-0232 S2 (#664: the RE-intent helper `planning.re_intent_match` and its RE floor in `_apply_floors`; hard dependency, S1 does not start before it is merged). Merge order on `owner_turn.py`: #649 → 0218-S3b → 0230-S5 → 0232-S2 → 0245-S1 → 0233-S1 (CoS ruling 2026-10-20).

| File | Change |
| --- | --- |
| `backend/app/decision/large_prompt.py` (new) | `precheck` (total; one call to 0232's `planning.re_intent_match`, then L1-L5 on the raw text and the split-mode rule; no RE detection of its own), `LargePromptPrecheck`, `LargePromptIntent` |
| `backend/app/decision/owner_turn.py` | Total `large_precheck` in `decide_owner_turn` inside the `try`, before the worker is submitted (outside the 50 ms `wait_for`); keyword `large_precheck` on `_decide_sync`, `_deadline_rules_result` and `_apply_floors`, passed at all three `_apply_floors` call sites; candidate and riders in `_decide_sync` (the one `decide()` is unchanged in count); large floor and final gate in `_apply_floors` **after** 0232-S2's RE floor; `large_prompt` field on `OwnerTurnDecision` |
| `backend/app/decision/adapters/rules.py` | Rider branches `large_prompt` and `large_prompt_split`, reading only the scalar keys `large_prompt_floor` and `large_prompt_rules` (0245-S1 only) |
| `backend/app/agent/request_routing.py` | Pass-through of the field (no new decide) |
| `tests/test_rfc0245_large_prompt_decision.py` (new) | Below |

Tests (CI: `pytest` job, step "Run full backend suite", `.github/workflows/pr-tests.yml`). Every test below goes through `decide_owner_turn`, not `rules.decide`:
- `test_path_plus_re_intent_routes_to_re_not_split`: a 4500-char prompt with `D:\cases\x\ffs`, RE dump/extraction intent and 3 questions → route `managed_task` with the RE task class from 0232-S2, `large_prompt is None`, no rider appended, the persona precheck still ran, exactly one `decide`. Same result on the deadline and exception paths (blocking or raising provider). The RE helper is faked at its #664 interface, so this test does not depend on its probe internals. This is 0245's side of 0232-S2's `test_path_plus_re_intent_routes_to_re_before_large_prompt_split` (`tests/test_rfc0232_intent_and_alias.py`).
- `test_plain_path_question_not_routed_to_re`: `C:\code\etl what does the extraction step do?` → not RE; normal routing (no `large_prompt`, since no rule fires), exactly as with the feature off. Same string as #664's named negative (0232 §Detection), through the real helper.
- `test_ffs_word_coding_question_not_routed_to_re`: `C:\Users\taco\proj ffs why does the build fail?` → not RE; normal routing. The same text padded with a 4500-char build log → not RE and `large_prompt.verdict == "large"` (0245 routing). Same string as #664's named negative, through the real helper.
- `test_precheck_outside_allowed_path_makes_no_fs_call`: with the real #664 helper, a 4500-char prompt naming `E:\elsewhere\ffs` (with fake dump markers) outside `allowed_directories` → `os.stat` / `Path.exists` spies record zero calls under that path, not RE, `large_prompt.verdict == "large"`. Repeated with `allowed_directories == []` (empty list admits nothing): same result, nothing stat'd.
- `test_explicit_dump_words_without_dump_target_not_re` (D2's two cases, real #664 helper, paths inside `allowed_directories`): `C:\code\tool what does the forensic image parser do?` and `C:\Users\taco\proj ffs of the tests fail again, why?` → not RE, normal routing, `large_prompt is None`; the second padded to 4500 chars → not RE and `large_prompt.verdict == "large"`.
- `test_precheck_time_not_charged_to_decide_budget`: injected clock; the owner-turn prechecks advance it by 40 ms in total and the provider by 20 ms → `decision_source != "deadline_fallback"`. It also asserts that `started` is taken after the last precheck call, so it stays true once 0233-S1 adds `gap_precheck` before the re-take (0233-S1 extends the fake to both prechecks and keeps this test).
- `test_precheck_within_own_bound`: precheck on a 100 KB paste with a real allowed-path probe stays under `LARGE_PRECHECK_BOUND_MS`; an overrun fake logs one line with the ms and the verdict is still used.
- `test_precheck_exception_keeps_route_and_re_floor`: `planning.re_intent_match` raising (and, separately, a rule raising) → `decide_owner_turn` returns a normal decision with today's route and 0232's RE floor applied, `large_prompt is None`, one log line; it never falls back to `request_routing.py::evaluate_request_route`.
- `test_size_rules_use_full_prompt_not_reflex_projection`: a 5000-char prompt (L1) and a 900-char 5-item list (L2) give `large` through `decide_owner_turn`, although `compact_state` cuts the projection to 800 chars.
- `test_deadline_fallback_keeps_large_verdict_and_full_question`: a provider that blocks past the 50 ms `wait_for` on a 5000-char prompt → `decision_source == "deadline_fallback"`, `large_prompt.verdict == "large"`, `"L1" in large_prompt.rules_fired`, and the `Task` created from it has `len(task.prompt) == 5000`. Same for a provider that raises (exception tail).
- `test_provider_direct_reply_nulls_large_verdict`: provider `direct_reply` at 0.8 on a 4500-char prompt → `large_prompt is None`, decision equal to today's.
- `test_rules_floor_each_rule_fires` (L1-L5, one prompt each).
- `test_short_prompt_no_rider`: no rider appended, and the decision is equal to the decision with the feature disabled.
- `test_short_project_prompt_not_large`: "Make a quick snake game" → `is_large_request` true, `large_prompt is None`.
- `test_precheck_bounded_on_100kb_prompt`: `precheck` on a 100 KB paste finishes under 20 ms (`perf_counter`, generous bound) and does one pass per rule (counted regex calls).
- `test_provider_cannot_lower_large`.
- `test_provider_raises_only_at_075`.
- `test_one_decide_per_turn`: exactly one `decide()` call (counted on the Reflex fake) for a large turn, a path-plus-RE turn and a short turn; the persona precheck runs on all three.
- `test_security_and_literal_excluded`: also social, clarify, self_status and basic_qa shapes.
- `test_questions_mode_from_l3`.
- `test_disabled_is_byte_identical`.

### S2: Workflow seeding on the landed #649 engine, pipeline tables, settings

**Model:** Grok 4.5 · **Lane:** D2 · **Depends:** S1 (merge order only; no code dependency). #649 has landed (`ee786dc`), so there is no draft dependency.

| File | Change |
| --- | --- |
| `backend/app/db/models.py` | Only: `LargePromptPipeline` and `LargePromptSection` (§4 tables), appended after `TaskPromptStep`; the #649 models are untouched |
| `backend/app/agent/task_workflow.py` | Only: append `StepSpec` and `seed_workflow` after `workflow_payload`; every landed #649 function is untouched (second owner after #649) |
| `backend/app/config.py` | Only: `LargePromptSettings` and `AppSettings.large_prompts`, next to `decision` (`config.py`); `large_task_reviews` is #649's and is untouched |
| `backend/app/api/settings.py` | Only: `large_prompts` on the existing GET/PUT, next to #649's `large_task_reviews` |
| `tests/test_rfc0245_prompt_steps.py` (new) | Below |

`agent/loop.py` and `api/tasks.py` are **not** edited by S2. #649's hunks are already there; S4 and S5 own the 0245 hunks in those files.

Tests (CI: `pytest` job, step "Run full backend suite", `.github/workflows/pr-tests.yml`; the landed `tests/test_rfc0224_task_workflow.py` runs in the same step and must stay green):
- `test_seed_workflow_writes_plan_and_steps_in_caller_session`: rows are visible in the same session before commit; `task.plan_json` lists the prompts.
- `test_seed_workflow_idempotent`: a second call writes nothing.
- `test_seed_workflow_bounds`: 0 steps, 13 steps, and a goal over 16000 chars each raise `ValueError`, and no rows are written.
- `test_seeded_child_runs_on_landed_engine_without_planner`: a seeded task runs its stored prompts in order through `loop.py`, and `MANAGER.chat` is never called with `PLAN_SYSTEM`.
- `test_seeded_steps_include_deeper_and_quantitative_and_reviews_toggle`: `large_task_reviews` on gives work, deeper, quantitative, bugfix, fact_check, quality_control; off gives the first three.
- `test_tables_created_on_fresh_db` (`init_db` on an empty DB).
- `test_large_prompts_settings_roundtrip` (GET/PUT, defaults `enabled=True`, `target_runtime="anzu-coder-27b"`, `store="db"`).
- `test_unseeded_large_request_keeps_649_planner`: with no pipeline row, an `is_large_request` prompt still goes through `prepare_workflow` exactly as landed.

### S3: Split, completeness, compile, mandatory sub-tasks, persistence

**Model:** Grok 4.5 · **Lane:** D2 · **Depends:** S2

| File | Change |
| --- | --- |
| `backend/app/agent/large_prompt_intake.py` (new) | split, completeness rounds, repairs, compile, step specs, validators, DB and vault persist |
| `tests/test_rfc0245_large_prompt_intake.py` (new) | Below |
| `tests/fixtures/rfc0245/` (new) | Prompt fixtures: 5-item list, 4 questions, 6000-char spec, dangling-reference section, 12 headings |

Tests (CI: `pytest` job, step "Run full backend suite", `.github/workflows/pr-tests.yml`):
- `test_split_list_sections`.
- `test_split_questions_mode`.
- `test_preamble_and_trailer_shared`.
- `test_max_8_merges_smallest`.
- `test_completeness_repair_merges_dangling`.
- `test_round_bound_sets_needs_owner_with_line`: exactly 3 rounds, then `needs_owner`.
- `test_compile_template_and_6000_cap`.
- `test_every_prompt_has_deeper_and_quantitative`.
- `test_validate_deeper_headings`.
- `test_validate_quantitative_table_numeric_sourced_acceptance`.
- `test_validator_two_retries_then_visible_failure`.
- `test_vault_mirror_create_and_edit`.
- `test_vault_recovery_no_duplicate_create`: a second persist for the same section (recovery re-dispatch, follow-up recompile) never calls `create_note` again and raises nothing.
- `test_vault_summary_appended_not_replaced`: after part terminal the note body is the original prompt body followed by `## Result` and the summary.
- `test_needs_owner_line_is_event_not_speech`: the round-bound line is one `large_prompt` event on the parent and no `chat_tts`.
- `test_vault_owner_edit_conflict_not_forced`.
- `test_vault_failure_keeps_db`.
- `test_large_ingress_blob_ref`.

### S4: Ack, preload, create_task large branch, lease

**Model:** Grok 4.6 · **Lane:** D1 · **Depends:** **S0** (target profile, requirement, `gate_outlook`, leases, `owner_line(speak=)`; hard dependency, S4 does not start before S0 is merged), S1, S2, S3, RFC-0225 S3 (`prepare_engine_for` behind `MANAGER.load(task_id=)`), RFC-0228 S2 (public `NINE_B_REWARM` / `schedule_orchestrator_restore`, `idle_unload_seconds`; `rewarm.py` not edited), RFC-0218 S3b (`create_task` persona block), RFC-0230 S0 (`turn_trace.mark`, `scripts/anzu-latency-repro.ps1`) and S3 (`turn_prewarm.cancel_prewarm`, `register_lease_probe`), RFC-0232 S3/S4 (`loop.py` order)

| File | Change |
| --- | --- |
| `backend/app/agent/large_prompt.py` (new) | `resolve_target` (enabled rows, no-target reason, bounded late reconcile inside the preload task), `preload` (lease, `apply_runtime_profile_to_settings(persist=False)` + `MANAGER.load(task_id=)`, `/api/ps` check, `record_anzu_load`), `_leases` keyed by parent task id (`hold_request_lease` / `release_request_lease`), `release_lease`, `waiting` idle timer (`start_wait_timer` / `cancel_wait_timer`), `active_target()` registered with 0230-S3's `register_lease_probe`, ack texts by outlook, restore |
| `backend/app/agent/loop.py` | Large branch in `create_task` after 0230's prewarm/decision, 0232's RE dispatch, the Task commit and S3b's block (replacing the generic ack for large turns only): pipeline row (the mark), `cancel_prewarm`, `gate_outlook`, one ack with `mark(..., "tts_enqueued", lane="front")`, preload start. In `_run`: for a pipeline parent, skip `_run_managed_front_lane` and the front-off fallback and return into the parent runner **before** `loop.py`, so #649's planner never runs for a pipeline parent |
| `scripts/anzu-latency-repro.ps1` | Append one `--cases tests\fixtures\rfc0245\latency_cases.json` argument (0230-S0's case-file hook) |
| `tests/fixtures/rfc0245/latency_cases.json` (new) | Three large typed turns built from the S3 fixtures (5-item list, 4 questions, 6000-char spec) |
| `tests/test_rfc0245_ack_preload.py` (new) | Below |
| `tests/test_rfc0245_engine_modes.py` (new) | The two S4 engine-mode tests below, plus S5's `test_engine_mode_reflex_only_parks_recovered_pipeline` (S5 adds that test to this file) |

Tests (CI: `pytest` job, step "Run full backend suite", `.github/workflows/pr-tests.yml`):
- `test_ack_chat_tts_within_150ms_of_decision`: `BUS.publish` timestamped, preload fake blocks for 5 s, assert ≤ 150 ms.
- `test_ack_not_delayed_by_split`: split fake blocks for 5 s; the ack is still ≤ 150 ms and the split starts after the ack event.
- `test_parent_speaks_exactly_one_line_before_part_results`: a 3-part pipeline with the front lane enabled → exactly one `chat_tts` on the parent before its terminal outcome (the ack); no `_run_managed_front_lane` call, no front-off fallback `chat_tts`, no `publish_owner_text`; part, gate and needs_owner lines are events only.
- `test_ack_marked_on_front_lane`: one `tts_enqueued` mark with `lane="front"` and `source="large_prompt_ack"` on the turn trace.
- `test_large_verdict_does_not_prewarm_9b`: with an unloaded 9B and outlook `allow`, `cancel_prewarm` is called and no 9B `prepare_engine_for` is issued by the prewarm.
- `test_ack_variant_when_gate_will_refuse`: Taco's default (LM Studio 9B owner-loaded, managed off) **and** `last_free_vram()` 8.0 GB recorded 10 s earlier → the `refuse` text, which contains no "load"; no preload started; one event naming the managed-mode toggle; the parts run on the 9B and the parent completes.
- `test_taco_default_without_reading_allows_then_gate_refuses`: the same setup with no VRAM reading → `allow` ack, preload starts, the real step-5 gate refuses → `gate_refused:<reason>`, lease released, the parts run on the 9B, nothing unloaded, parent `completed`.
- `test_ack_never_claims_load`: no ack constant contains "loading", and the `resident` text is used only when `gate_outlook` returns `resident`.
- `test_gate_refuses_runs_on_loaded_9b_without_failing`: real step-5 refusal after outlook `allow` → lease released, `preload_status` `gate_refused:<reason>`, owner line with `speak=False`, the parts run on the current model, parent `completed`.
- `test_never_unloads_model_anzu_did_not_load`: owner-loaded 9B and owner-loaded 27B through a whole pipeline and its restore → zero unload calls and no `keep_alive` change for either.
- `test_ack_never_uses_publish_owner_text`.
- `test_ack_title_not_speak_reply`.
- `test_0218_ack_after_persona_switched_still_under_50ms`.
- `test_preload_started_not_awaited`.
- `test_target_resolution_order`, using RFC-0228's `settings_lmstudio_9b.json` fixture plus the S0 `recommended-anzu-coder-27b` row: enabled → it is the target; disabled → step 2 (`route_runtime`); absent → step 2.
- `test_no_target_event_names_reconcile_outcome`: `ollama_unreachable` → "Ollama isn't running…"; `not_advertised` → "Ollama doesn't list anzu-coder-27b…".
- `test_late_ollama_start_enables_on_next_large_turn`: startup ended `ollama_unreachable`; Ollama now lists the model → the preload task's one bounded reconcile (≤ 3 s, fake clock) enables the row and the preload targets it; the ack path made no probe.
- `test_preload_ollama_anzu_loaded_recorded`: `/api/ps` without the model → warm with `keep_alive "900s"` (RFC-0228's `idle_unload_seconds`, never `-1`) → listed → exactly one `record_anzu_load("ollama@127.0.0.1:11434", "anzu-coder-27b")`, `preload_status == "loaded"`.
- `test_preload_ollama_owner_loaded_not_recorded`: `/api/ps` already lists it → no warm call, no `record_anzu_load`, `preload_status == "already_loaded"`.
- `test_preload_loads_through_manager_with_task_id`: the preload calls `apply_runtime_profile_to_settings(target, persist=False)` and `MANAGER.load(..., task_id=parent)` once each, which reach `prepare_engine_for` once; `save_settings` is never called and no `hotswap.py` function other than `apply_runtime_profile_to_settings` is called; `hotswap.py` is unchanged by this RFC (the S4 diff has no hunk in it).
- `test_preload_never_persists_selection`: `settings.json` is byte-identical before and after preload and through the whole pipeline.
- `test_owner_selection_restored_after_pipeline`: after the parent completes, `MANAGER.state` is the owner's saved selection again; no `keep_alive` call is sent at release.
- `test_restore_with_settings_merge`: the owner saves a different model mid-pipeline through settings (`_merge_settings_changes`) → nothing is restored over it.
- `test_target_held_across_parts`: between part 1 and 2 (and with a 2 s gap), neither RFC-0225 step 6 nor a `NINE_B_REWARM` fire (driven through its public `schedule`) unloads the target; the lease is held while the parent is `running`.
- `test_waiting_releases_anzu_loaded_27b_after_idle_unload_seconds`: parent enters `waiting` with an ANZU-loaded target; at 899 fake seconds the lease is held; one `keep_alive` refresh at 450 s and none after release; at 900 s the lease is released, `preload_status == "released:waiting_idle"`, and a 9B `prepare_engine_for` then takes step 6's unload path; `/continue` afterwards re-preloads before the next dispatch. `/continue` at 600 s cancels the timer and dispatches without a reload.
- `test_long_tool_step_keeps_target_resident`: a fake 30-minute tool step inside a running part with an ANZU-loaded target → `keep_alive` refreshes at 450 s intervals, the target stays in `/api/ps`, and no `NINE_B_REWARM` reload fires.
- `test_no_unload_reload_churn_while_leased`: across a 3-part pipeline with gaps and one long tool step, zero 27B unloads and zero 9B reloads happen until the lease is released; refreshes stop at release; an owner-loaded target gets no refresh.
- `test_preload_does_not_rebind_owner_conversations`: `rebind_owner_conversations_after_hotswap` is never called by the preload; owner conversations keep the saved selection's context limit.
- `test_waiting_never_touches_owner_loaded_target`: same with an owner-loaded 27B (`already_loaded`) → at 900 s the lease is released and zero unload or `keep_alive` calls are made.
- `test_chat_turn_prewarm_skips_while_lease_held`: with a pipeline holding its lease, a chat turn's 0230-S3 `prewarm_worker("turn")` sees `large_prompt.active_target()` through `register_lease_probe` and issues no `prepare_engine_for` (neither 9B nor 27B); after parent terminal the same turn prewarms as usual.
- `test_chat_turn_between_parts_does_not_unload_target`: a chat turn between two parts is answered on the loaded target and the target stays resident.
- `test_chat_turn_during_pipeline_routes_to_target`: `prepare_answer_route` for a concurrent chat turn uses the target, and the front lane still speaks first.
- `test_resume_after_keep_alive_expiry_repreloads`: target no longer in `/api/ps` when the owner sends `/continue` (and on `recover_on_startup`) → `preload` runs again before the next dispatch.
- `test_preload_timeout_180s_fallback`, with a fake clock.
- `test_orchestrator_restore_only_at_parent_terminal`: no `schedule_orchestrator_restore` call while the parent is `running` or `waiting`; exactly one at terminal.
- `test_lease_tracked_by_task_id_public_api_only`: `_leases[parent]` holds the token from `hold_request_lease`; `release_lease(parent)` calls `release_request_lease` once; the S4 diff has no hunk in `hotswap.py` or `rewarm.py`.
- `test_649_planner_not_called_for_pipeline_parent_or_child`: `MANAGER.chat` is never called with `PLAN_SYSTEM` for a parent (marked by its pipeline row) or a seeded child.
- `test_649_planner_unchanged_when_large_prompts_disabled`: with `large_prompts.enabled=false`, a 4000-char prompt goes through `prepare_workflow` exactly as landed.
- `test_engine_mode_reflex_only_runs_no_pipeline_no_preload_no_ack` (`tests/test_rfc0245_engine_modes.py`): settings with `engine_mode == "reflex_only"` and a 5000-char three-question prompt → `decide_owner_turn` returns `large_prompt is None` with no rider and zero calls to `planning.re_intent_match` from the precheck; `create_task` writes no `large_prompt_pipelines` row and calls none of `gate_outlook`, `large_prompt.preload`, `hold_request_lease`; zero `acknowledgement` events and zero `chat_tts` from 0245; `MANAGER.load` is never called; `_run` ends in RFC-0244's `reflex_only_reply`. With `large_prompts.enabled=true` and the target enabled, so the only reason nothing happens is the mode.
- `test_engine_mode_model_only_runs_pipeline_without_jev_laya` (same file): `engine_mode == "model_only"`, fake Reflex providers that count calls → zero JEV and Laya calls; the same 5000-char prompt gives `large_prompt.verdict == "large"` from rules (`"L1" in rules_fired`, `decision_source` is the rules source); a 700-char prompt that a provider fake would raise to `large` at confidence 0.8 stays `None`; a pipeline row is created, exactly one ack is spoken on the parent's front lane, the preload starts and the first child is dispatched. Run again with `engine_mode == "hybrid"` for the same 5000-char prompt: identical pipeline outcome (the mode changes only who decides).

**Live audit** (on Taco's PC; numbers recorded in the PR, none invented in advance): the three large-turn cases in `scripts/anzu-latency-repro.ps1` against RFC-0230's ≤ 1.5 s p50 / ≤ 2.0 s p95 first audible word; once with managed mode off (expected: the `refuse` ack when a fresh free-VRAM reading exists, otherwise the `allow` ack followed by `gate_refused`; either way parts on the LM Studio 9B and nothing unloaded; record which happened) and once with it on (gate unload path, 27B used, 9B restored after the pipeline); which gate path ran in each.

### S5: Sequential queue, lifecycle, follow-ups, recovery

**Model:** Grok 4.6 · **Lane:** D1 · **Depends:** S4

| File | Change |
| --- | --- |
| `backend/app/agent/large_prompt_queue.py` (new) | `is_pipeline_parent`, `dispatch_next` (breaker admit + bind), `on_child_terminal` (cancelled-pipeline check first), `on_parent_cancel`, `on_child_cancel_api`, `bind_loop` (captures the main loop), `request_parent_cancel` (sync; sets `cancelling`, hands `on_parent_cancel` to the loop thread-safely, or before `bind_loop` only sets the flag and logs, never raises), parent completion, `payload`, `recover_on_startup` (lease, re-preload; honours `cancelling`) |
| `backend/app/agent/loop.py` | `pipeline_section` keyword in `create_task`; child path in `_run` (no front lane, seeded workflow, target profile); validator gate for `deeper` / `quantitative` steps before `workflow.finish_current` and before the final completion of the last stored step (S3 validators, 2 retries, then `_fail_task` with the S3 text); terminal hook call (`AgentRuntime._update`); cancel hook: one added call `large_prompt_queue.request_parent_cancel(task_id)` inside the sync `AGENT.cancel`; `/continue` redirect (`AgentRuntime.continue_task`) and parent follow-up with re-preload |
| `backend/app/api/tasks.py` | `large_prompt` payload in `get_task` and `get_task_observability`; `cancel_task` routes pipeline children through `large_prompt_queue.on_child_cancel_api` |
| `backend/app/main.py` | Two startup lines, in this order: `large_prompt_queue.bind_loop(asyncio.get_running_loop())`, then `await large_prompt_queue.recover_on_startup()` |
| `tests/test_rfc0245_large_prompt_queue.py` (new) | Below |

Tests (CI: `pytest` job, step "Run full backend suite", `.github/workflows/pr-tests.yml`):
- `test_parts_run_strictly_sequential`: part 2 is created only after part 1 is terminal.
- `test_child_ids_stable_uuid5`.
- `test_breaker_admission_and_kill_switch_stops`.
- `test_breaker_run_bound_to_child`: every admitted run is bound with `bind_run_to_task` to its child; 8 completed parts in a row never trip the breaker or exhaust its budget.
- `test_child_no_decide_no_persona_no_ack_no_speech`.
- `test_failed_part_fails_parent_with_text`.
- `test_child_cancel_skips_part`.
- `test_parent_cancel_cancels_child_and_rest`: after `POST /api/tasks/{parent}/cancel` the running child's terminal hook sees the cancelled pipeline; no further `create_task`, every remaining section `cancelled`, lease and `waiting` timer released.
- `test_cancel_endpoint_awaits_parent_cancel_before_sync_cancel`: call order is `await on_parent_cancel(parent)` then the sync `AGENT.cancel(parent)`; `AGENT.cancel` stays a plain function (`inspect.iscoroutinefunction` is false).
- `test_startup_binds_loop_before_recovery`: the startup sequence calls `bind_loop` with the running loop before `recover_on_startup`; a cancel issued from a worker thread right after startup reaches `on_parent_cancel` on that loop.
- `test_request_parent_cancel_before_bind_loop_stops_dispatch`: no loop bound; `request_parent_cancel(parent)` returns without raising, sets `cancelling` and logs one `cancel_before_bind` line; the next `dispatch_next` dispatches nothing and marks the pipeline `cancelled`; `recover_on_startup` on a `running` pipeline with the flag set does the same.
- `test_sync_cancel_after_runner_returned_stops_pipeline`: parent `running`, runner already returned, a child running; sync `AGENT.cancel(parent)` from the loop thread → `on_parent_cancel` runs once, zero further `create_task`, every remaining section `cancelled`, lease released; the endpoint afterwards is a no-op.
- `test_cancel_from_realtime_voice_stop_reaches_pipeline` (`mobile/realtime_voice.py::interrupt_turn`, called from a worker thread via `run_coroutine_threadsafe`).
- `test_cancel_from_media_reaches_pipeline` (`mobile/media.py::VoiceBridge.accept_audio`).
- `test_cancel_from_self_dev_reaches_pipeline` (`agent/self_dev.py::activate_kill_switch`).
- `test_cancel_from_live_agent_suite_reaches_pipeline` (`inference/live_agent_suite.py::_run_live_suite`).
  Each of the four: same assertions as above, and the child's `CancelledError` hook running before `on_parent_cancel` takes the lock still dispatches nothing (the `cancelling` flag).
- `test_continue_sets_waiting_back_to_running`: a `needs_owner` part answered via `/continue` and re-checked `complete` → pipeline `waiting → running`, the `waiting` timer cancelled, the part dispatched.
- `test_recovery_of_preparing_reruns_intake_once`: a pipeline left in `preparing` at restart → intake re-runs, sections are not duplicated (unique ordinal), preload runs, status `running` after the first dispatch.
- `test_every_status_has_setter_and_reader`: walks the §5 *Statuses* table.
- `test_cancel_queued_child_advances`: `POST /api/tasks/{child}/cancel` on a queued child with no runner marks the part `skipped` and dispatches the next one.
- `test_needs_owner_waits_then_continue_one_round`.
- `test_skip_part_n`.
- `test_followup_appends_part_dedupe`.
- `test_continue_on_child_redirects`.
- `test_parent_combined_result_and_verification`.
- `test_restore_after_parent_terminal`.
- `test_recovery_redispatch_advance_resume`: also re-takes the lease and re-preloads a non-resident target.
- `test_large_prompt_payload`: same object on `GET /api/tasks/{id}` and `/observability`.
- `test_validator_gate_retries_stored_step_then_fails_visibly`: a quantitative step whose result has no numeric row is retried twice with the validator message, then the child fails with "Part n of N: quantitative sub-task did not meet its format after 3 attempts", and `finish_current` is never called for it.
- `test_engine_mode_reflex_only_parks_recovered_pipeline` (`tests/test_rfc0245_engine_modes.py`): a pipeline with part 2 pending at restart and a `/continue` on a `needs_owner` parent, both under `engine_mode == "reflex_only"` → no `large_prompt.preload`, no `dispatch_next`, no `create_task` for a child, one non-spoken parent event naming Reflex only, parent status unchanged (not failed, lease not taken); then the mode set to `hybrid` and `/continue` → `preload` runs and part 2 dispatches. A child already running when the mode changes is not cancelled (RFC-0244: mode applies at request entry).

### S6: Large-prompt sections in the live "Saved plan" block

**Model:** Composer 2.5 · **Lane:** UX · **Depends:** S5, RFC-0230 S0 and RFC-0218 S3 (sequential owners of `api.ts`)

| File | Change |
| --- | --- |
| `frontend/src/components/largePromptSectionsView.ts` (new) | Pure view model (§6): rows, chips, actions with method and path, child line, status line |
| `frontend/src/components/LargePromptSections.tsx` (new) | Thin render of the view model |
| `frontend/src/components/TaskActivity.tsx` | Add-only: the `||` in the `TaskActivityPanel` condition and one mount after the existing `<ol>` (§6). The landed rows are otherwise byte-identical |
| `frontend/src/taskStatus.ts` | Add-only: `large_prompt` in `mergeObservability` and in the `TaskObservability` field list |
| `frontend/src/api.ts` | Add-only `LargePromptPayload` and `Task.large_prompt?` / `TaskObservability.large_prompt?` |
| `frontend/large-prompt-sections.test.mjs` (new) | Imports only `.ts`: view-model rows, chips, button→endpoint mapping, child line, `null` without payload, `humanizeToken` labels for `deeper`/`quantitative`, and `mergeObservability` preserving `large_prompt` and every existing field |
| `frontend/package.json` | Append `test:large-prompt-sections` (`node --experimental-strip-types large-prompt-sections.test.mjs`) |
| `.github/workflows/pr-tests.yml` | Append the step `Large prompt sections tests (RFC-0245 S6)` → `npm run test:large-prompt-sections` after "Persona morph hook tests (RFC-0218 S5)" in `frontend-build`. The existing "Build frontend" step (`npm run build`) is the TSX gate |

## Ownership chains (handoff order on shared files)

On `loop.py` and `owner_turn.py` the order is RFC-0230 (#666), then RFC-0232 (#664), then RFC-0245 (CoS ruling 2026-10-20), matching #664 (RFC-0232; final head in this PR's body) and #666 (RFC-0230, landed as `94a62fa0`; `docs/rfcs/0230-pc-first-response-latency.md` on `development`). The 0245 tickets merge onto whichever of those has landed, with merge commits.

| File | Order |
| --- | --- |
| `backend/app/agent/loop.py` | #649 (landed) → 0218-S3b → 0230-S0 → 0230-S2 → 0230-S3 → 0232-S3 → 0232-S4 → 0232-S5 → 0245-S4 → 0245-S5 → 0233-S3 → 0233-S4 (#668; #670, RFC-0211, does not edit `loop.py`). In `create_task`: 0230's `prewarm_worker` and route decision, then 0232's RE dispatch (S3 FFS, S5 APK), then 0245's large branch |
| `backend/app/decision/owner_turn.py` | #649 (landed) → 0218-S3b (not landed) → 0230-S5 → 0232-S2 → 0245-S1 → 0233-S1 (#668) |
| `backend/app/decision/adapters/rules.py` | 0245-S1 → 0233-S1 (#668; `capability_gap` rider branch) |
| `backend/app/agent/request_routing.py` | 0245-S1 → 0233-S1 (#668 (RFC-0233; final head in this PR's body); pass-through of the new field only; 0230 and 0232 do not edit it) |
| `backend/app/agent/large_prompt_queue.py` | 0245-S5 (creates it) → 0233-S4 (#668 (RFC-0233; final head in this PR's body); `dispatch_next` waits on the capability queue and the part-ask hooks) |
| `backend/app/config.py` | #649 (landed) → 0228-S1 → 0228-S2 → 0245-S2 → 0233-S1 (#668) → #670 (RFC-0211, supersedes #585; draft, merges `development` in when it is picked up, never rebases) |
| `backend/app/main.py` | 0225-S2 → 0225-S3 → 0230-S0 → 0230-S5 → 0245-S0 → 0245-S5 → 0233-S4 (#668) → #670 (RFC-0211, supersedes #585; draft, same rule). RFC-0225 goes first on `main.py` (CoS) |
| `backend/app/api/tasks.py` | #649 (landed) → 0245-S5 → 0233-S3 → 0233-S4 (#668) |
| `backend/app/inference/hotswap.py` | 0225-S3 only (#652 (RFC-0225; final head in this PR's body), #655 (RFC-0228; final head in this PR's body)). 0245 does not edit it: the preload calls the existing `apply_runtime_profile_to_settings(persist=False)` and `MANAGER.load` |
| `backend/app/inference/engine_coexistence.py` | 0225-S3 (creates it) → 0245-S0 (#652 S3 file table names the second owner) |
| `backend/app/inference/rewarm.py` | 0228-S2 only (#655, RFC-0228; final head in this PR's body). 0245 uses `NINE_B_REWARM` / `schedule_orchestrator_restore` through their public API and does not edit it |
| `backend/app/inference/model_stack.py`, `backend/app/inference/anzu_coder.py` | 0245-S0 only |
| `backend/app/db/models.py` | #649 (landed) → 0245-S2 → 0233-S3 (#668) |
| `backend/app/agent/task_workflow.py` | #649 (landed, created it) → 0245-S2 |
| `backend/app/api/settings.py` | #649 (landed) → 0245-S2 → 0233-S1 (#668) |
| `scripts/anzu-latency-repro.ps1`, `scripts/latency_repro.py` | 0230-S0 (creates them) → 0245-S4 (append-only: one `--cases` argument) |
| `frontend/src/api.ts` | 0230-S0 → 0218-S3 → 0227 → 0245-S6 → 0233-S6 |
| `frontend/src/taskStatus.ts`, `frontend/src/components/TaskActivity.tsx` | #649 (landed) → 0245-S6 |
| `frontend/package.json`, `.github/workflows/pr-tests.yml` | **Append-only.** The Architect owns the workflow file. Rule: each ticket appends its own step, never edits another's, and on a conflict merges `development` with a merge commit and keeps both steps |

## Ticket cards

| ID | Title | Model | Lane | Depends |
| --- | --- | --- | --- | --- |
| 0245-S0 | `anzu-coder-27b` profile, VRAM requirement, reconcile, gate outlook, leases | Grok 4.5 | D1 | 0225-S3 |
| 0245-S1 | Large-prompt detection riders (full-prompt precheck, RE precedence) | Grok 4.5 | D2 | **0232-S2** (merge order after 0230-S5) |
| 0245-S2 | Workflow seeding on landed #649, pipeline tables, settings | Grok 4.5 | D2 | S1 (order) |
| 0245-S3 | Split, completeness, compile, sub-tasks, persistence | Grok 4.5 | D2 | S2 |
| 0245-S4 | Ack, preload, create_task branch, lease | Grok 4.6 | D1 | **S0**, S1-S3, 0225-S3, 0228-S2, 0218-S3b, 0230-S0/S3, 0232-S3/S4 |
| 0245-S5 | Sequential queue, lifecycle, recovery | Grok 4.6 | D1 | S4 |
| 0245-S6 | Large-prompt sections in the live "Saved plan" block | Composer 2.5 | UX | S5, 0230-S0, 0218-S3 |

All seven run with fast mode off.

## Overall acceptance

- [ ] A large spoken or typed prompt gets exactly one spoken ack on the parent's front lane, persisted ≤ 150 ms after the decision (CI) and held to RFC-0230's ≤ 1.5 s p50 / ≤ 2.0 s p95 first audible word (live audit), worded from the RFC-0225 gate outlook so it never claims a load the gate did not allow.
- [ ] A path plus RE intent goes to reverse engineering and is never split; a path with a plain or coding question routes normally.
- [ ] Size detection uses the full prompt, also on the deadline and exception fallbacks.
- [ ] The prompt is split, every section is complete or explicitly `needs_owner` within 3 rounds, and each section becomes one detailed prompt stored in SQLite (and idempotently in the vault when enabled).
- [ ] The parts run strictly one after another on a target that nothing unloads until the parent is terminal; the large-task load is never saved as the owner's selection, and the owner's selection is back afterwards.
- [ ] On Taco's default (LM Studio 9B owner-loaded, managed mode off, 16 GB) the parts run on the 9B with an honest ack and the task completes; nothing ANZU did not load is unloaded.
- [ ] Every part has validated deeper and quantitative sub-tasks, and the parent shows progress, can be cancelled, and ends with a combined, verified result.
- [ ] With `large_prompts.enabled=false`, behaviour is identical to today, including #649's planner.
- [ ] RFC-0244 engine modes: under `reflex_only` a large prompt starts no pipeline, preload or ack and gets RFC-0244's model-required reply; under `model_only` the pipeline runs with a rules-only precheck and no JEV or Laya call (named tests in S4/S5).
- [ ] On Taco's PC (Ollama lists `anzu-coder-27b:latest`), the S0 profile is enabled at startup and is the preload target; on an install without it, the template stays disabled and routing is unchanged.

## Out of scope

- Persona, presence, WebGL, morph and voice choice (Astra).
- Merging `agent/intake.py` with this pipeline.
- Parallel execution of parts.
- A settings UI for `large_prompts`.
- Changing `stream_owner_chat`.
- The #670 scheduler itself.

## Risks

- **27B load time over 180 s on a cold disk.** Mitigation: defined fallback plus owner line. The deadline is a module constant, so it is tunable after the live audit.
- **Deterministic split mis-sections free prose.** Mitigation: completeness repairs and the owner `needs_owner` loop. N == 1 is always valid.
- **The quantitative format feels forced on qualitative parts.** Mitigation: the "Measurable criteria" row keeps the format honest without inventing numbers.
- **Collisions in `loop.py`.** Mitigation: the strict ownership chain above, with two 0245 slices (S4, S5) in sequence after landed #649.
