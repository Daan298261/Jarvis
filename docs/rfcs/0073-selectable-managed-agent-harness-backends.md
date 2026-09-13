# RFC-0073: Selectable managed agent harness backends

**Status:** accepted  
**Queue item:** P4 — execution portability / managed agent harness integration  
**Author:** ChatGPT competitor-watch synthesis  
**Date:** 2026-09-12

## Problem

Jarvis owns its local agent harness, persistent workers, GoalRuns, policy, approvals, verification and audit. OpenAI's Agents API public beta (2026-09-10) introduces a maintained Codex-based agent harness that can run long-lived sessions, compact context, search/load tools dynamically, coordinate subagents, use MCP, recover across long tasks, and execute inside OpenAI-hosted, self-hosted, or partner sandboxes. Perplexity is also consolidating its Sonar API into its Agent API, with Sonar tiers retiring on 2026-09-27. Perplexity Agent API combines current web retrieval, URL fetching, code execution, MCP/connectors and multiple models behind one programmable agent surface. These systems are broader than inference providers and broader than RFC-0013's analysis-only Advisor: they are external execution/research harnesses. Jarvis should be able to use maintained harnesses selectively without surrendering canonical task state or making cloud execution mandatory.

## Decision

Introduce an optional `AgentHarnessBackend` abstraction separate from `InferenceBackend`, `InferenceOffloadBackend`, worker placement, and sandbox providers.

Initial modes:

- `JARVIS_NATIVE` — Jarvis owns the complete agent loop and execution lifecycle.
- `OPENAI_AGENTS_API` — delegate a bounded execution segment to OpenAI's managed Codex harness.
- `PERPLEXITY_AGENT_API` — delegate bounded research/search-oriented execution to Perplexity Agent API, including supported web retrieval, URL fetch, code execution, MCP/connectors and model presets.
- `AUTO` — choose an allowed harness based on task class, privacy, expected capability, cost, latency, provider health and user policy.

The external harness is an execution provider, not the control plane. Jarvis remains authoritative for `GoalRun` identity, task intent, Agent Profile, policy, approval ceilings, budgets, sensitive-data egress decisions, verification requirements, audit, cancellation intent, result acceptance and long-term memory.

Each delegated run SHALL create a Jarvis-owned `HarnessExecution` record linking the Jarvis GoalRun/step to provider session/request ID, backend/version, model or preset, environment type where applicable, requested capabilities, effective policy, data-egress classification, cost/usage, lifecycle status and returned evidence/artifacts. Provider sessions are never the only copy of critical Jarvis task state.

Supported environment modes for `OPENAI_AGENTS_API` may include OpenAI-hosted sandbox, owner/self-hosted sandbox, and supported partner sandbox. Perplexity Agent API is treated as a remote managed service even when it invokes MCP or connector tools against owner resources. Environment selection is independently policy-controlled. `LOCAL ONLY` must never route to either remote managed harness. A self-hosted execution environment does not make a remote harness itself local; Jarvis must accurately disclose which control/model/context data leaves the machine.

Jarvis SHOULD map delegated work to bounded subproblems with explicit inputs, expected outputs and verifier criteria. External subagents remain internal to the provider session and do not gain Jarvis swarm identity, credentials, standing authority or permission to create new Jarvis goals unless Jarvis explicitly accepts a returned delegation proposal.

Provider tool/MCP access MUST be capability-minimized. Prefer provider-side tools only for the delegated scope. Jarvis-owned consequential actions should remain behind Jarvis tool/policy boundaries where practical; external harness completion cannot override RFC-0027/0031/0044 security decisions or owner approval requirements.

Provider adapters MUST expose capabilities rather than pretending all managed harnesses are equivalent. At minimum Jarvis distinguishes durable/resumable sessions, web retrieval, code execution, subagents, MCP/connectors, arbitrary custom tools, artifacts, streamed progress, sandbox selection, provider-side model/preset choice, usage telemetry and cancellation semantics. `AUTO` only chooses a backend that advertises the capabilities required by the delegated segment.

Perplexity Sonar endpoints are deprecated and SHALL NOT be introduced as a new Jarvis dependency. If Jarvis ever detects/configures a legacy Sonar integration, migration should map it to `PERPLEXITY_AGENT_API` presets before the 2026-09-27 retirement date, with an explicit compatibility error after retirement rather than silent fallback to another cloud provider.

Fallback must be explicit. If an external harness fails before a consequential external effect, policy may retry or fall back to `JARVIS_NATIVE` or another explicitly allowed compatible backend. If execution state is ambiguous after a possible external effect, RFC-0029 replay/idempotency rules apply and Jarvis must not blindly rerun the segment.

## Acceptance criteria

