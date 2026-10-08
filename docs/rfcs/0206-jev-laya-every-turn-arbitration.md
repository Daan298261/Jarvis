# RFC-0206: Jev/Laya on every turn, arbitration, front self-awareness

**Status:** accepted  
**Queue item:** (none — no §58 checkbox; Architect may add one after this spec merges)  
**Author:** Chief of Staff (Taco-authorized exception: specs may be written in parallel with the Architect)  
**Date:** 2026-10-08

**Aligns with:** [`ANZU_PRODUCT_NORTH_STAR.md`](../../ANZU_PRODUCT_NORTH_STAR.md) — one assistant, local-first, fast when the request is simple, honest when optional providers are absent, no stubbed dual brains.  
**Amends the behaviour of (does not edit those files):** [0116](0116-typesafe-jev-optional-decision-tier.md), [0117](0117-tiny-front-chat-responder.md), [0171](0171-system-one-reflex-lane-jev-laya-priority.md), [0203](0203-fast-path-lane-consolidation.md) §3.  
**Numbering:** `0204` (Android) and `0205` (DeepHat) are real RFCs. This ticket is **0206**.

Product name in owner-facing answers is **ANZU Superassistant**. The engineering tree stays Jarvis.

## Problem

ANZU still treats the System-One reflex lane as an optional refinement, then reconciles the two chat lanes with hardcoded string rules, and lets a regex classifier decide what the owner just said.

Verified on `development` at `222ac17`:

1. **Reflex is not on every turn.** `REFLEX_DECISION_CLASSES` in `backend/app/decision/types.py` lists bounded classes (`request_routing`, `persona_model_routing`, `turn_batch`, …). `decide()` (`backend/app/decision/reflex.py`) runs only when a call site asks. `stream_owner_chat` (`backend/app/persona/owner_chat.py`) never calls it. The agent loop does (`AgentLoop` → `evaluate_request_route` in `backend/app/agent/request_routing.py`, `loop.py`), and even there a provider answer below confidence `0.75` is discarded and the regex baseline is kept. Profile pick calls `route_persona_model` only when **two or more** tier-eligible profiles exist (`select_runtime_for_decision` in `backend/app/inference/answer_routing.py`). A one-profile turn, and every ordinary owner-chat turn, skips the lane.

2. **Front vs worker merge is a hardcoded policy.** `merge_front_and_worker` / `consolidate_front_and_worker` (`backend/app/agent/front_responder.py`) decide keep / drop / append with sequence-ratio and correction-cue branches. `run_two_lane_chat` applies that result as the owner-facing turn. No decision class owns the choice.

3. **Owner chat is regex-routed.** `route_request` (`backend/app/agent/planning.py`) classifies `direct_reply` / `direct_lookup` / `managed_task` from keyword and regex lists (`is_plain_conversation`, `_TRIVIAL_CHAT`, `_TOOL_REQUEST`, app/file/LTA patterns). `classify_front_action` calls `route_request` and then defaults almost everything else to `ack_continue`. `stream_owner_chat` uses the same regex family to delegate tool/app/file turns, and calls `route_request` again when scheduling background verify.

4. **The front model cannot answer questions about ANZU.** `small_context_envelope` sends `FRONT_SYSTEM`, an action hint, a few history turns, and the user text. It does not attach live settings. `FRONT_SYSTEM` forbids invented live facts and internal model names. `enforce_front_safety` then rejects `_INVENTED_FACTS` (including `currently <number>`) and `_REASONING_LEAK` (including `answer_tier` / `runtime_role`). A true statement about the loaded profile has nowhere to come from, and a numeric reading can be stripped.

5. **Literal instructions get the canned holding line.** `SAFE_ACK` is `I can start with the short version while I check the details.` `classify_front_action("Say only the word ready")` is `ack_continue`: the utterance is not `_TRIVIAL_CHAT`, and `is_plain_conversation` is false, so `route_request` returns `managed_task` and the classifier falls through to `ack_continue`. `FRONT_SYSTEM` tells the model that `ack_continue` means acknowledge and say it is checking the details. `fallback_text_for_action` returns `SAFE_ACK` whenever the front provider is missing or returns empty (`generate_front_reply`). The owner asked for one word and hears the holding phrase.

That fails the north star. The owner should tell ANZU what they want. A one-word instruction should be obeyed. A question about ANZU's own setup should be answered from real state. Two internal lanes must come back as one voice. Optional cloud and local decision models must participate on every turn, and a miss must fall back honestly inside 50 ms.

