# RFC-0231: Large-prompt pipeline (reflex detect, immediate large-model load, spoken ack, split, completeness, durable sequential prompts)

**Status:** accepted
**Priority:** P1 (Taco ask B, relayed by Chief of Staff 2026-10-20)
**Author:** Jarvis Architect
**Date:** 2026-10-20
**Traced on:** `development` @ `11b264a7`. Drafts and RFC PRs pinned: #649 @ `edb4685` (identical to `b5c3640` for every file cited here), #652 (RFC-0225) @ `140482b`, #655 (RFC-0228) @ `973b979`, #585 (RFC-0211) @ `f412dad`, #663 (RFC-0218 delivery fix) @ `c5db314`.
**Amended 2026-10-20 (CoS, #665 peer):** the large target `anzu-coder-27b` was assumed to exist as a runtime profile. It does not (see *Target profile: `anzu-coder-27b`*), so new slice **0231-S0** adds it and 0231-S4 hard-depends on it. Re-traced for S0 and for the `hotswap.py`, `config.py` and `main.py` citations on `development` @ `d214b6d` (#648 landed; #663 landed at `781004c`), #652 @ `916cf25`, #655 @ `971ca15`, #649 @ `edb4685`.

**Owner ask (Taco, ask B, intent as relayed):** when Taco speaks or types a large or complex task, Jev/Laya decide that it is complex. Then:
1. ANZU immediately loads the large model (anzu-coder-27b or whichever large model applies). `anzu-coder-27b` is the 0231-S0 runtime profile.
2. In parallel, the small front model says something short, such as "This is a large task, I'm loading the larger model."
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
- [RFC-0224](0224-responsive-conversation-and-durable-task-prompts.md) (#649 draft): persisted prompt stages. Its engine is ported here.
- [RFC-0225](0225-local-engine-coexistence-and-resilient-api.md) (#652): `prepare_engine_for` and the VRAM gate.
- [RFC-0228](0228-installer-update-default-9b-idle-unload.md) (#655): the `NINE_B_REWARM` coordinator.
- [RFC-0218](0218-persona-surfaces-and-intent-switch.md) S3b, as amended by #663: tasks-path persona switch, `switch_id`, switch line delivered as `chat_tts`.
- [RFC-0211](0211-ollama-self-development-scheduler.md) (#585 draft): the scheduler.
- [RFC-0071](0071-automation-failure-circuit-breaker.md): breaker admission.

Some of these links point at RFC files that live only on their open PRs. They resolve once those PRs land.

**Drafts #649 and #585:** neither gates this RFC. The pieces that overlap are ported with hunk citations (see *Relationship to drafts*).

**Astra boundary:** persona, WebGL, presence, morph and appearance are out of scope (Astra). This RFC emits no persona events and edits no persona or presence component.

This PR is **specs-only**. It contains no application code.

---

## Problem

Verified on `development` @ `11b264a7`.

1. **"Large" is not a decision.** The single owner-turn decide (`decision/owner_turn.py::decide_owner_turn` L517-610, via `agent/request_routing.py::evaluate_request_route`) yields route, tier and `persona_intent` (`OwnerTurnDecision` L144-156). Nothing decides "this prompt is a multi-part large task". The only related signals are:
   - `policy.local_complexity_tier` (`decision/policy.py:25`): tier 4 for expert hints or more than 4000 chars, tier 3 for complex hints or more than 1200 chars.
   - The separate `complexity_escalation` surface (`decision/surfaces.py:360-380`).
   - #649's regex `is_large_request` (#649 `agent/task_workflow.py:31-37`), which is not a reflex decision.
2. **No immediate load of the large model.** `prepare_answer_route` only runs when the loaded model is an orchestrator, or tier ≤ 1 (`agent/loop.py:2455-2475`), and it runs inside `_run`, after the front lane. A large prompt starts on whatever model is loaded. The swap to the large model happens later, if it happens at all, through `execute_visible_model_switch` (`inference/model_escalation.py:128-203`).
3. **No large-task ack.** `create_task` publishes the generic `task_acknowledgement(prompt)` as an `acknowledgement` event (`loop.py:547-556`), and it is not spoken. As #663 found, `publish_owner_text` goes to `OWNER_CHAT_CHANNEL` (`persona/chat_delivery.py:71`, `:100`), and no client reads that channel. The only path the live UI speaks is a `chat_tts` event on the task stream: `useTaskSpeech.ts:41-56` → `queueChatSpeech`, mounted in HUD chat and Chat.
4. **The prompt is split only for a dead endpoint.** `agent/intake.py` has a sequential chain:
   - `MAX_SEQUENTIAL_PARTS = 8`, `part_prompt` L235-247, `advance_chain` L281-313.
   - Chains are stored as JSON files under `data/intake_chains`.
   - Its only caller is `persona/owner_chat.py:379-410`, the `stream_owner_chat` endpoint, which has no client.
   - Chat sends go to `/api/tasks`, which never splits. Splitting is all-or-nothing, with no completeness check.
5. **No completeness check.** No section-level check or bounded iteration exists anywhere.
6. **Durable prompt stages exist only in a draft.** #649 adds `TaskPromptPlan` and `TaskPromptStep` and executes them one at a time (#649 `db/models.py` +62-88, `agent/loop.py` +2672-2724, +3639-3662). That draft is not merged. Its planner also asks the model for the plan (`PLAN_SYSTEM`, #649 `task_workflow.py:20-28`), which needs the large model to be loaded first.
7. **No queue that runs owner prompts one after another.**
   - `mobile/scheduler.py::tick` (L77-121) runs periodic automations. It skips while the previous run is non-terminal (L88-94) and is admitted by `automation/breaker.admit_automatic_trigger` (L236-320).
   - `agent/queue_watcher.py` is a file drop queue.
   - #585's `DevelopmentScheduler` (L132, tick L380-411) is a draft and reserves Ollama for Grokbot work.
   - None of them takes N owner sub-prompts and runs them in order.
8. **No guaranteed deeper or quantitative work.** #649's steps are `work` plus `REVIEW_STEPS` (bugfix, fact_check, quality_control; #649 `task_workflow.py:15-19`). Nothing requires a deeper-analysis or quantitative sub-task, and nothing validates one.

## Decision

Ship **one RFC with seven implement slices (S0-S6)**, one named model per slice and fast mode off. Nothing waits for #649 or #585.

**Pipeline at a glance.** A large owner turn becomes one **parent task** (the one the HUD is already following) and N **child tasks**, one per section, run strictly one after another.

```
owner turn ─► decide_owner_turn (one decide, riders large_prompt / large_prompt_split)
   │ large
   ├─► Task row committed ─► RFC-0218 S3b persona block (unchanged)
   ├─► preload task started (not awaited): resolve target → activate_runtime_profile (RFC-0225 prepare_engine_for / VRAM gate) → warm
   ├─► ack: "acknowledgement" event + chat_tts on the parent stream (≤ 150 ms after the decision)
   └─► parent runner: split → completeness rounds (≤ 3) → compile detailed prompts → persist (DB, optional vault mirror)
          → await preload (≤ 180 s, defined fallback) → dispatch part 1 as a child task
child terminal hook ─► completed: dispatch next │ failed: stop, parent fails visibly │ needs_owner: parent waits
last part done ─► parent completes with the combined result ─► compare-and-restore settings ─► release rewarm hold
```

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

- **Precheck (rules, sync, under 1 ms)** in `_decide_sync` (`owner_turn.py:399-449`), next to the persona precheck. It produces a candidate only when **all** of these hold:
  - `route_kind == "managed_task"`;
  - `security_role == ""`;
  - the reply shape is none of literal, clarify, self_status or basic_qa;
  - `settings.large_prompts.enabled` is true;
  - at least one floor rule L1-L5 below fires.

  Without a candidate, no rider is appended and the decision is unchanged byte for byte.
- **Riders (appended to `OWNER_TURN_QUESTIONS` for that call only):**
  - `large_prompt`: choice `standard` | `large`, `decision_class="complexity_escalation"`.
  - `large_prompt_split`: choice `sections` | `questions`, `decision_class="workflow_branch"`.

  Both classes are already in `REFLEX_DECISION_CLASSES` (`decision/types.py:14-39`), so the unlisted-class check at `reflex.py:229-234` passes.
- **Rules floor**, in `decision/adapters/rules.py`, next to the arbitration branch (L226) and the persona rider branch (L237). `large` fires if any of these holds:
  - **L1:** `len(prompt) ≥ 4000`.
  - **L2:** at least 3 list items (`^\s*(\d+[.)]|[-*•])\s+`) and `len ≥ 600`.
  - **L3:** at least 3 question sentences (ending in `?`, or starting with an interrogative word in en/nl) and `len ≥ 200`. This also sets split `questions`.
  - **L4:** the project-scale patterns of #649 `is_large_request` (L31-37), ported verbatim into `decision/large_prompt.py`.
  - **L5:** `local_complexity_tier(prompt) == 4`.

  Split mode: `questions` when L3 fired and fewer than 3 list items exist, otherwise `sections`.
- **Floor semantics.** This follows the existing rule at `reflex.py:398-410`, where providers may raise a tier but never lower it.
  - A typed provider may raise `standard → large` only at confidence ≥ 0.75, and may never lower `large → standard`.
  - The deadline fallback (`_deadline_rules_result`, 50 ms `OWNER_TURN_DEADLINE_MS`) is the rules answer.
  - A provider's split answer wins only when L3 did not fire.
- **Output.** New field `OwnerTurnDecision.large_prompt: LargePromptIntent | None`, with fields:
  - `verdict`;
  - `mode`;
  - `rules_fired: tuple[str, ...]`;
  - `decision_source`;
  - `confidence`.

  `_apply_floors` (L278-350) applies the floor. `request_routing` passes the field through unchanged.
- **Arbitration class.** The large ack is a front notice, not an answer. The parent's final result is the combined child outcome, which matches `keep_worker` semantics (`surfaces.py:395-410`). `arbitrate_front_and_worker` is not called for the ack, because no front model text exists to arbitrate.

### 2. Ack and preload (S4)

**Insertion point.** In `AgentRuntime.create_task` (`loop.py:478-558`), in this order:
1. the `Task` commit;
2. RFC-0218 S3b's persona block (unchanged, including `publish_persona_switch_line` per #663);
3. this RFC's large branch.

The large branch replaces only the generic ack at L547-556:

1. **Start the preload** with `asyncio.create_task(large_prompt.preload(task.id, target))`. It is not awaited. The handle is stored on the runtime so cancel can reach it.
2. **Ack.** It is a fixed template, not front-model generation, because a model generation cannot meet the budget, the front model may be cold, and the 27B load contends for the GPU. It is published with:
   - `BUS.publish(task.id, "acknowledgement", "Acknowledged", text, stage="queued")`, the same event the 0218 S3b latency test measures;
   - `BUS.publish(task.id, "chat_tts", "Large task", text, stage="large_prompt_ack")`.

   The title is not `"Speak reply"`, so the ack never joins the reply prefix (`useTaskSpeech.ts:48`). The final combined result is still spoken in full. The ack is **never** sent through `publish_owner_text`, because that channel has no client (#663). The voice is the active persona's voice through the existing browser `queueChatSpeech`.
3. Record `ack_ms = (t_ack − t_decision_return) × 1000` on the pipeline row.
4. `_start_runner(task.id, self._run(task.id, continue_existing=False))`, unchanged.

**Ack texts** (en, module constants, owner-reviewable):

| Case | Text |
| --- | --- |
| Target resolved, not yet loaded | "This is a large task. I'm loading the larger model and splitting it into parts." |
| Target already loaded | "This is a large task. I'll split it into parts and work through them one by one." |
| No target available | "This is a large task. I'll split it into parts and work through them on the current model." |

**Latency budget (hard, normative).**
- **Server budget:** the ack `chat_tts` is persisted **≤ 150 ms** after `evaluate_request_route` returns. A CI test checks this with fakes, and with a preload fake that blocks for 5 s. The budget covers the Task commit, the 0218 persona block and two publishes.
- The decision itself stays under the existing 50 ms owner-turn deadline. The total is therefore ≤ 200 ms from turn start to ack event.
- **Audible budget:** first ack audio ≤ **1200 ms** after the decision on Taco's PC, with the TTS voice warm. This is a live audit (S4 acceptance), not CI.

**Target resolution** (`agent/large_prompt.py::resolve_target(settings) -> RuntimeProfile | None`, pure):
1. `settings.large_prompts.target_runtime` (default `"anzu-coder-27b"`, the 0231-S0 profile), matched against **enabled** runtime profiles (`list_runtime_profiles()`, `enabled is True`) by `name`, then `model_profile`, then the provider model id. A disabled row never matches, the same rule `route_runtime` applies (`runtime_router.py:284-285`).
2. Otherwise `route_runtime` (`runtime_router.py:320`) with `minimum_answer_tier=3`, `task_specialization="coding"` when `task_class` is code/build/debug and `"reasoning"` otherwise, and `preferred_profiles=("expert", "ornith_35b")`. This is ported from `answer_routing.py:57-71`, with tier 3 as the floor and no new router.
3. Otherwise `None`. The ack uses the "no target available" text and the pipeline runs on the current model, with `preload_status="no_target"` shown in the panel.

**Preload** (`large_prompt.preload`). No new loader:
1. Snapshot `settings.inference` (JSON) into `previous_selection_json`, because `hotswap.apply_runtime_profile_to_settings` persists what it applies (`hotswap.py:88-194` on `d214b6d`).
2. Take a rewarm **hold** (see *Rewarm hold*).
3. Call `await hotswap.activate_runtime_profile(target)` (`hotswap.py:197-238` on `d214b6d`). After RFC-0225 S3 this routes through `prepare_engine_for`: single-flight, revive or respawn, identity check, VRAM gate step 5, and owner lines. The pipeline adds no gate logic of its own.
4. Warm with `gpu_prefer.ensure_ollama_gpu` (L124) or `ensure_lmstudio_gpu` (L67), by provider. For an Ollama target (the S0 profile), the preload first reads Ollama `GET /api/ps`:
   - model already listed → no warm call (an owner-loaded model's `keep_alive` is not touched), not recorded in `anzu_loads`, `preload_status = "already_loaded"`;
   - model not listed → warm, then `GET /api/ps` again; listed → `engine_coexistence.record_anzu_load(engine_id="ollama@127.0.0.1:11434", model="anzu-coder-27b")` (RFC-0225 S3, #652 L43 "every model instance ANZU itself loaded into an engine it does not own"), `preload_status = "loaded"`; not listed → `failed:warm_not_resident`.
5. Set `preload_status`: `loaded`, `already_loaded`, `failed:<reason>`, `gate_refused:<reason>` or `timeout`.

**Preload outcomes (defined, never silent):**

| Outcome | Behaviour |
| --- | --- |
| loaded / already_loaded | Children run on the target. |
| VRAM gate refuses (owner-loaded 9B, managed mode off; RFC-0225 step 5) | RFC-0225's owner line names the reason. The pipeline then runs on the current model, and the parent shows one event, "Running on <current> — <reason>". |
| load error | The same fallback, with the error text in the event. |
| not loaded within `PRELOAD_DEADLINE_S = 180` | The preload task is cancelled, then the same fallback with "The larger model took too long to load". |
| owner cancels the parent during preload | The preload task is cancelled. Compare-and-restore runs and the hold is released. |

**Restore at pipeline end** (any terminal parent status):
- **Compare-and-restore:** if `settings.inference` still equals what the preload applied, restore `previous_selection_json` through `activate_runtime_profile` of the previous profile. If the owner changed the model meanwhile, leave it as it is and log.
- Then release the hold and call `schedule_orchestrator_restore` (`model_escalation.py:73-93`). After RFC-0228 S2 that call is `NINE_B_REWARM`, which reloads the 9B only after the 27B has left VRAM.

**Rewarm hold** (S4 edits `inference/rewarm.py`, after RFC-0228 S2 creates it):
- `NINE_B_REWARM.hold(reason: str) -> str` and `release(token)`.
- While any hold is held, both rewarm triggers defer, the same way they defer while the 27B is resident.
- `release` of an unknown token is a no-op.
- Holds are in-memory. Startup recovery (§5) re-takes a hold for every pipeline still `running`.

This prevents the 120 s idle restore from swapping the worker away between two parts. Only RFC-0228 S2 creates the coordinator, and this RFC adds the two methods.

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
  - *ANZU-loaded:* ANZU's preload warmed it and `/api/ps` did not list it before (§2 preload step 4). It is recorded in `anzu_loads`, and the reverse gate (step 6) may unload it with `keep_alive: 0` when the 9B needs the VRAM back.
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

Each outcome is logged once as `anzu_coder_profile outcome=<outcome>` and returned, so `startup_health` records it. This follows the existing rule that a discovered local model becomes an enabled runtime row (`model_discovery.py:338-366`). If the model is removed from Ollama later, the next preload fails visibly through `activate_runtime_profile` ("Model 'anzu-coder-27b' is not loaded in Ollama…") and takes the "load error" fallback in §2.

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
  - One `chat_tts` and one event go on the parent: `Part N isn't clear enough to start: <missing, ≤ 120 chars>. Tell me what you mean, or say "skip part N".`
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
- **Vault mirror:** applies when `public_binding_status` (`memory/obsidian_vault.py:305`) is bound and `large_prompts.store == "db_and_vault"`. `create_note` (L741) writes `_Temporal/LargePrompts/<parent_id>/part-NN.md` with frontmatter (parent, ordinal, status) and the detailed prompt. At part terminal, `edit_note` (L801) appends the result summary.
- **Owner-edit conflict:** `edit_note` reports a conflict without `force`. The pipeline does not force. It records `vault_conflict` on the row and shows one parent event, "Part n note was edited in Obsidian; ANZU left your edit and kept the result in ANZU".
- **Mirror failure:** produces a visible parent event. DB persistence and the run continue.
- `large_prompts.store` takes the values `"db"` (default) or `"db_and_vault"`.

### 4. Storage: #649's engine, ported (S2)

**Port** from #649 @ `edb4685`, verbatim except where noted. The ported tests go in `tests/test_rfc0231_prompt_steps.py`.

| From #649 | To | Port note |
| --- | --- | --- |
| `db/models.py` +62-88 `TaskPromptPlan`, `TaskPromptStep` (uq `task_id`+`ordinal`) | same | verbatim |
| `agent/task_workflow.py` `REVIEW_STEPS` L15-19, `TaskWorkflow` L40-98, `load_workflow` L101-112, `workflow_payload` L172-177 | same new file | verbatim. **Not ported:** `PLAN_SYSTEM`, `is_large_request` (moved to S1 rules L4), model-planned `prepare_workflow`, `append_followup`. The parent handles follow-ups (§5). |
| — | `task_workflow.seed_workflow(session, task_id, steps: list[StepSpec])` | new. Writes the plan and steps in the caller's session, before the runner starts. Idempotent on (`task_id`, `ordinal`). |
| `agent/loop.py` +2344-2349 (stored workflow load), +2672-2724 (workflow execution incl. `max_steps` L2719), +2968-2984 (per-prompt step limit), +3639-3662 (`finish_current`, advance to the next prompt), +776-788 (completion guard) | `agent/loop.py` | ported, but run only when a stored workflow exists. #649's auto-planning branch is not ported. |
| `api/tasks.py` +287-288, +304-307 (`prompt_steps` in the task payload) | `api/tasks.py` | verbatim |
| `config.py` +494 `large_task_reviews=True`; `api/settings.py` +72, +240-241 | same | verbatim |

**New tables** (`db/models.py`; created by `create_all`, no ALTER needed):

`large_prompt_pipelines`:
- `parent_task_id` (PK, FK tasks);
- `mode`;
- `status`: preparing | running | waiting | completed | failed | cancelled;
- `target_profile`;
- `preload_status`;
- `previous_selection_json`;
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
  - The id is stable, so a re-dispatch after a crash reuses the same child (`loop.py:492-499` request_id reuse).
- **`create_task(..., pipeline_section: str | None = None)`**, keyword-only, default `None`, so every existing call is unchanged. When it is set:
  - The route is fixed to MANAGED with the parent's task class and **no decide** (the parent turn already decided; still exactly one decide per owner turn).
  - No persona block, no large branch (no recursion) and no generic ack.
  - `seed_workflow` with `work, deeper, quantitative, *REVIEW_STEPS?` runs in the same session as the Task commit, before `_start_runner`.
  - The title is `Part n of N · <section title ≤ 60 chars>`.
- **`_run` for a child:** skip the managed front lane (L2400-2420) and its `chat_tts`. Children never speak, because the HUD follows the parent. Run the seeded workflow on the target profile. Per-child `speak_outcome` in the terminal hook is suppressed.
- **Terminal hook** (`_update`, L786-812), placed next to `advance_intake_chain`, as `large_prompt_queue.on_child_terminal(child_id, status, result)`:

| Child status | Effect |
| --- | --- |
| completed | Section `completed` with `result_summary`; vault `edit_note`; parent event "Part n of N done"; dispatch the next part. If the next part is `needs_owner`, the parent goes to `waiting` and repeats the line once. If there is no next part, the parent completes. |
| cancelled by the owner (child cancel) | Section `skipped`; parent event "Part n skipped"; dispatch the next part. |
| failed | Section `failed`; remaining sections `cancelled`. The parent **fails** with "Part n of N failed: <error ≤ 200>. Parts n+1–N were not started." That text is spoken by the existing outcome path. |
| kill switch / breaker | Same as failed, with the breaker reason. |

- **Parent completion:**
  - `result` is the per-part Markdown sections ("## Part n: title" plus result).
  - `verification` has one line per part: the part's own verification, plus "deeper ✓ quantitative ✓".
  - Status is `completed`. The existing `speak_outcome` and the `useTaskSpeech` final speech run unchanged.
  - Then the restore (§2).
- **Parent runner:**
  1. Run intake (§3).
  2. Await the preload up to its deadline.
  3. Set parent status `running` with `current_action` "Part 1 of N".
  4. Dispatch.
  5. **Return without a terminal status.** The parent stays `running` (or `waiting`), driven by the hook.

  `_update`'s terminal hook therefore never sees a parent until the pipeline itself sets it terminal.
- **Cancel:**
  - `AGENT.cancel(parent)` also cancels the running child and the preload task, and marks the rest `cancelled`. `cancel` (L732-737) gets one call, `large_prompt_queue.on_parent_cancel(parent)`.
  - `POST /api/tasks/{child}/cancel` (existing, `api/tasks.py:336-346`) skips that part only.
- **Follow-ups:**
  - `/continue` on a **child** is redirected to the parent, in `continue_task` (L560-589).
  - `/continue` on the **parent** is handled in `_run`'s follow-up path, after S3b's follow-up persona block. If a part is `needs_owner`, the reply answers it (§3). Otherwise the text is appended as a new last part (content hash dedupe, the #649 `append_followup` L180-216 rule) and goes through completeness and compile.
- **Startup recovery** (`main.py`, after `reconcile_execution_on_startup`, L213-218 on `d214b6d`). For each pipeline in `running` or `waiting`:
  - re-take the rewarm hold;
  - if the current child is terminal, run `on_child_terminal` (a missed advance);
  - if it is `queued` without a runner, dispatch it again (same id);
  - if it is `running` without a runner, call `continue_task(child)`, which resumes the durable run (RFC-0029).
- **Visibility:** `get_task` (`api/tasks.py:255-287`) gains a `large_prompt` object containing:
  - mode;
  - status;
  - target;
  - preload_status;
  - ack_ms;
  - sections (`ordinal`, `title`, `status`, `completeness`, `rounds`, `missing`, `child_task_id`, `vault_rel_path`, `vault_conflict`).

  Parent events are plain human text, so Show work (`OwnerChatTranscript.tsx:232-280`, which renders `title` and `detail`) shows the progress without an edit.
- **Recents:** children appear in `/api/tasks` (polled by `App.tsx:221`) with their "Part n of N" titles. The list endpoint is unchanged.

### 6. Owner UI (S6)

- **`TaskActivity.tsx`:** a new `LargePromptSections` component, mounted with one line inside `TaskActivityPanel` (L185), add-alongside. It shows:
  - one row per section: ordinal, title, status chip, completeness, and the rounds count;
  - an "Open" link to the child, a "Cancel part" button (POST child cancel) and an "Obsidian note" path when one is mirrored;
  - a "Cancel remaining" button (POST parent cancel);
  - a status line with target, preload_status and ack_ms.
- **Prompt steps UI:** #649's prompt-steps UI (`TaskActivity.tsx` +306-319, `taskStatus.ts` +207) is ported for children.
- **`api.ts`:** add-only types (`LargePromptPayload`, `PromptStep`; #649 `api.ts` +230, +269).
- **Not edited:** OwnerChatTranscript, HudChat, Chat, Phone, `useTaskSpeech` and every persona component.

### Live-UI add-alongside reasoning pass (2026-10-14 standing order)

Touched live UI: TaskActivity panel (HudChat, Chat, Phone), task speech, Show work.

| Surface | Existing behaviour kept? | Addition |
| --- | --- | --- |
| `TaskActivityPanel` (every existing row, ChildExecution L162, buttons) | **Yes**, untouched | One mount line for `<LargePromptSections task={task} />`, rendered only when `task.large_prompt` is present. |
| `useTaskSpeech` | **Yes**, unchanged | The ack and needs_owner lines are ordinary `chat_tts` events with title ≠ "Speak reply". |
| Show work (`OwnerChatTranscript.tsx:232-280`) | **Yes**, unchanged | Parent events are human-readable text, so no formatter is needed. |
| RFC-0218 persona switch line, highlight, morph | **Yes** | Parent switch per S3b, before the ack. Children emit no persona events. |
| Phone | **Yes** | Shows the parent's events and panel via its existing poll. No speech is added. |
| Task recents (`App.tsx:221`) | **Yes** | Part children are listed with "Part n of N" titles. |

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

`AppSettings.large_prompts` is added next to `decision` (`config.py:477-519` on `d214b6d`). `api/settings.py` exposes it on the existing settings GET and PUT. No new settings UI is part of this RFC; the setting is editable through the existing advanced settings JSON.

---

## Reconciliation

| With | Rule |
| --- | --- |
| **RFC-0224 / #649** | Its storage and execution engine is ported (§4), with hunks cited. Its model-planned `prepare_workflow` and `append_followup` are not ported: the plan here is the deterministic compile. If #649 lands first, S2 drops the duplicate hunks and keeps `seed_workflow`. If this RFC lands first, #649 rebases onto the ported files. Neither waits for the other. |
| **RFC-0211 / #585** | Sections are rows a future scheduler can list as "upcoming tasks". When `DevelopmentScheduler` lands, its `resource_hold` (L380-411) is respected: dispatch defers while a hold names Ollama, with the parent event "Waiting for the scheduler's model hold". Nothing here waits on #585. |
| **RFC-0026 / 0029** | Children are ordinary durable tasks created through `AgentRuntime.create_task`. Follow-ups use `/continue`, and recovery uses `continue_task`. There is no second task system. |
| **Reflex arbitration** | One decide per owner turn, with two riders. The ack is a fixed front notice, so `keep_worker` semantics apply to the parent result (§1). |
| **RFC-0218 S3b (+ #663)** | The parent turn's persona block runs first, unchanged. `switch_id = task_id:seq` is counted on the parent only. Children never call `apply_persona_switch`, so they publish no `persona_switched` or `persona_switch_failed`, and their `seq` counter stays empty. The 0218 test `t(acknowledgement) − t(persona_switched) < 50 ms` still holds, because the large branch publishes the `acknowledgement` event in the same position. |
| **RFC-0225 S3** | The preload is exactly `activate_runtime_profile`, which 0225-S3 routes through `prepare_engine_for`. There is no separate VRAM gate, loader or owner-line channel. |
| **RFC-0228 S1 / S4** | Not the owner of `anzu-coder-27b`: 0228-S1 is the Fable 9B default and 0228 L360 excludes the coder. No `model-catalog.json` entry is added (not an installer asset). |
| **RFC-0225 S3 (gate requirement)** | 0231-S0 adds the `anzu-coder-27b` requirement (12 GB) as the first lookup in the step-5 gate. The gate logic, ledger and owner lines stay 0225's. |
| **RFC-0228 S2** | The restore goes through `schedule_orchestrator_restore` → `NINE_B_REWARM`. The hold API is added to `rewarm.py` after 0228-S2. |
| **`agent/intake.py`** | Left in place for `stream_owner_chat`. The large pipeline replaces its use only on the tasks path. Merging the two is out of scope. |
| **RFC-0230** (in flight) | Unknown content at time of writing. Its slices go **first** on every shared file listed below, and 0231 slices rebase onto them. |

## Relationship to drafts

| Draft hunk | Taken? | Where |
| --- | --- | --- |
| #649 models, task_workflow subset, loop workflow execution, `prompt_steps`, `large_task_reviews`, UI steps | **Ported** | S2, S6 |
| #649 `is_large_request` | **Ported** as rules L4 | S1 |
| #649 `PLAN_SYSTEM` / model planning / `append_followup` | Not ported (replaced by the deterministic compile and the parent follow-up rule) | — |
| #649 `basic_qa` reply shape in `owner_turn.py` | Not ported here. The precheck excludes basic_qa only when the shape exists; otherwise the condition is skipped. | S1 |
| #585 scheduler | Not ported (respected when it lands) | S5 |

---

## Slices (one ticket each, one developer each, fast off)

### S0: `anzu-coder-27b` runtime profile, VRAM requirement, enable reconcile

**Model:** Grok 4.5 · **Depends:** RFC-0225 S3 (creates `engine_coexistence.py` with `prepare_engine_for`; `main.py` chain)

| File | Change |
| --- | --- |
| `backend/app/inference/model_stack.py` | `MODEL_CATALOG["anzu-coder-27b"]` `SpecialistModel` (§2a values); only owner in the batch |
| `backend/app/inference/anzu_coder.py` (new) | `VRAM_ESTIMATE_GB`, `vram_requirement_gb`, `reconcile_anzu_coder_profile` |
| `backend/app/inference/engine_coexistence.py` | Only: the step-5 requirement lookup consults `anzu_coder.vram_requirement_gb(target)` first (second owner after 0225-S3) |
| `backend/app/main.py` | One line: `_start_optional_step("anzu_coder_profile", reconcile_anzu_coder_profile)` plus its import |
| `tests/test_rfc0231_anzu_coder_profile.py` (new) | Below |

Tests (CI: `pytest` job, step "Run full backend suite", `.github/workflows/pr-tests.yml:94-95`):
- `test_template_fields_exact`: `default_runtime_profiles()` contains a row equal, field by field, to the §2a table (id, name, label, model, provider, endpoint, context_limit, quantization, privacy_class, cost_ceiling_usd, capability_tags, specialization_tags, model_profile, is_local, description, enabled=False, runtime_role, answer_tier, gguf_path).
- `test_existing_routes_unchanged_when_template_disabled`: `route_runtime` and `prepare_answer_route` give the same result with and without the template, for the leader, orchestrator and tier-2/3/4 answer preference sets.
- `test_enabled_profile_does_not_outrank_expert_for_reasoning_answers`: template enabled, tier-4 reasoning answer route → `expert`.
- `test_reconcile_enables_when_ollama_lists_model` (`anzu-coder-27b:latest` advertised) → `enabled`, row enabled, `auto_enabled_at` written.
- `test_reconcile_not_advertised_leaves_disabled`.
- `test_reconcile_unreachable_retries_bounded`: fake clock, 10 attempts 60 s apart, then `ollama_unreachable`.
- `test_reconcile_respects_owner_row_and_owner_disable`: owner-created `anzu-coder-27b` row → `owner_row`, untouched; template disabled after `auto_enabled_at` → `owner_disabled`, stays disabled.
- `test_reconcile_runs_as_optional_startup_step`: startup reaches `/api/health` without awaiting the probe; the step name is in `startup_health.report()`.
- `test_vram_requirement_12gb_for_coder_only`: `anzu-coder-27b` and `anzu-coder-27b:latest` on Ollama → 12.0; other models → `None`.
- `test_gate_uses_coder_requirement`: with 12.5 GB free and an ANZU-loaded 9B, `prepare_engine_for(<S0 profile>)` takes the gate's unload path (12.0 + 1 GB > 12.5); with 13.5 GB free nothing is unloaded.

### S1: Large-prompt detection riders

**Model:** Grok 4.5 · **Depends:** none (after RFC-0230's `owner_turn.py` slice, if any)

| File | Change |
| --- | --- |
| `backend/app/decision/large_prompt.py` (new) | Floor rules L1-L5, `LargePromptIntent`, split-mode rule |
| `backend/app/decision/owner_turn.py` | Precheck plus riders in `_decide_sync`, floor in `_apply_floors`, `large_prompt` field |
| `backend/app/decision/adapters/rules.py` | Rider branches `large_prompt` and `large_prompt_split` |
| `backend/app/agent/request_routing.py` | Pass-through of the field (no new decide) |
| `tests/test_rfc0231_large_prompt_decision.py` (new) | Below |

Tests (CI: `pytest` job, step "Run full backend suite"):
- `test_rules_floor_each_rule_fires` (L1-L5, one prompt each).
- `test_short_prompt_no_rider`: no rider appended, and the decision is equal to the decision with the feature disabled.
- `test_provider_cannot_lower_large`.
- `test_provider_raises_only_at_075`.
- `test_deadline_fallback_is_rules`.
- `test_one_decide_per_turn`: `decide_owner_turn` is called exactly once for a large turn.
- `test_security_and_literal_excluded`.
- `test_questions_mode_from_l3`.
- `test_disabled_is_byte_identical`.

### S2: Prompt-step engine port, tables, settings

**Model:** Grok 4.6 · **Depends:** S1 (none in code; S1 only goes first in the merge order)

| File | Change |
| --- | --- |
| `backend/app/db/models.py` | #649 `TaskPromptPlan` and `TaskPromptStep`; `LargePromptPipeline`, `LargePromptSection` |
| `backend/app/agent/task_workflow.py` (new) | #649 subset plus `seed_workflow` |
| `backend/app/agent/loop.py` | #649 workflow execution hunks (§4) |
| `backend/app/api/tasks.py` | `prompt_steps` in the payload |
| `backend/app/config.py` | `large_task_reviews`, `LargePromptSettings` |
| `backend/app/api/settings.py` | #649 hunks plus `large_prompts` |
| `tests/test_rfc0231_prompt_steps.py` (new) | #649 `tests/test_rfc0224_task_workflow.py` cases ported, plus new cases |

Tests:
- `test_seed_workflow_idempotent`.
- `test_steps_execute_in_order_fresh_context`.
- `test_step_limit_enforced`.
- `test_review_steps_toggle`.
- `test_prompt_steps_in_task_payload`.
- `test_tables_created_on_fresh_db` (`init_db` on an empty DB).
- `test_no_workflow_path_unchanged`: a task without a stored workflow runs exactly as before.

### S3: Split, completeness, compile, mandatory sub-tasks, persistence

**Model:** Grok 4.5 · **Depends:** S2

| File | Change |
| --- | --- |
| `backend/app/agent/large_prompt_intake.py` (new) | split, completeness rounds, repairs, compile, step specs, validators, DB and vault persist |
| `tests/test_rfc0231_large_prompt_intake.py` (new) | Below |
| `tests/fixtures/rfc0231/` (new) | Prompt fixtures: 5-item list, 4 questions, 6000-char spec, dangling-reference section, 12 headings |

Tests:
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
- `test_vault_owner_edit_conflict_not_forced`.
- `test_vault_failure_keeps_db`.
- `test_large_ingress_blob_ref`.

### S4: Ack, preload, create_task large branch, rewarm hold

**Model:** Grok 4.6 · **Depends:** **S0** (the `anzu-coder-27b` target profile and its VRAM requirement; hard dependency, S4 does not start before S0 is merged), S1, S2, S3, RFC-0225 S3 (`prepare_engine_for` in `hotswap.py`), RFC-0228 S2 (`inference/rewarm.py`), RFC-0218 S3b (`create_task` persona block)

| File | Change |
| --- | --- |
| `backend/app/agent/large_prompt.py` (new) | `resolve_target` (enabled rows only), `preload` (incl. the Ollama `/api/ps` check and `record_anzu_load`), ack texts, compare-and-restore |
| `backend/app/agent/loop.py` | Large branch in `create_task` (after S3b's block, replacing the generic ack for large turns only); parent runner entry in `_run` |
| `backend/app/inference/rewarm.py` | `hold` and `release`, plus deferral while held (second owner after 0228-S2) |
| `tests/test_rfc0231_ack_preload.py` (new) | Below |

Tests:
- `test_ack_chat_tts_within_150ms_of_decision`: `BUS.publish` timestamped, preload fake blocks for 5 s, assert ≤ 150 ms.
- `test_ack_never_uses_publish_owner_text`.
- `test_ack_title_not_speak_reply`.
- `test_0218_ack_after_persona_switched_still_under_50ms`.
- `test_preload_started_not_awaited`.
- `test_target_resolution_order`, using RFC-0228's `settings_lmstudio_9b.json` fixture plus the S0 `recommended-anzu-coder-27b` row: enabled → it is the target; disabled → step 2 (`route_runtime`); absent → step 2.
- `test_preload_ollama_anzu_loaded_recorded`: `/api/ps` without the model → warm → listed → exactly one `record_anzu_load("ollama@127.0.0.1:11434", "anzu-coder-27b")`, `preload_status == "loaded"`.
- `test_preload_ollama_owner_loaded_not_recorded`: `/api/ps` already lists it → no warm call, no `record_anzu_load`, `preload_status == "already_loaded"`.
- `test_preload_uses_activate_runtime_profile_only`: no `MANAGER.load` or direct engine call.
- `test_gate_refused_falls_back_visibly`.
- `test_preload_timeout_180s_fallback`, with a fake clock.
- `test_compare_and_restore_keeps_owner_change`.
- `test_hold_defers_rewarm_until_release`.
- `test_no_target_ack_text`.

**Live audit** (on Taco's PC; numbers recorded in the PR): first ack audio ≤ 1200 ms after the decision; the 27B is loaded via the gate and the 9B is re-warmed after the pipeline.

### S5: Sequential queue, lifecycle, follow-ups, recovery

**Model:** Grok 4.6 · **Depends:** S4

| File | Change |
| --- | --- |
| `backend/app/agent/large_prompt_queue.py` (new) | `dispatch_next`, `on_child_terminal`, `on_parent_cancel`, parent completion, `recover_on_startup` |
| `backend/app/agent/loop.py` | `pipeline_section` keyword in `create_task`; child path in `_run` (no front lane, seeded workflow, target profile); terminal hook call; cancel hook; `/continue` redirect and parent follow-up |
| `backend/app/api/tasks.py` | `large_prompt` payload in `get_task` |
| `backend/app/main.py` | One startup call to `recover_on_startup` |
| `tests/test_rfc0231_large_prompt_queue.py` (new) | Below |

Tests:
- `test_parts_run_strictly_sequential`: part 2 is created only after part 1 is terminal.
- `test_child_ids_stable_uuid5`.
- `test_breaker_admission_and_kill_switch_stops`.
- `test_child_no_decide_no_persona_no_ack_no_speech`.
- `test_failed_part_fails_parent_with_text`.
- `test_child_cancel_skips_part`.
- `test_parent_cancel_cancels_child_and_rest`.
- `test_needs_owner_waits_then_continue_one_round`.
- `test_skip_part_n`.
- `test_followup_appends_part_dedupe`.
- `test_continue_on_child_redirects`.
- `test_parent_combined_result_and_verification`.
- `test_restore_after_parent_terminal`.
- `test_recovery_redispatch_advance_resume`.
- `test_large_prompt_payload`.

### S6: Large-prompt sections panel

**Model:** Composer 2.5 · **Depends:** S5, RFC-0218 S3 (sequential owner of `api.ts`)

| File | Change |
| --- | --- |
| `frontend/src/components/LargePromptSections.tsx` (new) | Panel (§6) |
| `frontend/src/components/TaskActivity.tsx` | One mount line, plus the #649 prompt-steps rows (+306-319) |
| `frontend/src/api.ts` | Add-only types |
| `frontend/src/taskStatus.ts` | #649 +207 (step status label) |
| `frontend/large-prompt-sections.test.mjs` (new) | Rows render, buttons call the correct endpoints, absent payload renders nothing, existing panel rows still present |
| `frontend/package.json` | Append `test:large-prompt-sections` |
| `.github/workflows/pr-tests.yml` | Append the step `Large prompt sections tests (RFC-0231 S6)` → `npm run test:large-prompt-sections` after "Persona morph hook tests (RFC-0218 S5)" in `frontend-build` |

## Ownership chains (handoff order on shared files)

Every listed RFC-0230 slice goes **first** on any file it claims. When RFC-0230 lands, the 0231 tickets rebase onto it.

| File | Order |
| --- | --- |
| `backend/app/agent/loop.py` | 0218-S3b → (0230) → 0231-S2 → 0231-S4 → 0231-S5 |
| `backend/app/decision/owner_turn.py`, `adapters/rules.py` | (0230) → 0231-S1 |
| `backend/app/config.py` | 0228-S1 → 0228-S2 → (0230) → 0231-S2 |
| `backend/app/api/tasks.py` | (0230) → 0231-S2 → 0231-S5 |
| `backend/app/inference/rewarm.py` | 0228-S2 (creates it) → 0231-S4 |
| `backend/app/inference/hotswap.py` | 0225-S3 → 0228-S2. 0231 does **not** edit it. |
| `backend/app/main.py` | (0230-S0 → 0230-S5) → 0225-S1 → S2 → S3 → 0231-S0 → 0231-S5 |
| `backend/app/inference/engine_coexistence.py` | 0225-S3 (creates it) → 0231-S0 |
| `backend/app/inference/model_stack.py`, `backend/app/inference/anzu_coder.py` | 0231-S0 only |
| `backend/app/db/models.py` | (0230) → 0231-S2 |
| `frontend/src/api.ts` | 0218-S3 → 0231-S6 |
| `frontend/src/components/TaskActivity.tsx` | (#649 if it lands first) → 0231-S6 |
| `frontend/package.json`, `.github/workflows/pr-tests.yml` | Append-only, any order, rebase on conflict |

## Ticket cards

| ID | Title | Model | Depends |
| --- | --- | --- | --- |
| 0231-S0 | `anzu-coder-27b` runtime profile, VRAM requirement, enable reconcile | Grok 4.5 | 0225-S3 |
| 0231-S1 | Large-prompt detection riders | Grok 4.5 | — |
| 0231-S2 | Prompt-step engine port, tables, settings | Grok 4.6 | S1 (order) |
| 0231-S3 | Split, completeness, compile, sub-tasks, persistence | Grok 4.5 | S2 |
| 0231-S4 | Ack, preload, create_task branch, rewarm hold | Grok 4.6 | **S0**, S1-S3, 0225-S3, 0228-S2, 0218-S3b |
| 0231-S5 | Sequential queue, lifecycle, recovery | Grok 4.6 | S4 |
| 0231-S6 | Large-prompt sections panel | Composer 2.5 | S5, 0218-S3 |

All seven run with fast mode off.

## Overall acceptance

- [ ] A large spoken or typed prompt has its ack persisted ≤ 150 ms after the decision (CI) and audible ≤ 1200 ms after it (live audit), while the 27B loads through the RFC-0225 gate.
- [ ] The prompt is split, every section is complete or explicitly `needs_owner` within 3 rounds, and each section becomes one detailed prompt stored in SQLite (and in the vault when enabled).
- [ ] The parts run strictly one after another. Every part has validated deeper and quantitative sub-tasks, and the parent shows progress, can be cancelled, and ends with a combined, verified result.
- [ ] With `large_prompts.enabled=false`, behaviour is identical to today.
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
- **Collisions in `loop.py`.** Mitigation: the strict ownership chain above, three 0231 slices in sequence.
