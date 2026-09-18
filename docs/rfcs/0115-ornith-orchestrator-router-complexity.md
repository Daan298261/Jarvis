# RFC-0115: Ornith as orchestrator-router + complexity tiers + visible handoff

**Status:** accepted  
**Queue item:** (none — no new §58 checkbox; implement is a named follow-up after CoS names it)  
**Author:** Jarvis Architect  
**Date:** 2026-09-17

**Parent / living spec:** [`JARVIS_1.4_SPECS.md`](../../JARVIS_1.4_SPECS.md) work packages **E + F** (§7–8) + screenshot **G** (§9 routing/inspection slice) + inference reroute slice of §10 + routing observability §11 + tests 16–23 and 33 / DoD §14 / principle §15.  
**Related (do not rewrite):** [RFC-0003](0003-runtime-model-profiles-routing.md) `RuntimeProfile` + AUTO scoring (warm-model bonus **must not** bypass 1.4 capability gates). [RFC-0048](0048-specialist-model-stack-routing.md) — Ornith already tagged `orchestrator`; 1.4 **deepens** role + `answer_tier` + visible handoff. Do **not** invent new LE/Red/Purple/ATO gates; RFC-0048 security-role password gates stay as-is. [RFC-0073](0073-hud-model-hotswap-selector.md) / [RFC-0077](0077-local-lmstudio-discovery-and-hotswap-context.md) owner pin/hotswap remain; this RFC is **automatic** routing, not a HUD rewrite. [RFC-0078](0078-in-app-help-and-qwen38-9b-default.md) everyday Qwen3.8-9B when present. [RFC-0114](0114-context-overflow-preflight-recovery.md) preflight; this RFC owns the **escalation hook** when context/capability cannot be met. RFC-0083: hidden reasoning is not shown in chat and **not** transferred on handoff. [RFC-0122](0122-ingress-size-gate-spill-and-trajectory-cap.md) is a cheap ingress size-gate on `front_responder` — **do not** duplicate this RFC’s Ornith rewrite.

This PR is **specs-only**. Product code is a follow-up implement ticket. Full intent; **no stubs / soft-fail** (Ornith answering architecture questions until it 400s, a Continue button to finish a switch, or a warm 9B winning `minimum_answer_tier >= 2`, is a fail).

**Recommended implement model:** Grok 4.6 for the role/tier/gate contract (1.4 **PR 1**); Composer 2.5 reviewed by Grok 4.5/4.6 for visible switch + handoff (**PR 3**). Independent architecture review by a **different** strong model than the implementer. Do **not** assign Ornith itself to implement or validate this architecture.

## Problem

Lightweight models such as **Ornith 1.5 9B** are treated as “the loaded model,” so they attempt difficult answers until they fail (including the 16K context overflow in RFC-0114’s screenshot). Jarvis should feel like **one** assistant while internally routing, escalating, and handing off.

RFC-0003 already scores warm-model, cost, privacy, and context fit. Warmth can let a loaded orchestrator **win work it cannot do**. RFC-0048 named Ornith as `orchestrator` but did not ship `runtime_role` / `answer_tier` on `RuntimeProfile`, a deterministic complexity baseline, a small routing envelope, or a user-visible automatic switch **without** Continue.

Tip `RuntimeProfile` (`backend/app/inference/runtime_profiles.py`) has no `runtime_role` or `answer_tier`. `AgentRoutingPreferences` has no `minimum_answer_tier`. There is no structured router result (`answer_basic` / `use_tool` / `switch_model` / …) and no `model_switch` chat event.

## Decision

Jarvis is the persistent orchestration layer. The currently loaded model is **not** Jarvis. Ornith 1.5 9B is optimized to **route**; it answers only basic/trivial turns. Complexity is classified with **rules + model output**. Capability gates run **before** scoring. Switches are visible, automatic, and continuous.

### 1. Jarvis is the orchestration layer

