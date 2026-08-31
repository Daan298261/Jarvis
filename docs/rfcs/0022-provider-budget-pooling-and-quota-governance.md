# RFC-0022: Provider budget pooling and quota governance

**Status:** accepted  
**Queue item:** Cost governance / provider abstraction  
**Author:** ChatGPT competitor-watch synthesis  
**Date:** 2026-08-31

## Problem

Jarvis can route among local and remote runtimes, but cloud usage becomes difficult to manage when every provider exposes different units, quotas, rate limits, subscriptions, API pricing, and failure modes. Users need one understandable budget/governance layer without pretending heterogeneous providers are economically interchangeable.

## Decision

Add a `ProviderBudget` and `UsageLedger` abstraction above individual runtime/provider billing. Jarvis normalizes usage into policy-relevant measures such as monetary estimate, request count, token/input/output units, provider quota state, and local compute resource use while preserving the provider-native values for audit.

The user-facing layer may present a pooled monthly/weekly budget across eligible cloud runtimes, but routing must still use actual provider cost/limits underneath. A pooled allowance is therefore a governance abstraction, not a fake universal token currency.

Budgets can be attached at installation, workspace, agent, workflow, GoalRun, or task level. Child work inherits and cannot exceed the effective parent ceiling unless an explicit approval raises it.

## Acceptance criteria

- [ ] Persist provider-native usage plus normalized monetary estimate and resource metadata in a durable `UsageLedger`.
- [ ] `ProviderBudget` supports time-window ceilings, hard/soft limits, per-provider caps, per-model/runtime caps, and local-vs-cloud constraints.
- [ ] Effective budget is calculated hierarchically across installation, workspace, agent/workflow, goal, and task scopes; the strictest applicable hard ceiling wins.
- [ ] Router can consider remaining quota/budget and avoid a provider/model likely to exceed the effective ceiling.
- [ ] Users can define a pooled cloud-spend ceiling without losing visibility into which provider/runtime actually consumed it.
- [ ] Soft thresholds can trigger warnings or approval requests; hard thresholds prevent new billable work before execution where cost can be estimated.
- [ ] Long-running GoalRuns and scheduled work re-check current budget before each new child task/remote inference rather than relying on the budget available at creation time.
- [ ] Unknown or stale provider pricing is surfaced explicitly and can be configured to fail closed for cost-sensitive policies.
- [ ] Failed/retried calls are recorded distinctly so retry storms and hidden cost are visible.
- [ ] Dashboard shows spend/usage by provider, runtime, agent, workspace, workflow, and goal plus remaining budget/quota where known.
- [ ] Budget data never requires Jarvis to store provider account passwords; provider API credentials remain in the credential store.
- [ ] Tests cover hierarchical ceilings, concurrent spend reservation, retry accounting, stale pricing, provider quota exhaustion, and router avoidance behavior.
- [ ] Unit tests pass (`python3 -m pytest`).
- [ ] If portal code changes, `npm --prefix frontend run build` passes.

## Likely files

| Area | Paths |
| --- | --- |
| Backend | `backend/app/billing/...`, `backend/app/router/...`, usage/budget models |
| Integrations | provider usage/pricing/quota adapters |
| Frontend | budget settings and usage dashboard |
| Tests | budget inheritance, accounting, routing, concurrency tests |
| Docs | cost-governance and provider-accounting specification |

## Out of scope

Jarvis reselling third-party model credits, implementing payment processing, or guaranteeing that all provider usage can be metered identically. Commercial subscription/entitlement billing remains separate from inference usage governance.

## Notes

Inspiration: Merlin's pooled multi-model allowance, adapted for a BYO-provider/local-first agent OS. Discovery date: 2026-08-31. Recommendation: **ADAPT** the simplified budget UX, not the closed subscription model.
