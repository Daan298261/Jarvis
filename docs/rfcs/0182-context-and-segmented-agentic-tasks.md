# RFC-0182: Usable context and segmented agentic tasks

**Status:** accepted  
**Author:** Codex, following owner request 2026-09-26  
**Date:** 2026-09-28

## Problem

The fast reply lane formerly capped output near 128 tokens, which looked like a context limit. Release 1.4.16 raised that cap, but an attached LM Studio server may still expose only a 4K live context despite a 32K profile. Long owner messages are split into a preview list while the full message is still sent in one inference call. Managed tasks spill large input to the database but initially show only its first segment. Explicit requests to use a named tool must remain in the durable plan, act, observe, verify loop.

## Decision

Keep the existing ANZU agent loop as the harness. Make the live server context and requested profile context distinct in the model UI. Load locally started LM Studio models with a context length chosen from the selected runtime profile. For oversized owner turns, process every stored segment in bounded read-only inference calls into a compact working brief before the managed agent plans and uses tools. Keep the original blob addressable for precise later reads. Route explicit named-tool requests through managed tasks and expose only the selected enabled tool plus ordinary recovery capabilities.

## Acceptance criteria

- Model status clearly identifies the live server window, the configured target, and the action required when an external server is loaded too small.
- Locally auto-loaded LM Studio models request at least 16K context when their profile supports it; a remote or already running server is never falsely reported as resized.
- Oversized requests are processed in ordered, bounded prompts with no silently skipped segments. The agent receives a compact brief and a way to retrieve exact source slices.
- Explicit "run/use/call tool X" requests enter the managed agent loop, with the requested enabled schema available; tool authorization and verification remain in force.
- Vendor-independent code works with OpenAI-compatible local Qwen/Ornith model endpoints; no new external harness is required.

## Likely files

`backend/app/agent/`, `backend/app/inference/`, `backend/app/memory/`, `backend/app/tools/`, `frontend/src/pages/Model.tsx`.

## Out of scope

Changing GGUF model weights, forcibly unloading an already serving LM Studio seat, or promoting a development commit to main without a separate release request.
