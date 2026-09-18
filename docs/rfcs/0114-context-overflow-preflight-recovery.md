# RFC-0114: Context overflow preflight + automatic recovery

**Status:** implemented
**Queue item:** (none — no new §58 checkbox; implement is a named follow-up after CoS names it)  
**Author:** Jarvis Architect  
**Date:** 2026-09-17

**Parent / living spec:** [`JARVIS_1.4_SPECS.md`](../../JARVIS_1.4_SPECS.md) work package **D** (§6) + inference error classification §10 + context observability §11 + tests 24–33 / DoD §14. Work package **G** screenshot scenario: this RFC owns “must not die on `Context size has been exceeded`”; [RFC-0115](0115-ornith-orchestrator-router-complexity.md) owns routing/switch/inspection for the same prompt.  
**Related (do not rewrite):** [RFC-0107](0107-obsidian-linked-memory-brain.md) durable brain — **not** “compress forever”; `n_keep ≥ n_ctx` 400 band-aids are **not** 0107’s end-state. This RFC is the **inference preflight + recovery** ticket 0107 explicitly left separate. [RFC-0011](0011-memory-context-repositories-consolidation.md) / [RFC-0013](0013-local-harness-advisor-escalation.md) compaction as emergency clamp. [RFC-0003](0003-runtime-model-profiles-routing.md) context fit. RFC-0115 escalation hook when the current model cannot satisfy required context.

This PR is **specs-only**. Product code is a follow-up implement ticket. Full intent; **no stubs / soft-fail** (catching 400 and immediately `fail_task`, or truncating blindly without a shared budget, is a fail).

**Recommended implement model:** Grok 4.6 or Grok 4.5 (1.4 §2 — cross-layer recovery). Separate stronger reviewer than the primary implementer. Composer 2.5 may write regression tests under that review.

## Problem

Observed owner-visible flow (few visible chat messages):

```text
Understanding the request
Context 16384 · vision lazy · thinking selective
Inference failed
Inference server error (400): Context size has been exceeded.
```

Jarvis 1.4 must **not** expose this as the normal outcome of a recoverable context problem.

Current architecture has **multiple** context calculations and inconsistent heuristics:

- `backend/app/agent/model_policy.py`
- `backend/app/agent/context_policy.py`
- `backend/app/agent/compaction.py`
- `backend/app/inference/manager.py`
- `backend/app/agent/loop.py`

Issues:

1. Jarvis calculates recommended/wanted context separately from the **initial server context actually applied**.
2. Different layers use different character-to-token assumptions.
3. The server may expose a **smaller live context** than the model’s nominal profile cap.
4. A 400 context error is treated as **fatal** instead of a recovery signal. Tip has no shared `is_context_overflow` detector.

RFC-0107 removes durable junk from the prompt over time. This RFC makes the **live turn** survive overflow: preflight, compact, expand, retry, then escalate — with retry limits.

## Decision

One canonical prompt-budget, one preflight path on every inference call, overflow detection, and an automatic recovery flow that does **not** mark the task failed until recovery is exhausted.

### 1. Canonical prompt budget

All inference paths use the same implementation:

```python
@dataclass
class PromptBudget:
    prompt_tokens: int
    tool_tokens: int
    output_reserve: int
    system_reserve: int
    required_context: int
    active_context: int
    profile_cap: int
    pressure: float
```

`required_context` includes **tool schemas** and **completion/output token reserve**. `active_context` is the **live server** window, not only profile metadata. `pressure = required_context / active_context` (guard zero).

### 2. Token counting priority

Preferred order:

1. backend-native tokenizer / tokenizer endpoint if supported;
2. model tokenizer bundled with the runtime;
3. conservative fallback estimate.

Use a character heuristic **only** when no tokenizer is available. Do **not** let one module assume 4 chars/token while another independently assumes 2 chars/token for the **same** request.

### 3. Central inference preflight

Every inference call runs through one path:

