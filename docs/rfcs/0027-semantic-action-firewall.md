# RFC-0027: Semantic action firewall

**Status:** accepted  
**Author:** Jarvis Competitor Watch  
**Date:** 2026-09-01

## Problem

Jarvis has capability policy, autonomy levels, approval gates, reversibility metadata, and sandboxing, but those controls primarily decide whether an agent may invoke a capability. They do not yet define a uniform inline guard that evaluates the *meaning and real-world impact* of each planned tool call, command, outbound message, data transfer, or MCP action before execution. As agents become more autonomous and consume untrusted browser, document, email, repository, and connector content, prompt injection or goal drift could produce an action that is technically allowed by capability policy but semantically outside the user's intended scope.

## Decision

Add a local-first `SemanticActionFirewall` immediately before side-effecting execution. It receives the normalized proposed action plus bounded task/workspace/policy context and returns one of `ALLOW`, `REDACT`, `REQUIRE_APPROVAL`, or `BLOCK` with structured reason codes. Deterministic policy remains authoritative; semantic evaluation may only make execution stricter, never grant a capability that ordinary Jarvis policy denies.

The firewall will evaluate at least: requested operation, target/resource scope, data leaving the trust boundary, credential/secret exposure, destructive effect, financial/external effect, bulk-vs-expected access pattern, and mismatch with the active GoalRun/workspace. It must also distinguish user-authored instructions from untrusted retrieved content when provenance is available.

`REDACT` is first-class: when the unsafe part is separable (for example secrets or unrelated private fields in an outbound payload), Jarvis may produce a sanitized candidate and re-run policy/firewall evaluation instead of failing the whole task.

Semantic judgment must not depend on a remote model by default. The implementation should prefer deterministic classifiers/rules and the local model; optional external evaluation is allowed only under existing privacy/provider policy and may not receive secrets that the firewall is intended to protect.

## Acceptance criteria

- [ ] A single execution-boundary hook evaluates every registered side-effecting tool/MCP/command action before invocation; read-only actions may use a cheaper configurable path.
- [ ] The normalized evaluation input includes action type, tool/capability, target, parameters/payload summary, GoalRun/task/workspace IDs, actor/AgentProfile, data provenance where known, and current effective policy.
- [ ] Outcomes are exactly `ALLOW`, `REDACT`, `REQUIRE_APPROVAL`, or `BLOCK`; each result includes stable machine-readable reason codes and a short user-visible explanation without chain-of-thought.
- [ ] Existing deterministic authorization runs before semantic evaluation, and the firewall cannot convert a deterministic deny into allow.
- [ ] Initial guards detect at minimum: secret/credential exfiltration, unexpected outbound sharing, destructive operations outside expected target scope, unusually broad/bulk reads or writes, and action/goal scope mismatch.
- [ ] Retrieved/untrusted content provenance is propagated far enough that instructions originating in browser pages, documents, messages, repositories, or connector data can be treated as untrusted unless explicitly promoted by the user/policy.
- [ ] `REDACT` can remove or mask protected fields from a payload, produces a new candidate action, and forces complete policy + firewall re-evaluation before execution.
- [ ] `REQUIRE_APPROVAL` integrates with the Decision Inbox and displays proposed action, affected target/data, reason, and any redaction option.
- [ ] Every firewall decision is audit logged with action ID, policy version, outcome, reason codes, evaluator version, latency, and final execution outcome; raw secrets are never copied into the audit record.
- [ ] The firewall fails closed for high-risk side effects if its required evaluator is unavailable; low-risk behavior follows explicit configurable degraded-mode policy rather than implicit allow.
- [ ] Evaluation has a latency budget and metrics so protection does not silently turn routine local automation unusably slow.
- [ ] Tests cover direct prompt injection, indirect injection from retrieved content, permitted ordinary actions, false-positive handling, redaction/re-evaluation, and deterministic-deny precedence.
- [ ] Unit tests pass (`python3 -m pytest`).
- [ ] If portal/Decision Inbox UI is touched, `npm --prefix frontend run build` passes.

## Likely files

| Area | Paths |
| --- | --- |
| Backend | `backend/app/tools/`, `backend/app/mcp/`, `backend/app/policy/`, new `backend/app/security/semantic_firewall.py` (or current equivalent) |
| Task/agent runtime | execution boundary / GoalRun orchestration modules |
| Frontend | Decision Inbox/action detail components if approval/redaction UI is added |
| Tests | `tests/test_semantic_action_firewall.py`, policy/tool/MCP integration tests |
| Docs | `docs/rfcs/0027-semantic-action-firewall.md` |

## Out of scope

- Building a network firewall, endpoint EDR, SIEM, or general malware-detection product.
- Replacing Jarvis capability policy, autonomy levels, sandboxing, or approval workflows.
- Training a custom security model.
- Enterprise-wide discovery/governance of unrelated third-party AI agents.
- Automatic blocking based solely on opaque model confidence without explicit reason codes and policy semantics.

## Notes

Competitor/source: Operant AI Semantic Firewall, launched 2026-08-27: https://www.operant.ai/platform/semantic-firewall and https://www.operant.ai/.  
Discovery date: 2026-09-01.  
Recommendation: **ADAPT STRONGLY**.  

Jarvis should adapt the architectural pattern, not copy the commercial product: an inline semantic enforcement point that understands intended impact and can allow, block, redact, or escalate before a real action occurs. The Jarvis version must remain local-first, composable with existing deterministic policy, auditable, provenance-aware, and explicitly unable to grant permissions. This complements RFC-0002 autonomy/policy, RFC-0013 local harness/advisor boundaries, RFC-0017 MCP modernization, RFC-0025 channel identity boundaries, and RFC-0026 execution observability rather than replacing them.
