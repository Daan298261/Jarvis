# RFC-0242: Accurate model identity, restrictions and separate load/pin actions

**Status:** accepted
**Author:** Codex, requested by Daan
**Date:** 2026-10-28

## Problem

The HUD labels a running 27B GGUF as a 9B uncensored candidate. Generic catalog match terms can assign unrelated model families to a row, absent candidates appear loadable, and pinning can activate inference. Short labels and icon-only actions obscure size, performance and refusal behavior.

## Decision

Require model-family identity before ranking GGUF matches, reject absent catalog models, and expose the actual file beside clear model names, weight size, quantization, estimated speed and publisher-described restrictions. Prefer the serving model identity in the HUD. Add registration-only bind endpoints so pinning saves a shortcut without activation. Use explicit Load and Pin buttons with a visible slot chooser. Research refusal-reduced models against primary model cards, including published refusal measurements; never promise zero refusals or invent current illicit-market facts. Preserve existing security gates and routing policy.

## Acceptance criteria

- [ ] A 27B Heretic, Gemma Aggressive or arbitrary Q4 file cannot match a different 9B/4B family; absent candidates cannot load or pin.
- [ ] Pinning discovered and graded models creates a shortcut without loading, changing runtime selection or starting tools.
- [ ] Load and Pin are visibly distinct; slot tiles fill their grid width and model names wrap.
- [ ] Menu shows actual artifact, GiB weights, quantization, speed estimates and honest refusal labels; live runtime identity takes precedence over a stale label.
- [ ] Primary-source model comparison records exact artifacts, published evidence and local validation limits.
- [ ] Backend regressions, full pytest, frontend build/lint and browser interaction/layout checks run; installed app status is reported separately.

## Likely files

| Area | Paths |
| --- | --- |
| Backend | `backend/app/inference/lmstudio_catalog.py`, `lmstudio_graded_profiles.json`, `backends.py`, `hotswap.py`, `backend/app/api/lmstudio.py` |
| Frontend | `frontend/src/api.ts`, `frontend/src/hud/HudModelSelector.tsx`, `hud-v2.css` |
| Tests | `tests/test_lmstudio_catalog.py`, focused browser validation |
| Docs | This RFC and model comparison under `docs/` |

## Out of scope

Security-gate changes, automatic model downloads or promotion, installer replacement, unrelated model/voice architecture and architect-owned specifications.
