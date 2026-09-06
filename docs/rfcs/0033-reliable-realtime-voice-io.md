# RFC-0033: Reliable provider-neutral realtime voice I/O

**Status:** draft  
**Queue item:** Future voice interface — do not promote ahead of active core work  
**Author:** ChatGPT competitor-review synthesis  
**Date:** 2026-09-06

## Problem

Jarvis has a future voice-interface requirement, but reliable voice is more than adding a microphone button. Cross-platform audio libraries often expose duplicate or pseudo devices, device indices move when hardware is connected, an endpoint may claim to support a sample rate while failing at stream-open time, and a stream may open successfully while not transporting audio correctly. Network/provider reconnects or device changes should also not unnecessarily erase the active conversation. A future voice layer should solve these reliability issues without binding Jarvis to Gemini Live, PyQt, or one operating system.

## Decision

Introduce a provider-neutral realtime voice I/O layer when voice work is promoted.

Audio-device discovery stores stable device identity/name information rather than volatile integer indices, filters duplicate/pseudo endpoints, and probes candidates using the same sample rate, direction and stream mode Jarvis will actually ship. Input and output may select different host APIs/backends when measurements show that is more reliable. Enumeration/probing runs asynchronously and is cached so opening settings does not stall the UI. If a saved device disappears, Jarvis falls back safely and reports the degraded choice.

Expose live normalized input/output amplitude telemetry as ordinary frontend events. The existing React/Tauri HUD may use those events to animate the current `ParticleOrb`/voice affordance; do not transplant a third-party PyQt HUD or reactor UI. Visual response is functional status feedback first, decoration second.

Define a `RealtimeVoiceProvider`/equivalent abstraction for session creation, bidirectional audio, interruption, voice selection, reconnect and optional provider session-resumption handles. Conversation state remains Jarvis-owned. When a provider supports compatible resumption, transient network or audio-device changes should preserve the active conversation; where it does not, Jarvis reconstructs from its normal conversation state rather than silently losing context.

Voice selection is a user/profile preference mapped through provider capabilities. Provider-specific voice names remain adapter metadata rather than a core Jarvis contract.

## Acceptance criteria

- [ ] Add a provider-neutral realtime voice interface independent of Gemini Live or any other single vendor.
- [ ] Audio device preferences survive ordinary device index reorder/replug events through stable name/identity resolution.
- [ ] Device lists remove obvious OS/host-API aliases and duplicate endpoints while retaining an explicit `System default` option.
- [ ] Candidate input/output devices are tested at the actual shipping sample rate, direction and stream mode before being presented as verified-working.
- [ ] Input and output host API/backend selection is independent when required by measured behavior.
- [ ] Discovery/probing is asynchronous/cached and cannot freeze the main React/Tauri UI.
- [ ] Missing saved hardware falls back to a usable/default endpoint with visible diagnostic state rather than preventing Jarvis startup.
- [ ] Runtime publishes bounded-rate input/output audio-level events that the existing HUD can consume without coupling the backend to a specific animation.
- [ ] The existing `ParticleOrb` or a successor voice indicator visibly distinguishes idle/listening/speaking/degraded states without obscuring task-status information.
- [ ] Provider adapters may expose voice choices and session-resumption capability; unsupported features degrade explicitly.
- [ ] Compatible transient reconnect/device-switch paths preserve conversation/session continuity where the provider allows it.
- [ ] When native provider resumption is unavailable, Jarvis restores conversational context from Jarvis-owned state instead of assuming the remote session is authoritative memory.
- [ ] Changing voice/device does not inject an illegal mid-conversation system message; existing system-message ordering constraints remain satisfied.
- [ ] Tests cover duplicate device enumeration, index reorder, missing device fallback, false-positive stream capability, separate input/output backend choice, reconnect and unsupported resumption.
- [ ] Unit tests pass (`python3 -m pytest`).
- [ ] `npm --prefix frontend run build` passes if HUD/settings are touched.

## Likely files

| Area | Paths |
| --- | --- |
| Backend | voice/audio abstraction, provider adapters, audio device probe/cache service, realtime event transport |
| Frontend | voice settings, HUD listening/speaking/degraded state, existing `frontend/src/hud/ParticleOrb.tsx` integration |
| Tests | audio device fixtures/probes, provider reconnect/resumption, frontend state tests |
| Docs | future voice provider and device-selection contract |

## Out of scope

Promoting voice ahead of the current master-plan priority; copying the MARK LII PyQt UI; requiring Gemini Live; affect/emotion inference; wake-word hardware; boot sounds/live theming; changing Android remote-control architecture.

## Notes

Reference reviewed: `FatihMakes/Mark-LII`, especially its measured audio-device selection, live audio-level HUD feedback and session-continuity design. The repository is CC BY-NC 4.0, so Jarvis should independently implement the reliability principles rather than copy the source. The existing Jarvis frontend is React/Tauri and already has a dedicated HUD/ParticleOrb, making conceptual adaptation preferable to UI code reuse.

Recommendation: **ADAPT**, but defer implementation until the master-plan voice work is explicitly promoted.
