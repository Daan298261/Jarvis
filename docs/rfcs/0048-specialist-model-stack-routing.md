# RFC-0048: Specialist model stack and capability routing

**Status:** implemented  
**Queue item:** Model-stack specialization and security-agent routing  
**Author:** ChatGPT design session, requested by Taco  
**Date:** 2026-09-08

**VERIFIED —** specialist routing PR #109 (`92045ca`); security gates + HexStrike boundary PR #110 (`ef25ad2`). On `development`.

## Problem

Jarvis already has runtime profiles, local/remote routing, escalation, benchmarking, and security-agent boundaries, but model selection is still mostly generic (`fast`, `balanced`, `quality`, `expert`). Jarvis needs explicit model roles so a small always-on orchestrator can delegate to a stronger local leader, defensive cybersecurity specialists, and remote frontier models without making every task pay the cost of the largest model.

Security specialists also need an operator-controlled enablement mechanism that survives restart. Blue and Red must not become active just because a runtime profile exists or because `force_profile` names one. Red additionally remains subject to the repository's manual/LE authorization requirements.

## Decision

Add a data-driven **specialist model catalog**, **role-to-runtime routing policy**, and **persistent security-role password gate** on top of RFC-0003 runtime profiles. Model IDs are recommendations, not hard dependencies; an administrator can replace a model while retaining the same capability/specialization tags.

### Recommended role map

| Role | Preferred model | Residency | Primary tags | Generic routing |
| --- | --- | --- | --- | --- |
| `orchestrator` | `ornith-ai/Ornith-1.5-9B` | local, warm/always-on | orchestration, agentic, tool-use, low-latency | allowed |
| `leader` | `Qwen/Qwen3.8-27B` | local/hybrid, on demand | reasoning, coding, vision, computer-use | allowed |
| `blue-team` | `RISys-Lab/RedSage-Qwen3-8B-DPO` | local, optional warm | cybersecurity, blue-team, SOC, threat-analysis | password-gated |
| `dfir` | `IMPERUM/Imperum-CybersecurityLLM-v1.0-GGUF` | local/hybrid, on demand | cybersecurity, DFIR, detection-engineering | Blue password gate |
| `red-team` | `DeepHat/DeepHat-V1-7B` | local, manual/LE gated | cybersecurity, red-team, code-security | password + manual/case gate |
| `frontier` | provider-configured frontier model | remote | high-quality, reasoning, long-context | allowed when policy permits |
| `cheap-frontier` | provider-configured GLM/DeepSeek class model | remote | agentic, reasoning, cost-optimized | allowed when policy permits |

Voice (`Qwen3-ASR`, Qwen3-TTS/Chatterbox) and memory (`Qwen3-Embedding` / `Qwen3-Reranker`) remain service-level components and are not part of LLM task routing in this RFC.

### Routing behavior

1. Agent/task role is translated into required capability tags, preferred runtime profiles, and a specialization tag.
2. Existing policy remains authoritative: `local-only`, `local-first`, `best-result`, or `cost-optimized`.
3. Warm models, node load, hardware fit, privacy class, cost ceiling, and user force/preference settings continue to affect final selection.
4. Specialist profiles shipped as recommendations are **disabled until configured**. A disabled endpoint must never win normal routing, and `force_profile` must not bypass the disabled state.
5. Blue/DFIR and Red use a separate persisted security gate. Unlock state is not written into the generic runtime registry; the authorized role route receives a temporary enabled view of the relevant profiles. This prevents generic `/route` and `force_profile` calls from reusing an unlocked security specialist outside the security-role path.
6. The Blue password gate is sufficient to route Blue/DFIR models. Red requires the Red password gate **plus** an explicit authorization/case reference and a human-confirmed request. A password is an operator factor, not a substitute for the repository's LE/manual authorization rules.
7. Generic `routing_preferences_for_role("red-team")` still fails closed unless the caller explicitly indicates that the external manual gate has already been satisfied.
8. Model selection never grants tools or permissions. Existing security/LE gates remain authoritative for network actions and tool exposure.
9. No model is automatically downloaded and no API key/provider is automatically enabled by this RFC.

### Persistent security password gates

