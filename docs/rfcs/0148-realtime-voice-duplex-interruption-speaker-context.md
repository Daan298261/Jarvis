# RFC-0148: Realtime voice — duplex, interruption and conversational presence

**Status:** accepted  
**Date:** 2026-09-24

## Problem
Voice parity requires natural turn-taking, low latency and interruption handling, not sequential STT→LLM→TTS buttons.

## Decision
Create a provider-neutral realtime voice session runtime. Pipeline supports local and cloud STT/TTS/realtime models, streaming partials, VAD, wake phrase, barge-in, cancellation, backchannels and device handoff. Maintain a short ephemeral ambient buffer only when explicitly enabled; persist only owner-selected transcript/memory. Separate speaker diarization from identity: unknown speakers remain unknown unless explicitly enrolled. Route spoken tasks through the same persona/model router and approval system as text.

## Acceptance criteria
- [ ] First-audio/first-text latency metrics are recorded.
- [ ] User interruption stops queued speech and stale tool execution appropriately.
- [ ] Local-only voice path remains functional offline.
- [ ] Ambient buffer has visible state, bounded retention and hard off switch.
- [ ] Speaker labels never silently become authenticated identities.
- [ ] Phone/desktop handoff preserves one logical session.

## Likely files
Voice runtime, audio transport, companion app, HUD, telemetry/tests.
