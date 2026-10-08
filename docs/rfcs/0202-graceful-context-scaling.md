# RFC-0202: Graceful context scaling and large input

**Status:** accepted  
**Author:** Codex / owner request  
**Date:** 2026-10-08

## Problem

The owner's external Qwen instance was loaded at 4096 tokens. History compaction preserves a large latest user message, so a single long input can still overflow and fail without spoken feedback.

## Decision

Default the quick profile to 16K. Use the actual loaded server window, including modern LM Studio instance configuration. Permit local LM Studio growth only after its resource estimate fits with 3 GiB GPU and 12 GiB available RAM reserved, serialize reloads, and roll back unsuccessful loads. Never resize remote servers automatically. On the owner desktop, 64K is the largest admitted GPU tier for the current Qwen Q4 model; 262K requires more GPU memory than installed.

Before compressing oversized user text, speak an acknowledgment once. Preserve the complete original in a private content-addressed file. Summarize every section with the active provider, preserving questions, constraints, identifiers, and uncertainty; recursively reduce summaries with bounded passes. Keep summaries in the original message role and identify their source and coverage. Never silently clip original input. If preparation cannot fit or reduction fails, return an explicit capacity failure with the retained input available for retry. Existing eligible larger-model selection runs before sectioning.

## Acceptance criteria

- [ ] Quick profile defaults to 16384; actual Qwen instance verified at safe 65536 with headroom.
- [ ] Modern live-instance probing distinguishes loaded context from theoretical maximum.
- [ ] Resource guard rejects oversized loads; reload failure restores original instance.
- [ ] Long text queues speech, all sections are processed, original is retained, and final budget fits.
- [ ] Provider failures and non-reducing summaries fail explicitly rather than discarding text.
- [ ] Focused and full backend tests; real local model long-input check.

## Likely files

Backend inference profiles, context window, backends, manager, prompt budget, new large-input and LM Studio context modules; focused tests.

## Out of scope

Cloud model provisioning, new inference servers, public PR merges, reverse engineering (RFC-0201 / PR #547).

## Desktop latency correction

The owner requested slow behavior be fixed after the initial code was pushed. A real thread dump found startup self-check calling VoiceStudio network availability on the API event loop. Move these checks to worker threads, give all fallback endpoints one shared deadline, and cache short-lived availability results. Verify ordinary requests remain responsive while a voice probe is blocked; include the voice-status API path in this correction. This supports prompt speech feedback without blocking chat or model status.