## Decision

Three code changes, one new decision class, one front-lane contract. No new chat model, no fake Jev, no second merge policy left behind in `front_responder`.

```text
owner utterance
  -> deterministic floors (tools, app/file control, LTA, harm, approval, unambiguous literal)
  -> ONE Reflex decide() for the turn (route + reply shape), deadline 50 ms
  -> front lane speaks from that decision
  -> worker lane only when the decision requires it
  -> ONE Reflex decide() for arbitration when both lanes produced text, deadline 50 ms
  -> string executor applies the typed disposition
```

The **<50 ms added latency on the path to first text is accepted.** It is the cost of putting the safeguard on every request. Do not skip the call to save that budget. Do not raise the budget so a slow provider can finish.

### 1. Every turn enters the reflex lane

Add `decide_owner_turn(user_message, *, baseline, decision_tier)` in `backend/app/decision/owner_turn.py`. It is the only routing entry for `stream_owner_chat` and for the agent-loop intake that today calls `evaluate_request_route`.

It always calls `decide()` (`backend/app/decision/reflex.py`) **before** `generate_front_reply`. The call happens when `decision.tier` is `local`, when Jev is disconnected, when Laya is cold, and when `select_runtime_for_decision` would have seen fewer than two eligible profiles. "Tier-eligible refinement" is no longer the gate.

| Item | Contract |
| --- | --- |
| Decision class | Existing `request_routing`. Do not invent a second routing class. |
| Deadline | `deadline_ms=50`. Outer `asyncio.wait_for(..., 0.05)` around `asyncio.to_thread`, same pattern as `evaluate_request_route`, with the timeout lowered from `0.15` s / `INTAKE_DEADLINE_MS = 100` to **50 ms**. The outer wait is the wall-clock cap. |
| Questions (one batched call) | `request_route`: choice `direct_reply` \| `direct_lookup` \| `managed_task` (descriptions already in `request_routing._evaluate`). `reply_shape`: choice `literal` \| `self_status` \| `social` \| `ack` \| `clarify` \| `handoff`. |
| State | `user_message` via `compact_state`, `baseline_route`, `literal_candidate` (short string, may be empty), `decision_tier`. Pass the `AppSettings` object the caller already holds. Do not call `load_settings()` inside the decision; `request_routing.py` already avoids a cold settings load because that alone can blow the deadline. Unknown tier → privacy `local_only`. |
| Privacy | `privacy_for_tier(decision_tier)` from `backend/app/decision/surfaces.py`. |
| Audit | Every call records the existing reflex audit event with `decision_class=request_routing`, provider, `fallback_used`, `fallback_reason`, and total latency. A skipped call is a test failure. |

**Who may answer**

Provider order stays `quartermaster.select_provider_order`: Laya when `laya_runtime.is_ready()`, then Jev when `jev_adapter.available` is true, then the generative adapter, then `deadline_fallback` to rules. `decide()` already implements that chain, the confidence fall-through at `0.35`, out-of-domain rejection, and the "never strand the turn" path. This RFC does not replace it.

| Provider | When it runs | When it does not | Owner-visible failure |
| --- | --- | --- | --- |
| **Laya** (`laya_adapter`, in-process `laya_runtime.decide_local`) | Installed, enabled, and warm. One worker thread; the caller's deadline already bounds the wait. Test injection stays `set_decide_fn` and is always `fixture=True`. | Not installed, not warm, or the forward pass exceeds the remaining budget. | `fallback_used=true`. Source is the next provider or `deadline_fallback`. Never `source=laya` for a fixture presented as the live encoder. |
| **Jev** (`jev_adapter` → `post_systemone`) | `privacy` is `allow_cloud` (`jev_optional` or entitled `jev_plus`), `jev_calls_allowed` (tier not `local`, availability `connected`, key bound, Plus present when tier is `jev_plus`), and remaining budget is enough to try. | Tier `local`, WAN deny, missing key, probe not `connected`, Plus missing, or `privacy` is `local_only` / `require_local`. `available()` already returns false in those cases. | Do not open a TypeSafe socket. Do not label rules or the generative adapter as Jev. A timeout inside 50 ms becomes `deadline_fallback` with an explicit reason. |
| **Rules** (`adapters/rules.py`) | Hard floors below, and the deadline / exhaustion fallback. | — | This is a real classifier, the same family as today's `route_request` / `classify_front_action`. It is the safe answer, not a stub that returns `ack` for everything. |
| **Generative adapter** | Only after typed providers miss, as today: it **reuses rules** and sets `source=generative` so audits do not claim Jev or Laya. | — | Do not add a chat-model JSON mode and label it Jev or Laya. |