> The currently loaded model is not Jarvis. Jarvis is the orchestration layer that selects models and workers.

The same conversation may use:

- Ornith for routing;
- Qwen 9B / Qwen3.8-9B (or equivalent) for ordinary answers;
- a reasoning model for complex questions;
- a 27B/expert model for difficult work;
- a specialist for coding/security/vision;
- another model for verification.

The user still experiences **one** Jarvis conversation. 1.4 §15: the lightweight always-on model optimizes for responsiveness and correct delegation; stronger models run when the task justifies them.

### 2. Ornith 1.5 9B role

Optimized for:

- intent classification;
- task classification;
- deciding whether tools are required;
- selecting workers/models;
- detecting vision requirements;
- deciding whether a stronger model is required;
- **basic short answers** when confidence/capability is sufficient.

It must **not** be expected to answer arbitrary complex reasoning, architecture, coding, long-context, or deep analysis **simply because it is currently loaded**.

Ornith **35B** may be evaluated separately as a Senior Worker/Leader candidate; it does **not** automatically inherit the 9B restriction.

### 3. Extend runtime profiles with role and answer tier

```python
@dataclass
class RuntimeProfile:
    ...
    runtime_role: str = "general"
    answer_tier: int = 2
```

Roles: `orchestrator` | `general` | `reasoner` | `expert` | `specialist`

Answer tiers:

```text
0 = route only, no direct owner answer
1 = basic/trivial answers
2 = ordinary general answers
3 = complex/reasoning answers
4 = expert/high-consequence/very difficult work
```

Suggested defaults:

```text
Ornith 1.5 9B / bootstrap:
    runtime_role = orchestrator
    answer_tier = 1

General local 9B / Qwen3.8-9B everyday:
    runtime_role = general
    answer_tier = 2

Quality/reasoning model:
    runtime_role = reasoner
    answer_tier = 3

27B expert:
    runtime_role = expert
    answer_tier = 4
```

Do not conflict with RFC-0078: if Qwen3.8-9B uncensored is the everyday autoload, it is **general / tier 2**, not the orchestrator. Ornith (when selected/warm as bootstrap) stays tier 1.

### 4. Router input is small

Do **not** send the full conversation to Ornith merely to decide routing.

Routing envelope:

```json
{
  "latest_user_message": "...",
  "conversation_summary": "...",
  "recent_turn_count": 4,
  "current_model": "ornith_9b",
  "available_models": [
    {"id": "qwen38_9b", "role": "general", "answer_tier": 2, "context": 32768},
    {"id": "expert", "role": "expert", "answer_tier": 4, "context": 32768}
  ],
  "tools_available": true,
  "vision_requested": false
}
```

Structured router output:

```json
{
  "action": "switch_model",
  "required_answer_tier": 3,
  "required_capabilities": ["reasoning"],
  "preferred_context": 32768,
  "reason": "The request needs broader reasoning than the orchestration model should perform."
}
```

Allowed actions: `answer_basic` | `use_tool` | `switch_model` | `delegate` | `ask_clarification`

### 5. Capability gates happen before scoring

Warm lightweight models must not win merely because they are loaded.

```python
@dataclass
class AgentRoutingPreferences:
    ...
    minimum_answer_tier: int = 0
    required_runtime_role: str | None = None
```

Filter first:

```python
if profile.answer_tier < prefs.minimum_answer_tier:
    continue
if prefs.required_runtime_role and profile.runtime_role != prefs.required_runtime_role:
    continue
```

Only **then** score eligible candidates (latency, cost, warmth, privacy, load, specialization — RFC-0003). **Warm-model bonus must never override a hard capability requirement.**

### 6. Work package F — question complexity classification

The router needs a **deterministic baseline** so it does not depend only on a small model’s self-assessment. Lightweight scorer = **rules + model output**. The router may override **upward**. It should almost never override **downward** when hard rules require a tier.

#### Tier 1 — basic (Ornith may answer directly)