```python
async def prepare_inference(messages, tools, profile, max_tokens):
    budget = await calculate_prompt_budget(
        messages, tools, profile=profile, max_tokens=max_tokens,
    )
    if budget.pressure < 0.70:
        return PreparedInference(messages, tools, profile)

    messages = compact_history(messages)
    budget = await calculate_prompt_budget(...)
    if budget.pressure < 0.70:
        return PreparedInference(messages, tools, profile)

    if MANAGER.state.context_size < profile.context_size:
        target = choose_context_window(
            required=budget.required_context,
            cap=profile.context_size,
        )
        await MANAGER.apply_context(settings, target, allow_shrink=False)
        budget = await calculate_prompt_budget(...)
        if budget.pressure < 0.85:
            return PreparedInference(messages, tools, profile)

    raise ModelCapacityExceeded(budget)
```

`ModelCapacityExceeded` is a **recovery signal** (escalate via RFC-0115 if another eligible model can satisfy required context/capability), not an immediate task failure.

### 4. Context growth tiers

Keep existing practical tiers unless a model/backend supports another verified size:

```text
8K -> 16K -> 32K
```

Rules:

- do **not** shrink mid-turn;
- expand **before** sending a request that is already near the active limit;
- respect **actual server context**, not just profile metadata;
- reserve output tokens before deciding the prompt fits.

### 5. Detect context overflow errors

One shared detector:

```python
def is_context_overflow(exc: Exception) -> bool:
    text = str(exc).lower()
    markers = (
        "context size has been exceeded",
        "context length exceeded",
        "maximum context length",
        "too many tokens",
        "prompt is too long",
    )
    return any(marker in text for marker in markers)
```

HTTP 400 with those markers is recoverable. Do not special-case only llama.cpp wording.

### 6. Automatic recovery flow

When a context error occurs:

```text
1. Do not mark task failed.
2. Compact older history.
3. Recalculate prompt budget.
4. Expand active context if possible.
5. Retry the same inference turn.
6. If the current model cannot satisfy required context/capability:
      escalate to another model (RFC-0115 hook).
7. Retry on the stronger model.
8. Limit retries to prevent loops.
9. Only surface failure after recovery paths are exhausted.
```

Suggested maximum:

```text
context-only retry: 1
model escalation retry: 1
absolute inference recovery attempts per turn: 2
```

### 7. Agent-loop pattern

```python
except APIStatusError as exc:
    if is_context_overflow(exc):
        recovered = await self._recover_context_pressure(
            task_id=task_id,
            messages=messages,
            working=working,
            profile=profile,
            settings=settings,
        )
        if recovered:
            continue
    await fail_task(...)
```

A recoverable error must **not** immediately set the task to `failed`.

### 8. Inference error classification (1.4 §10, this ticket’s slice)

```text
context_overflow       -> recover (this RFC)
server_unreachable     -> retry/recover according to existing policy
model_missing          -> reroute if another eligible model exists (RFC-0115)
model_load_failed      -> reroute if possible (RFC-0115)
output_empty           -> retry once, then reroute if appropriate
timeout                -> recover or reroute according to task state
unrecoverable_error    -> fail visibly
```

This RFC must classify `context_overflow` and run recovery. Reroute actions are RFC-0115; the loop must call that hook rather than failing closed.

### 9. Observability

Events: `context_pressure_detected`, `context_compaction_started`, `context_expanded`, `context_retry`, `context_recovery_failed`. Include `required_context`, `active_context`, `profile_cap`, `pressure`, retry counts. Routing log fields when escalation happens are RFC-0115 (`from_model`, `to_model`, `required_context`, `active_context`, `automatic: true`).

### 10. Screenshot regression (shared with RFC-0115)

Input:

```text
Can you tell me about your current capabilities, e.g. how much of it is fully implemented and working and how much is only half baked?
```

**Forbidden** as the outcome (this RFC):

```text
Context 16384
Inference failed
Context size has been exceeded
```

Jarvis must either answer or **visibly** switch models (RFC-0115). A few visible messages must not produce a raw overflow failure. If accurate answering needs repo/runtime evidence, the router selects a system-inspection/tool path (RFC-0115) rather than stuffing the world into 16K.

**Will not:** treat `n_keep` / truncation as the product destination (RFC-0107). Infinite recovery loops. Shrink mid-turn. Invent LE/Red/Purple gates. Dump full vault/catalog into the prompt “to be safe.”