Class-specific confidence for `request_route` stays **0.75**, applied inside `decide_owner_turn` after `decide()` returns: below that, use the rules answer for the route. The `decide()` call still happened. `reply_shape` uses the lane's existing `0.35` quality fall-through, then the floors below.

**Floors (applied after the provider answer, in one guard, same idea as `_apply_policy_guard`)**

These are product invariants. A provider cannot weaken them.

| Floor | Rule |
| --- | --- |
| Explicit action | `requests_agent_tools`, `simple_app_control`, `simple_file_control`, or `lta_protected_folder_path` forces `request_route=managed_task` and `reply_shape=handoff`. |
| Weather | `is_weather_query` forces `direct_lookup`. A provider cannot turn a weather ask into a completed `final_basic` answer. |
| Unambiguous literal | If `literal_candidate` is non-empty, `reply_shape=literal`. A provider cannot demote it to `ack`, `handoff`, or `clarify`. |
| Policy / harm | Unchanged. `approval_signal`, `risk_signal`, and `harm_veto` stay out of this call. Arbitration and routing never grant a tool or skip an approval. |

`literal_candidate` is ordinary code on the raw utterance, run **before** `compact_state` so a long paste cannot drop the token. Closed patterns (case-insensitive, one token or one quoted span):

- `say only the word <token>`
- `say only <token>`
- `reply with only <token>`
- `just say <token>`
- `respond with exactly "<span>"` / `reply with exactly "<span>"`

`<token>` is a single word of letters, digits, or hyphens. The quoted form keeps the inner span verbatim, including spaces, up to 80 characters. Anything else leaves `literal_candidate` empty and the provider decides `reply_shape`.

Map `reply_shape` to the existing front action. Do not add a sixth `FRONT_ACTIONS` value.

| `reply_shape` | `front_action` | Worker |
| --- | --- | --- |
| `literal` | `final_basic` | no |
| `self_status` | `final_basic` when the snapshot covers the question; `ack` when the snapshot has no relevant field | worker only for the `ack` case |
| `social` | `final_basic` | no |
| `clarify` | `ask_clarification` | no |
| `ack` | `ack_continue` | yes |
| `handoff` | `handoff_notice` | yes |

`classify_front_action` becomes a reader of `OwnerTurnDecision`. It stops calling `route_request`. `stream_owner_chat` stops calling `route_request` for background-verify `route_kind`; it passes the turn decision's route. The early delegate for app/file/tool control stays, and it is the floor above, not a parallel chat router.

RFC-0203 §3's pipeline (`resolve_owner_turn_routing`) is the intended single routing entry once that RFC is implemented. Until then, `decide_owner_turn` is that entry. When the pipeline lands, it calls `decide_owner_turn` and does not add a third classifier. Reflex on this path is mandatory; it is not "refine only among eligible profiles."

### 2. Decision class `arbitration`

Add `"arbitration"` to `REFLEX_DECISION_CLASSES`. It is **not** in `POLICY_HARDENED_CLASSES`. It owns the choice of how the front-lane answer and the worker-lane answer become one owner-facing turn. `merge_front_and_worker`'s action branches and `consolidate_front_and_worker`'s keep/append/replace policy move into this class. The string functions that remain are an executor.

**When it runs.** After both `front_text` and `worker_text` are non-empty, inside the merge that `run_two_lane_chat` performs today. One side empty: return the other side in the executor and do not call a provider (there is nothing to reconcile). `silent_skip` with only a worker answer: return the worker, no provider call. Terminal `final_basic` / `ask_clarification` with no worker: unchanged, no arbitration call.

**Deadline.** `50` ms, off the first-token path. The front line may already be on screen (`ACK_HOLD_SECONDS` and early TTS stay as they are). Missing the deadline applies the rules disposition immediately and audits `deadline_fallback`. Do not hold the `done` event past that cap.

**Inputs** (`compact_state`, no system prompts, no API keys, no tool catalogs):

