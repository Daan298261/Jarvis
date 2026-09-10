# RFC-0064: Agent Client Protocol interoperability

**Status:** accepted  
**Queue item:** Extensible Agent OS — external client interoperability  
**Author:** ChatGPT competitor-watch synthesis  
**Date:** 2026-09-10

## Problem

Jarvis can consume MCP tools and expose its own desktop/web/mobile surfaces, but it does not define a standard way for third-party agent clients such as Zed, JetBrains IDEs, VS Code ACP clients, Neovim integrations, or other compatible hosts to drive a persistent Jarvis Agent Profile. Letta's September 2026 `letta-acp` adapter demonstrates a mature pattern: one durable stateful agent can be exposed over the open Agent Client Protocol (ACP), preserve sessions across adapter restarts, stream tool/reasoning updates, forward explicit permission requests to the client, reuse MCP servers supplied by the client, and keep the agent/runtime independent from the editor UI. Without an ACP boundary, Jarvis would need bespoke integrations for each editor/client and would fragment session, permission, and tool semantics.

## Decision

Add an optional Jarvis-owned `ACPAgentAdapter` that exposes selected Jarvis Agent Profiles as ACP agents while keeping Jarvis task state, policy, approvals, verification, memory, and execution authority inside Jarvis.

ACP is a client/agent interoperability protocol, not a replacement for MCP or Jarvis's ChannelGateway. MCP remains the tool/server boundary; ACP lets an external interactive client host the user experience for a Jarvis agent. The adapter SHALL translate ACP lifecycle/session operations into existing Jarvis conversations, Agent Profiles, GoalRuns, execution events, Decision Inbox requests, and tool results rather than creating a parallel agent runtime.

The first implementation SHOULD use ACP's normal stdio transport for local clients. Remote transports may be added only once the ACP ecosystem standardizes them sufficiently and Jarvis can authenticate them safely.

Each ACP session SHALL bind explicitly to one permitted Jarvis Agent Profile and workspace/CWD scope. Session creation, loading, listing, cancellation, model/mode selection, and stream updates MUST reuse Jarvis's existing durable identifiers and authority model. An external ACP client may request filesystem/terminal operations or present MCP servers, but client-provided capabilities never broaden the effective Jarvis policy; effective authority is the intersection of Agent Profile, workspace/task policy, ACP client capability, and any node/runtime restrictions.

Permission prompts SHALL map to exact Jarvis approval objects with action identity, scope, nonce/expiry where applicable, and audit provenance. Generic client modes such as `standard`, edit-auto-approval, or unrestricted-like modes are treated only as requested convenience policy; they cannot override Jarvis hard denies, configured autonomy ceilings, semantic firewall decisions, credential boundaries, or reversibility gates.

ACP session state MUST remain resumable across adapter restarts. The adapter should map one ACP session ID to one durable Jarvis conversation/GoalRun context and replay bounded normalized history/events when a client reconnects. Client UI state is not authoritative task state.

Where the ACP client exposes editor filesystem capabilities, Jarvis MAY register client-delegated file tools so edits can land in the editor buffer/diff/undo workflow rather than bypassing it with raw disk writes. These delegated operations remain normal Jarvis tools with provenance, policy and approval checks.

ACP clients may supply MCP server configurations for a session. Jarvis SHALL route those through the existing MCP abstraction and RFC-0017 policy/version/auth handling; ACP does not get a second independent MCP implementation.

## Acceptance criteria

