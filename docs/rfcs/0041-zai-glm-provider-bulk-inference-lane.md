# RFC-0041: Z.ai / GLM provider and bulk-inference lane

**Status:** accepted  
**Queue item:** P4 — provider routing / cost-aware cloud inference  
**Author:** ChatGPT research synthesis  
**Date:** 2026-09-07

## Problem

Jarvis already supports provider-neutral model routing, privacy policy, cost governance, and local/cloud fallback, but it does not yet define a concrete Z.ai/GLM provider path or a routing class optimized for long, token-heavy agent work. GLM-5.3 and GLM-5.3-Flash are attractive candidates for coding, tool use, repo-scale work, long-horizon agents, and security analysis, while stronger or more expensive frontier models may still be preferable for difficult architectural decisions and final verification. Jarvis should exploit that cost/capability split without binding agent identities to one vendor or routing private data to cloud by accident.

## Decision

Add Z.ai as a first-class optional model provider behind the existing provider/runtime abstractions and introduce a normalized `BULK_AGENT` inference intent for high-volume, latency-tolerant, tool-heavy work.

Use Z.ai's supported API directly through a provider adapter or the existing OpenAI-compatible provider path where protocol compatibility is sufficient. Do **not** integrate GLM by spoofing Claude Code configuration or hard-coding Claude model aliases. Claude Code compatibility is useful evidence that GLM works in mature agent harnesses, not the architecture Jarvis should copy.

Provider discovery should obtain the currently available model list and capability metadata from the configured Z.ai account/endpoint where possible. Do not permanently hard-code `GLM-5.3` as the provider default. A runtime profile may pin a model, but automatic profiles should follow provider discovery and Jarvis benchmark/admission policy.

Define at least these routing intents:

- `INTERACTIVE` — normal chat and low-latency tool loops;
- `BULK_AGENT` — repo-wide analysis, refactors, tests, documentation, log analysis, repetitive tool-driven work, long autonomous runs;
- `DEEP_REASONING` — difficult architecture, ambiguous debugging, high-risk reasoning, or tasks that already defeated a cheaper model;
- `VERIFICATION` — independent review using a model chosen for quality/diversity rather than cost alone.

GLM is an eligible implementation for these intents, not a permanent owner of them. Initial policy should strongly consider GLM-5.3 for `BULK_AGENT`, benchmark GLM-5.3-Flash for multimodal/computer-use workloads, and permit escalation to a stronger configured frontier model when confidence, benchmark history, task risk, or verifier policy requires it.

Jarvis's Blue/Developer/Research/etc. agents retain their identities, permissions and authority. A GLM runtime is only an inference resource underneath those agents. Security-related routing must not grant additional security tool permissions or bypass `SECURITY_AGENTS.md` policy.

### Cost and quota behavior

Extend provider accounting from RFC-0022 so the Z.ai adapter can represent, where observable:

- remaining plan/API quota;
- quota reset window;
- provider-native credits/usage;
- request and token usage;
- off-peak or promotional compute windows;
- current model availability;
- retry/rate-limit/quota-exhaustion state.

Scheduled, non-urgent bulk jobs may be shifted to cheaper/off-peak windows when the user policy allows delay. `BULK_AGENT` tasks must re-check quota before spawning large child-task trees. Quota exhaustion should move to the next allowed runtime profile rather than creating retry storms.

### Privacy behavior

Z.ai is remote inference. Before any request leaves the local system, Jarvis must apply the existing workspace/agent privacy policy. Source code, private documents, PII, screenshots, or other protected context may only be sent when the effective policy explicitly permits that class of cloud data.

`LOCAL ONLY` is absolute. Failure of a local runtime or exhaustion of a local queue must never silently reroute a task to Z.ai.

### Benchmark admission

Vendor benchmark claims are useful for candidate selection but not sufficient for automatic trust. Add GLM models through the normal benchmark/admission path and record Jarvis-measured results for relevant workloads, including:

- coding-agent completion success;
- tool-call validity and recovery;
- repo-scale patch quality;
- long-context stability;
- security-review precision/verification rate;
- multimodal/computer-use success for Flash where applicable;
- latency and tail latency;
- tokens/output and provider-native cost/quota usage;
- verifier disagreement/failure rate.

Routing should learn from these measurements and may demote a model for a task class even if its general benchmark reputation is strong.

## Acceptance criteria

- [ ] Add a `zai` provider configuration using Z.ai's supported API protocol/endpoints without Claude Code as a dependency.
- [ ] Provider credentials remain in Jarvis secret storage and are never written into prompts, logs, or repository files.
- [ ] Discover available Z.ai models from the account/endpoint where supported; manual model IDs remain possible for advanced users.
- [ ] Do not hard-code GLM-5.3 as a permanent default mapping.
- [ ] Add normalized task inference intents including `BULK_AGENT`, `DEEP_REASONING`, and `VERIFICATION` without tying them to one provider.
- [ ] `BULK_AGENT` can prefer GLM according to measured capability, cost, quota and policy.
- [ ] A stronger configured model can be used for escalation or independent verification when policy permits.
- [ ] GLM-5.3-Flash is separately benchmarked/admitted for multimodal and computer-use tasks rather than assumed equivalent to GLM-5.3.
- [ ] Security agents using GLM receive no permissions beyond the owning Agent Profile/security policy.
- [ ] Z.ai usage integrates with `ProviderBudget`/`UsageLedger` and preserves provider-native quota/credit values where observable.
- [ ] Router recognizes quota exhaustion/rate limiting and follows configured fallback without uncontrolled retries.
- [ ] Non-urgent scheduled bulk work may prefer known lower-cost/off-peak windows when enabled by user policy.
- [ ] Privacy governor blocks remote calls when the task context contains a class not allowed for cloud use.
- [ ] `LOCAL ONLY` cannot fall through to Z.ai.
- [ ] Routing telemetry records provider, requested/actual model, task intent, selection reason, measured latency, usage/cost/quota state, fallback and verification result.
- [ ] Benchmark harness evaluates GLM on representative Jarvis agent tasks before enabling high-confidence automatic routing for a task class.
- [ ] Unit tests pass (`python3 -m pytest`).
- [ ] If portal code changes, `npm --prefix frontend run build` passes.

## Likely files

| Area | Paths |
| --- | --- |
| Provider/backend | `backend/app/inference/...`, OpenAI-compatible provider adapter, provider discovery |
| Router | task-intent classification, escalation/verifier selection |
| Cost | `ProviderBudget`, `UsageLedger`, quota/off-peak metadata adapters |
| Privacy | cloud-data classification/policy checks before provider dispatch |
| Frontend | provider setup, quota/usage display, routing explanation |
| Tests | provider protocol, quota failure, privacy block, bulk routing, escalation, benchmark admission |
| Docs | provider setup and benchmark/admission notes |

## Out of scope

Embedding or redistributing GLM weights; making Z.ai mandatory; replacing local-first operation; implementing Claude Code as Jarvis's orchestration layer; treating vendor security benchmarks as authorization for offensive behavior; permanently assigning any Agent Profile to GLM.

## Notes

Primary references:

- Source guide reviewed 2026-09-07: "How to run GLM-5.3 inside Claude Code for $12 a month".
- https://zcode.z.ai/en
- https://zcode.z.ai/en/changelog
- https://zcode.z.ai/cn/docs/configuration
- https://z.ai/model-api
- `docs/rfcs/0003-runtime-model-profiles-routing.md`
- `docs/rfcs/0022-provider-budget-pooling-and-quota-governance.md`

Official ZCode release notes show GLM-5.3 was added on 2026-08-14 and GLM-5.3-Flash on 2026-08-26. The current Z.ai/ZCode documentation exposes Coding Plan and OpenAI-compatible API paths. Plan pricing, quotas, model mappings and promotions are provider state and must be discovered/configured rather than encoded as permanent product assumptions.

Recommendation: **ADAPT STRONGLY**.
