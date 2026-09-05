# RFC-0027: Semantic action firewall

**Status:** accepted  
**Author:** Jarvis Competitor Watch  
**Date:** 2026-09-01; updated 2026-09-05

## Problem

Jarvis has capability policy, autonomy levels, approval gates, reversibility metadata, and sandboxing, but those controls primarily decide whether an agent may invoke a capability. They do not yet define a uniform inline guard that evaluates the *meaning and real-world impact* of each planned tool call, command, outbound message, remote-model request, data transfer, or MCP action before execution. As agents become more autonomous and consume untrusted browser, document, email, repository, connector, memory, and tool context, prompt injection, goal drift, or hybrid cloud escalation could produce an action that is technically allowed but semantically outside the user's intended scope or leak sensitive local data.

## Decision

Add a local-first `SemanticActionFirewall` immediately before side-effecting execution and every trust-boundary egress. It receives the normalized proposed action plus bounded task/workspace/policy context and returns one of `ALLOW`, `REDACT`, `REQUIRE_APPROVAL`, or `BLOCK` with structured reason codes. Deterministic policy remains authoritative; semantic evaluation may only make execution stricter, never grant a capability that ordinary Jarvis policy denies.

The firewall evaluates at least: requested operation, target/resource scope, data leaving the trust boundary, credential/secret exposure, destructive effect, financial/external effect, bulk-vs-expected access pattern, mismatch with the active GoalRun/workspace, and provenance of instructions/data. `REDACT` is first-class: when unsafe content is separable, Jarvis produces a sanitized candidate and re-runs policy/firewall evaluation instead of failing the whole task.

For remote model/provider calls, the firewall also acts as a `PrivacyGateway`. It evaluates the **final serialized outbound payload** after memory retrieval, compaction, tool results, attachment extraction, and intermediate summaries have been assembled. A compact replaceable local detector may identify sensitive spans/categories, including repeated identifiers across a long conversation. The gateway may keep protected data local, redact it into stable local placeholders, require explicit approval, or block egress entirely. Placeholder-to-original mappings remain local.

Hybrid execution remains Jarvis-owned: cloud models may receive public research, abstractions, anonymized questions, or sanitized facts while local workers retain sensitive files and execute protected actions. A remote advisor/model cannot implicitly request raw protected values; every later disclosure is a new firewall decision.

Semantic/privacy judgment must not depend on a remote model by default. Prefer deterministic rules/classifiers and local models. Optional external evaluation is allowed only under existing privacy/provider policy and may not receive the secrets the firewall is intended to protect.

## Acceptance criteria