| Field | Source |
| --- | --- |
| `user_message` | The owner utterance |
| `front_text` | Sanitized front reply |
| `worker_text` | Worker reply |
| `front_action` | One of `FRONT_ACTIONS` |
| `front_spoken` | Whether that front line was already shown or spoken |
| `reply_shape` | From `decide_owner_turn` |

**Output.** One batched `decide()` with a single choice question:

| id | type | choices | Meaning the executor applies |
| --- | --- | --- | --- |
| `disposition` | choice | `keep_front`, `keep_worker`, `append_novel` | `keep_front`: owner text is the front line. `keep_worker`: owner text is the worker line (use this when the worker already contains the front line, or when the worker corrects it). `append_novel`: owner text is the front line, a blank line, then worker sentences that fail `_sentence_restates_front`. |

The decision model does not write the merged paragraph. Open-ended generation stays off the reflex lane (RFC-0171).

**Executor.** New `apply_disposition(disposition, front_text, worker_text) -> str` in `front_responder.py`. It uses the existing sentence split, `_sentence_restates_front`, and `_strip_legacy_merge_heading`. It never emits the legacy `Deeper result` heading.

| `disposition` | Result |
| --- | --- |
| `keep_front` | Front line. |
| `keep_worker` | Worker line. |
| `append_novel` | Front, then novel worker sentences. If every worker sentence restates the front line, degrade to `keep_front` so a bad provider cannot duplicate the ack. |

**Guards (after the provider answer, one function).**

- `reply_shape=literal`, or `front_action=final_basic` with safe front text: force `keep_front`. The worker cannot overwrite "ready".
- `is_unsafe_front_claim` on the front line: that line was already replaced by `enforce_front_safety` before merge. Arbitration does not re-admit it.
- Out-of-domain or missing `disposition`: rules fallback, same as any other class.

**Rules adapter for `arbitration`.** Encode today's `consolidate_front_and_worker` outcome as the choice, so a cold Laya and a declined Jev reproduce current owner-visible text:

| Today's outcome | `disposition` |
| --- | --- |
| Paraphrase dropped (`test_duplicate_worker_is_suppressed_and_new_info_is_kept`) | `keep_front` |
| Novel worker sentence kept after the ack (`test_merge_front_and_worker_is_one_turn`, "Mild rain later, sir.") | `append_novel` |
| Correction with a different time (`The meeting is at 3.` → `4:30` + room) | `keep_worker` |
| `final_basic` and empty worker | no call; executor returns the front line |

**Jev on this class.** Same availability gate as §1. The state is owner text plus both replies, so cloud upload happens only when the owner already opted into Jev. `compact_state` remains the projection (head/tail compression, not a raw transcript). A Jev miss inside 50 ms uses the rules disposition and `fallback_used=true`.

**Laya on this class.** Same in-process runtime. Choice cardinality is 3, inside Laya's published short-choice head (`MAX_CHOICE_OPTIONS = 16`). A timeout on the Laya worker thread falls through; it does not queue behind another decision.

`merge_front_and_worker` becomes: call `arbitrate_front_and_worker` in `surfaces.py` when both sides are non-empty, then `apply_disposition`. `merge_consecutive_assistant_turns` uses the same helper. Delete the policy branches once the rules adapter covers the fixture table. Do not leave a second reconciliation in `owner_chat.py`.

### 3. Owner-chat routing leaves the regex

`stream_owner_chat` obtains `OwnerTurnDecision` from `decide_owner_turn` and threads `reply_shape`, `literal_text`, and `route` into `generate_front_reply` and `run_two_lane_chat`.

`route_request` remains the **rules-adapter baseline** for `request_route` (and the `baseline` argument). It is not called as the primary classifier from `owner_chat.py`, `classify_front_action`, or `run_two_lane_chat`.

`evaluate_request_route` becomes a thin async wrapper around `decide_owner_turn` so `loop.py` and owner chat share one path. Its current behaviour of ignoring an in-domain provider answer below `0.75` moves into the §1 confidence rule. Its current behaviour of refusing to downgrade an explicit action stays as the floor, not as a regex that also classifies "Say only the word ready".

### 4. Front-model self-awareness

When `reply_shape` is `self_status`, or when the turn decision's rules/provider mark the utterance as asking about ANZU itself, the front envelope gains a system message built by `build_self_knowledge_snapshot(settings, inference_state) -> dict` in `backend/app/agent/self_knowledge.py`. The front model answers **from that dict**. It does not invent fields, and it does not refuse a field that is present.

