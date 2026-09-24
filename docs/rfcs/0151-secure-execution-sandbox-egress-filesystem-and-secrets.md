# RFC-0151: Secure execution sandbox and zero-trust tool boundary

**Status:** accepted  
**Date:** 2026-09-24

## Problem
More autonomous tools/plugins increase blast radius. Policy prompts alone are insufficient isolation.

## Decision
Add execution profiles for code, shell, browser and third-party capability packages. Profiles declare filesystem mounts, network/egress allowlists, CPU/RAM/time limits, environment variables, secret handles and process privileges. Prefer OS/container isolation when available; otherwise fail closed for capabilities requiring guarantees the host cannot enforce. Tool/model/plugin outputs are untrusted data. Secrets are brokered per invocation and never copied into prompts/logs.

## Acceptance criteria
- [ ] Default-deny egress/filesystem profiles for untrusted execution.
- [ ] Resource/time/process limits are enforced and reported.
- [ ] Secrets are opaque handles with scoped lease/revocation.
- [ ] Prompt/tool output cannot expand permissions.
- [ ] Capability SDK declares required sandbox profile.
- [ ] Escape/egress regression tests run in release gates.

## Likely files
Policy/tool gateway, sandbox runtime, credential broker, plugin SDK, tests.
