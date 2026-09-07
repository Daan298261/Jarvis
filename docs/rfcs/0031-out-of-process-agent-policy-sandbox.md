# RFC-0031: Out-of-process agent policy sandbox

**Status:** accepted  
**Queue item:** P2/P3 — autonomous execution safety  
**Author:** ChatGPT NVIDIA local-AI architecture review  
**Date:** 2026-09-07

## Problem

Jarvis has capability policy, semantic action filtering, approvals and isolated workers, but a sufficiently capable or self-modifying agent must not be the ultimate enforcer of its own permissions. NVIDIA OpenShell demonstrates a useful runtime pattern: enforce filesystem, process, network and credential boundaries outside the agent/harness, with deny-by-default policy, live scoped approvals and audit. Jarvis needs the same invariant without becoming dependent on OpenShell or NVIDIA hardware.

## Decision

Introduce a provider-neutral `AgentExecutionSandbox` boundary that runs autonomous/high-risk workers inside an isolation runtime whose policy is enforced outside the agent process. Jarvis policy compiles into runtime-enforceable filesystem, process, network-egress, credential and resource grants. The agent may request a broader grant, but cannot grant it to itself.

Initial providers may include a Jarvis-native container/process sandbox and optional NVIDIA OpenShell integration where supported. OpenShell is an adapter, not Jarvis's policy source of truth.

Use deny-by-default for network and protected host resources in autonomous sandboxes. Approvals produce narrowly scoped, expiring grants bound to the GoalRun/worker/action where feasible. Credentials should be injected or proxied only for the permitted operation and should not be exposed as ordinary environment variables/files when the backend supports brokered access.

Memory, retrieved content, skills and model output are untrusted inputs, never authorization. Runtime enforcement remains authoritative even if an agent is prompt-injected or modifies its own skill files.

## Acceptance criteria

- [ ] Define an `AgentExecutionSandbox` provider interface covering create/start/stop/destroy, policy application, capability discovery, resource limits, audit events and health.
- [ ] Provide normalized policy primitives for filesystem paths/modes, executable/process constraints, network destination/port/protocol, credential handles, device access and CPU/RAM/GPU limits where enforceable.
- [ ] High-autonomy/high-risk workers can be configured to require an external sandbox; failure to create the required sandbox fails closed.
- [ ] Sandbox policy is enforced outside the agent/model/harness process and cannot be weakened by tool output, memory, skills or prompt instructions.
- [ ] Default autonomous-worker network policy is deny unless allowed by effective Jarvis policy.
- [ ] A blocked action produces a structured event containing worker/GoalRun, attempted resource, rule/reason and timestamp without leaking protected credential values.
- [ ] Decision Inbox can approve a blocked capability as a narrow grant with explicit scope and expiry; the worker cannot self-approve.
- [ ] Live policy updates are versioned and audited; revoke takes effect without requiring the agent to cooperate.
- [ ] Credential access supports opaque/brokered handles when the provider permits it; raw secrets are not persisted into agent memory, ordinary logs or trajectories.
- [ ] Sandbox events feed RFC-0026 execution observability and RFC-0027 semantic-action-firewall audit rather than creating a second operator event model.
- [ ] Add an optional NVIDIA OpenShell provider behind the same interface when available; absence of OpenShell does not disable Jarvis-native isolation.
- [ ] OpenShell/provider capabilities are discovered at runtime and unsupported policy primitives are reported rather than silently assumed.
- [ ] Tests prove prompt-injected/self-modifying workers cannot widen filesystem/network/credential authority without an external policy grant.
- [ ] Tests cover grant, expiry, revoke, sandbox crash, provider unavailable and audit behavior.
- [ ] Unit tests pass (`python3 -m pytest`).
- [ ] If portal/Decision Inbox UI is touched, `npm --prefix frontend run build` passes.

## Likely files

| Area | Paths |
| --- | --- |
| Backend | worker runtime/sandbox provider abstraction, policy compiler, OpenShell adapter |
| Security | capability policy, credential broker, network/filesystem/process enforcement adapters |
| Frontend | worker security detail, Decision Inbox grant preview, sandbox/provider status |
| Tests | sandbox policy, escape/denial, grant/revoke/expiry, provider fallback |
| Docs | autonomous worker isolation and provider contract |

## Out of scope

Replacing RFC-0027 semantic evaluation; building a full EDR/SIEM; making OpenShell mandatory; implementing VM-grade isolation on every OS in the first pass; allowing an agent to author or approve its own effective security policy.

## Notes

Source: https://developer.nvidia.com/blog/run-autonomous-self-evolving-agents-more-safely-with-nvidia-openshell/  
Source: https://developer.nvidia.com/blog/four-ways-to-deploy-more-secure-ai-agents/  
Source: https://developer.nvidia.com/blog/how-to-govern-autonomous-agents-in-enterprise-ai-factories/  
Source: https://developer.nvidia.com/topics/ai/local-ai  
Discovery date: 2026-09-07  
Recommendation: **ADAPT STRONGLY**.

Jarvis adapts the architectural invariant, not NVIDIA's stack: the security control point lives outside the model/harness, policies are deny-by-default and auditable, credentials can remain outside the sandbox, and approvals become scoped runtime grants. NVIDIA OpenShell can be offered as an optional maintained provider on compatible systems while Jarvis retains policy, GoalRun, approval and audit authority.