- [ ] A single execution-boundary hook evaluates every registered side-effecting tool/MCP/command action before invocation; read-only actions may use a cheaper configurable path.
- [ ] Every remote-model/provider request is evaluated after its final outbound payload is serialized, not merely when source documents are first read.
- [ ] The normalized evaluation input includes action type, tool/capability, target, parameters/payload summary, GoalRun/task/workspace IDs, actor/AgentProfile, data provenance where known, and current effective policy.
- [ ] Outcomes are exactly `ALLOW`, `REDACT`, `REQUIRE_APPROVAL`, or `BLOCK`; each result includes stable machine-readable reason codes and a short user-visible explanation without chain-of-thought.
- [ ] Existing deterministic authorization runs before semantic evaluation, and the firewall cannot convert a deterministic deny into allow.
- [ ] Initial guards detect at minimum: secret/credential exfiltration, payment/account and government identifiers, private contact details, user-marked confidential data, unexpected outbound sharing, destructive operations outside expected target scope, unusually broad/bulk reads or writes, and action/goal scope mismatch.
- [ ] Sensitive-data checks cover the actual outbound combination of prompt text, memory, conversation history, tool output, summaries, attachment-derived content, and generated intermediate context.
- [ ] Retrieved/untrusted content provenance is propagated so instructions originating in browser pages, documents, messages, repositories, or connector data can be treated as untrusted unless explicitly promoted by user/policy.
- [ ] `REDACT` removes/masks protected fields, produces a new candidate action, and forces complete policy + firewall re-evaluation before execution.
- [ ] Redaction can use stable placeholders for locally re-associated values; the mapping and raw protected values never enter cloud-visible metadata or ordinary logs.
- [ ] Workspace/profile/provider policy can define classes as always-local, redactable, approval-required, or blocked; narrower policy may make global settings stricter but not weaker.
- [ ] `REQUIRE_APPROVAL` integrates with Decision Inbox and previews the target, data categories, intended recipient/provider, and sanitized/unredacted portions relevant to the decision without exposing secrets in logs.
- [ ] Every firewall/egress decision is audit logged with action/request ID, provider/model where relevant, policy version, outcome, detected categories, evaluator version, released byte/token count, approval ID, latency, and final execution outcome; raw secrets are not copied into audit records.
- [ ] The local sensitive-data detector is replaceable behind an interface and benchmarkable; adopting a detector such as Perplexity PII-Tracer requires license/runtime/quality validation rather than hard-coding that implementation.
- [ ] Long-context tests include repeated sensitive identifiers across multiple turns and verify all occurrences are protected before egress.
- [ ] A remote Advisor cannot bypass protection by requesting a second-step disclosure through another worker/tool; the later egress is independently evaluated.
- [ ] When cloud escalation is blocked, Jarvis can continue locally where possible and reports the reason/degraded state instead of silently failing or silently leaking.
- [ ] The firewall fails closed for high-risk side effects/egress if its required evaluator is unavailable; low-risk behavior follows explicit configurable degraded-mode policy rather than implicit allow.
- [ ] Evaluation has latency metrics/budgets so protection does not silently make routine local automation unusably slow.
- [ ] Tests cover direct/indirect prompt injection, ordinary permitted actions, false-positive handling, redaction/re-evaluation, repeated PII, deny/approval, deterministic-deny precedence, and attempted second-step exfiltration.
- [ ] Unit tests pass (`python3 -m pytest`).
- [ ] If portal/Decision Inbox UI is touched, `npm --prefix frontend run build` passes.

## Likely files

| Area | Paths |
| --- | --- |
| Backend | `backend/app/tools/`, `backend/app/mcp/`, `backend/app/policy/`, security/firewall + privacy-egress evaluator |
| Task/agent runtime | execution boundary, remote-provider/Advisor request assembly, GoalRun orchestration |
| Frontend | Decision Inbox/action detail, privacy/routing settings, egress audit detail |
| Tests | semantic firewall, egress policy, redaction, repeated-PII and exfiltration tests |
| Docs | semantic-action and remote-data-egress contract |

## Out of scope

- Building a network firewall, endpoint EDR, SIEM, or general DLP product.
- Replacing Jarvis capability policy, autonomy levels, sandboxing, or approval workflows.
- Training a custom security/privacy model.
- Enterprise-wide discovery/governance of unrelated third-party AI agents.
- Automatic blocking based solely on opaque model confidence without explicit reason codes and policy semantics.

## Notes

Original competitor/source: Operant AI Semantic Firewall, launched 2026-08-27: https://www.operant.ai/platform/semantic-firewall  
New sources: Perplexity Hybrid Compute and PII-TRACE/PII-Tracer, published 2026-09-01: https://www.perplexity.ai/hub/blog/introducing-hybrid-compute-on-mac and https://www.perplexity.ai/hub/blog/pii-trace-detecting-personal-data-before-it-leaves-the-device  
Discovery/update date: 2026-09-05.  
Recommendation: **ADAPT STRONGLY**.  

Jarvis adapts the local privacy-gateway/selective hybrid-compute boundary into its existing semantic firewall: final-payload egress inspection, local detection, redaction, consent, audit, and local fallback remain Jarvis-owned. It does not copy Perplexity's Mac-specific stack or make one vendor detector/provider mandatory. This complements RFC-0013 Advisor authority isolation and RFC-0030 selectable inference backends.