The snapshot is code reading live in-memory state. It is not a reflex generation and not a tool call.

**May be included** (owner-facing labels, real values):

| Reading | Source |
| --- | --- |
| Product name `ANZU Superassistant` | Constant in the snapshot builder |
| Active persona id | `settings.named_personas.active_id` |
| Inference profile, backend, loaded flag, model alias, configured `context_size`, live `server_n_ctx` when non-zero | `settings.inference` and `InferenceState` (`loaded`, `profile`, `alias`, `backend`, `context_size`, `server_n_ctx`, `family`) |
| Front lane enabled, profile, placement, device, `timeout_ms`, `max_output_tokens` | `settings.front_responder` |
| Decision tier, Jev availability label, Laya installed / warm / enabled | `resolve_status()` and `laya_runtime.status()` — labels only |
| Voice profile id, TTS `engine`, `quality_engine` | `settings.voice.active_profile_id`, `settings.tts` |
| Dialogue verbosity, personality preset, output language | `settings.dialogue` |
| Address style | `settings.social_commentary.address_style` |
| Shell | `settings.presentation.shell` |
| Vault bound (boolean) | `settings.knowledge_vault.vault_path` non-empty. Do not include vault file contents. |

Say which context number is configured and which is the live server window when both exist. Do not describe a bugfix for context scaling here; report the values the process actually holds.

**Must be absent from the dict and from the prompt:**

- `auth_token`, `inference.api_key`, `front_responder.remote_api_key`, `voice.voicestudio_api_key`, TypeSafe key, license/lease material
- Filesystem paths: `model_path`, `gguf_path`, `mmproj_path`, `vault_path`, `remote_base_url`
- Process id, routing scores, hidden reasoning, tool catalogs, MCP server definitions
- Household guest labels and perception observations

If the owner asks for an absent reading, the front reply says that reading is not in the self snapshot, in one sentence, and does not guess. Covered questions are `final_basic` and do not start the worker. A question the snapshot cannot cover at all (`reply_shape` stays `self_status` but every relevant field is missing) uses `ack` and the worker, and the front line still must not invent the missing fact.

`enforce_front_safety` allows numbers and the tokens `runtime_role` / `answer_tier` only when they occur in the snapshot and `reply_shape` is `self_status`. Other invented-fact and tool-claim checks stay.

The self-status addendum addresses the owner as ANZU. This RFC does not sweep other Jarvis strings.

### 5. Holding-phrase fix

`SAFE_ACK` remains the empty-generation fallback **only** when `reply_shape` is `ack` or `handoff` needs a line and the model returned nothing. `fallback_text_for_action` must not return `SAFE_ACK` for `literal`, `social`, `self_status`, or `clarify`.

`FRONT_SYSTEM` gains an explicit instruction: when the hint is `final_basic` and the owner asked for a literal or terse reply, output that reply and nothing else. Do not prepend or append a holding sentence. Do not say you are checking details.

For `reply_shape=literal`:

