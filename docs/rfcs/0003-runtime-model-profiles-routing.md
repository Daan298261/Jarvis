# RFC-0003: Named runtime/model profiles and policy-aware routing

**Status:** accepted  
**Queue item:** Model routing / worker configuration  
**Author:** ChatGPT competitor-watch synthesis  
**Date:** 2026-08-28

## Problem

Jarvis needs persistent named inference/runtime profiles so workers can use different models, endpoints, context limits, quantizations, privacy rules, and cost ceilings without embedding those choices in agent prompts.

## Decision

Add reusable `RuntimeProfile` objects and allow Agent Profiles to select a preferred profile while the router retains authority to override preferences when policy or capacity requires it. Routing evaluates expected success, latency, monetary cost, privacy, model/node load, network transfer, warm-model state, specialization, and hardware fit.

Separate the decision “which intelligence/runtime?” from “which physical node executes it?”.

## Acceptance criteria

- [ ] Runtime profiles store model, endpoint/provider, context limit, quantization, privacy class, cost ceiling, and capability tags.
- [ ] Agents can specify preferred and forbidden profiles without hard-binding unless explicitly forced.
- [ ] Router emits an explainable score/reason for selected runtime and node.
- [ ] Routing supports local-only, local-first, best-result, and cost-optimized policies.
- [ ] Warm-model and specialization bonuses are supported.
- [ ] Router fails closed when privacy policy forbids all available remote candidates.
- [ ] Unit tests cover routing decisions and policy conflicts.
- [ ] Portal can create/edit/select runtime profiles.

## Likely files

| Area | Paths |
| --- | --- |
| Backend | `backend/app/inference/...`, `backend/app/router/...`, schemas |
| Frontend | model/runtime profile settings |
| Tests | routing and profile tests |
| Docs | routing policy docs |

## Out of scope

New inference engines or model downloads themselves.

## Notes

Inspiration: OpenHands saved LLM profiles/model routing and broader local-first agent platforms. Recommendation: ADAPT.
