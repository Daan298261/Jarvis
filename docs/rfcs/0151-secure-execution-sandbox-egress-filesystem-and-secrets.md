# RFC-0151: Secure execution sandbox and zero-trust tool boundary

**Status:** accepted  
**Date:** 2026-09-24  
**Updated:** 2026-09-25

## Problem
More autonomous tools/plugins increase blast radius. Policy prompts alone are insufficient isolation.

## Decision
Add execution profiles for code, shell, browser and third-party capability packages. Profiles declare filesystem mounts, network/egress allowlists, CPU/RAM/time limits, environment variables, secret handles and process privileges. Prefer OS/container isolation when available; otherwise fail closed for capabilities requiring guarantees the host cannot enforce. Tool/model/plugin outputs are untrusted data. Secrets are brokered per invocation and never copied into prompts/logs.

Treat containment as a tested property, not a configuration assumption. Maintain an adversarial release suite that attempts prohibited egress, undeclared filesystem access, localhost/service access, credential/environment discovery, process-boundary violations and permission expansion. Each execution profile declares which guarantees are enforceable on the current host; unsupported guarantees must be visible to the operator and capabilities requiring them fail closed.

## Acceptance criteria
- [ ] Default-deny egress/filesystem profiles for untrusted execution.
- [ ] Resource/time/process limits are enforced and reported.
- [ ] Secrets are opaque handles with scoped lease/revocation.
- [ ] Prompt/tool output cannot expand permissions.
- [ ] Capability SDK declares required sandbox profile.
- [ ] Release tests attempt denied network egress, localhost/service access and undeclared filesystem reads/writes.
- [ ] Tests verify secrets/credentials are not exposed through prompts, logs, environment enumeration or child processes outside their lease.
- [ ] Host/runtime capability detection reports which isolation guarantees are actually enforced.
- [ ] A failed containment test blocks release for the affected execution profile.
- [ ] Containment-test results retain runtime/OS/profile version and audit provenance.

## Likely files
Policy/tool gateway, sandbox runtime, credential broker, plugin SDK, runtime capability detector, release-gate tests and Control Room security diagnostics.

## Out of scope
- Claiming VM/container isolation is perfect.
- Replacing host OS security controls.
- Granting external sandbox providers authority over Jarvis policy, approvals or task state.

## Notes
- Source: https://www.perplexity.ai/hub/blog/escaping-space-part-i
- Discovery date: 2026-09-25
- Recommendation: ADAPT
- Adaptation: adopt adversarial verification of containment guarantees and fail-closed capability reporting; do not copy vendor-specific exploit techniques or architecture.