Security gate state is stored locally in `data/security-model-gates.json` and survives restart. Passwords are never stored in plaintext. Each role uses a unique random salt plus Python's `hashlib.scrypt`; verification uses constant-time comparison. The API exposes status, password setup/change, unlock, and lock operations.

Managed security profiles cannot be enabled through the generic runtime-profile `enabled=true` API. They remain disabled in the generic registry even after a security gate is unlocked. This deliberately separates "operator has unlocked this role" from "all Jarvis routing may now select this model."

The Blue gate covers RedSage and Imperum/DFIR. The Red gate covers DeepHat. Password changes require the current password once a gate has been configured.

### Initial model templates

Jarvis exposes disabled runtime templates for Qwen3.8-27B, RedSage 8B, Imperum CybersecurityLLM, and DeepHat V1 7B. The existing Ornith profile receives first-class `orchestration`, `agentic`, and `tool-use` tags. Templates use OpenAI-compatible local endpoints so llama.cpp, vLLM, LM Studio, or another compatible server can satisfy them without changing the router.

DeepHat exists in the runtime registry only as a disabled template. The Red role endpoint can temporarily activate that profile for an authorized routing decision after the password + manual/case checks. Generic routing never sees it as enabled.

The catalog is intentionally replaceable: capability tags are the contract. If later benchmarking identifies a better model for a role, replacing the concrete model should not require rewriting agent logic.

## HexStrike AI integration decision

HexStrike AI v6.0 is useful as a **tool execution substrate**, not as Jarvis's authorization boundary. The upstream project advertises 150+ security tools, 12+ autonomous agents, target analysis, tool selection, vulnerability correlation, browser automation, and a generic command endpoint. Its own documentation warns that agents receive powerful system access, recommends isolated environments, and suggests adding authentication for production use.

As of 2026-09-08 the upstream issue tracker also contains open reports covering unauthenticated command/Python execution, command injection, arbitrary file write/path traversal, and other RCE-class risks. Therefore Jarvis must **not** expose the raw HexStrike server or MCP directly to ordinary agents.

### HexStrike deployment boundary

HexStrike, if installed, runs in a dedicated security VM/container or isolated Linux node, bound to loopback/private management networking. Jarvis talks to it only through a local **HexStrike Gateway**. The gateway owns authentication, scope validation, rate/resource limits, audit logging, and endpoint allowlisting.

The gateway must not proxy raw generic command/Python/file-write endpoints. It should expose task-level operations rather than arbitrary shell strings. All targets are validated against the active exercise/case allowlist before a request leaves Jarvis. Every operation records case/exercise ID, actor, target, phase, selected tool family, start/end state, and artifacts in the Jarvis SIEM/audit store.

### Authorized Red assessment workflow

The complete Jarvis-managed workflow is lifecycle-complete without making HexStrike itself the policy engine:

1. **Authorization and scope** — Red password gate, case/exercise reference, explicit human confirmation, target/segment allowlist, time window, and stop conditions.
2. **Asset discovery** — identify only in-scope hosts/services and create a normalized asset inventory.
3. **Surface mapping** — classify exposed services, web/API surfaces, cloud/container context, versions, and likely technology stack.
4. **Vulnerability assessment** — correlate scanner findings, CVEs, configuration weaknesses, and Blue/SIEM observations; deduplicate and rank findings.
5. **Validation checkpoint** — potentially intrusive validation requires a new human approval tied to the same case/scope. The default gateway remains non-destructive.
6. **Evidence capture** — retain commands/tool identifiers, timestamps, target, findings, screenshots/log excerpts, and hashes of collected artifacts.
7. **Blue/Purple handoff** — send validated observations to Blue for detection-rule improvement and to Purple for safe regression exercises on owned lab assets.
8. **Remediation planning** — produce prioritized fixes, compensating controls, detection recommendations, and ownership.
9. **Retest** — rerun the relevant assessment checks against the same authorized scope and close/reopen findings based on evidence.
10. **Closeout** — revoke the active Red session, retain the audit trail, and leave the persistent role gate in its configured state unless the operator explicitly locks it.