- short factual chat;
- simple UI command;
- simple file lookup;
- simple scheduling intent;
- deterministic tool routing.

#### Tier 2 — general (general answer model)

- normal explanatory questions;
- moderate comparisons;
- multi-step but straightforward tasks;
- ordinary tool synthesis.

#### Tier 3 — complex (reasoning-capable model)

- architecture;
- debugging spanning subsystems;
- coding plans;
- long-context synthesis;
- reasoning across multiple sources;
- ambiguous technical diagnosis;
- important recommendations requiring qualification.

#### Tier 4 — expert (expert/leader or specialist)

- complex software architecture changes;
- repeated failure recovery;
- difficult security analysis;
- large refactors;
- tasks explicitly requesting highest quality/expert model;
- tasks where lower-tier model confidence is low after an attempted plan.

Hard rules that assign tier ≥ 2 **must** set `minimum_answer_tier` accordingly **before** Ornith can `answer_basic`.

### 7. User-visible model switching

When Ornith is insufficient, Jarvis states this naturally and **continues automatically**.

Canonical wording:

```text
I'm switching to a more capable model so I can answer that properly.
```

Shorter wording is allowed if it still communicates escalation rather than failure. **No Continue button** is required. Do not rewind chat into a PLAN/ACCEPTANCE board.

### 8. Model-switch event

```python
await BUS.publish(
    task_id,
    "model_switch",
    "Switching model",
    {
        "from": current_profile.name,
        "to": target_profile.name,
        "reason": decision.reason,
        "user_message": (
            "I'm switching to a more capable model so I can answer that properly."
        ),
    },
    stage="model",
)
```

Suggested UI:

```text
Jarvis
I'm switching to a more capable model so I can answer that properly.

ORNITH 1.5 9B
        ↓
QWEN / REASONING MODEL
```

Do **not** expose internal stack traces or routing score dumps in normal chat.

### 9. Model handoff package

A switch preserves conversation continuity **without copying hidden reasoning**.

```python
@dataclass
class ModelHandoff:
    user_request: str
    conversation_summary: str
    recent_turns: list[ChatMessage]
    working_state: str
    relevant_observations: list[str]
    failed_attempts: list[str]
```

Required contents:

- current user request **verbatim**;
- last 6–10 relevant turns verbatim when they fit;
- older conversation as compact summary;
- relevant tool results;
- current task/working state;
- failed approaches needed to avoid repetition;
- **no hidden chain-of-thought**.

Reuse existing compaction infrastructure where possible (RFC-0114 compact path).

### 10. Do not immediately downgrade mid-turn

Once a user turn escalates:

```python
working.model_escalation_count += 1
working.active_answer_profile = target.name
```

Keep that model for the **remainder of the current user turn** unless a further specialist handoff is required.

After completion, Jarvis may return to the lightweight orchestrator after an idle timeout:

```text
heavy model idle 60-180 seconds
    -> unload heavy model
    -> restore warm orchestrator
```

Exact timeout remains configurable.

### 11. Screenshot scenario (routing slice)

Input (same as RFC-0114):

```text
Can you tell me about your current capabilities, e.g. how much of it is fully implemented and working and how much is only half baked?
```

Expected flow:

```text
Understanding request
Routing with Ornith 1.5 9B

I'm switching to a more capable model so I can answer that properly.

Loading general/reasoning model
Inspecting current Jarvis implementation if required
Answering...
```

If answering accurately requires inspecting Jarvis source/status, the router selects a **system-inspection/tool path** rather than allowing Ornith to hallucinate implementation state:

```json
{
  "action": "use_tool",
  "required_answer_tier": 2,
  "task_class": "system-inspection",
  "reason": "The question asks about current implementation state and should be grounded in repository/runtime evidence."
}
```

Forbidden overflow death is RFC-0114. This RFC forbids Ornith answering that prompt as tier-1 `answer_basic`.

### 12. Observability