- [ ] Implement an optional `ACPAgentAdapter` behind a clear enable/disable setting; Jarvis works normally with ACP absent.
- [ ] Support ACP initialization/capability negotiation and local stdio transport using the maintained ACP SDK or a protocol-compatible abstraction.
- [ ] `session/new`, `session/load`, `session/list`, prompt/stream update, cancellation/close, and permission-request flows map onto existing Jarvis Agent Profile/conversation/GoalRun state rather than parallel stores.
- [ ] An ACP session explicitly records `agent_profile_id`, workspace/CWD scope, external client implementation/version where available, and negotiated capabilities.
- [ ] ACP session identifiers remain resumable across adapter process restarts and do not create duplicate Jarvis tasks on reconnect.
- [ ] Streaming maps Jarvis assistant text, tool calls/results, execution phase, verifier status, and recoverable errors into ACP updates without exposing private chain-of-thought.
- [ ] Client-requested permission modes can only reduce friction within existing Jarvis policy and cannot override deterministic denies, autonomy ceilings, RFC-0027 semantic/privacy firewall decisions, RFC-0031 reversibility gates, or credential policy.
- [ ] Each consequential ACP approval is linked to one exact Jarvis Decision Inbox/action identity and is auditable with client/session provenance.
- [ ] If the client advertises filesystem capabilities, Jarvis can optionally expose editor-delegated read/write tools; their effective filesystem scope is bounded by the session workspace and normal Jarvis policy.
- [ ] Client-provided MCP server definitions are consumed through the existing RFC-0017 MCP implementation, with normal version negotiation, credential handling, failure isolation and cleanup.
- [ ] ACP client disconnect/crash does not corrupt the underlying Jarvis task; persistent work follows the task's configured persistence/proactivity policy rather than the lifetime of the editor process.
- [ ] Disabling/revoking an ACP binding prevents new sessions while preserving existing Jarvis agent memory/task records for owner inspection.
- [ ] Adapter logs protocol/session/action IDs and compatibility errors but never raw credentials or private model reasoning.
- [ ] Compatibility tests exercise at least one real ACP client or published conformance/CLI tool plus a deterministic fake client.
- [ ] Tests cover reconnect/resume, duplicate request handling, permission escalation attempts, client capability loss, malformed protocol input, MCP handoff, and editor-file delegation.
- [ ] Unit tests pass (`python3 -m pytest`).
- [ ] If portal settings/status UI is touched, `npm --prefix frontend run build` passes.

## Likely files

| Area | Paths |
| --- | --- |
| Backend | ACP adapter/server, agent/session bridge, execution-event translator, policy/approval bridge |
| Integrations | existing MCP registry/client reused for ACP-supplied MCP servers |
| Frontend | optional ACP enablement, bindings, active sessions/compatibility status |
| Tests | protocol lifecycle, reconnect/idempotency, permissions, MCP handoff, delegated filesystem fixtures |
| Docs | ACP setup, supported capabilities, client compatibility and trust model |

## Out of scope

- Replacing MCP, ChannelGateway, Jarvis's own desktop/mobile UI, or the native task/orchestration engine.
- Making ACP clients authoritative for Jarvis memory, policy, approvals, verification, budgets or durable task state.
- Implementing bespoke plugins for every editor once standard ACP support is sufficient.
- Remote ACP transport until a stable interoperable transport and authentication profile is available.
- Automatically granting full local filesystem or terminal access merely because the ACP client advertises those capabilities.

## Notes

Primary competitor/source: https://github.com/letta-ai/letta-acp  
ACP ecosystem/specification: https://agentclientprotocol.com/ and https://zed.dev/acp  
Discovery date: 2026-09-10.  
Recommendation: **ADAPT STRONGLY**.

Jarvis adapts Letta's useful separation between a durable stateful agent and a thin ACP client adapter, but does not adopt Letta as a runtime dependency. Jarvis remains the authority for identity, memory, GoalRuns, policy, approvals, verification, MCP ownership, audit and persistence. The practical payoff is "implement once, appear in many clients": a Jarvis Developer agent could be used from Jarvis's own UI, Zed, JetBrains, VS Code or another ACP-compatible environment without creating separate bots or memories for each surface. This complements RFC-0009 agent runtime portability, RFC-0017 MCP interoperability and RFC-0025 multi-channel continuity while addressing a distinct agent-to-client protocol boundary.