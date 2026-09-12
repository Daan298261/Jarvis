# RFC-0078: In-app help + local Qwen3.8-9B uncensored default

**Status:** implemented
**Author:** Cursor worker (Taco request)
**Date:** 2026-09-12
**Owner for implement:** this ticket (same PR)

**Related (do not rewrite):** RFC-0003 AUTO routing; RFC-0043 LM Studio catalog (Qwen3.8-9B was a documented gap); RFC-0060 docs-first grounding; RFC-0073 / RFC-0077 ModelSelector.

## Problem

Everyday default is still Qwen3.5-9B Abliterated even when a newer local **Qwen3.8-9B uncensored** GGUF is already on disk (Jarvis `models/` or the current user’s LM Studio tree). Separately, owners have no HUD help control that answers product questions from shipped docs first, then the public web, with a short list of distinguished features (phone pairing, custom models, swarms, autonomy).

## Decision

1. **Prefer Qwen3.8-9B uncensored when installed.** Discover GGUFs whose names match Qwen 3.8 + 9B (also accept a `3m8` spelling). Prefer files tagged uncensored / abliterated / defiant / heretic / unfiltered. If found, that profile (`qwen38_9b`) is the everyday autoload default unless the owner already pinned a non-everyday profile (`expert`, Ornith, bootstrap, or a runtime/LM Studio selection). Do not hardcode usernames or download weights.
2. **Help icon** on HUD (and classic chrome) opens a compact help chatbox.
3. **Help answers** always retrieve local product docs / the RFC-0060 reference pack first. If local hits are weak, a secondary public-web lookup may run (query only — never upload the local corpus, keys, or settings). A small installed profile (`bootstrap` / `fast`) is preferred when no model is loaded; if a model is already resident, help uses it with a docs-grounded prompt and does not GPU-swap.
4. **Guides tab** lists distinguished features: phone pairing, custom models, swarms, autonomy, plus voice and companion APK.

### Will not

- Change AUTO routing policy (RFC-0003)
- Download models from the internet
- Edit Architect spec files (`JARVIS_MASTER_PLAN.md`, `PORTAL_UX.md`, …)
- Add offensive / red-team tools (uncensored = low-refusal everyday GGUF only)

## Acceptance criteria

- [x] Qwen3.8-9B uncensored GGUF, if present under `models/` or `~/.lmstudio/models`, becomes the everyday default
- [x] Explicit non-everyday profile pins are not overridden
- [x] Help icon opens a chatbox; answers cite local docs first
- [x] Weak local hits may use a secondary web lookup without uploading local secrets
- [x] Guides tab includes phone pairing, custom models, swarms, autonomy
- [x] Product docs (README / INSTALL / reference pack) mention the conditional Qwen3.8-9B default
- [x] `python3 -m pytest`; `npm --prefix frontend run build`

## Likely files

| Area | Paths |
| --- | --- |
| Backend | `backend/app/inference/profiles.py`, new local Qwen3.8 discovery, `backend/app/help/*`, `backend/app/api/help.py`, autoload in `main.py` |
| Frontend | HUD help icon + panel; classic chrome help |
| Docs | this RFC; `README.md`; `docs/INSTALL.md`; RFC-0060 reference pack help topics |
| Tests | discovery/default + help retrieve/chat |

## Out of scope

Windows installer rewrite. Live GPU load (desktop sign-off). Architect master-plan §58/§59 ticks.

## Notes

Linux cloud VMs cannot sign off live Qwen3.8-9B load or first-token help latency.

## Implementation note

Implemented in this PR: local Qwen3.8-9B uncensored discovery + everyday autoload; HUD/classic Help icon with Ask + Guides; docs-first retrieve then optional public-web fallback. Live GGUF load remains desktop sign-off.