Events: `model_route_decision`, `model_switch_started`, `model_switch_completed`. Recommended fields:

```json
{
  "request_id": "...",
  "from_model": "ornith_9b",
  "to_model": "qwen38_9b",
  "required_answer_tier": 3,
  "required_context": 24500,
  "active_context": 16384,
  "reason": "complex reasoning + context pressure",
  "automatic": true
}
```

Inference reroute (`model_missing`, `model_load_failed`, `output_empty` after retry) uses the same gate + visible switch when a different model takes over.

**Will not:** make Ornith 9B the expert. Let warmth bypass tier gates. Require Continue. Transfer hidden CoT. Invent LE/Red/Purple/ATO product gates (RFC-0048 security roles unchanged). Replace HUD ModelSelector. Rewrite RFC-0107 as “just compact.” Assign Ornith to implement this RFC.

## Acceptance criteria

- [ ] Specs-only in this PR (no product code)
- [ ] `RuntimeProfile` carries `runtime_role` and `answer_tier` with defaults as specified (Ornith 9B orchestrator / tier 1)
- [ ] Complexity scorer + hard rules assign tiers 1–4; router may raise, almost never lowers a hard tier
- [ ] Capability gate runs **before** RFC-0003 scoring; Ornith 9B **cannot** directly satisfy `minimum_answer_tier >= 2` (test 16)
- [ ] Warm-model bonus cannot bypass the tier gate (test 17)
- [ ] A trivial request may remain on Ornith (`answer_basic`, test 18)
- [ ] A complex architecture question escalates automatically (test 19)
- [ ] Model switch emits a visible user-facing event with canonical (or equivalent) copy (test 20); no Continue button
- [ ] Handoff preserves current user request and recent conversation (test 21); hidden reasoning is **not** transferred (test 22)
- [ ] Escalated model stays active for the remainder of the current user turn (test 23)
- [ ] Idle downgrade 60–180s (configurable) restores the warm orchestrator after the turn
- [ ] Screenshot prompt is at least tier 2 + tool/system-inspection when needed; not Ornith-only hallucination (test 33 with RFC-0114)
- [ ] Structured routing logs/events as specified
- [ ] Implement follow-up: `python3 -m pytest` (`tests/test_rfc0115_*.py`). Live Ornith→Qwen load/switch is Windows desktop sign-off. Recommended Grok 4.6 + separate reviewer.

## Likely files

| Area | Paths |
| --- | --- |
| Backend | `backend/app/inference/runtime_profiles.py`, `runtime_router.py`, `model_stack.py`, `candidate_routing.py`, `profiles.py`; `backend/app/agent/loop.py`, `model_policy.py`; events/BUS; new complexity scorer + `ModelHandoff` |
| Frontend | owner chat / Daybreak HUD rendering of `model_switch` (no score dump); do not rebuild ModelSelector |
| Tests | `tests/test_rfc0115_*.py`; updates to existing router tests |
| Docs | this RFC; `JARVIS_1.4_SPECS.md`; `JARVIS_MASTER_PLAN.md` §59 only |

## Out of scope

Product implementation in this PR. RFC-0114 prompt-budget internals (this RFC consumes `ModelCapacityExceeded` / required context). RFC-0111/0112 TTS. RFC-0113 Settings. RFC-0107 vault. HUD hotswap redesign. New security authorization gates. Swarm P3. Exploit recipes. Persona merge (RFC-0104). Bulk Instagram RFCs 0095–0104.

## Notes

- 1.4 suggested implement order: **PR 1** (roles/tiers/gates, no UI) then **PR 3** (visible switch + handoff). CoS may split into two named tickets; both remain this RFC’s contract unless a successor is filed.
- Linux cloud unit-tests gates, envelope, handoff contents, and event payload. Live model load remains desktop sign-off.
- Implement launch: this RFC only (or the named PR-1/PR-3 slice); branch from `development`; pytest; do not edit Architect spec docs; PR against `development`; do not merge other PRs.
