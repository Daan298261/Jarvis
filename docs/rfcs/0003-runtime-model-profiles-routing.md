# RFC-0003: Named runtime/model profiles and policy-aware routing

**Status:** accepted  
**Queue item:** Model routing / worker configuration  
**Author:** ChatGPT competitor-watch synthesis  
**Date:** 2026-08-28

## Problem

Jarvis needs persistent named inference/runtime profiles so workers can use different models, endpoints, context limits, quantizations, privacy rules, and cost ceilings without embedding those choices in agent prompts. It must also make multi-model operation feel automatic: users should not need to understand every model/provider to get a good result, while advanced users still need deterministic overrides and an explanation of why Jarvis selected a runtime.

## Decision

Add reusable `RuntimeProfile` objects and make `AUTO` the first-class routing mode. Agent Profiles may select preferred/forbidden profiles, while the router retains authority to override preferences when policy, capability, budget, or capacity requires it. Routing evaluates expected success, latency, monetary cost, privacy, model/node load, network transfer, warm-model state, specialization, context fit, tool requirements, modality, and hardware fit.

Separate the decisions “which intelligence/runtime?” and “which physical node executes it?”. A user may explicitly pin either decision when deterministic behavior is required.

Automatic routing must be observable rather than opaque. Each decision records a compact reason, alternatives considered, confidence, estimated cost class, and fallback chain. Provider/model branding must remain an implementation detail unless the user asks to see it or pins a model.

## Acceptance criteria

- [ ] Runtime profiles store model, endpoint/provider, context limit, quantization, privacy class, cost ceiling, capability/modality tags, tool support, and availability state.
- [ ] `AUTO` routing is available as the default user-facing mode and can choose among local and remote runtime profiles without requiring the user to pick a model manually.
- [ ] Agents can specify preferred and forbidden profiles without hard-binding unless explicitly forced.
- [ ] Users can pin a runtime/model or node for a task, agent, or workflow; pinned selections are never silently changed except when policy makes execution impossible.
- [ ] Router scoring considers capability/task fit, context fit, privacy, expected result quality, latency, monetary cost, node/model load, network transfer, warm-model state, specialization, and hardware fit.
- [ ] Router emits a durable explanation containing selected runtime, selected node, top decision factors, confidence, estimated cost class, and fallback order.
- [ ] Routing supports local-only, local-first, best-result, cost-optimized, and automatic/balanced policies.
- [ ] Warm-model and specialization bonuses are supported without overriding privacy or explicit user policy.
- [ ] Router can retry/fallback to the next eligible profile after provider/model failure without repeating externally visible side effects.
- [ ] Router fails closed when privacy policy forbids all available remote candidates.
- [ ] Portal shows a simple `Auto` choice first, with advanced model/runtime controls available on demand rather than exposed by default.
- [ ] Unit tests cover task-fit decisions, pinned overrides, policy conflicts, fallback, unavailable providers, privacy failure, and explanation output.
- [ ] Unit tests pass (`python3 -m pytest`).
- [ ] If portal code changes, `npm --prefix frontend run build` passes.

## Likely files

| Area | Paths |
| --- | --- |
| Backend | `backend/app/inference/...`, `backend/app/router/...`, runtime-profile schemas |
| Frontend | model/runtime profile settings, task composer advanced routing controls |
| Tests | routing, fallback, profile, explanation tests |
| Docs | routing policy and `Auto` behavior docs |

## Out of scope

New inference engines or model downloads themselves; provider credit resale/accounting is handled separately.

## Notes

Initial inspiration: OpenHands saved LLM profiles/model routing and broader local-first agent platforms. Merlin competitor review on 2026-08-31 reinforced one product requirement: multi-model breadth is useful only if automatic model selection is the default and manual model choice remains optional. Recommendation: **ADAPT STRONGLY**.