- [ ] Define `AgentHarnessBackend` with capability discovery, create/resume/cancel execution where supported, event/progress streaming or normalized polling, tool/MCP declaration, artifact/evidence retrieval, usage/cost telemetry, normalized errors and backend version metadata.
- [ ] Implement configuration values `JARVIS_NATIVE`, `OPENAI_AGENTS_API`, `PERPLEXITY_AGENT_API`, and `AUTO`, with `FORCED`, `PREFERRED`, `AUTO`, and `DISABLED` selection policy at global and Agent Profile/task scope.
- [ ] Keep harness selection distinct from model/inference routing and from sandbox placement; UI and telemetry must show all three separately when relevant.
- [ ] Add durable `HarnessExecution` state linking Jarvis GoalRun/ExecutionStep IDs to external provider session/request IDs so Jarvis can resume, inspect, cancel and reconcile without treating provider state as canonical.
- [ ] External provider sessions cannot create or widen Jarvis permissions, credentials, budgets, financial authority, filesystem scope or long-term memory merely through prompt/tool output.
- [ ] Delegated work has explicit input scope, expected outputs, verifier/evidence requirements and maximum runtime/cost/subagent ceilings where supported.
- [ ] OpenAI Agents API adapter supports durable sessions, streamed progress/events, MCP/custom-tool configuration, cancellation, artifacts and usage metadata using documented public APIs only.
- [ ] Perplexity Agent API adapter supports documented presets/models, web retrieval, URL fetching, code execution and MCP/connectors when enabled, with cited/source-bearing evidence normalized into Jarvis results.
- [ ] Provider capability discovery is normalized; `AUTO` never routes a task to a provider missing a required capability simply because it is cheaper or healthier.
- [ ] OpenAI-hosted, self-hosted and supported partner sandbox options are represented as separate environment choices with capability/region/privacy metadata; unavailable choices fail clearly.
- [ ] `LOCAL ONLY` forbids both managed remote harnesses; other privacy modes show exactly what task/context/files/tool definitions may leave the local system before first use and when policy requires approval.
- [ ] `AUTO` cannot choose a remote managed harness solely because it is healthy; selection uses task suitability, required capabilities, privacy, cost ceiling, latency history, provider availability and measured verified-success history.
- [ ] External subagents are treated as provider-internal execution details and cannot directly join the Jarvis swarm or become authoritative Agent Profiles.
- [ ] If a delegated run returns a proposal for additional work, Jarvis validates it against the original GoalRun lineage and policy before admitting new executable work.
- [ ] Failure before side effects may follow configured retry/fallback; ambiguous external effects invoke RFC-0029 reconciliation and are never blindly duplicated.
- [ ] Task detail shows harness backend, provider session/request, environment type where applicable, model/preset, runtime/cost, fallback reason, streamed phase/progress, verification result and artifact/evidence links without exposing hidden chain-of-thought.
- [ ] Legacy Sonar configuration, if present, is detected and mapped to Perplexity Agent API presets with a deprecation warning; Jarvis does not add new Sonar dependencies.
- [ ] Tests cover provider outage, cancellation, reconnect/resume where supported, duplicate event delivery, policy escalation attempts, privacy-mode blocking, tool-scope reduction, cost ceiling, capability mismatch, fallback, ambiguous-effect recovery, provider session loss and Sonar migration handling.
- [ ] Jarvis remains fully functional with no OpenAI or Perplexity API key and no external harness configured.
- [ ] Unit tests pass (`python3 -m pytest`).
- [ ] If portal is touched, `npm --prefix frontend run build` passes.

## Likely files

| Area | Paths |
| --- | --- |
| Backend | agent harness provider abstraction, OpenAI/Perplexity adapters, execution bridge, policy/router, provider event normalization |
| State | `HarnessExecution` persistence linked to GoalRun/ExecutionStep |
| Frontend | Agent Profile/task harness policy, privacy/cost disclosure, execution detail |
| Tests | harness selection, capability matching, policy isolation, resume/cancel, fallback/reconciliation, telemetry, Sonar migration |
| Docs | managed harness backend setup, provider capability matrix and trust boundaries |

## Out of scope

Replacing Jarvis orchestration/GoalRuns with provider sessions; making OpenAI or Perplexity mandatory; copying managed harness internals into Jarvis; treating a self-hosted sandbox as fully local when a remote harness/model still receives data; replacing RFC-0013 Advisor, RFC-0030 inference offload, RFC-0044 sandboxing, or RFC-0029 durable execution; exposing Jarvis credentials directly to provider subagents by default; reproducing Perplexity's retrieval stack locally; maintaining legacy Sonar after its retirement.

## Notes

Sources:  
- https://openai.com/index/introducing-the-agents-api/ — OpenAI Agents API, released 2026-09-10.  
- https://www.perplexity.ai/hub/blog/agent-api-one-place-to-build-with-llms-the-web-and-agents — Perplexity Agent API / Sonar consolidation; Sonar retirement 2026-09-27.  
- https://community.perplexity.ai/t/sonar-moving-to-agents-api/6061 — Perplexity staff confirmation of the 2026-09-27 Sonar endpoint retirement.  

Original discovery: 2026-09-12; Perplexity update: 2026-09-13.  
Recommendation: **ADAPT STRONGLY**.  

Jarvis adapts the provider boundary, not any provider's control plane. The important capability is that maintained external harnesses can be selected as bounded execution backends while Jarvis retains identity, state, policy, approvals, verification, audit and local-first behavior. Adding a second provider validates that `AgentHarnessBackend` must remain genuinely provider-neutral rather than becoming a thin OpenAI-specific wrapper. This follows the same integration-first principle as RFC-0030: use maintained external subsystems where they are strong, preserve Jarvis-native execution and user choice, and document exact capability/privacy boundaries rather than presenting remote harness execution as equivalent to local Jarvis execution.