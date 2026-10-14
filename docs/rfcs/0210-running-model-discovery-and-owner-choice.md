# RFC-0210: Running model discovery and owner choice

**Status:** accepted
**Date:** 2026-10-09
**Author:** Codex, from the recovered owner request

## Problem

The owner runs Antigravity/Cursor and a Qwen coding agent through Aider and wants ANZU to reuse available model servers after coding finishes. Current external inference requires manually configuring an endpoint. The owner also requests a scheduler review for RFC/bugfix work against ANZU's repository and an evaluation of manager-based recovery when ANZU itself cannot start.

## Decision

Implement this one ticket: bounded background discovery of local inference servers and an owner choice to use, leave alone, stop, or replace with ANZU's model. Discovery reads model metadata; it does not send prompts, inspect client secrets, start models, or infer an API from a running editor. Use the existing external provider and preserve owner conversation history. Keep the front/voice seat independent. Remember use/leave choices; ask again when a server advertises a different model. Stop only identified llama-server processes, with current listener/PID/create-time verification, or unload an identified Ollama model through its API. Never terminate Cursor, Aider, or Antigravity.

The HUD offers the choices and the existing owner-chat/TTS delivery announces a new choice once. Model settings expose previously dismissed choices. Discovery and process inspection must not block health/chat request paths. Owner decisions must be serialized and stale selections rejected.

Review the existing scheduler and manager source and write a separate findings document. This request says to look at the scheduler and evaluate embedding a recovery model; it does not authorize an unattended release/merge schedule or invent its cadence.

## Acceptance criteria

- [x] Detect OpenAI-compatible local servers on known ports and additional ports owned by recognized inference server processes.
- [x] Reject HTTP errors, redirects, unrelated JSON, and empty model inventories. For Ollama, report loaded models from `/api/ps`, not every downloaded model.
- [x] Ignore ANZU's managed worker and front seat; preserve unrelated processes.
- [x] Use attaches through the existing provider without local GGUF requirements; owner choice is saved only after success.
- [x] Remember use/leave decisions, revalidate endpoint/model before mutations, and preserve conversations on model switch.
- [x] Expose all four choices in the HUD and Model page, with visible failures and a spoken owner-choice notification.
- [x] Tests cover malformed servers, deadlines, stale choices, process identity changes, and attachment.
- [x] Review scheduler RFC selection, isolation, validation, deduplication and recovery gaps; evaluate an independent manager repair strategy.
- [ ] Run focused/full backend tests, frontend build/lint and diff checks. Windows live and installed acceptance remain separately reported.

## Likely files

`backend/app/inference/running_models.py`, `backend/app/api/model.py`, `backend/app/main.py`, `frontend/src/hud/RunningModels.tsx`, Model/HUD integration, focused tests, `docs/audits/2026-10-09-model-reuse-scheduler-manager.md`.
