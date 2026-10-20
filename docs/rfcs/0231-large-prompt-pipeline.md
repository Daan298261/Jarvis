# RFC-0231: Large-prompt pipeline (reflex detect, immediate large-model load, spoken ack, split, completeness, durable sequential prompts)

**Status:** accepted
**Priority:** P1 (Taco ask B, relayed by Chief of Staff 2026-10-20)
**Author:** Jarvis Architect
**Date:** 2026-10-20
**Traced on:** `development` @ `11b264a7`. Drafts and RFC PRs pinned: #649 @ `edb4685` (identical to `b5c3640` for every file cited here), #652 (RFC-0225) @ `140482b`, #655 (RFC-0228) @ `973b979`, #585 (RFC-0211) @ `f412dad`, #663 (RFC-0218 delivery fix) @ `c5db314`.
**Amended 2026-10-20 (#649 landed):** #649 merged into `development` as `ee786dc`, so S2 no longer ports it. S2 now cites the landed engine and adds only what #649 lacks: `seed_workflow`, the two pipeline tables, and `LargePromptSettings`. Every #649 reference in §4-§6 and S1-S6 is re-traced on `development` @ `d85c9d4`, and so is every `loop.py`, `owner_turn.py`, `api/tasks.py` and `App.tsx` line number (#648 and #649 shifted them).
**Amended 2026-10-20 (cross-citation pass):** #664 re-cited at `df37b22` with its final helper `planning.re_intent_match(prompt, *, allowed=None) -> ReIntent | None` (cached per turn) and probe `planning.probe_dump_target`; 0218-S3b (not landed) added to the `owner_turn.py` chain.
**Amended 2026-10-20 (UX peer, 17 blockers at `8d713f0`; CoS rulings 1-6; D2 + CoS floor change):** RFC-0232 precedence (verbatim CoS text, §1) with 0232's RE helper consumed in the precheck and its RE floor in `_apply_floors`, one `decide()` per turn; size rules on the full prompt, outside the 50 ms window, also on deadline/exception fallbacks; candidate from the baseline route plus the final gate after floors; #649's planner skipped for a marked parent; one spoken ack on the parent's front lane, worded from the RFC-0225 gate outlook and never claiming a load; Taco's default (LM Studio 9B owner-loaded, managed off, 16 GB) runs the parts on the 9B; request lease holds the target for the whole parent, and the large-task load is never persisted, with the owner's selection restored; breaker bind, cancel races, idempotent vault, L4 length floor, S0 outlook/lease/late-reconcile; S6 extends the live "Saved plan" rows; complete ownership chains with lanes. Re-traced on `development` @ `3007696` (`d85c9d4` plus #660, #667 and #662; only `pr-tests.yml` lines moved: "Build frontend" L118-119, "Persona morph hook tests" L130). Cross-checked with #666 @ `2819851`, #664 @ `df37b22`, #652 @ `aac2f5c`.
**Amended 2026-10-20 (CoS, #665 peer):** the large target `anzu-coder-27b` was assumed to exist as a runtime profile. It does not (see *Target profile: `anzu-coder-27b`*), so new slice **0231-S0** adds it and 0231-S4 hard-depends on it. Re-traced for S0 and for the `hotswap.py`, `config.py` and `main.py` citations on `development` @ `d214b6d` (#648 landed; #663 landed at `781004c`), #652 @ `916cf25`, #655 @ `971ca15`, #649 @ `edb4685`.

**Owner ask (Taco, ask B, intent as relayed):** when Taco speaks or types a large or complex task, Jev/Laya decide that it is complex. Then:
1. ANZU immediately loads the large model (anzu-coder-27b or whichever large model applies). `anzu-coder-27b` is the 0231-S0 runtime profile.
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
- [RFC-0211](0211-ollama-self-development-scheduler.md) (#585 draft): the scheduler.
- [RFC-0071](0071-automation-failure-circuit-breaker.md): breaker admission.

Some of these links point at RFC files that live only on their open PRs. They resolve once those PRs land.

**#649 and #585:** #649 has landed and S2 builds on it (see *Relationship to #649 and #585*). #585 is still a draft and does not gate this RFC.

**Astra boundary:** persona, WebGL, presence, morph and appearance are out of scope (Astra). This RFC emits no persona events and edits no persona or presence component.

This PR is **specs-only**. It contains no application code.

---

## Problem

Verified on `development` @ `11b264a7`.

1. **"Large" is not a decision.** The single owner-turn decide (`decision/owner_turn.py::decide_owner_turn` L537-630 on `development` @ `d85c9d4`, via `agent/request_routing.py::evaluate_request_route`) yields route, tier and `persona_intent` (`OwnerTurnDecision` L145-158). Nothing decides "this prompt is a multi-part large task". The only related signals are:
   - `policy.local_complexity_tier` (`decision/policy.py:25`): tier 4 for expert hints or more than 4000 chars, tier 3 for complex hints or more than 1200 chars.
   - The separate `complexity_escalation` surface (`decision/surfaces.py:360-380`).
   - #649's regex `is_large_request` (`agent/task_workflow.py:31-37`, landed), which is not a reflex decision. It only triggers #649's model planner inside `_run` (`loop.py:2686-2707`).
2. **No immediate load of the large model.** `prepare_answer_route` only runs when the loaded model is an orchestrator, or tier ≤ 1 (`agent/loop.py:2475-2495`), and it runs inside `_run`, after the front lane. A large prompt starts on whatever model is loaded. The swap to the large model happens later, if it happens at all, through `execute_visible_model_switch` (`inference/model_escalation.py:128-203`).
3. **No large-task ack.** `create_task` publishes the generic `task_acknowledgement(prompt)` as an `acknowledgement` event (`loop.py:548-557`), and it is not spoken. As #663 found, `publish_owner_text` goes to `OWNER_CHAT_CHANNEL` (`persona/chat_delivery.py:71`, `:100`), and no client reads that channel. The only path the live UI speaks is a `chat_tts` event on the task stream: `useTaskSpeech.ts:41-56` → `queueChatSpeech`, mounted in HUD chat and Chat.
4. **The prompt is split only for a dead endpoint.** `agent/intake.py` has a sequential chain:
   - `MAX_SEQUENTIAL_PARTS = 8`, `part_prompt` L235-247, `advance_chain` L281-313.
   - Chains are stored as JSON files under `data/intake_chains`.
   - Its only caller is `persona/owner_chat.py:379-410`, the `stream_owner_chat` endpoint, which has no client.
   - Chat sends go to `/api/tasks`. Since #649, `_run` asks the loaded model for a 1-8 step plan when `is_large_request` fires (`loop.py:2686-2707`, `task_workflow.py:115-169`). That plan is model-generated, so it isn't a split of the owner's text. It runs on whatever model is loaded, with no completeness check, and a planner failure fails the task (`task_workflow.py:151-152`).
5. **No completeness check.** No section-level check or bounded iteration exists anywhere.
6. **Durable prompt stages exist (landed #649), but only one task at a time.** `TaskPromptPlan` / `TaskPromptStep` (`db/models.py:66-88`) are executed one stored prompt at a time inside one task (`loop.py:2709-2722`, `:2969-2984`, `:3639-3660`, completion guard `:776-788`). Its planner asks the model for the plan (`PLAN_SYSTEM`, `task_workflow.py:20-28`), which needs a capable model already loaded. It has no notion of a parent with one child task per section, no section completeness, and no mandatory deeper/quantitative steps.
7. **No queue that runs owner prompts one after another.**
   - `mobile/scheduler.py::tick` (L77-121) runs periodic automations. It skips while the previous run is non-terminal (L88-94) and is admitted by `automation/breaker.admit_automatic_trigger` (L236-320).
   - `agent/queue_watcher.py` is a file drop queue.
   - #585's `DevelopmentScheduler` (L132, tick L380-411) is a draft and reserves Ollama for Grokbot work.
   - None of them takes N owner sub-prompts and runs them in order.
8. **No guaranteed deeper or quantitative work.** #649's steps are `work` plus `REVIEW_STEPS` (bugfix, fact_check, quality_control; #649 `task_workflow.py:15-19`). Nothing requires a deeper-analysis or quantitative sub-task, and nothing validates one.

## Decision

Ship **one RFC with seven implement slices (S0-S6)**, one named model per slice and fast mode off. Nothing waits for #585. #649 has landed and is reused.

**Pipeline at a glance.** A large owner turn becomes one **parent task** (the one the HUD is already following) and N **child tasks**, one per section, run strictly one after another.

```
owner turn ─► decide_owner_turn: large-prompt precheck on the FULL raw prompt (outside the 50 ms window)
   │           ─► _decide_sync: one decide (riders large_prompt / large_prompt_split only when 0232's RE helper did not match)
   │           ─► _apply_floors: 0232 RE floor, then 0231 large floor
   │ large (and not RE)
   ├─► create_task: 0230 prewarm_worker + route decision ─► 0232 RE dispatch (not taken) ─► Task row ─► 0218 S3b persona block
   ├─► 0231 large branch: cancel 0230's pending 9B prewarm; read the RFC-0225 gate outlook (in memory, no probe)
   ├─► ONE spoken ack on the front lane (_speak_front_reply, lane "front", 0230-S0 marks), worded from the gate outlook
   ├─► preload task started (not awaited), only when the outlook allows: request lease → activate_runtime_profile(persist=False) → warm
   └─► parent runner (after the ack): split → completeness rounds (≤ 3) → compile → persist → await preload (≤ 180 s, defined fallback)
          → dispatch part 1 as a child task (breaker admit + bind)
child terminal hook ─► completed: dispatch next │ failed: stop, parent fails visibly │ needs_owner: parent waits (lease kept)
last part done ─► parent completes with the combined result ─► release lease ─► restore the owner's saved selection ─► release rewarm hold
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

**Precedence (CoS ruling, normative, verbatim):** A turn whose prompt contains an absolute filesystem path together with RE intent (RFC-0232's narrowed dump/extraction detection) routes to reverse engineering and is never split by RFC-0231; a path with a plain or coding question routes normally.

Mechanically (D2 + CoS ruling 2026-10-20): RFC-0232 S2's precedence is a **floor in `_apply_floors`** (`owner_turn.py:296-370` on `d85c9d4`), not an early return. Every turn keeps the persona precheck (L448) and **exactly one `decide()`**. RE intent is decided only by RFC-0232 S2's helper `planning.re_intent_match(prompt, *, allowed=None) -> ReIntent | None` (cached per turn), whose two-stage detection (a wording/path prefilter, then the on-disk probe `planning.probe_dump_target`) is specified in #664 @ `df37b22` and is not restated or re-implemented here. 0231 consumes its result in two places:
- **Precheck:** `large_prompt.precheck` calls `planning.re_intent_match(text)` once on the raw text (the per-turn cache means 0232's own floor reuses the same result) (outside the 50 ms window, so the dump probe never eats the decide budget) and stores `re_match`. When it matches there is **no candidate**: no rider is appended to the one `decide()`, and `large_prompt_floor` is not set.
- **Floors and fallbacks:** in `_apply_floors`, 0232's RE floor runs first and 0231's large-prompt floor after it; when the RE floor applied, `large_prompt` stays `None`. `_with_deadline_large_prompt` on the deadline and exception paths returns `large_prompt=None` when `precheck.re_match` is set.

RFC-0232 S2 owns the RE-side test `test_path_plus_re_intent_routes_to_re_before_large_prompt_split` (`tests/test_rfc0232_intent_and_alias.py`). 0231-S1 adds its side of the contract (S1 tests), and `test_one_decide_per_turn` (S1) asserts exactly one `decide()` for a large turn and for a path-plus-RE turn.

- **Precheck on the full prompt (rules, sync).** Reflex runs the rules adapter on `compact_state(raw_state)` (`reflex.py:235`), which cuts every string over 800 chars to 800 (`decision/types.py:248`). So size rules are **never** evaluated inside `decide()`. `decision/large_prompt.py::precheck(text: str, settings) -> LargePromptPrecheck` runs in `decide_owner_turn` (`owner_turn.py:537-630`) on the raw `user_message`, next to `resolve_persona_context` (L563) and **outside** the 50 ms `wait_for`. It computes L1-L5 and the split mode and returns `rules_fired`, `floor` (`large` | `standard`) and `mode`. It is passed to `_decide_sync`, `_deadline_rules_result` (L373-400) and the new `_with_deadline_large_prompt`. Cost is linear in the prompt with one regex pass per rule: `test_precheck_bounded_on_100kb_prompt` bounds it.
- **Candidate (inside `_decide_sync`, before the one `decide()`).** A candidate exists only when **all** of these hold:
  - `precheck.re_match` is not set (RFC-0232 S2's helper did not match);
  - the baseline route is managed (`baseline.kind == MANAGED_TASK`), and `infer_rules_reply_shape(text)` is none of literal, clarify, self_status, basic_qa or social (all in `REPLY_SHAPES`, `owner_turn.py:43`);
  - `security_role == ""`;
  - `settings.large_prompts.enabled` is true;
  - `precheck.floor == "large"` (at least one rule below fires).

  Without a candidate, no rider is appended and the decision is unchanged byte for byte.
- **Riders (appended to `OWNER_TURN_QUESTIONS` for that call only):**
  - `large_prompt`: choice `standard` | `large`, `decision_class="complexity_escalation"`.
  - `large_prompt_split`: choice `sections` | `questions`, `decision_class="workflow_branch"`.

  Both classes are already in `REFLEX_DECISION_CLASSES` (`decision/types.py:14-39`), so the unlisted-class check at `reflex.py:229-231` passes. The rules adapter's rider branches (`decision/adapters/rules.py`, next to L226/L237) read only the scalar state keys `large_prompt_floor` and `large_prompt_rules` that `_decide_sync` sets from the precheck; they never measure text.
- **Rules (computed by the precheck on the raw text).** `large` fires if any of these holds:
  - **L1:** `len(prompt) ≥ 4000`.
  - **L2:** at least 3 list items (`^\s*(\d+[.)]|[-*•])\s+`) and `len ≥ 600`.
  - **L3:** at least 3 question sentences (ending in `?`, or starting with an interrogative word in en/nl) and `len ≥ 200`. This also sets split `questions`.
  - **L4:** `task_workflow.is_large_request(prompt)` (landed #649, `agent/task_workflow.py:31-37`), imported and called as is, **counted only when `len ≥ 600` or another rule also fires**. "Make a quick snake game" is therefore not large.
  - **L5:** `local_complexity_tier(prompt) == 4`.

  Split mode: `questions` when L3 fired and fewer than 3 list items exist, otherwise `sections`.
- **Floor semantics** (the rule at `reflex.py:398-410`: providers may raise a tier but never lower it):
  - `_apply_floors` (L296-370) applies `precheck.floor`. A typed provider may raise `standard → large` only at confidence ≥ 0.75, and may never lower `large → standard`.
  - **Deadline and exception fallbacks keep the verdict and the full question.** `_deadline_rules_result` asks `OWNER_TURN_QUESTIONS` plus the riders when a candidate exists, and the outer `TimeoutError` / `Exception` paths (L585-630) call `_with_deadline_large_prompt(decision, precheck, text)` after `_with_deadline_persona`. The fallback decision carries the untruncated `user_message` into `create_task`; the precheck object is never rebuilt from the projection.
  - A provider's split answer wins only when L3 did not fire.
- **Final gate after the floors.** The verdict is nulled when 0232's RE floor applied, and unless the final route is `managed_task` and the final reply shape is not in {literal, clarify, self_status, basic_qa, social}. A provider that answers `direct_reply` at ≥ 0.75 on a 4500-char prompt therefore leaves `large_prompt is None`, as today.
- **Output.** New field `OwnerTurnDecision.large_prompt: LargePromptIntent | None` (`OwnerTurnDecision` L145-158), with fields `verdict`, `mode`, `rules_fired: tuple[str, ...]`, `decision_source`, `confidence`. `request_routing` passes the field through unchanged.
- **#649's planner is not a second decision.** The landed auto-planner (`loop.py:2344-2349` `needs_workflow`, `:2686-2707` `prepare_workflow(..., planner=MANAGER.chat)`) never runs for a pipeline parent or child (S4/S5 mark and skip, §2). When `large_prompts.enabled` is false or the verdict is `None`, #649 behaves exactly as landed.
- **Arbitration class.** The large ack is a front notice, not an answer. The parent's final result is the combined child outcome, which matches `keep_worker` semantics (`surfaces.py:395-410`). `arbitrate_front_and_worker` is not called for the ack.

### 2. Ack and preload (S4)

**Order inside `AgentRuntime.create_task`** (`loop.py:479-559` on `d85c9d4`), matching #666 and #664 @ `df37b22`:
1. RFC-0230 S3's `prewarm_worker("turn")` and the route decision (RFC-0230 owns that position);
2. RFC-0232's RE dispatch (an RE turn never reaches step 4, and its decision has `large_prompt=None`, §1);
3. the `Task` commit and RFC-0218 S3b's persona block (unchanged, including `publish_persona_switch_line` per #663);
4. **this RFC's large branch**, which replaces only the generic ack at L548-557 for a large turn.

**Marking the parent.** The large branch inserts the `large_prompt_pipelines` row (§4) in the same session as the `Task` commit, before `_start_runner`. That row is the mark: `large_prompt_queue.is_pipeline_parent(task_id)` reads it, and `_run` returns into the parent runner **before** `loop.py:2344` (#649's `needs_workflow`), so #649's planner never plans a 0231 parent (CoS ruling 2). Children are seeded (§4), so `load_workflow` finds a stored plan and #649 never auto-plans them either.

**The large branch, step by step** (all in-memory, no I/O probe, so the ack stays inside its budget):
1. **Cancel 0230's 9B prewarm** when a target resolves and the gate outlook is not `refuse`: `turn_prewarm.cancel_prewarm(turn_id)` (RFC-0230 S3 exposes it; #666 S3). A prewarm that has not yet called `prepare_engine_for` is cancelled. One already inside `prepare_engine_for` finishes under its single-flight, and the preload's own gate call queues behind it. With the outlook `refuse`, the prewarm is left alone (the parts will run on the 9B).
2. **Resolve the target** (`large_prompt.resolve_target`, below) and **ask the RFC-0225 gate before wording the ack** (CoS ruling 4): `engine_coexistence.gate_outlook(target) -> GateOutlook(verdict: "resident" | "allow" | "refuse", reason: str)`, added by 0231-S0 (§2a). It reads only RFC-0225's in-memory state:
   - `resident`: the target is in `anzu_loaded_instances()` or the last `/api/ps` snapshot RFC-0225 keeps;
   - `refuse`: the resident worker is owner-loaded (not in `anzu_loads`, e.g. Taco's LM Studio `127.0.0.1:1234` `qwen3.5-9b-defiant-fable-uncensored`) and `is_managed(<its engine>)` is false. That is #652 L76's refusal, predicted without a probe;
   - `allow` otherwise. The real step-5 gate still decides in the preload.
3. **Speak the one ack** (CoS ruling 5). The text is a module constant chosen from the outlook. **No variant says the larger model is loading**, so the ack can never claim a load the gate has not allowed:

   | Outlook | Text |
   | --- | --- |
   | `resident` | "This is a large task. I'll split it into parts and work through them one by one with the larger model." |
   | `allow` | "This is a large task. I'll split it into parts and work through them one by one." |
   | `refuse` | "This is a large task. I'll split it into parts and work through them on the model you have loaded." |
   | no target | "This is a large task. I'll split it into parts and work through them on the current model." |

   **Delivery is the parent's front lane (RFC-0230 rule 1, #666 L61).** For a pipeline parent `_run` skips `_run_managed_front_lane` (L2420-2430) and the front-off fallback (`chat_tts` plus `publish_owner_text`, L2431-2445). The ack **is** the parent's front-lane line, published as `BUS.publish(task.id, "acknowledgement", "Acknowledged", text, stage="queued")` (the event the 0218 S3b latency test measures) plus `BUS.publish(task.id, "chat_tts", "Large task", text, stage="large_prompt_ack")`, and stamped with RFC-0230 S0's `mark(turn_id, "tts_enqueued", lane="front", source="large_prompt_ack")`. The client's `first_audio` mark (`chatTtsPlayer.ts`, 0230-S0) closes the clock. The title is not `"Speak reply"`, so the ack never joins the reply prefix (`useTaskSpeech.ts:48`). The ack never goes through `publish_owner_text` (no client, #663). It is a fixed text, not a front-model generation, because a generation could claim a load the gate refuses (ruling 4).
   **Nothing else on the parent is spoken until its terminal outcome.** The gate line, preload status, "Part n of N done", needs_owner and vault lines are `BUS.publish(parent, "large_prompt", …)` events only (visible in Show work and the panel). RFC-0225 owner lines raised by the preload carry `task_id=parent` and `speak=False` (§2a), so they show as a chip and a task event but are not spoken. The terminal outcome (combined result or failure text) is the task's answer, spoken by the existing outcome path once.
4. **Start the preload** with `asyncio.create_task(large_prompt.preload(task.id, target, outlook))` only when a target resolved and the outlook is `resident` or `allow`. It is not awaited, and the handle is stored on the runtime so cancel can reach it. With `refuse`, no preload runs, no model is touched, and the parent shows one event: "Running on <loaded model>: the larger model needs about 12 GB and would need the 9B unloaded, which ANZU only does in managed mode (Settings → Local engines → Let ANZU manage this engine)."
5. Record `ack_ms` on the pipeline row, then `_start_runner(task.id, self._run(task.id, continue_existing=False))`, unchanged.

**Splitting runs after the ack (normative).** No split, completeness or compile work runs in `create_task`; it all runs in the parent runner, which starts after the ack is published. `test_ack_not_delayed_by_split` holds this with a split fake that blocks for 5 s.

**Latency budget (normative), on RFC-0230's clock.**
- **CI:** the ack `chat_tts` is persisted ≤ 150 ms after `evaluate_request_route` returns, with a preload fake that blocks for 5 s and a split fake that blocks for 5 s.
- **Owner-visible target:** the large turn is held to RFC-0230's target, **first audible word ≤ 1.5 s at p50 and ≤ 2.0 s at p95 from end of owner input** (#666 L53), measured with 0230-S0's marks. 0231-S4 adds three large-turn cases (`tests/fixtures/rfc0231/latency_cases.json`, from the S3 fixtures: 5-item list, 4 questions, 6000-char spec) through 0230-S0's `--cases` hook in `scripts/anzu-latency-repro.ps1`. The headline is 0230's client-clock `first_audio − input_end`, closed by the browser's `playing` event. There is no separate 0231 clock.

**Target resolution** (`agent/large_prompt.py::resolve_target(settings) -> TargetResolution`, sync, in-memory):
1. `settings.large_prompts.target_runtime` (default `"anzu-coder-27b"`, the 0231-S0 profile), matched against **enabled** runtime profiles (`list_runtime_profiles()`, `enabled is True`) by `name`, then `model_profile`, then the provider model id. A disabled row never matches (`runtime_router.py:284-285`).
2. Otherwise `route_runtime` (`runtime_router.py:320`) with `minimum_answer_tier=3`, `task_specialization="coding"` when `task_class` is code/build/debug and `"reasoning"` otherwise, and `preferred_profiles=("expert", "ornith_35b")` (ported from `answer_routing.py:57-71`).
3. Otherwise no target, with `reason` = S0's last reconcile outcome (`anzu_coder.last_outcome()`). The parent event names it: `ollama_unreachable` → "Ollama isn't running, so the larger model isn't available; running on the current model."; `not_advertised` → "Ollama doesn't list anzu-coder-27b; running on the current model."; `owner_disabled` → "anzu-coder-27b is turned off in your runtime profiles; running on the current model." When the outcome was `ollama_unreachable` and the template is disabled, the **preload task** (never the ack path) first runs one bounded reconcile, `reconcile_anzu_coder_profile(attempts=1, timeout_s=3.0)`. If that enables the row, it re-resolves and continues with the preload, and the event says "Found anzu-coder-27b in Ollama; using it for the parts."

**Preload** (`large_prompt.preload`). No new loader:
1. **Request lease first.** `token = engine_coexistence.hold_request_lease(engine_id, model, reason=f"large-prompt:{parent}")` (§2a). The lease is held from here until the parent is terminal, across every part, every gap between parts and every `waiting` period (CoS ruling 3).
2. Call `await hotswap.activate_runtime_profile(target, persist=False, task_id=parent)` (`hotswap.py:197`). On `d85c9d4` it applies with `persist=False` at L209, loads through `MANAGER.load`, then saves `settings.inference` at L231-232. 0231-S4 adds the keyword `persist: bool = True` (default unchanged for every caller): with `False` the L231-232 save is skipped, so **a large-task load never becomes the owner's saved selection** (ruling 3). `task_id` is forwarded to `prepare_engine_for` (RFC-0225 already accepts it). After RFC-0225 S3 this is single-flight, revive or respawn, identity check, step-5 VRAM gate and owner lines; the pipeline adds no gate logic.
3. Warm with `gpu_prefer.ensure_ollama_gpu` (L124) or `ensure_lmstudio_gpu` (L67), by provider. For an Ollama target the preload first reads `GET /api/ps`:
   - already listed → no warm call (an owner-loaded model's `keep_alive` is never touched), not recorded in `anzu_loads`, `preload_status = "already_loaded"`;
   - not listed → warm with `keep_alive: "-1"` (pinned while the lease is held), then `GET /api/ps` again; listed → `engine_coexistence.record_anzu_load(engine_id="ollama@127.0.0.1:11434", model="anzu-coder-27b")`, `preload_status = "loaded"`; not listed → `failed:warm_not_resident`.
4. Set `preload_status`: `loaded`, `already_loaded`, `failed:<reason>`, `gate_refused:<reason>` or `timeout`. On any non-loaded status the lease is released at once.

**While the lease is held** (the parent is `running` or `waiting`):
- RFC-0225 step 6 sees a held request lease and never unloads the target; step 7 never unloads during a lease (#652 L81, L86).
- RFC-0228 S2's Ollama keep-alive does not expire it: an ANZU-loaded target was warmed with `keep_alive: "-1"`. An owner-loaded target keeps the owner's keep-alive, untouched.
- The rewarm hold (below) defers `NINE_B_REWARM`, so the 120 s idle restore never swaps the worker between parts.
- **Chat turns during a pipeline** route to the loaded target: `prepare_answer_route` uses the loaded runtime (`loop.py:2475`), and the front lane still speaks first per RFC-0230. A chat turn that explicitly needs the 9B (persona brain, explicit switch) waits on the lease under RFC-0225 step 7 and gets that step's visible line. Nothing unloads the target between parts.

**Preload outcomes (defined, never silent):**

| Outcome | Behaviour |
| --- | --- |
| loaded / already_loaded | Children run on the target. |
| outlook `refuse` (no preload) | The parts run on the loaded 9B. Nothing is unloaded (ANZU never unloads a model it did not load). One event, as in step 4 above. The task does not fail. |
| real gate refuses (step 5) | RFC-0225's owner line (with `task_id=parent`, `speak=False`) names the reason. The lease is released and the parts run on the current model, with one event "Running on <current>: <reason>". The task does not fail. |
| load error | The same fallback, with the error text in the event. |
| not loaded within `PRELOAD_DEADLINE_S = 180` | The preload task is cancelled, then the same fallback with "The larger model took too long to load". |
| owner cancels the parent during preload | The preload task is cancelled, the lease and hold are released, and the restore runs. |

**Re-preload on resume.** `/continue` on the parent and `recover_on_startup` (§5) check `MANAGER.state` and Ollama `/api/ps`. When the target is no longer resident (backend restart, owner unloaded it, keep-alive expired before a restart), they re-run `preload` (same lease, same outcomes) before the next dispatch.

**Restore at pipeline end** (any terminal parent status):
1. Release the request lease. For an ANZU-loaded Ollama target, send one `POST /api/generate {"model": <target>, "keep_alive": "<idle_unload_seconds>s"}` so normal RFC-0228 expiry resumes.
2. **Restore the owner's selection.** Because the preload never persisted, `load_settings().inference` is still the owner's selection. If `MANAGER.state` still points at the target the pipeline loaded, the restore calls `engine_coexistence.prepare_engine_for(load_settings().inference, task_id=parent)` and then `MANAGER.load` of that selection, i.e. RFC-0225 step 6 unloads the ANZU-loaded target when the 9B needs the room, and never unloads an owner-loaded one. If the owner changed the model meanwhile (through settings, which merge via `_merge_settings_changes`, `config.py:589`, used at L619), `MANAGER.state` no longer points at the target and nothing is restored.
3. Release the rewarm hold and call `schedule_orchestrator_restore` (`model_escalation.py:73-93`; after RFC-0228 S2 that is `NINE_B_REWARM`).

**Rewarm hold** (S4 edits `inference/rewarm.py`, after RFC-0228 S2 creates it):
- `NINE_B_REWARM.hold(reason: str) -> str` and `release(token)`.
- While any hold is held, both rewarm triggers defer, the same way they defer while the 27B is resident.
- `release` of an unknown token is a no-op.
- Holds and leases are in-memory. Startup recovery (§5) re-takes both for every pipeline still `running` or `waiting`.

### 2a. Target profile: `anzu-coder-27b` (S0)

**Source trace (normative).** `anzu-coder-27b` is an Ollama model on Taco's PC, not something ANZU ships:
- `development` @ `d214b6d`: no runtime profile, model profile, specialist catalogue entry or installer asset defines it. `rg anzu-coder` over `backend/`, `config/`, `installer/` and `tests/` returns nothing. `installer/windows/model-catalog.json` does not exist yet (RFC-0228 S1/S4 create it). `config/default.json` has no runtime profiles; the registry defaults are `runtime_profiles.py:146-154` (`PROFILES` + `model_stack.recommended_specialist_runtime_profiles()`), and neither contains it.
- The only mentions on `development` are observations and fixtures: `docs/audits/2026-10-09-model-reuse-scheduler-manager.md:13` ("Ollama exposed `anzu-coder-27b:latest` at 11434") and RFC-0227 `docs/rfcs/0227-model-chooser-and-dropdown-persistence.md:69` (HUD slot fixture, provider `ollama`, model `anzu-coder-27b`).
- RFC-0228 (#655 @ `971ca15`): owner context L10 ("`anzu-coder-27b` (Ollama, ~12 GB GPU) is for coding"), VRAM yielding L63, and out of scope L360 ("Changing the 27B coder or its Ollama model configuration"). 0228-S1 owns the Fable 9B default and `fable_9b` (L41, L206), not the coder, and `dl_expert27b` (L31) is the separate Qwen3.5-27B GGUF for `expert`. **0228-S1 is therefore not the owner; #655 is not amended.**
- RFC-0225 (#652 @ `916cf25`): uses the model only in the gate and in owner lines (L70, L73 "`anzu-coder-27b` ≈ 12 GB", L76, L81-82, test L382 "free VRAM < 13 GB"). It adds no profile.
- Taco's drafts #648 (landed as `d214b6d`) and #649 @ `edb4685`: no hunk names `anzu-coder` (`gh pr diff` searched).

**Owner: 0231-S0.** It adds one shipped runtime-profile template in the existing schema (`RuntimeProfile`, `runtime_profiles.py:28-50`, produced by `SpecialistModel.runtime_profile()`, `model_stack.py:47-74`), so no schema field is added:

| `RuntimeProfile` field | Value | Why |
| --- | --- | --- |
| `id` | `recommended-anzu-coder-27b` | `model_stack.py:56` pattern |
| `name` | `anzu-coder-27b` | `large_prompts.target_runtime` default; equals `create_runtime_profile`'s normalisation (`runtime_profiles.py:240`) |
| `label` (display name) | `ANZU Coder 27B (Ollama)` | |
| `model` (model key) | `anzu-coder-27b` | Ollama tag; `anzu-coder-27b:latest` resolves through the existing `resolve_advertised_model` substring match in `apply_runtime_profile_to_settings` |
| `provider` | `ollama` | as in the RFC-0227 fixture and RFC-0228 L10 |
| `endpoint` (runtime) | `127.0.0.1:11434` | Ollama loopback, same form as the Umi entry (`model_stack.py:93`). LM Studio `http://127.0.0.1:1234/v1` keeps serving the 9B `qwen3.5-9b-defiant-fable-uncensored`, and nothing here changes it. |
| `context_limit` | `16384` | `RuntimeProfile.from_dict` default. A compiled part is ≤ 6000 chars plus ≤ 1800 chars carry-over, so 16k leaves room for the tool loop and keeps the footprint inside the 12 GB estimate. |
| `quantization` | `ollama` | the Umi convention (`model_stack.py:95`); the quant is inside Taco's Ollama model |
| `privacy_class` | `local-only` | |
| `cost_ceiling_usd` | `0.0` | local (`model_stack.py:65`) |
| `capability_tags` | `("llm_inference", "text", "coding", "agentic", "tool-use")` | no `high-quality`, so `_quality_score` (`runtime_router.py:155-165`) does not lift it over the preferred `expert` in answer routing |
| `specialization_tags` | `("coding",)` | no `reasoning`, so answer routing's `task_specialization="reasoning"` bonus (`answer_routing.py:61-66`) does not go to it |
| `model_profile` | `None` | an Ollama runtime has no `PROFILES` entry; `activate_runtime_profile` then keeps `settings.inference.profile` |
| `is_local` | `True` | |
| `description` | `Taco's 27B coding model in Ollama (~12 GB GPU). ANZU enables it only when Ollama lists it.` | |
| `enabled` | `False` as shipped; set to `True` by the S0 reconcile below | specialist templates ship disabled (`tests/test_model_stack.py::test_specialist_runtime_templates_are_disabled_by_default`), so installs without the model route exactly as today |
| `runtime_role`, `answer_tier` | `expert`, `4` | `SpecialistModel.role = "leader"` (`model_stack.py:53-54`); `profile_roles.py` is not edited (0228-S2 owns it) |
| `gguf_path` | `""` | not a GGUF ANZU loads |

The `SpecialistModel` entry is `MODEL_CATALOG["anzu-coder-27b"]` with `key`/`runtime_profile_name` `anzu-coder-27b`, `role="leader"`, `enabled_by_default=False`, `ship_runtime_template=True`, `manual_gate=False`, `inference_profile=None`, and the values above. `ROLE_SPECS["leader"].preferred_profiles` is **not** changed (`tests/test_model_stack.py::test_leader_role_prefers_qwen38_then_local_fallbacks` keeps passing).

**Values outside `RuntimeProfile` (no new schema field):**
- **VRAM estimate:** `anzu_coder.VRAM_ESTIMATE_GB = 12.0`, the total requirement at `context_limit` 16384 (Taco's figure; #652 L73, L76). `anzu_coder.vram_requirement_gb(target) -> float | None` returns `12.0` when the target provider is `ollama` and its model is `anzu-coder-27b` or `anzu-coder-27b:<tag>`, otherwise `None`. S0 adds one hunk to RFC-0225's `engine_coexistence.prepare_engine_for` step-5 requirement lookup: consult `vram_requirement_gb` first, then the existing catalogue / graded `weight_gb` lookup unchanged. With the 1 GB headroom the gate acts below 13 GB free, which is #652's test threshold (L382).
- **`idle_unload_seconds`:** not per profile. ANZU-originated Ollama loads use RFC-0228 S2's `settings.inference.idle_unload_seconds` (default 900, so `keep_alive: "900s"`; `0` means `"-1"`, pinned; #655 L62). This profile inherits it.
- **ANZU-loaded vs owner-loaded (RFC-0225, #652 L43-44, L74-82):**
  - *ANZU-loaded:* ANZU's preload warmed it and `/api/ps` did not list it before (§2 preload step 3). It is recorded in `anzu_loads`, and the reverse gate (step 6) may unload it with `keep_alive: 0` when the 9B needs the VRAM back.
  - *Owner-loaded:* listed by `/api/ps` before ANZU asked (e.g. Taco ran it from his shell). Not recorded, never unloaded by ANZU, and the reverse gate gives its "which you loaded" error line instead.
  - With the profile enabled, Ollama on 11434 counts as `anzu_configured` under RFC-0225 S3's classification ("Ollama referenced by an enabled runtime profile"), so it is never offered for stopping.
- **Installer catalogue size / sha256:** none. The model is Taco's own Ollama build, so it is not an installer asset: `installer/windows/model-catalog.json` (RFC-0228) gets no entry, and S0 changes no installer file. #655 L360 already excludes it.

**Enable reconcile** (`backend/app/inference/anzu_coder.py::reconcile_anzu_coder_profile() -> dict`, new). It runs once per backend start as `_start_optional_step("anzu_coder_profile", reconcile_anzu_coder_profile)` in `main.py` startup, next to the existing optional steps (`main.py:140-143`, `:226`), so startup never waits on it:
1. `probe_remote_server("127.0.0.1", 11434, timeout=3.0)` (`backends.py:159`). If Ollama is unreachable, it retries every 60 s, at most 10 attempts, then stops with outcome `ollama_unreachable`.
2. Ollama answers but doesn't list `anzu-coder-27b` / `anzu-coder-27b:<tag>` → `not_advertised`. Nothing changes.
3. A registry row named `anzu-coder-27b` whose id is not `recommended-anzu-coder-27b` (an owner-created row) → `owner_row`. That row is left alone and resolution uses it (`_merge_missing_defaults`, `runtime_profiles.py:157-164`, never adds the template over it).
4. The template row is already enabled → `already_enabled`.
5. The template row is disabled and `runtime_profiles_root()/anzu-coder-profile.json` has `auto_enabled_at` → `owner_disabled`. The owner turned it off after an earlier auto-enable, so it is not re-enabled.
6. Otherwise → `update_runtime_profile("recommended-anzu-coder-27b", enabled=True)`, write `{"auto_enabled_at": <ISO-8601 UTC>}` to that file, outcome `enabled`.

Each outcome is logged once as `anzu_coder_profile outcome=<outcome>` and returned, so `startup_health` records it. This follows the existing rule that a discovered local model becomes an enabled runtime row (`model_discovery.py:338-366`). If the model is removed from Ollama later, the next preload fails visibly through `activate_runtime_profile` ("Model 'anzu-coder-27b' is not loaded in Ollama…") and takes the "load error" fallback in §2; the parts then run on the current model and the task does not fail.

**Taco's 16 GB card (normative statement).** `anzu-coder-27b` needs about 12 GB (`VRAM_ESTIMATE_GB`), and the resident 9B needs about 7 GB (#652 L82). 12 + 7 = 19 GB exceeds a 16 GB card, so on Taco's PC the step-5 gate **always** takes either the unload path (the 9B is ANZU-loaded, or managed mode is on) or the refuse path (the 9B is owner-loaded and managed mode is off, which is Taco's default: LM Studio `127.0.0.1:1234`, `qwen3.5-9b-defiant-fable-uncensored`, #652 L42). The S4 live audit records which path ran, once with managed mode off and once with it on.

**Late Ollama start.** `reconcile_anzu_coder_profile(*, attempts: int = 10, timeout_s: float = 3.0)` keeps the startup behaviour above with its defaults. The last outcome is kept in memory and returned by `anzu_coder.last_outcome() -> str | None`. When RFC-0225 S3 starts `ollama serve` after the 10 attempts ran out, the next large turn's preload task runs one bounded reconcile (`attempts=1`, ≤ 3 s, never on the ack path; §2 target resolution step 3).

**RFC-0225 additions owned by 0231-S0** (`engine_coexistence.py`, second owner after 0225-S3; #652 lists it):
- `gate_outlook(target) -> GateOutlook` (§2 step 2): pure, in-memory only (`is_managed`, `anzu_loaded_instances()`, the last `/api/ps` snapshot, the selected engine's owner/ANZU classification). No probe, no I/O.
- `hold_request_lease(engine_id, model, *, reason) -> str` and `release_request_lease(token) -> None`. A held token counts as a request lease in steps 6 and 7 (#652 L81, L86), exactly like a turn's lease. Release of an unknown token is a no-op. `held_leases()` lists them for diagnostics.
- `owner_line(..., speak: bool = True)`: with `speak=False` and a `task_id`, (b) publishes the `engine_notice` task event but not the task `chat_tts`. Every existing call keeps the default, so RFC-0225 and RFC-0228 lines are unchanged. The ephemeral (a) frame carries the `task_id`, so `EngineNotices` does not speak it while that task is open (#652 "unless `task_id` equals `openTaskId`").

### 3. Split, completeness, compile (S3)

All of this lives in `agent/large_prompt_intake.py` (new). It runs in the parent runner, deterministically, on CPU, and does not wait for the preload.

**Split** (`split_prompt(text, mode) -> SplitResult`):
- **sections mode:**
  - Split boundaries are, in priority order: Markdown headings, top-level numbered or bulleted items, then blank-line paragraphs. This reuses `decision/intake.py:128 split_segments` for paragraph segmentation.
  - Text before the first boundary is the **shared context** (preamble). A trailing paragraph that begins "Constraints", "Requirements", "Note", "Let op" or "Eisen", or that contains no boundary marker after the last item, is the **shared constraints** block (trailer).
- **questions mode:** one section per question sentence. Non-question sentences that sit between questions attach to the following question as context.
- **Bounds:**
  - 1 ≤ N ≤ `MAX_SECTIONS = 8`, the same value as `intake.MAX_SEQUENTIAL_PARTS`.
  - When N > 8, the two smallest adjacent sections are merged repeatedly.
  - A section under 40 chars is merged into its predecessor.
  - N == 1 is valid: the pipeline still runs one detailed prompt with sub-tasks.
- **Ingress.** A prompt over 6000 chars stores the original once with `memory/ingress_spill.store_ingress_blob` (L35). Every section then carries the blob reference so the child can `read_ingress`. The `maybe_mirror_to_vault` swallow at L161 is not used.

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

**Compile** (`compile_prompt(section, ctx) -> str`, deterministic template, ≤ 6000 chars; #649's brief budget at `task_workflow.py:120`):

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
- **Vault mirror:** applies when `public_binding_status` (`memory/obsidian_vault.py:305`) is bound and `large_prompts.store == "db_and_vault"`. It is **idempotent, keyed on the section's `vault_rel_path`** (`_Temporal/LargePrompts/<parent_id>/part-NN.md`):
  - **get-or-create:** when the row already has `vault_rel_path` and the note exists, it is reused; only otherwise `create_note` (L741) writes it with frontmatter (parent, ordinal, status) and the detailed prompt. `create_note` raises `FileExistsError` on an existing file (L756), so a recovery re-dispatch or a follow-up recompile never calls it twice; an existing file without a row path is adopted and its path stored.
  - **append, not replace:** `edit_note` (L801) replaces the body, so at part terminal the pipeline reads the current body, composes `<existing body>\n\n## Result\n<summary>` and passes that to `edit_note`. A recompile appends `## Prompt (revised)` the same way.
- **Owner-edit conflict:** `edit_note` reports a conflict without `force`. The pipeline does not force. It records `vault_conflict` on the row and shows one parent event (not spoken), "Part n note was edited in Obsidian; ANZU left your edit and kept the result in ANZU".
- **Mirror failure:** produces a visible parent event (not spoken). DB persistence and the run continue.
- `large_prompts.store` takes the values `"db"` (default) or `"db_and_vault"`.

### 4. Storage: landed #649 engine plus seeding (S2)

#649 landed as `ee786dc`. S2 **reuses** its engine unchanged and ports nothing. Every citation below is `development` @ `d85c9d4`:

| Landed #649 piece | Where | Used by 0231 as |
| --- | --- | --- |
| `TaskPromptPlan` (goal, source_ref, followups_json), `TaskPromptStep` (uq `task_id`+`ordinal`, kind, prompt, status, result) | `db/models.py:66-88` | child prompt storage, unchanged |
| `REVIEW_STEPS` | `agent/task_workflow.py:15-19` | appended to every child when `large_task_reviews` is on |
| `TaskWorkflow` (`prompt()` with bounded predecessor summaries, `owns_history`, `finish_current`, `mark_running`) | `task_workflow.py:40-98` | runs the child's seeded steps |
| `load_workflow` | `task_workflow.py:101-112` | child `_run` finds its seeded plan |
| `workflow_payload`, `prompt_steps` in `GET /api/tasks/{id}` and observability | `task_workflow.py:172-177`, `api/tasks.py:288`, `:306` | child payload, unchanged |
| stored-workflow load and the `needs_workflow` flag | `agent/loop.py:2344-2349` | a child with seeded steps takes the workflow path |
| stored-workflow execution (`mark_running`, prompt, `max_steps = min(320, policy.max_steps × steps)`) | `loop.py:2709-2722` | unchanged |
| per-prompt step limit | `loop.py:2981-2983` | unchanged |
| advance to the next stored prompt with fresh context | `loop.py:3639-3660` | unchanged, plus the S5 validator gate before L3640 (§3) |
| completion guard (no completion while more than one stored prompt is open) | `loop.py:776-788` | unchanged |
| `large_task_reviews` setting | `config.py:494`; `api/settings.py:72`, `:240-241` | unchanged |
| prompt-steps rows in the panel, status label, types | `TaskActivity.tsx:306-319`, `taskStatus.ts:207`, `api.ts:230`, `:269` | child panel, unchanged (S6 adds no prompt-steps UI) |
| tests | `tests/test_rfc0224_task_workflow.py` (24 tests, `pytest` "Run full backend suite") | stays #649's; S2 doesn't edit it, and it must keep passing |

**Not used by the pipeline (left exactly as landed):** `PLAN_SYSTEM` / `prepare_workflow` (`task_workflow.py:20-28`, `:115-169`), the auto-plan branch (`loop.py:2686-2707`) and `append_followup` (`task_workflow.py:180-216`, `loop.py:2675-2683`):
- A pipeline **parent** never reaches them: S4's parent-runner entry returns before `loop.py:2344`.
- A **child** has seeded steps, so `workflow is not None` and the auto-plan branch is skipped (`loop.py:2686`).
- Child `/continue` goes to the parent (§5), so `append_followup` never runs for a child.
- Every other task, including any large request when `large_prompts.enabled=false` or the precheck excludes the turn, keeps #649's behaviour unchanged.

**Added by S2 (what #649 does not provide):**
- `task_workflow.seed_workflow(session, task_id, *, goal: str, source_ref: str, steps: list[StepSpec]) -> None`, appended to `task_workflow.py` after `workflow_payload`. `StepSpec = tuple[str, str]` is (kind, prompt). It runs in the caller's session, before `_start_runner`. It writes one `TaskPromptPlan` and one `TaskPromptStep` per spec (ordinal 1..n, status `pending`) and sets `task.plan_json` the way `prepare_workflow` does at L165. It is idempotent: if a plan already exists for `task_id`, it returns without writing. Bounds are 1 ≤ len(steps) ≤ 12 and `len(goal) ≤ 16000`, the same ceiling `append_followup` enforces at L200. Anything over raises `ValueError`, and the child is never created.
- **What a child's seeded rows contain:**
  - `goal`: the section's `detailed_prompt` (≤ 6000 chars), plus `Previous part result` (≤ 1800 chars) when there is one;
  - `source_ref`: `large_prompt_sections id=<id>`, plus `; read_ingress blob_id=<blob>` when the pipeline has a blob;
  - steps: `("work", "Deliver this part as specified in the goal.")`, `("deeper", <deeper prompt, §3>)`, `("quantitative", <quantitative prompt, §3>)`, then `REVIEW_STEPS` when `large_task_reviews` is on.
- The two pipeline tables below and `LargePromptSettings` (§Settings).

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

This reuses the semantics of `agent/intake.py`'s chain (stable ids, advance on terminal, stop on failure; L224, L260, L281-313), moved from JSON files to the DB, and admits each child through the same breaker scheduled runs use.

- **Dispatch** (`large_prompt_queue.dispatch_next(parent_id)`):
  - Under a per-parent `asyncio.Lock`, pick the lowest-ordinal `pending` or `queued` section.
  - Call `admit_automatic_trigger` (`automation/breaker.py:236-320`) with automation id `large-prompt:<parent>`, `ensure_automation` first. When the kill switch is engaged or the breaker is open, the parent fails visibly with the breaker reason. No retry loop.
  - Call `AGENT.create_task(child_prompt, request_id=uuid5(NS, f"large-prompt:{parent}:{ordinal}"), pipeline_section=section_id, profile=target)`.
  - The id is stable, so a re-dispatch after a crash reuses the same child (`loop.py:493-500` request_id reuse).
  - **Bind the admitted run to the child:** `bind_run_to_task(run_id, child.id)` (`automation/breaker.py:322`) right after `create_task` returns, the same call the scheduler makes (`mobile/scheduler.py:112`). Without it the admitted run stays in flight and eats the failure budget (`breaker.py:225`, `:284-285`). A re-dispatch that reuses the child id re-binds the same run id.
- **`create_task(..., pipeline_section: str | None = None)`**, keyword-only, default `None`, so every existing call is unchanged. When it is set:
  - The route is fixed to MANAGED with the parent's task class and **no decide** (the parent turn already decided; still exactly one decide per owner turn).
  - No persona block, no large branch (no recursion) and no generic ack.
  - `seed_workflow` with `work, deeper, quantitative, *REVIEW_STEPS?` runs in the same session as the Task commit, before `_start_runner`.
  - The title is `Part n of N · <section title ≤ 60 chars>`.
- **`_run` for a child:** skip the managed front lane (L2420-2445) and its `chat_tts`. Children never speak, because the HUD follows the parent. Run the seeded workflow on the target profile. Per-child `speak_outcome` in the terminal hook is suppressed.
- **Terminal hook** (`_update`, L800-826), placed next to `advance_intake_chain` (L804-813), as `large_prompt_queue.on_child_terminal(child_id, status, result)`. **First check:** when `pipeline.status == "cancelled"` (the parent was cancelled), the hook records the child's section as `cancelled` and returns; it never dispatches. Otherwise:

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
  - `AGENT.cancel(parent)` calls `large_prompt_queue.on_parent_cancel(parent)` (one call in `cancel`, L733-738). Under the per-parent lock it sets `pipeline.status = "cancelled"` **first**, then cancels the running child and the preload task, marks the rest `cancelled`, releases the lease and hold and runs the restore. The running child's later terminal hook sees the cancelled pipeline and never dispatches.
  - `POST /api/tasks/{id}/cancel` (`api/tasks.py:341-352`) sets `status = "cancelled"` directly, without `_update`, so the terminal hook would never fire for a queued child with no runner. S5 adds one call after that commit: when the task is a pipeline child, `await large_prompt_queue.on_child_cancel_api(child_id)`, which runs `on_child_terminal(child_id, "cancelled", None)` (skip that part, dispatch the next). When the task is a pipeline parent the existing `AGENT.cancel` already reached `on_parent_cancel`.
- **Follow-ups:**
  - `/continue` on a **child** is redirected to the parent, in `continue_task` (L561-590).
  - `/continue` on the **parent** is handled in `_run`'s follow-up path, after S3b's follow-up persona block. It first re-preloads when the target is no longer resident (§2). If a part is `needs_owner`, the reply answers it (§3). Otherwise the text is appended as a new last part (content-hash dedupe, the same rule as landed `append_followup`, `task_workflow.py:182-186`; the parent has no stored workflow, so `append_followup` itself is not called) and goes through completeness and compile.
- **Startup recovery** (`main.py`, after `reconcile_execution_on_startup`, L213-218 on `d85c9d4`). For each pipeline in `running` or `waiting`:
  - re-take the rewarm hold and the request lease;
  - when the target is not resident, re-run `preload` (§2 "Re-preload on resume");
  - if the current child is terminal, run `on_child_terminal` (a missed advance);
  - if it is `queued` without a runner, dispatch it again (same id);
  - if it is `running` without a runner, call `continue_task(child)`, which resumes the durable run (RFC-0029).
- **Visibility:** `get_task` (`api/tasks.py:256-289`) **and** `get_task_observability` (`api/tasks.py:292-308`, which the live panel polls from `TaskActivity.tsx:208`) both gain the same `large_prompt` object (one builder, `large_prompt_queue.payload(task_id)`), containing:
  - mode;
  - status;
  - target;
  - preload_status;
  - ack_ms;
  - sections (`ordinal`, `title`, `status`, `completeness`, `rounds`, `missing`, `child_task_id`, `vault_rel_path`, `vault_conflict`).

  Parent events are plain human text, so Show work (`OwnerChatTranscript.tsx:232-280`, which renders `title` and `detail`) shows the progress without an edit.
- **Recents:** children appear in `/api/tasks` (polled by `App.tsx:223`) with their "Part n of N" titles. The list endpoint is unchanged.

### 6. Owner UI (S6)

The live panel already has #649's "Saved plan and task prompts" block (`TaskActivity.tsx:306-319` on `d85c9d4`, `mergeObservability` carrying `prompt_steps` at `taskStatus.ts:207`, `prompt_steps` types at `api.ts:230`, `:269`). S6 **extends those rows add-only** and does not build a second plan list (CoS ruling 2).

- **Data.** `large_prompt` arrives on both `GET /api/tasks/{id}` and `GET /api/tasks/{id}/observability` (§5). `mergeObservability` (`taskStatus.ts:203`) gains one line, `large_prompt: obs.large_prompt ?? task.large_prompt`, next to `prompt_steps`. `TaskObservability`'s field list gains `"large_prompt"`.
- **View model, pure TS:** `frontend/src/components/largePromptSectionsView.ts` (new). `largePromptSectionsView(task: Task): LargePromptView | null` returns `null` when `task.large_prompt` is absent. Otherwise it returns:
  - for a **parent**: one row per section (ordinal, title, status chip label and tone, completeness, rounds, missing text), each with actions `{label: "Open", taskId: child_task_id}`, `{label: "Cancel part", method: "POST", path: "/api/tasks/<child>/cancel"}` (only when queued or running) and the vault path when mirrored; one `{label: "Cancel remaining", method: "POST", path: "/api/tasks/<parent>/cancel"}`; and a status line built from target, preload_status and ack_ms;
  - for a **child**: one line, "Part n of N of <parent title>", with an Open action to the parent.
  Step labels come from the existing `humanizeToken` (`taskStatus.ts:12`): `deeper` → "Deeper", `quantitative` → "Quantitative". No new label table.
- **Render (thin, add-only)** in `TaskActivity.tsx`:
  - the existing condition `{!!view.prompt_steps?.length && (` (L306) becomes `{(!!view.prompt_steps?.length || !!largeView) && (`; the `<summary>Saved plan and task prompts</summary>` and the existing `<ol>` of prompt steps stay byte-identical, and the `<ol>` still renders only when `prompt_steps` has rows;
  - after that `<ol>`, inside the same `<details>`, one added mount `{largeView && <LargePromptSections view={largeView} />}`;
  - `frontend/src/components/LargePromptSections.tsx` (new) renders the view model and wires buttons to `api()` with the view model's method and path.
  A pipeline child (which has seeded `prompt_steps`) therefore shows the live rows exactly as today plus the "Part n of N" line; a parent (no prompt steps) shows the sections list inside the same block.
- **Tests run on the pure file.** `frontend/large-prompt-sections.test.mjs` imports `largePromptSectionsView.ts` and `taskStatus.ts` under `node --experimental-strip-types` (no `.tsx` import, like `avatar-motion.test.mjs:3`). `npm run build` (`pr-tests.yml:118-119`, "Build frontend") is the TSX type gate for `TaskActivity.tsx` and `LargePromptSections.tsx`.
- **Not edited:** OwnerChatTranscript, HudChat, Chat, Phone, `useTaskSpeech` and every persona component.

### Live-UI add-alongside reasoning pass (2026-10-14 standing order)

Touched live UI: the TaskActivity panel (HudChat, Chat, Phone), task speech, Show work, the front lane.

| Surface | Existing behaviour kept? | Addition and reasoning |
| --- | --- | --- |
| "Saved plan and task prompts" (`TaskActivity.tsx:306-319`) | **Yes.** Summary text, `<ol>`, rows, `humanizeToken` labels and the nested "Stage result" details are byte-identical. For a task without `large_prompt` the condition evaluates exactly as today (`largeView` is `null`). | One `||` in the condition and one mount after the `<ol>`. Reasoning: a non-pipeline task cannot see any change; a pipeline child gains one line; a parent gains the sections list where the owner already looks for "the plan". |
| Rest of `TaskActivityPanel` (`ChildExecution`, `VerificationPanel`, `PhaseHistory`, buttons) | **Yes**, untouched | None. |
| `mergeObservability` | **Yes**: every existing field still merged the same way | One added field. A test asserts all existing fields are unchanged. |
| `useTaskSpeech` | **Yes**, unchanged | The ack is an ordinary `chat_tts` with title "Large task" (≠ "Speak reply"). Nothing else on the parent is spoken until its outcome. |
| Parent front lane (`_run_managed_front_lane`, front-off fallback L2431-2445) | **Changed only for a pipeline parent**: skipped, because the ack is its front-lane line. Every other task runs the front lane as today. | Reasoning: two front lines (ack plus a model reply) would break ruling 5, and a model line could claim a load. Children already skip it. |
| Show work (`OwnerChatTranscript.tsx:232-280`) | **Yes**, unchanged | Parent events are human-readable text, so no formatter is needed. |
| `EngineNotices` (RFC-0225) | **Yes** | Preload lines carry `task_id=parent` and `speak=False`: chip and task event, no speech. |
| RFC-0218 persona switch line, highlight, morph | **Yes** | Parent switch per S3b, before the ack. Children emit no persona events. |
| Phone | **Yes** | Shows the parent's events and panel via its existing poll. No speech is added. |
| Task recents (`App.tsx:223`) | **Yes** | Part children are listed with "Part n of N" titles. |

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
    target_runtime: str = "anzu-coder-27b"  # the 0231-S0 runtime profile name
    store: Literal["db", "db_and_vault"] = "db"
```

`AppSettings.large_prompts` is added next to `decision` (`config.py:512` on `d85c9d4`). `api/settings.py` exposes it on the existing settings GET and PUT. No new settings UI is part of this RFC; the setting is editable through the existing advanced settings JSON.

---

## Reconciliation

| With | Rule |
| --- | --- |
| **RFC-0224 / #649 (landed `ee786dc`)** | Its engine is reused unchanged (§4). S2 adds `seed_workflow`, the pipeline tables and `LargePromptSettings`, and copies no #649 code. Pipeline parents are marked by their `large_prompt_pipelines` row and bypass #649's model planner (S4 entry before `loop.py:2344`; `test_649_planner_not_called_for_pipeline_parent_or_child`). Children are seeded, so they never auto-plan. Every other task keeps #649's behaviour. `tests/test_rfc0224_task_workflow.py` is not edited and must stay green. |
| **RFC-0211 / #585** | Sections are rows a future scheduler can list as "upcoming tasks". When `DevelopmentScheduler` lands, its `resource_hold` (L380-411) is respected: dispatch defers while a hold names Ollama, with the parent event "Waiting for the scheduler's model hold". Nothing here waits on #585. |
| **RFC-0026 / 0029** | Children are ordinary durable tasks created through `AgentRuntime.create_task`. Follow-ups use `/continue`, and recovery uses `continue_task`. There is no second task system. |
| **Reflex arbitration** | One decide per owner turn, with two riders only when a candidate exists. The ack is a fixed front notice worded from the gate outlook, so `keep_worker` semantics apply to the parent result (§1). |
| **RFC-0218 S3b (+ #663)** | The parent turn's persona block runs first, unchanged. `switch_id = task_id:seq` is counted on the parent only. Children never call `apply_persona_switch`, so they publish no `persona_switched` or `persona_switch_failed`, and their `seq` counter stays empty. The 0218 test `t(acknowledgement) − t(persona_switched) < 50 ms` still holds, because the large branch publishes the `acknowledgement` event in the same position. |
| **RFC-0225 S3** | The preload goes through `activate_runtime_profile(target, persist=False, task_id=parent)`, which 0225-S3 routes through `prepare_engine_for`. There is no separate VRAM gate, loader or owner-line channel. 0231 uses 0225's own gate inputs for the ack outlook, holds a 0225 request lease on the target for the whole parent (steps 6 and 7 respect it), and never unloads a model ANZU did not load. 0231-S0 is the second owner of `engine_coexistence.py` and 0231-S4 the third of `hotswap.py`; #652's file tables name both. |
| **RFC-0228 S1 / S4** | Not the owner of `anzu-coder-27b`: 0228-S1 is the Fable 9B default and 0228 L360 excludes the coder. No `model-catalog.json` entry is added (not an installer asset). |
| **RFC-0225 S3 (gate requirement)** | 0231-S0 adds the `anzu-coder-27b` requirement (12 GB) as the first lookup in the step-5 gate. The gate logic, ledger and owner lines stay 0225's. |
| **RFC-0228 S2** | An ANZU-loaded target is warmed with `keep_alive: "-1"` while the lease is held and handed back to `idle_unload_seconds` at release. The restore goes through the owner's unchanged saved selection and `schedule_orchestrator_restore` → `NINE_B_REWARM`. The hold API is added to `rewarm.py` after 0228-S2. |
| **`agent/intake.py`** | Left in place for `stream_owner_chat`. The large pipeline replaces its use only on the tasks path. Merging the two is out of scope. |
| **RFC-0232 (#664)** | **Precedence (CoS, verbatim):** A turn whose prompt contains an absolute filesystem path together with RE intent (RFC-0232's narrowed dump/extraction detection) routes to reverse engineering and is never split by RFC-0231; a path with a plain or coding question routes normally. 0232-S2's RE helper (two-stage, specified in #664) is called by 0231's precheck and suppresses the riders; 0232's RE floor in `_apply_floors` runs before 0231's; one `decide()` per turn (§1). Tests: 0232's `test_path_plus_re_intent_routes_to_re_before_large_prompt_split` (`tests/test_rfc0232_intent_and_alias.py`); 0231's `test_path_plus_re_intent_routes_to_re_not_split`, `test_plain_path_question_not_routed_to_re`, `test_ffs_word_coding_question_not_routed_to_re`, `test_one_decide_per_turn`. Files: 0232-S2 (`owner_turn.py`) before 0231-S1; 0232-S3 → S4 → S5 (`loop.py`) before 0231-S4 and -S5. |
| **RFC-0230 (#666)** | Its slices go **first** on the shared turn files: `loop.py` (0230-S0 → S2 → S3, after 0218-S3b), `owner_turn.py` (0230-S5, after 0218-S3b), `api.ts` (0230-S0). Then RFC-0232, then 0231. On `main.py` RFC-0225 goes first (0225-S1 → S2 → S3 → 0230-S0 → S5 → 0231-S0 → S5). The large ack is the parent's front-lane line (rule 1), marked with 0230-S0's `mark`, and is held to 0230's ≤ 1.5 s p50 / ≤ 2.0 s p95 through three large cases appended to `scripts/anzu-latency-repro.ps1`. On a large verdict 0231 calls 0230-S3's `turn_prewarm.cancel_prewarm(turn_id)`. Row 6 (the two-system-message HTTP 500) is fixed in code by landed #649 (#666). |

## Relationship to #649 and #585

| Draft hunk | Taken? | Where |
| --- | --- | --- |
| #649 models, `TaskWorkflow` engine, loop workflow execution, `prompt_steps`, `large_task_reviews`, UI steps | **Landed; reused unchanged** (`db/models.py:66-88`, `task_workflow.py:15-19`, `:40-112`, `:172-177`, `loop.py:2344-2349`, `:2709-2722`, `:2981-2983`, `:3639-3660`, `:776-788`, `TaskActivity.tsx:306-319`) | S2 (seeding only), S5, S6 |
| #649 `is_large_request` | **Landed; imported** as rules L4 (`task_workflow.py:31-37`) | S1 |
| #649 `PLAN_SYSTEM` / `prepare_workflow` / auto-plan branch / `append_followup` | Landed; **not used by the pipeline** and left unchanged for every other task (§4) | — |
| #649 `basic_qa` reply shape | Landed (`owner_turn.py:43`); the S1 precheck excludes it | S1 |
| #585 scheduler | Not ported (respected when it lands) | S5 |

---

## Slices (one ticket each, one developer each, fast off)

### S0: `anzu-coder-27b` runtime profile, VRAM requirement, enable reconcile, gate outlook and leases

**Model:** Grok 4.5 · **Lane:** D1 · **Depends:** RFC-0225 S3 (creates `engine_coexistence.py` with `prepare_engine_for`, `owner_line`, `anzu_loads`; `main.py` chain)

| File | Change |
| --- | --- |
| `backend/app/inference/model_stack.py` | `MODEL_CATALOG["anzu-coder-27b"]` `SpecialistModel` (§2a values); only owner in the batch |
| `backend/app/inference/anzu_coder.py` (new) | `VRAM_ESTIMATE_GB`, `vram_requirement_gb`, `reconcile_anzu_coder_profile(*, attempts=10, timeout_s=3.0)`, `last_outcome()` |
| `backend/app/inference/engine_coexistence.py` | Second owner after 0225-S3 (listed in #652's S3 file table): the step-5 requirement lookup consults `anzu_coder.vram_requirement_gb(target)` first; `gate_outlook`; `hold_request_lease` / `release_request_lease` / `held_leases` counted as request leases in steps 6 and 7; `owner_line(..., speak=True)` keyword (§2a) |
| `backend/app/main.py` | One line: `_start_optional_step("anzu_coder_profile", reconcile_anzu_coder_profile)` plus its import |
| `tests/test_rfc0231_anzu_coder_profile.py` (new) | Below |

Tests (CI: `pytest` job, step "Run full backend suite", `.github/workflows/pr-tests.yml:94-95`):
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
- `test_gate_outlook_refuse_for_owner_loaded_9b_managed_off`: LM Studio `127.0.0.1:1234` 9B owner-loaded, `is_managed` false → `refuse`; no HTTP or NVML call is made (fakes assert zero calls).
- `test_gate_outlook_resident_and_allow`: target in `anzu_loaded_instances()` → `resident`; ANZU-loaded 9B → `allow`.
- `test_request_lease_blocks_step6_unload`: an ANZU-loaded `anzu-coder-27b` with a held `hold_request_lease` token is not unloaded when a 9B `prepare_engine_for` runs; after `release_request_lease` it is.
- `test_owner_line_speak_false_publishes_event_not_tts`: `owner_line(..., task_id=t, speak=False)` publishes the `engine_notice` task event and the ephemeral frame, and no task `chat_tts`; the default still publishes `chat_tts`.

### S1: Large-prompt detection riders

**Model:** Grok 4.5 · **Lane:** D2 · **Depends:** RFC-0232 S2 (#664: the RE-intent helper `planning.re_intent_match` and its RE floor in `_apply_floors`; hard dependency, S1 does not start before it is merged). Merge order on `owner_turn.py`: #649 → 0218-S3b → 0230-S5 → 0232-S2 → 0231-S1 (CoS ruling 2026-10-20).

| File | Change |
| --- | --- |
| `backend/app/decision/large_prompt.py` (new) | `precheck` (one call to 0232's RE helper, then L1-L5 on the raw text and the split-mode rule), `LargePromptPrecheck`, `LargePromptIntent` |
| `backend/app/decision/owner_turn.py` | Precheck in `decide_owner_turn` next to `resolve_persona_context` (L563); candidate and riders in `_decide_sync` (the one `decide()` is unchanged in count); large floor and final gate in `_apply_floors` (L296-370) **after** 0232-S2's RE floor; riders in `_deadline_rules_result` (L373-400); new `_with_deadline_large_prompt` on the Timeout and Exception paths (L585-630); `large_prompt` field on `OwnerTurnDecision` (L145-158) |
| `backend/app/decision/adapters/rules.py` | Rider branches `large_prompt` and `large_prompt_split`, reading only the scalar keys `large_prompt_floor` and `large_prompt_rules` (0231-S1 only) |
| `backend/app/agent/request_routing.py` | Pass-through of the field (no new decide) |
| `tests/test_rfc0231_large_prompt_decision.py` (new) | Below |

Tests (CI: `pytest` job, step "Run full backend suite", `.github/workflows/pr-tests.yml:94-95`). Every test below goes through `decide_owner_turn`, not `rules.decide`:
- `test_path_plus_re_intent_routes_to_re_not_split`: a 4500-char prompt with `D:\cases\x\ffs`, RE dump/extraction intent and 3 questions → route `managed_task` with the RE task class from 0232-S2, `large_prompt is None`, no rider appended, the persona precheck still ran, exactly one `decide`. Same result on the deadline and exception paths (blocking or raising provider). The RE helper is faked at its #664 interface, so this test does not depend on its probe internals. This is 0231's side of 0232-S2's `test_path_plus_re_intent_routes_to_re_before_large_prompt_split` (`tests/test_rfc0232_intent_and_alias.py`).
- `test_plain_path_question_not_routed_to_re`: `C:\code\etl what does the extraction step do?` → not RE; normal routing (no `large_prompt`, since no rule fires), exactly as with the feature off.
- `test_ffs_word_coding_question_not_routed_to_re`: `C:\Users\taco\proj ffs why does the build fail?` → not RE; normal routing. The same text padded with a 4500-char build log → not RE and `large_prompt.verdict == "large"` (0231 routing).
- `test_size_rules_use_full_prompt_not_reflex_projection`: a 5000-char prompt (L1) and a 900-char 5-item list (L2) give `large` through `decide_owner_turn`, although `compact_state` cuts the projection to 800 chars.
- `test_deadline_fallback_keeps_large_verdict_and_full_question`: a provider that blocks past the 50 ms `wait_for` on a 5000-char prompt → `decision_source == "deadline_fallback"`, `large_prompt.verdict == "large"`, and the decision's `user_message` is the full 5000 chars. Same for a provider that raises.
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
| `backend/app/db/models.py` | Only: `LargePromptPipeline` and `LargePromptSection` (§4 tables), appended after `TaskPromptStep` (L75-88); the #649 models are untouched |
| `backend/app/agent/task_workflow.py` | Only: append `StepSpec` and `seed_workflow` after `workflow_payload` (L172-177); every landed #649 function is untouched (second owner after #649) |
| `backend/app/config.py` | Only: `LargePromptSettings` and `AppSettings.large_prompts`, next to `decision` (`config.py:512`); `large_task_reviews` (L494) is #649's and is untouched |
| `backend/app/api/settings.py` | Only: `large_prompts` on the existing GET/PUT, next to #649's `large_task_reviews` (L72, L240-241) |
| `tests/test_rfc0231_prompt_steps.py` (new) | Below |

`agent/loop.py` and `api/tasks.py` are **not** edited by S2. #649's hunks are already there; S4 and S5 own the 0231 hunks in those files.

Tests (CI: `pytest` job, step "Run full backend suite", `.github/workflows/pr-tests.yml:94-95`; the landed `tests/test_rfc0224_task_workflow.py` runs in the same step and must stay green):
- `test_seed_workflow_writes_plan_and_steps_in_caller_session`: rows are visible in the same session before commit; `task.plan_json` lists the prompts.
- `test_seed_workflow_idempotent`: a second call writes nothing.
- `test_seed_workflow_bounds`: 0 steps, 13 steps, and a goal over 16000 chars each raise `ValueError`, and no rows are written.
- `test_seeded_child_runs_on_landed_engine_without_planner`: a seeded task runs its stored prompts in order through `loop.py:2709-2722` / `:3639-3660`, and `MANAGER.chat` is never called with `PLAN_SYSTEM`.
- `test_seeded_steps_include_deeper_and_quantitative_and_reviews_toggle`: `large_task_reviews` on gives work, deeper, quantitative, bugfix, fact_check, quality_control; off gives the first three.
- `test_tables_created_on_fresh_db` (`init_db` on an empty DB).
- `test_large_prompts_settings_roundtrip` (GET/PUT, defaults `enabled=True`, `target_runtime="anzu-coder-27b"`, `store="db"`).
- `test_unseeded_large_request_keeps_649_planner`: with no pipeline row, an `is_large_request` prompt still goes through `prepare_workflow` exactly as landed.

### S3: Split, completeness, compile, mandatory sub-tasks, persistence

**Model:** Grok 4.5 · **Lane:** D2 · **Depends:** S2

| File | Change |
| --- | --- |
| `backend/app/agent/large_prompt_intake.py` (new) | split, completeness rounds, repairs, compile, step specs, validators, DB and vault persist |
| `tests/test_rfc0231_large_prompt_intake.py` (new) | Below |
| `tests/fixtures/rfc0231/` (new) | Prompt fixtures: 5-item list, 4 questions, 6000-char spec, dangling-reference section, 12 headings |

Tests (CI: `pytest` job, step "Run full backend suite", `.github/workflows/pr-tests.yml:94-95`):
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

### S4: Ack, preload, create_task large branch, lease, rewarm hold

**Model:** Grok 4.6 · **Lane:** D1 · **Depends:** **S0** (target profile, requirement, `gate_outlook`, leases, `owner_line(speak=)`; hard dependency, S4 does not start before S0 is merged), S1, S2, S3, RFC-0225 S3 (`prepare_engine_for` in `hotswap.py`), RFC-0228 S2 (`inference/rewarm.py`, `hotswap.py`), RFC-0218 S3b (`create_task` persona block), RFC-0230 S0 (`turn_trace.mark`, `scripts/anzu-latency-repro.ps1`) and S3 (`turn_prewarm.cancel_prewarm`), RFC-0232 S3/S4 (`loop.py` order)

| File | Change |
| --- | --- |
| `backend/app/agent/large_prompt.py` (new) | `resolve_target` (enabled rows, no-target reason, bounded late reconcile inside the preload task), `preload` (lease, `/api/ps` check, `record_anzu_load`, `keep_alive` pin and release), ack texts by outlook, restore |
| `backend/app/agent/loop.py` | Large branch in `create_task` after 0230's prewarm/decision, 0232's RE dispatch, the Task commit and S3b's block (replacing the generic ack L548-557 for large turns only): pipeline row (the mark), `cancel_prewarm`, `gate_outlook`, one ack with `mark(..., "tts_enqueued", lane="front")`, preload start. In `_run`: for a pipeline parent, skip `_run_managed_front_lane` and the front-off fallback (L2420-2445) and return into the parent runner **before** `loop.py:2344`, so #649's planner never runs for a pipeline parent |
| `backend/app/inference/hotswap.py` | Only: keywords `persist: bool = True` and `task_id: str \| None = None` on `activate_runtime_profile` (L197); `persist=False` skips the save at L231-232; `task_id` is forwarded to `prepare_engine_for`. Third owner after 0225-S3 → 0228-S2 |
| `backend/app/inference/rewarm.py` | `hold` and `release`, plus deferral while held (second owner after 0228-S2) |
| `scripts/anzu-latency-repro.ps1` | Append one `--cases tests\fixtures\rfc0231\latency_cases.json` argument (0230-S0's case-file hook) |
| `tests/fixtures/rfc0231/latency_cases.json` (new) | Three large typed turns built from the S3 fixtures (5-item list, 4 questions, 6000-char spec) |
| `tests/test_rfc0231_ack_preload.py` (new) | Below |

Tests (CI: `pytest` job, step "Run full backend suite", `.github/workflows/pr-tests.yml:94-95`):
- `test_ack_chat_tts_within_150ms_of_decision`: `BUS.publish` timestamped, preload fake blocks for 5 s, assert ≤ 150 ms.
- `test_ack_not_delayed_by_split`: split fake blocks for 5 s; the ack is still ≤ 150 ms and the split starts after the ack event.
- `test_parent_speaks_exactly_one_line_before_part_results`: a 3-part pipeline with the front lane enabled → exactly one `chat_tts` on the parent before its terminal outcome (the ack); no `_run_managed_front_lane` call, no front-off fallback `chat_tts`, no `publish_owner_text`; part, gate and needs_owner lines are events only.
- `test_ack_marked_on_front_lane`: one `tts_enqueued` mark with `lane="front"` and `source="large_prompt_ack"` on the turn trace.
- `test_large_verdict_does_not_prewarm_9b`: with an unloaded 9B and outlook `allow`, `cancel_prewarm` is called and no 9B `prepare_engine_for` is issued by the prewarm.
- `test_ack_variant_when_gate_will_refuse`: Taco's default (LM Studio 9B owner-loaded, managed off) → the `refuse` text, which contains no "load"; no preload started; one event naming the managed-mode toggle; the parts run on the 9B and the parent completes.
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
- `test_preload_ollama_anzu_loaded_recorded`: `/api/ps` without the model → warm with `keep_alive "-1"` → listed → exactly one `record_anzu_load("ollama@127.0.0.1:11434", "anzu-coder-27b")`, `preload_status == "loaded"`.
- `test_preload_ollama_owner_loaded_not_recorded`: `/api/ps` already lists it → no warm call, no `record_anzu_load`, `preload_status == "already_loaded"`.
- `test_preload_uses_activate_runtime_profile_only`: no `MANAGER.load` or direct engine call outside `activate_runtime_profile`.
- `test_preload_never_persists_selection`: `settings.json` is byte-identical before and after preload and through the whole pipeline; `activate_runtime_profile` was called with `persist=False`; every existing caller still persists (default).
- `test_owner_selection_restored_after_pipeline`: after the parent completes, `MANAGER.state` is the owner's saved selection again and the ANZU-loaded 27B got `keep_alive` back to `"<idle_unload_seconds>s"`.
- `test_restore_with_settings_merge`: the owner saves a different model mid-pipeline through settings (`_merge_settings_changes`) → nothing is restored over it.
- `test_target_held_across_parts_and_waiting`: between part 1 and 2, and for 20 fake minutes in `waiting`, neither RFC-0225 step 6, the RFC-0228 idle path nor the rewarm restore unloads the target; the lease is released only at parent terminal.
- `test_chat_turn_between_parts_does_not_unload_target`: a chat turn between two parts is answered on the loaded target and the target stays resident.
- `test_chat_turn_during_pipeline_routes_to_target`: `prepare_answer_route` for a concurrent chat turn uses the target, and the front lane still speaks first.
- `test_resume_after_keep_alive_expiry_repreloads`: target no longer in `/api/ps` when the owner sends `/continue` (and on `recover_on_startup`) → `preload` runs again before the next dispatch.
- `test_preload_timeout_180s_fallback`, with a fake clock.
- `test_hold_defers_rewarm_until_release`.
- `test_649_planner_not_called_for_pipeline_parent_or_child`: `MANAGER.chat` is never called with `PLAN_SYSTEM` for a parent (marked by its pipeline row) or a seeded child.
- `test_649_planner_unchanged_when_large_prompts_disabled`: with `large_prompts.enabled=false`, a 4000-char prompt goes through `prepare_workflow` exactly as landed.

**Live audit** (on Taco's PC; numbers recorded in the PR, none invented in advance): the three large-turn cases in `scripts/anzu-latency-repro.ps1` against RFC-0230's ≤ 1.5 s p50 / ≤ 2.0 s p95 first audible word; once with managed mode off (expected: `refuse` ack, parts on the LM Studio 9B, nothing unloaded) and once with it on (gate unload path, 27B used, 9B restored after the pipeline); which gate path ran in each.

### S5: Sequential queue, lifecycle, follow-ups, recovery

**Model:** Grok 4.6 · **Lane:** D1 · **Depends:** S4

| File | Change |
| --- | --- |
| `backend/app/agent/large_prompt_queue.py` (new) | `is_pipeline_parent`, `dispatch_next` (breaker admit + bind), `on_child_terminal` (cancelled-pipeline check first), `on_parent_cancel`, `on_child_cancel_api`, parent completion, `payload`, `recover_on_startup` (lease, hold, re-preload) |
| `backend/app/agent/loop.py` | `pipeline_section` keyword in `create_task`; child path in `_run` (no front lane, seeded workflow, target profile); validator gate for `deeper` / `quantitative` steps before `workflow.finish_current` (L3639-3640) and before the final completion of the last stored step (S3 validators, 2 retries, then `_fail_task` with the S3 text); terminal hook call (L800-826); cancel hook (L733-738); `/continue` redirect (L561-590) and parent follow-up with re-preload |
| `backend/app/api/tasks.py` | `large_prompt` payload in `get_task` (L256-289) and `get_task_observability` (L292-308); `cancel_task` (L341-352) routes pipeline children through `large_prompt_queue.on_child_cancel_api` |
| `backend/app/main.py` | One startup call to `recover_on_startup` |
| `tests/test_rfc0231_large_prompt_queue.py` (new) | Below |

Tests (CI: `pytest` job, step "Run full backend suite", `.github/workflows/pr-tests.yml:94-95`):
- `test_parts_run_strictly_sequential`: part 2 is created only after part 1 is terminal.
- `test_child_ids_stable_uuid5`.
- `test_breaker_admission_and_kill_switch_stops`.
- `test_breaker_run_bound_to_child`: every admitted run is bound with `bind_run_to_task` to its child; 8 completed parts in a row never trip the breaker or exhaust its budget.
- `test_child_no_decide_no_persona_no_ack_no_speech`.
- `test_failed_part_fails_parent_with_text`.
- `test_child_cancel_skips_part`.
- `test_parent_cancel_cancels_child_and_rest`: after `AGENT.cancel(parent)` the running child's terminal hook sees the cancelled pipeline; no further `create_task`, every remaining section `cancelled`, lease and hold released.
- `test_cancel_queued_child_advances`: `POST /api/tasks/{child}/cancel` on a queued child with no runner marks the part `skipped` and dispatches the next one.
- `test_needs_owner_waits_then_continue_one_round`.
- `test_skip_part_n`.
- `test_followup_appends_part_dedupe`.
- `test_continue_on_child_redirects`.
- `test_parent_combined_result_and_verification`.
- `test_restore_after_parent_terminal`.
- `test_recovery_redispatch_advance_resume`: also re-takes lease and hold and re-preloads a non-resident target.
- `test_large_prompt_payload`: same object on `GET /api/tasks/{id}` and `/observability`.
- `test_validator_gate_retries_stored_step_then_fails_visibly`: a quantitative step whose result has no numeric row is retried twice with the validator message, then the child fails with "Part n of N: quantitative sub-task did not meet its format after 3 attempts", and `finish_current` is never called for it.

### S6: Large-prompt sections in the live "Saved plan" block

**Model:** Composer 2.5 · **Lane:** UX · **Depends:** S5, RFC-0230 S0 and RFC-0218 S3 (sequential owners of `api.ts`)

| File | Change |
| --- | --- |
| `frontend/src/components/largePromptSectionsView.ts` (new) | Pure view model (§6): rows, chips, actions with method and path, child line, status line |
| `frontend/src/components/LargePromptSections.tsx` (new) | Thin render of the view model |
| `frontend/src/components/TaskActivity.tsx` | Add-only: the `||` in the L306 condition and one mount after the existing `<ol>` (§6). The landed rows (L306-319) are otherwise byte-identical |
| `frontend/src/taskStatus.ts` | Add-only: `large_prompt` in `mergeObservability` (L203) and in the `TaskObservability` field list |
| `frontend/src/api.ts` | Add-only `LargePromptPayload` and `Task.large_prompt?` / `TaskObservability.large_prompt?` |
| `frontend/large-prompt-sections.test.mjs` (new) | Imports only `.ts`: view-model rows, chips, button→endpoint mapping, child line, `null` without payload, `humanizeToken` labels for `deeper`/`quantitative`, and `mergeObservability` preserving `large_prompt` and every existing field |
| `frontend/package.json` | Append `test:large-prompt-sections` (`node --experimental-strip-types large-prompt-sections.test.mjs`) |
| `.github/workflows/pr-tests.yml` | Append the step `Large prompt sections tests (RFC-0231 S6)` → `npm run test:large-prompt-sections` after "Persona morph hook tests (RFC-0218 S5)" (L130) in `frontend-build`. The existing "Build frontend" step (`npm run build`, L118-119) is the TSX gate |

## Ownership chains (handoff order on shared files)

On `loop.py` and `owner_turn.py` the order is RFC-0230 (#666), then RFC-0232 (#664), then RFC-0231 (CoS ruling 2026-10-20), matching #664 @ `df37b22` and #666. The 0231 tickets merge onto whichever of those has landed, with merge commits.

| File | Order |
| --- | --- |
| `backend/app/agent/loop.py` | #649 (landed) → 0218-S3b → 0230-S0 → 0230-S2 → 0230-S3 → 0232-S3 → 0232-S4 → 0232-S5 → 0231-S4 → 0231-S5. In `create_task`: 0230's `prewarm_worker` and route decision, then 0232's RE dispatch (S3 FFS, S5 APK), then 0231's large branch |
| `backend/app/decision/owner_turn.py` | #649 (landed) → 0218-S3b (not landed) → 0230-S5 → 0232-S2 → 0231-S1 |
| `backend/app/decision/adapters/rules.py` | 0231-S1 only |
| `backend/app/config.py` | #649 (landed) → 0228-S1 → 0228-S2 → 0231-S2 → #585 (draft; rebases onto whatever has landed when it is picked up) |
| `backend/app/main.py` | 0225-S1 → 0225-S2 → 0225-S3 → 0230-S0 → 0230-S5 → 0231-S0 → 0231-S5 → #585 (draft, same rule). RFC-0225 goes first on `main.py` (CoS) |
| `backend/app/api/tasks.py` | #649 (landed) → 0231-S5 |
| `backend/app/inference/hotswap.py` | 0225-S3 → 0228-S2 → 0231-S4 (keywords only) |
| `backend/app/inference/engine_coexistence.py` | 0225-S3 (creates it) → 0231-S0 (#652 S3 file table names the second owner) |
| `backend/app/inference/rewarm.py` | 0228-S2 (creates it) → 0231-S4 |
| `backend/app/inference/model_stack.py`, `backend/app/inference/anzu_coder.py` | 0231-S0 only |
| `backend/app/db/models.py` | #649 (landed) → 0231-S2 |
| `backend/app/agent/task_workflow.py` | #649 (landed, created it) → 0231-S2 |
| `backend/app/api/settings.py` | #649 (landed) → 0231-S2 |
| `scripts/anzu-latency-repro.ps1`, `scripts/latency_repro.py` | 0230-S0 (creates them) → 0231-S4 (append-only: one `--cases` argument) |
| `frontend/src/api.ts` | 0230-S0 (`X-ANZU-Input-End`) → 0218-S3 → 0227 (selection helpers) → 0231-S6 |
| `frontend/src/taskStatus.ts`, `frontend/src/components/TaskActivity.tsx` | #649 (landed) → 0231-S6 |
| `frontend/package.json`, `.github/workflows/pr-tests.yml` | **Append-only.** The Architect owns the workflow file. Open appenders: #662 (0229-S1), 0228-S2, 0230-S0, 0230-S3, 0232-S6 and 0231-S0…S6. Rule: each ticket appends its own step, never edits another's, and on a conflict merges `development` with a merge commit and keeps both steps |

## Ticket cards

| ID | Title | Model | Lane | Depends |
| --- | --- | --- | --- | --- |
| 0231-S0 | `anzu-coder-27b` profile, VRAM requirement, reconcile, gate outlook, leases | Grok 4.5 | D1 | 0225-S3 |
| 0231-S1 | Large-prompt detection riders (full-prompt precheck, RE precedence) | Grok 4.5 | D2 | **0232-S2** (merge order after 0230-S5) |
| 0231-S2 | Workflow seeding on landed #649, pipeline tables, settings | Grok 4.5 | D2 | S1 (order) |
| 0231-S3 | Split, completeness, compile, sub-tasks, persistence | Grok 4.5 | D2 | S2 |
| 0231-S4 | Ack, preload, create_task branch, lease, rewarm hold | Grok 4.6 | D1 | **S0**, S1-S3, 0225-S3, 0228-S2, 0218-S3b, 0230-S0/S3, 0232-S3/S4 |
| 0231-S5 | Sequential queue, lifecycle, recovery | Grok 4.6 | D1 | S4 |
| 0231-S6 | Large-prompt sections in the live "Saved plan" block | Composer 2.5 | UX | S5, 0230-S0, 0218-S3 |

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
- [ ] On Taco's PC (Ollama lists `anzu-coder-27b:latest`), the S0 profile is enabled at startup and is the preload target; on an install without it, the template stays disabled and routing is unchanged.

## Out of scope

- Persona, presence, WebGL, morph and voice choice (Astra).
- Merging `agent/intake.py` with this pipeline.
- Parallel execution of parts.
- A settings UI for `large_prompts`.
- Changing `stream_owner_chat`.
- The #585 scheduler itself.

## Risks

- **27B load time over 180 s on a cold disk.** Mitigation: defined fallback plus owner line. The deadline is a module constant, so it is tunable after the live audit.
- **Deterministic split mis-sections free prose.** Mitigation: completeness repairs and the owner `needs_owner` loop. N == 1 is always valid.
- **The quantitative format feels forced on qualitative parts.** Mitigation: the "Measurable criteria" row keeps the format honest without inventing numbers.
- **Collisions in `loop.py`.** Mitigation: the strict ownership chain above, with two 0231 slices (S4, S5) in sequence after landed #649.
