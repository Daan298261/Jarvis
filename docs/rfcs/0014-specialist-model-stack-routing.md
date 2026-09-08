# RFC-0014: Specialist model stack and capability routing

**Status:** accepted  
**Queue item:** Model-stack specialization and security-agent routing  
**Author:** ChatGPT design session, requested by Taco  
**Date:** 2026-09-08

## Problem

Jarvis already has runtime profiles, local/remote routing, escalation, model benchmarking, and security-agent boundaries, but model selection is still mostly generic (`fast`, `balanced`, `quality`, `expert`). Jarvis needs explicit model roles so a small always-on orchestrator can delegate to a stronger local leader, cybersecurity specialists, and remote frontier models without making every task pay the cost of the largest model. Security also needs separate blue-team, DFIR, and explicitly authorized red-team model selection while preserving the existing tool/authorization gates.

## Decision

Add a data-driven **specialist model catalog** and **role-to-runtime routing policy** on top of RFC-0003 runtime profiles. Model IDs are recommendations, not hard dependencies; an administrator can replace a model while retaining the same capability/specialization tags.

### Recommended role map

| Role | Preferred model | Residency | Primary tags |
| --- | --- | --- | --- |
| `orchestrator` | `ornith-ai/Ornith-1.5-9B` | local, warm/always-on | orchestration, agentic, tool-use, low-latency |
| `leader` | `Qwen/Qwen3.8-27B` | local/hybrid, on demand | reasoning, coding, vision, computer-use |
| `blue-team` | `RISys-Lab/RedSage-Qwen3-8B-DPO` | local, optional warm | cybersecurity, blue-team, SOC, threat-analysis |
| `dfir` | `IMPERUM/Imperum-CybersecurityLLM-v1.0-GGUF` | local/hybrid, on demand | cybersecurity, DFIR, detection-engineering |
| `red-team` | `DeepHat/DeepHat-V1-7B` | local, explicitly enabled | cybersecurity, red-team, code-security |
| `frontier` | provider-configured frontier model | remote | high-quality, reasoning, long-context |
| `cheap-frontier` | provider-configured GLM/DeepSeek class model | remote | agentic, reasoning, cost-optimized |

Voice (`Qwen3-ASR`, Qwen3-TTS/Chatterbox) and memory (`Qwen3-Embedding` / `Qwen3-Reranker`) remain service-level components and are not part of LLM task routing in this RFC.

### Routing behavior

1. Agent/task role is translated into required capability tags, preferred runtime profiles, and a specialization tag.
2. Existing policy remains authoritative: `local-only`, `local-first`, `best-result`, or `cost-optimized`.
3. Warm models, node load, hardware fit, privacy class, cost ceiling, and user force/preference settings continue to affect the final choice.
4. Specialist profiles that are shipped as recommendations are **disabled until configured**. A disabled endpoint must never win routing.
5. Red-team model selection is separately gated. A red-team runtime requires an explicit authorization tag in addition to being enabled. Direct `force_profile` must not bypass required authorization.
6. Model selection never grants tools. Existing security/LE gates remain authoritative for network actions, tool exposure, payloads, or any other capability.
7. No model is automatically downloaded and no API key/provider is automatically enabled by this RFC.

### Initial model templates

Jarvis should expose disabled runtime templates for Qwen3.8-27B, RedSage 8B, Imperum CybersecurityLLM, and DeepHat 7B. The existing Ornith profile should receive first-class `orchestration`, `agentic`, and `tool-use` tags. Templates use OpenAI-compatible local endpoints so llama.cpp, vLLM, LM Studio, or another compatible server can satisfy them without changing the router.

The catalog is intentionally replaceable: capability tags are the contract. If a later benchmark shows a better 8B SOC model, replacing `RedSage` should not require rewriting agent logic.

## Acceptance criteria

- [ ] A specialist catalog exposes the recommended role/model mapping without auto-downloading models.
- [ ] Runtime profiles can be enabled/disabled; disabled profiles are ignored by normal and forced routing.
- [ ] Runtime profiles can declare required authorization tags.
- [ ] Routing preferences can declare granted authorization tags.
- [ ] A forced runtime profile fails closed when required authorization is absent.
- [ ] `orchestrator` role prefers the Ornith 1.5 9B runtime when available.
- [ ] `leader` role targets Qwen3.8-27B capability/specialization tags, with existing local expert profiles available as fallback.
- [ ] `blue-team` role requires cybersecurity + blue-team capability and prefers RedSage.
- [ ] `dfir` role requires cybersecurity + DFIR capability and prefers Imperum.
- [ ] `red-team` role cannot produce routable preferences unless explicitly authorized; the DeepHat runtime template is disabled by default and requires the red-team authorization tag.
- [ ] Security model routing adds no offensive tools, payload generation plumbing, hack-back behavior, or bypass of existing security gates.
- [ ] Existing registry files remain backward compatible when `enabled` / authorization fields are absent.
- [ ] Unit tests cover specialist role mapping, disabled profiles, authorization failure/success, and force-profile fail-closed behavior.
- [ ] Unit tests pass (`python3 -m pytest`).
- [ ] Live local model load/performance remains a Windows desktop sign-off item.

## Likely files

| Area | Paths |
| --- | --- |
| Backend | `backend/app/inference/model_stack.py`, `backend/app/inference/runtime_profiles.py`, `backend/app/inference/runtime_router.py` |
| Tests | `tests/test_model_stack.py`, `tests/test_runtime_profiles.py` |
| Docs | `docs/rfcs/0014-specialist-model-stack-routing.md` |

## Out of scope

- Downloading or quantizing model weights.
- Changing installer behavior or choosing exact GGUF community conversions.
- Implementing voice/ASR/TTS or embedding/reranker services.
- Adding offensive tools, exploit/payload automation, persistence, credential theft, hack-back, or counter-response capabilities.
- Changing the existing LE/security authorization model.
- Adding provider credentials or enabling paid remote inference automatically.
- Frontend model-management UI.
- Swarm placement changes beyond consuming the existing node/hardware routing signals.

## Notes

This RFC builds on RFC-0003 rather than replacing it. The specialist layer supplies capabilities and role intent; `runtime_router.py` still performs the final policy-aware selection. Model recommendations are dated 2026-09-08 and should be benchmarked on the target Windows/RTX system before any benchmark candidate becomes the permanent default.