## Acceptance criteria

Specs-only in **this** PR:

- [x] Specs-only in this PR (no product code) — specs PR #286

Implement follow-up (landed):

- [x] One `PromptBudget` implementation used by all inference paths; tool schemas **and** output reserve are in the budget (tests 31–32) — #293 `PromptBudget` / `tests/test_rfc0114_prompt_budget.py`
- [x] Token estimation is consistent for a given request (tokenizer priority as specified) — #293 shared `estimate_prompt_tokens`
- [x] Preflight runs before inference; compaction occurs before unnecessary model failure (test 25) — #293 `prepare_inference`
- [x] 16K pressure expands to 32K when profile/server allow it (test 24); no mid-turn shrink — #293 `choose_context_window` / expand preflight
- [x] `is_context_overflow` treats simulated 400 `Context size has been exceeded` as recoverable (test 26) — #293
- [x] One context error does **not** immediately mark the task failed (test 27) — #293 `test_overflow_does_not_immediately_fail_task`
- [x] Same model turn is retried after successful recovery (test 28) — #293 compact/expand/retry on the same model
- [ ] If the current model cannot satisfy required context, routing escalates to an eligible model (test 29 — hook to RFC-0115) — **not in #293**; same-model recovery only; **no** escalate placeholder
- [x] Recovery retry limits prevent infinite loops (test 30); caps as specified — #293 `context_recovery_attempts < 2` (≤2)
- [ ] Screenshot scenario (test 33): few visible messages → answer or visible model switch; **never** raw overflow as the outcome — simulated 400 recovery is covered in unit tests; live llama.cpp 400 + screenshot remain Windows desktop sign-off. Visible model switch is RFC-0115
- [x] Structured context events as specified — #293 `context_pressure_detected` / `context_compaction_started` / `context_expanded` / `context_retry` / `context_recovery_failed`
- [x] Implement follow-up: `python3 -m pytest` (`tests/test_rfc0114_*.py`) — #293. Live llama.cpp 400 reproduction is Windows desktop sign-off; cloud uses a simulated 400
- [ ] Windows desktop sign-off: live llama.cpp `Context size has been exceeded` reproduction. Cloud VMs cannot sign this off

## Likely files

| Area | Paths |
| --- | --- |
| Backend | `backend/app/agent/context_policy.py`, `compaction.py`, `model_policy.py`, `loop.py`; `backend/app/inference/manager.py`; new prompt-budget / overflow helper module |
| Tests | `tests/test_rfc0114_*.py`, updates to `tests/test_compaction.py` if needed |
| Docs | this RFC; `JARVIS_1.4_SPECS.md`; `JARVIS_MASTER_PLAN.md` §59 only |

## Out of scope

Product implementation in this PR. RFC-0107 vault indexer / per-turn tool search (cite; compaction here is recovery, not the durable-brain end-state). RFC-0115 role/tier/visible switch (this RFC only **calls** escalation). RFC-0111 TTS. Invented LE/Red/Purple/ATO gates. Exploit recipes.

## Notes

- 1.4 suggested implement order: **PR 2** (after RFC-0115 role/tier contract **PR 1**, or combined if CoS names both). Architecture first.
- Linux cloud unit-tests simulated 400 + budget math. Live GGUF overflow remains desktop sign-off.
- Implement launch: this RFC only; branch from `development`; pytest; recommended Grok 4.6; do not edit Architect spec docs; PR against `development`; do not merge other PRs.

## Implementation note

Landed on `development` via specs **#286** @ `1f8320d` (Jarvis 1.4 RFC split) + implement **#293** @ `265b758` (`PromptBudget` + `prepare_inference` preflight; overflow recoverable via compact/expand/retry ≤2; identity-only `n_keep` + per-message tools preserved). **No** RFC-0115 escalate placeholder — same-model recovery only; exhausted recovery fails with `context_capacity_error`. RFC-0107 durable brain stays the non-compress-forever end-state. Live llama.cpp 400 remains Windows desktop sign-off. No new §58 checkbox.
