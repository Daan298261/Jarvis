# RFC-0048: Specialist model stack and capability routing

**Status:** accepted  
**Queue item:** Model-stack specialization and security-agent routing  
**Author:** ChatGPT design session, requested by Taco  
**Date:** 2026-09-08

## Problem

Jarvis already has runtime profiles, local/remote routing, escalation, benchmarking, and security-agent boundaries, but model selection is still mostly generic (`fast`, `balanced`, `quality`, `expert`). Jarvis needs explicit model roles so a small always-on orchestrator can delegate to a stronger local leader, defensive cybersecurity specialists, and remote frontier models without making every task pay the cost of the largest model.

The design also needs to record the preferred Red Team model without violating the repository security rule that offensive/red capability may only be operationalized manually by Taco or through the dedicated PolitieGPT/LE gate. Generic/cloud workers must not create an automatic Red Team activation path.

## Decision

Add a data-driven **specialist model catalog** and **role-to-runtime routing policy** on top of RFC-0003 runtime profiles. Model IDs are recommendations, not hard dependencies; an administrator can replace a model while retaining the same capability/specialization tags.

### Recommended role map

| Role | Preferred model | Residency | Primary tags | Generic routing |
| --- | --- | --- | --- | --- |
| `orchestrator` | `ornith-ai/Ornith-1.5-9B` | local, warm/always-on | orchestration, agentic, tool-use, low-latency | allowed |
| `leader` | `Qwen/Qwen3.8-27B` | local/hybrid, on demand | reasoning, coding, vision, computer-use | allowed |
| `blue-team` | `RISys-Lab/RedSage-Qwen3-8B-DPO` | local, optional warm | cybersecurity, blue-team, SOC, threat-analysis | allowed |
| `dfir` | `IMPERUM/Imperum-CybersecurityLLM-v1.0-GGUF` | local/hybrid, on demand | cybersecurity, DFIR, detection-engineering | allowed |
| `red-team` | `DeepHat/DeepHat-V1-7B` | local, manual/LE gated | cybersecurity, red-team, code-security | **not allowed** |
| `frontier` | provider-configured frontier model | remote | high-quality, reasoning, long-context | allowed when policy permits |
| `cheap-frontier` | provider-configured GLM/DeepSeek class model | remote | agentic, reasoning, cost-optimized | allowed when policy permits |

Voice (`Qwen3-ASR`, Qwen3-TTS/Chatterbox) and memory (`Qwen3-Embedding` / `Qwen3-Reranker`) remain service-level components and are not part of LLM task routing in this RFC.

### Routing behavior

1. Agent/task role is translated into required capability tags, preferred runtime profiles, and a specialization tag.
2. Existing policy remains authoritative: `local-only`, `local-first`, `best-result`, or `cost-optimized`.
3. Warm models, node load, hardware fit, privacy class, cost ceiling, and user force/preference settings continue to affect final selection.
4. Specialist profiles shipped as recommendations are **disabled until configured**. A disabled endpoint must never win normal routing, and `force_profile` must not bypass the disabled state.
5. The Red Team recommendation is **catalog-only** in the generic model stack. It does not ship as a routable runtime template, and generic `routing_preferences_for_role("red-team")` fails closed. Activation belongs exclusively to Taco manual configuration or the existing PolitieGPT/LE security gate.
6. Model selection never grants tools or permissions. Existing security/LE gates remain authoritative for network actions, tool exposure, payloads, or any other capability.
7. No model is automatically downloaded and no API key/provider is automatically enabled by this RFC.

### Initial model templates

Jarvis exposes disabled runtime templates for Qwen3.8-27B, RedSage 8B, and Imperum CybersecurityLLM. The existing Ornith profile receives first-class `orchestration`, `agentic`, and `tool-use` tags. Templates use OpenAI-compatible local endpoints so llama.cpp, vLLM, LM Studio, or another compatible server can satisfy them without changing the router.

DeepHat remains visible in the specialist model catalog for architectural completeness, but no generic runtime profile is generated for it.

The catalog is intentionally replaceable: capability tags are the contract. If later benchmarking identifies a better model for a role, replacing the concrete model should not require rewriting agent logic.

## Acceptance criteria

- [ ] A specialist catalog exposes the recommended role/model mapping without auto-downloading models.
- [ ] Runtime profiles can be enabled/disabled; disabled profiles are ignored by normal routing.
- [ ] A disabled runtime profile cannot be selected through `force_profile`.
- [ ] Existing runtime registry files remain backward compatible when `enabled` is absent.
- [ ] `orchestrator` role prefers the Ornith 1.5 9B runtime when available.
- [ ] `leader` role targets Qwen3.8-27B capability/specialization tags, with existing local expert profiles available as fallback.
- [ ] `blue-team` role requires cybersecurity + blue-team capability and prefers RedSage.
- [ ] `dfir` role requires cybersecurity + DFIR capability and prefers Imperum.
- [ ] DeepHat/Red Team is catalog-only and is not emitted into generic default runtime profiles.
- [ ] Generic Red Team role routing fails closed and directs activation to Taco manual configuration or the existing PolitieGPT/LE gate.
- [ ] Security model routing adds no offensive tools, payload-generation plumbing, hack-back behavior, persistence, credential-theft capability, or bypass of existing security gates.
- [ ] Unit tests cover specialist role mapping, disabled profiles, Red Team manual gating, and forced disabled routing.
- [ ] Unit tests pass (`python3 -m pytest`).
- [ ] Live local model load/performance remains a Windows desktop sign-off item.

## Likely files

| Area | Paths |
| --- | --- |
| Backend | `backend/app/inference/model_stack.py`, `backend/app/inference/runtime_profiles.py`, `backend/app/inference/runtime_router.py`, `backend/app/api/runtime_profiles.py` |
| Tests | `tests/test_model_stack.py`, `tests/test_runtime_profiles.py` |
| Docs | `docs/rfcs/0048-specialist-model-stack-routing.md` |

## Out of scope

- Downloading or quantizing model weights.
- Changing installer behavior or choosing exact GGUF community conversions.
- Implementing voice/ASR/TTS or embedding/reranker services.
- Operationalizing Red Team routing in the generic worker path.
- Adding offensive tools, exploit/payload automation, persistence, credential theft, hack-back, or counter-response capabilities.
- Changing the existing LE/security authorization model.
- Adding provider credentials or enabling paid remote inference automatically.
- Frontend model-management UI.
- Swarm placement changes beyond consuming existing node/hardware routing signals.

## Notes

This RFC builds on RFC-0003 rather than replacing it. The specialist layer supplies capabilities and role intent; `runtime_router.py` still performs final policy-aware selection. Model recommendations are dated 2026-09-08 and should be benchmarked on the target Windows/RTX system before any benchmark candidate becomes the permanent default.