This RFC does not add payload generation, persistence, credential theft, evasion, exfiltration, hack-back, or autonomous exploitation plumbing. If a future LE-authorized module adds more intrusive operations, it remains a separate explicitly authorized implementation under `SECURITY_AGENTS.md`.

### HexStrike gateway phases

For implementation, expose capability groups rather than individual raw tools:

- `inventory` — in-scope asset/service discovery
- `web_surface` — application/API mapping
- `vulnerability_scan` — template/scanner-based assessment
- `cloud_posture` — cloud/container/IaC posture where credentials/scope explicitly permit
- `forensics` — evidence-oriented file/memory/metadata analysis
- `report` — normalized findings and retest comparison

The gateway is disabled by default and has no WAN listener. Upstream upgrades require re-running a security review because the external project's endpoint set and security posture may change.

## Acceptance criteria

- [x] A specialist catalog exposes the recommended role/model mapping without auto-downloading models.
- [x] Runtime profiles can be enabled/disabled; disabled profiles are ignored by normal routing.
- [x] A disabled runtime profile cannot be selected through `force_profile`.
- [x] Existing runtime registry files remain backward compatible when `enabled` is absent.
- [x] `orchestrator` role prefers the Ornith 1.5 9B runtime when available.
- [x] `leader` role targets Qwen3.8-27B capability/specialization tags, with existing local expert profiles available as fallback.
- [x] `blue-team` role requires cybersecurity + blue-team capability and prefers RedSage.
- [x] `dfir` role requires cybersecurity + DFIR capability and prefers Imperum.
- [x] DeepHat is emitted only as a disabled generic runtime template.
- [x] Blue and Red password hashes persist locally using salted scrypt; plaintext passwords are never persisted.
- [x] Security-role unlock state survives process restart.
- [x] Generic profile update/create cannot enable a managed security specialist and bypass the role gate.
- [x] Generic Red Team role routing fails closed.
- [x] Authorized Red routing requires password-gate unlock + authorization/case reference + explicit human confirmation.
- [x] Unlocking Red does not make generic `/route` or `force_profile` able to select DeepHat.
- [x] HexStrike integration is behind a Jarvis-controlled gateway with scope validation, audit logging, and no raw generic command/Python/file-write proxy.
- [x] Security model routing adds no offensive payload-generation plumbing, hack-back behavior, persistence, credential-theft capability, or bypass of existing security gates.
- [x] Unit tests cover specialist role mapping, persistent gates, generic-bypass prevention, Red authorization checks, and forced disabled routing.
- [x] Unit tests pass (`python3 -m pytest`).
- [ ] Live local model load/performance remains a Windows desktop sign-off item.

## Likely files

| Area | Paths |
| --- | --- |
| Backend | `backend/app/inference/model_stack.py`, `backend/app/inference/runtime_profiles.py`, `backend/app/inference/runtime_router.py`, `backend/app/inference/security_gates.py`, `backend/app/api/runtime_profiles.py` |
| Tests | `tests/test_model_stack.py`, `tests/test_runtime_profiles.py`, `tests/test_security_gates.py` |
| CI | `.github/workflows/pr-tests.yml` |
| Docs | `docs/rfcs/0048-specialist-model-stack-routing.md` |

## Out of scope

- Downloading or quantizing model weights.
- Changing installer behavior or choosing exact GGUF community conversions.
- Implementing voice/ASR/TTS or embedding/reranker services.
- Adding payload generation, persistence, credential theft, evasion, exfiltration, hack-back, or autonomous exploitation plumbing.
- Replacing the existing LE/security authorization model with a password-only check.
- Adding provider credentials or enabling paid remote inference automatically.
- Frontend model-management UI.
- Swarm placement changes beyond consuming existing node/hardware routing signals.
- Directly exposing the upstream HexStrike MCP/server to ordinary Jarvis agents.

## Notes

This RFC builds on RFC-0003 rather than replacing it. The specialist layer supplies capabilities and role intent; `runtime_router.py` still performs final policy-aware selection. Model recommendations are dated 2026-09-08 and should be benchmarked on the target Windows/RTX system before any benchmark candidate becomes the permanent default.

HexStrike references reviewed on 2026-09-08:
- https://github.com/0x4m4/hexstrike-ai
- https://github.com/0x4m4/hexstrike-ai/issues