- Owner-visible and spoken text is `literal_text` exactly (`ready` for `Say only the word ready`, preserving the token's case).
- `front_action` is `final_basic`.
- The worker lane does not start.
- If the model emits `SAFE_ACK`, a paraphrase of it, or any other sentence, `enforce_front_safety` replaces the text with `literal_text`.

`Say only the word ready` is the acceptance fixture. A real task (`Refactor the auth module and run the tests`) stays `handoff` / `ack` and may still use `SAFE_ACK` when the front model returns empty.

## Acceptance criteria

**This spec**

- [x] RFC-0206 accepted with the mandatory 50 ms call, the `arbitration` class, the owner-chat routing move, the self-snapshot allow/deny lists, and the literal-reply fixture.
- [x] `docs/rfcs/README.md` indexes 0206. `0204` and `0205` stay unused. Next free number is `0204`.

**Implementation (follow-on; unchecked)**

- [ ] Every `stream_owner_chat` turn and every agent-loop intake calls `decide()` once before the front reply, with a 50 ms cap, including `decision_tier=local` and single-profile turns. The audit event exists for that call. A unit test fails if the call is skipped.
- [ ] Local tier and missing Jev key: no TypeSafe HTTP. Connected `jev_optional` may call Jev only inside the remaining 50 ms budget. A late Jev body is not awaited. `source` is `jev` only when `provider=jev` and `fallback_used` is false.
- [ ] Cold or absent Laya does not stall the turn past 50 ms. Fallback source is `rules`, `generative`, or `deadline_fallback`, and the rules answer is the real route / disposition, not a constant `ack`.
- [ ] `arbitration` is in `REFLEX_DECISION_CLASSES`. Both-lanes merge goes through `arbitrate_front_and_worker` + `apply_disposition`. Existing merge fixtures still pass under the rules adapter, with no `Deeper result` heading. A fixture provider that returns `keep_front` drops a novel worker sentence; `append_novel` keeps it.
- [ ] `route_request` is not the primary classifier on `stream_owner_chat` / `classify_front_action`. Tool, app, file, and LTA utterances still force `managed_task`.
- [ ] Input `Say only the word ready` yields owner text `ready`, action `final_basic`, worker not started, and the holding phrase absent even when the front provider returns `SAFE_ACK` or is unavailable.
- [ ] `What profile is loaded?` (and the equivalent self-status phrasing the decision marks `self_status`) is answered from the snapshot, `final_basic`, with secrets and paths absent from the prompt. A field not in the snapshot is not invented.
- [ ] Hard policy, approval, and `harm_veto` behaviour is unchanged.
- [ ] `python3 -m pytest` passes. Frontend build is required only if a portal file changes; this RFC expects none.
- [ ] Desktop sign-off (not claimable from the Linux cloud VM): warm Laya p50 for `decide_owner_turn` ≤ 50 ms on the owner GPU; Jev opt-in either returns inside the cap or audits a deadline fallback without a visible stall.

## Implementable slices

Land in order. Each slice is one PR against `development` and keeps `python3 -m pytest` green. Do not start slice N+1 by reverting slice N's tests.

| Slice | Owns | Files | Done when |
| --- | --- | --- | --- |
| 1. Contract + rules | Decision lane | `backend/app/decision/types.py`, `adapters/rules.py`, `owner_turn.py` (new), `surfaces.py` (`arbitrate_front_and_worker`), `tests/test_rfc0206_decision_contract.py` | Both classes answer through `decide()` with Laya and Jev forced unavailable. Literal floor, action floor, and the merge fixture table match today's strings. No call-site change yet. |
| 2. Mandatory turn call | Owner chat + agent loop | `backend/app/decision/owner_turn.py`, `backend/app/agent/request_routing.py`, `backend/app/agent/loop.py` (intake call sites), `backend/app/persona/owner_chat.py`, `backend/app/agent/front_responder.py` (`classify_front_action` reads the decision) | Owner chat and `loop.py` both call `decide_owner_turn` before the front reply. 50 ms cap tested with a blocking provider. Local tier opens no Jev socket. |
| 3. Arbitration replaces merge | Front/worker merge | `backend/app/agent/front_responder.py` (`merge_front_and_worker`, `run_two_lane_chat`, `merge_consecutive_assistant_turns`) | Policy branches gone. Rules disposition reproduces `tests/test_front_responder.py` and `tests/test_owner_shell_delivery.py` merge cases. Provider fixture can force `keep_front` vs `append_novel`. |
| 4. Holding phrase | Front prompt + safety | `FRONT_SYSTEM`, `fallback_text_for_action`, `enforce_front_safety`, `generate_front_reply` | `Say only the word ready` fixture. Empty model on a real `ack` still yields `SAFE_ACK`. |
| 5. Self snapshot | Front envelope | `backend/app/agent/self_knowledge.py` (new), `small_context_envelope`, safety allowlist for snapshot tokens | Snapshot prompt test (allow list present, deny list absent). Covered question is `final_basic`. Missing field is not invented. |

Slice 2 depends on slice 1. Slice 3 depends on slice 1 and can follow slice 2 in either order after 1, but the literal `keep_front` guard needs slice 4's `reply_shape` to be wired, so ship 4 before or with the literal guard in 3. Slice 5 depends on slice 2's `reply_shape`.

No portal slice. If a later change touches `frontend/`, that change owns `npm --prefix frontend run build` and `npm --prefix frontend run lint`.

## Likely files

| Area | Paths |
| --- | --- |
| Decision | `backend/app/decision/types.py`, `reflex.py` (callers only; do not fork the provider chain), `surfaces.py`, `owner_turn.py`, `adapters/rules.py`, `adapters/jev_adapter.py`, `adapters/laya_adapter.py`, `laya/runtime.py` |
| Routing call sites | `backend/app/agent/request_routing.py`, `backend/app/agent/loop.py`, `backend/app/persona/owner_chat.py`, `backend/app/agent/planning.py` (baseline only) |
| Front lane | `backend/app/agent/front_responder.py`, `backend/app/agent/self_knowledge.py` |
| Tests | `tests/test_rfc0206_decision_contract.py`, `tests/test_rfc0206_owner_turn.py`, `tests/test_rfc0206_arbitration.py`, `tests/test_rfc0206_front_literal_and_self.py`; extend `tests/test_front_responder.py`, `tests/test_owner_shell_delivery.py` |
| Docs | this RFC; index line in `docs/rfcs/README.md` |

## Out of scope

- Nightly live-eval repairs already underway elsewhere: `chat_stream` deadline kwarg, context scaling stuck at 16k, memory tasks storing nothing, silent Ollama switch, Kokoro packaging, "You" attribution, unwanted file writes, leftover Jarvis strings, installer scratch-folder exclude.
- Editing `JARVIS_MASTER_PLAN.md` or any other Architect-owned spec. Queue wording is a note for the Architect, not a ledger edit in the implement PR.
- RFC-0203's terminal-turn resolver, slow-progress loop, and verify-admission collapse, except that the routing entry must call `decide_owner_turn`.
- New decision providers, a chat model posing as Jev/Laya, or raising `DEFAULT_DEADLINE_MS` (100 ms) globally. Only the two call sites in this RFC pass 50 ms.
- Persona, WebGL, presence, morph, voice UI, and a repo-wide product-rename.
- Tool permission, approval popups, and `harm_veto` policy changes.
- Swarm, Browser Use, and model-stack work.

## Risks and open questions

**Risks**

- **Jev will often miss a 50 ms cap.** RFC-0116's vendor range is roughly 70–500 ms and RFC-0171's cloud budget is p50 ≤ 350 ms. On this path the turn must not wait. Laya is the provider that can meet 50 ms (~33 ms published for one decision, desktop evidence still required). When Laya is cold, expect `deadline_fallback` rather than a Jev attribution. Implementers must not "fix" that by raising the cap.
- **Two calls can add up to 100 ms, on different parts of the turn.** `decide_owner_turn` is on the way to first text (the accepted 50 ms). `arbitration` runs only once both texts exist and must not delay the front token or the held ack.
- **Rules fallback is the product when both models are down.** A rules adapter that returns `ack` for every utterance, or `append_novel` for every merge, reintroduces the holding phrase and the dual voice. Slice 1's fixture table is the guard.
- **`compact_state` drops the middle of long prompts.** The literal extractor has to see the raw utterance. Put `literal_candidate` in state as a short field.
- **Self snapshot can leak if the builder is careless.** The deny list is tested by rendering the prompt, not by inspecting the dict alone.
- **RFC-0203 collision.** A pipeline that still treats reflex as optional refinement will bypass this RFC. The pipeline's only legal routing call is `decide_owner_turn`.
- **Cloud VM cannot sign live latency.** Unit tests use the Laya fixture and a stub Jev transport. Desktop soak stays unchecked until an owner machine measures it.

**Open questions**

- Non-English literals ("di solo la parola ready") have no rules-floor pattern in v1. Laya may still return `reply_shape=literal` when it is warm; the extractor then accepts a quoted span. Unquoted non-English forms fall through to the provider and, on a deadline miss, to today's ack path. Widen the floor only with fixtures, not with an open-ended regex router.
- Whether `mentions_self` should be a third batched boolean for mixed asks ("what model are you, then refactor auth"). v1 uses a single `reply_shape`. Mixed asks that include an explicit tool/app/file floor stay `handoff`. Revisit only if owners hit a real mixed case the single choice gets wrong.
- Speech of an `append_novel` merge stays on the existing cursor (`speakable_worker_remainder`). Arbitration does not choose a second speak policy.

## Notes

- Implement model: Composer 2.5 standard. One slice per worker prompt.
- `decide_turn` in `backend/app/decision/tier.py` (speak class, complexity, tool, approval) stays the authorize/hook batch. Do not also call it at the start of owner chat; that would be a second pre-speech reflex call this RFC does not budget.
- North-star check for the implementer: a literal reply is exact; a self question uses real state; a provider outage still answers; the owner hears one voice; Jev is named only when Jev actually answered.
