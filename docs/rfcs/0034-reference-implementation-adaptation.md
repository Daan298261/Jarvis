# RFC-0034: Reference implementation adaptation and native integration

**Status:** accepted  
**Queue item:** P1 — engineering acceleration / native platform integration  
**Author:** ChatGPT competitor-review synthesis  
**Date:** 2026-09-06

## Problem

Jarvis should move faster by reusing proven implementation work from compatible open-source/reference projects when that reduces delivery time, but copied code must not turn Jarvis into a fork of another assistant or introduce architecture that conflicts with Jarvis's local-first, provider-neutral, React/Tauri, durable-execution and swarm design. The immediate reference is `FatihMakes/Mark-LII`, which already implements several ideas Jarvis independently planned: reversible actions, UI-originated confirmation, plugin discovery, measured audio-device probing, realtime audio activity, session continuity and compact memory recall.

Jarvis is currently being developed for non-commercial/private use, so non-commercial source may be used where its license permits. However, any such code must remain identifiable and replaceable so a later commercialization decision does not create a hidden licensing blocker.

## Decision

Adopt a **native-first adaptation rule**:

1. Reuse implementation code directly when the upstream license permits the current Jarvis use, the code cleanly fits a Jarvis interface, and doing so materially saves engineering/debugging time.
2. Port/adapt the behavior into Jarvis-native modules when the upstream implementation is tightly coupled to another UI, model provider, process layout, persistence model or runtime.
3. Reimplement from the observed behavior/algorithm when direct code reuse would create architectural debt, security weakness, performance loss, or licensing uncertainty.
4. Never make another assistant repository a required runtime dependency or let it own Jarvis orchestration.

Every adapted source component gets a small provenance record containing upstream repository, exact commit/revision, source file(s), license, adaptation type (`COPIED`, `PORTED`, `REIMPLEMENTED_FROM_BEHAVIOR`), Jarvis destination, material modifications and replacement status. Preserve required notices/attribution for copied or adapted code.

For `FatihMakes/Mark-LII`, preferred near-term extraction targets are:

- measured audio device enumeration/probing and stable-name resolution;
- UI-originated human confirmation semantics;
- undo/reversibility mechanics where they can be expressed through Jarvis durable execution;
- plugin discovery ergonomics, validation, collision detection and crash isolation;
- memory prompt-core + recall-index technique;
- session continuity/reconnect handling;
- live audio-level telemetry for HUD feedback.

Do **not** transplant the PyQt HUD, Gemini-owned session architecture, plain-HTTP/custom-encryption dashboard, JSON memory store, or in-process plugin security model as Jarvis architecture. Reuse individual algorithms/helpers only when they sit behind Jarvis-native contracts.

If Jarvis later becomes commercial, all components whose upstream license is non-commercial must be discoverable by provenance metadata and either relicensed from the author or replaced with independently implemented equivalents before commercial distribution.

## Acceptance criteria

- [ ] Add a lightweight source-provenance/adaptation record format for externally derived implementation work.
- [ ] Every directly copied or materially adapted external source file records upstream repository, revision, license and source path.
- [ ] Required attribution/license notices are preserved for code reused under attribution licenses.
- [ ] External assistant repositories are never required runtime dependencies of Jarvis.
- [ ] Reused code is placed behind Jarvis-native interfaces rather than exposing upstream architecture throughout the codebase.
- [ ] Fatih-derived confirmation behavior integrates with RFC-0031 approval provenance rather than importing a second confirmation system.
- [ ] Fatih-derived undo behavior integrates with RFC-0029 durable execution and RFC-0031 recovery records rather than an in-process closure stack.
- [ ] Fatih-derived plugin ideas integrate with Jarvis capability/policy/isolation contracts rather than unrestricted imports into the trusted process.
- [ ] Fatih-derived audio code is provider-neutral and does not require Gemini Live or PyQt.
- [ ] Fatih-derived memory ideas augment RFC-0011 and do not replace Jarvis's authoritative memory/provenance store.
- [ ] A future-commercialization audit can enumerate every component with a non-commercial or otherwise restrictive upstream license.
- [ ] Tests validate adapted behavior independently of the upstream project.
- [ ] Unit tests pass (`python3 -m pytest`).
- [ ] If frontend code is touched, `npm --prefix frontend run build` passes.

## Likely files

| Area | Paths |
| --- | --- |
| Provenance | `docs/`, source headers or a small machine-readable adaptation ledger |
| Backend | confirmation/recovery, audio, plugins/extensions, memory retrieval helpers |
| Frontend | existing React/Tauri HUD only where adapted behavior needs UI feedback |
| Tests | regression/parity tests for adapted components |

## Out of scope

Forking Mark-LII as Jarvis; copying its complete UI; changing Jarvis to Gemini-first; removing Jarvis policy/sandbox boundaries; asserting that renaming code changes its license; deciding a future commercial licensing strategy now.

## Notes

Primary reference: `FatihMakes/Mark-LII` at the revision inspected on 2026-09-06. It declares CC BY-NC 4.0. Current use may therefore adapt code for non-commercial Jarvis development subject to the license and attribution requirements, but restrictive-origin code must remain traceable for future replacement/relicensing if product goals change.

Recommendation: **ADAPT STRONGLY and reuse code selectively where it is genuinely native-compatible.**
