# RFC-0003: Named runtime/model profiles and policy-aware routing

**Status:** accepted  
**Queue item:** Model routing / worker configuration  
**Author:** ChatGPT competitor-watch synthesis  
**Date:** 2026-08-28

## Problem

Jarvis needs persistent named inference/runtime profiles so workers can use different models, endpoints, context limits, quantizations, privacy rules, and cost ceilings without embedding those choices in agent prompts. It must also make multi-model operation feel automatic: users should not need to understand every model/provider to get a good result, while advanced users still need deterministic overrides and an explanation of why Jarvis selected a runtime. Provider-hosted models also have independent lifecycles: OpenAI announced on 2026-09-18 that GPT-5.5 will retire from ChatGPT, ChatGPT Work, and Codex on 2026-10-14, requiring saved model settings, custom agents, scheduled tasks, and scripts that pin it to migrate. Jarvis therefore cannot treat a currently valid model ID as indefinitely valid configuration.

## Decision

Add reusable `RuntimeProfile` objects and make `AUTO` the first-class routing mode. Agent Profiles may select preferred/forbidden profiles, while the router retains authority to override preferences when policy, capability, budget, capacity, or model lifecycle requires it. Routing evaluates expected success, latency, monetary cost, privacy, model/node load, network transfer, warm-model state, specialization, context fit, tool requirements, modality, hardware fit, and lifecycle health.

Separate the decisions “which intelligence/runtime?” and “which physical node executes it?”. A user may explicitly pin either decision when deterministic behavior is required.

Automatic routing must be observable rather than opaque. Each decision records a compact reason, alternatives considered, confidence, estimated cost class, and fallback chain. Provider/model branding must remain an implementation detail unless the user asks to see it or pins a model.

Jarvis SHALL maintain lifecycle metadata for provider-backed runtime profiles where that information is available: `ACTIVE`, `DEPRECATED`, `RETIRING`, `RETIRED`, or `UNKNOWN`, plus announced retirement time, replacement/successor hints, source/probe time, and last successful availability check. Provider announcements or capability probes update this metadata without silently rewriting user-owned configuration.

`AUTO` must stop selecting `RETIRED` models and should avoid `RETIRING` models when an eligible replacement exists. Explicit pins remain visible as pins, but a retired/unavailable pin must fail with a migration recommendation or require an explicit configured fallback; Jarvis must never silently reinterpret a forced model ID as another model. Scheduled automations, persistent Agent Profiles, workspace defaults, scripts/workflows, and other durable references must be discoverable through a dependency scan so one retirement can be remediated before the cutoff. Migration is previewable and auditable, preserves policy/capability/privacy constraints, and does not automatically accept a provider-recommended successor if it violates them.

## Acceptance criteria

- [ ] Runtime profiles store model, endpoint/provider, context limit, quantization, privacy class, cost ceiling, capability/modality tags, tool support, availability state, and lifecycle state.
- [ ] Provider-backed profiles can record `ACTIVE`, `DEPRECATED`, `RETIRING`, `RETIRED`, or `UNKNOWN`, announced retirement time, replacement hint, lifecycle source/probe time, and last successful availability check.
- [ ] `AUTO` routing is available as the default user-facing mode and can choose among local and remote runtime profiles without requiring the user to pick a model manually.
- [ ] `AUTO` never selects a known `RETIRED` profile and penalizes `RETIRING` profiles when a policy-compatible replacement exists.
- [ ] Agents can specify preferred and forbidden profiles without hard-binding unless explicitly forced.
- [ ] Users can pin a runtime/model or node for a task, agent, or workflow; pinned selections are never silently changed except when policy makes execution impossible.
- [ ] A retired or unavailable forced pin produces a clear blocked/migration state or uses only an explicitly configured fallback; it is never silently remapped to another model ID.
- [ ] A dependency scan can enumerate durable references to a retiring model across at least Agent Profiles, workspace/default settings, scheduled automations, and persisted workflow/runtime configuration.
- [ ] Before an announced retirement deadline, the UI/API can surface affected references and preview a migration plan with old profile, proposed replacement, capability/policy differences, and fallback behavior.
- [ ] Applying a lifecycle migration is explicit, audited, idempotent, and preserves privacy, cost, capability, tool/modality, and owner policy constraints; incompatible provider-recommended successors fail closed for manual review.
- [ ] Lifecycle metadata can be refreshed from provider capability discovery/health probes or trusted provider notices without granting the provider authority over Jarvis task state or policy.
- [ ] Router scoring considers capability/task fit, context fit, privacy, expected result quality, latency, monetary cost, node/model load, network transfer, warm-model state, specialization, hardware fit, and lifecycle health.
- [ ] Router emits a durable explanation containing selected runtime, selected node, top decision factors, confidence, estimated cost class, and fallback order.
- [ ] Routing supports local-only, local-first, best-result, cost-optimized, and automatic/balanced policies.
- [ ] Warm-model and specialization bonuses are supported without overriding privacy or explicit user policy.
- [ ] Router can retry/fallback to the next eligible profile after provider/model failure without repeating externally visible side effects.
- [ ] Router fails closed when privacy policy forbids all available remote candidates.
- [ ] Portal shows a simple `Auto` choice first, with advanced model/runtime controls and lifecycle warnings available on demand rather than exposed by default.
- [ ] Unit tests cover task-fit decisions, pinned overrides, policy conflicts, fallback, unavailable providers, privacy failure, explanation output, retirement cutoff, lifecycle refresh, dependency scanning, migration preview, incompatible successor rejection, and idempotent migration.
- [ ] Unit tests pass (`python3 -m pytest`).
- [ ] If portal code changes, `npm --prefix frontend run build` passes.

## Likely files

| Area | Paths |
| --- | --- |
| Backend | `backend/app/inference/...`, `backend/app/router/...`, runtime-profile schemas, provider capability/lifecycle probes, dependency scanner/migration service |
| Frontend | model/runtime profile settings, lifecycle warnings/migration preview, task composer advanced routing controls |
| Tests | routing, fallback, profile, lifecycle, migration, explanation tests |
| Docs | routing policy, model lifecycle/migration, and `Auto` behavior docs |

## Out of scope

New inference engines or model downloads themselves; provider credit resale/accounting is handled separately. Jarvis does not promise automatic migration between models with materially incompatible capabilities or privacy/cost properties, and it does not let a provider retirement notice rewrite active tasks or policy without Jarvis validation.

## Notes

Initial inspiration: OpenHands saved LLM profiles/model routing and broader local-first agent platforms. Merlin competitor review on 2026-08-31 reinforced one product requirement: multi-model breadth is useful only if automatic model selection is the default and manual model choice remains optional. Recommendation: **ADAPT STRONGLY**.

2026-09-19 competitor-watch update: OpenAI's 2026-09-18 Codex/ChatGPT weekly update announced that GPT-5.5 will retire from ChatGPT, ChatGPT Work, and Codex on 2026-10-14 and explicitly told users to update saved model settings, workspace defaults, custom agents, scheduled tasks, and scripts. Source: https://developers.openai.com/docs/whats-new . Recommendation: **ADAPT STRONGLY**. Jarvis adapts the operational lesson—model references need lifecycle health, dependency discovery, migration preview, and deterministic fallback—not OpenAI-specific model naming or provider control.