# RFC-0073: Selectable managed agent harness backends

**Status:** accepted  
**Queue item:** P4 — execution portability / managed agent harness integration  
**Author:** ChatGPT competitor-watch synthesis  
**Date:** 2026-09-12

## Problem

Jarvis owns its local agent harness, persistent workers, GoalRuns, policy, approvals, verification and audit. OpenAI's Agents API public beta (2026-09-10) introduces a maintained Codex-based agent harness that can run long-lived sessions, compact context, search/load tools dynamically, coordinate subagents, use MCP, recover across long tasks, and execute inside OpenAI-hosted, self-hosted, or partner sandboxes. This is broader than an inference provider and broader than RFC-0013's analysis-only Advisor: it is an external execution harness. Jarvis should be able to use such a maintained harness selectively without surrendering canonical task state or making cloud execution mandatory.

## Decision

Introduce an optional `AgentHarnessBackend` abstraction separate from `InferenceBackend`, `InferenceOffloadBackend`, worker placement, and sandbox providers.

Initial modes:

- `JARVIS_NATIVE` — Jarvis owns the complete agent loop and execution lifecycle.
- `OPENAI_AGENTS_API` — delegate a bounded execution segment to OpenAI's managed Codex harness.
- `AUTO` — choose an allowed harness based on task class, privacy, expected capability, cost, latency, provider health and user policy.

The external harness is an execution provider, not the control plane. Jarvis remains authoritative for `GoalRun` identity, task intent, Agent Profile, policy, approval ceilings, budgets, sensitive-data egress decisions, verification requirements, audit, cancellation intent, result acceptance and long-term memory.

Each delegated run SHALL create a Jarvis-owned `HarnessExecution` record linking the Jarvis GoalRun/step to provider session ID, backend/version, model, environment type, requested capabilities, effective policy, data-egress classification, cost/usage, lifecycle status and returned evidence/artifacts. Provider sessions are never the only copy of critical Jarvis task state.

Supported environment modes for `OPENAI_AGENTS_API` may include OpenAI-hosted sandbox, owner/self-hosted sandbox, and supported partner sandbox. Environment selection is independently policy-controlled. `LOCAL ONLY` must never route to a hosted environment. A self-hosted environment does not make the remote harness itself local; Jarvis must accurately disclose which control/model/context data leaves the machine.

Jarvis SHOULD map delegated work to bounded subproblems with explicit inputs, expected outputs and verifier criteria. External subagents remain internal to the provider session and do not gain Jarvis swarm identity, credentials, standing authority or permission to create new Jarvis goals unless Jarvis explicitly accepts a returned delegation proposal.

Provider tool/MCP access MUST be capability-minimized. Prefer provider-side tools only for the delegated scope. Jarvis-owned consequential actions should remain behind Jarvis tool/policy boundaries where practical; external harness completion cannot override RFC-0027/0031/0044 security decisions or owner approval requirements.

Fallback must be explicit. If an external harness fails before a consequential external effect, policy may retry or fall back to `JARVIS_NATIVE`. If execution state is ambiguous after a possible external effect, RFC-0029 replay/idempotency rules apply and Jarvis must not blindly rerun the segment.

## Acceptance criteria

- [ ] Define `AgentHarnessBackend` with capability discovery, create/resume/cancel execution, event streaming, tool/MCP declaration, artifact retrieval, usage/cost telemetry, normalized errors and backend version metadata.
- [ ] Implement configuration values `JARVIS_NATIVE`, `OPENAI_AGENTS_API`, and `AUTO`, with `FORCED`, `PREFERRED`, `AUTO`, and `DISABLED` selection policy at global and Agent Profile/task scope.
- [ ] Keep harness selection distinct from model/inference routing and from sandbox placement; UI and telemetry must show all three separately when relevant.
- [ ] Add durable `HarnessExecution` state linking Jarvis GoalRun/ExecutionStep IDs to external provider session IDs so Jarvis can resume, inspect, cancel and reconcile without treating provider state as canonical.
- [ ] External provider sessions cannot create or widen Jarvis permissions, credentials, budgets, financial authority, filesystem scope or long-term memory merely through prompt/tool output.
- [ ] Delegated work has explicit input scope, expected outputs, verifier/evidence requirements and maximum runtime/cost/subagent ceilings.
- [ ] OpenAI Agents API adapter supports durable sessions, streamed progress/events, MCP/custom-tool configuration, cancellation, artifacts and usage metadata using documented public APIs only.
- [ ] OpenAI-hosted, self-hosted and supported partner sandbox options are represented as separate environment choices with capability/region/privacy metadata; unavailable choices fail clearly.
- [ ] `LOCAL ONLY` forbids `OPENAI_AGENTS_API`; other privacy modes show exactly what task/context/files/tool definitions may leave the local system before first use and when policy requires approval.
- [ ] `AUTO` cannot choose a remote managed harness solely because it is healthy; selection uses task suitability, privacy, cost ceiling, latency history, provider availability and measured verified-success history.
- [ ] External subagents are treated as provider-internal execution details and cannot directly join the Jarvis swarm or become authoritative Agent Profiles.
- [ ] If a delegated run returns a proposal for additional work, Jarvis validates it against the original GoalRun lineage and policy before admitting new executable work.
- [ ] Failure before side effects may follow configured retry/fallback; ambiguous external effects invoke RFC-0029 reconciliation and are never blindly duplicated.
- [ ] Task detail shows harness backend, provider session, environment type, model, runtime/cost, fallback reason, streamed phase, verification result and artifact/evidence links without exposing hidden chain-of-thought.
- [ ] Tests cover provider outage, cancellation, reconnect/resume, duplicate event delivery, policy escalation attempts, privacy-mode blocking, tool-scope reduction, cost ceiling, fallback, ambiguous-effect recovery and provider session loss.
- [ ] Jarvis remains fully functional with no OpenAI API key or external harness configured.
- [ ] Unit tests pass (`python3 -m pytest`).
- [ ] If portal is touched, `npm --prefix frontend run build` passes.

## Likely files

| Area | Paths |
| --- | --- |
| Backend | agent harness provider abstraction, OpenAI Agents API adapter, execution bridge, policy/router, provider event normalization |
| State | `HarnessExecution` persistence linked to GoalRun/ExecutionStep |
| Frontend | Agent Profile/task harness policy, privacy/cost disclosure, execution detail |
| Tests | harness selection, policy isolation, resume/cancel, fallback/reconciliation, telemetry |
| Docs | managed harness backend setup and trust boundaries |

## Out of scope

Replacing Jarvis orchestration/GoalRuns with OpenAI sessions; making OpenAI mandatory; copying the Codex harness internals into Jarvis; treating a self-hosted sandbox as fully local when the remote harness/model still receives data; replacing RFC-0013 Advisor, RFC-0030 inference offload, RFC-0044 sandboxing, or RFC-0029 durable execution; exposing Jarvis credentials directly to provider subagents by default.

## Notes

Primary source: https://openai.com/index/introducing-the-agents-api/  
Release date: 2026-09-10; discovery date: 2026-09-12.  
Recommendation: **ADAPT STRONGLY**.  

Jarvis adapts the provider boundary, not OpenAI's control plane. The important new capability is that a maintained external harness can be selected like a bounded execution backend while Jarvis retains identity, state, policy, approvals, verification, audit and local-first behavior. This follows the same integration-first principle as RFC-0030: use a maintained external subsystem where it is strong, preserve Jarvis-native execution and user choice, and document the exact capability/privacy boundary rather than presenting remote harness execution as equivalent to local Jarvis execution.
