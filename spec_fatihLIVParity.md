# FatihMakes Mark-LIV Parity Specification

**Target:** ANZU / Jarvis  
**Reference repository:** `FatihMakes/Mark-LIV`  
**Reference commit:** `476a9c09d64423e97b08958c4088fde29a1b1713`  
**Purpose:** Identify implementation and UX patterns Mark-LIV executes well and specify the lowest-cost lawful parity/adaptation path for ANZU/Jarvis.

## 0. Source-reuse and licensing policy

**Current project status:** Jarvis/ANZU is presently a **personal-use, non-commercial project** and the Jarvis repository currently has **no project license selected**. Mark-LIV is published under **CC BY-NC 4.0**, which permits reuse subject to its terms but explicitly prohibits commercial use.

Reference: [Mark-LIV LICENSE, lines 1-6](https://github.com/FatihMakes/Mark-LIV/blob/476a9c09d64423e97b08958c4088fde29a1b1713/LICENSE#L1-L6)

### Current personal-use phase

For the current non-commercial Jarvis build, engineering agents may use the **cheapest technically sound implementation path**, including direct adaptation of Mark-LIV code when that is materially cheaper than rewriting it.

When Mark-LIV code is used as a source, agents should **adapt rather than vendor it unchanged**:

- rename classes, functions, modules, configuration keys, and internal concepts to ANZU/Jarvis terminology where that improves architectural consistency;
- restructure functions/classes to fit ANZU-owned interfaces and package boundaries;
- replace Mark-LIV-specific UI plumbing, state management, prompts, and naming with ANZU equivalents;
- refactor control flow where ANZU already has stronger abstractions;
- split or combine upstream functions when that reduces duplication or aligns with ANZU services;
- add ANZU tests around the required behavior rather than relying on upstream structure;
- preserve a clear provenance marker identifying the upstream source even after substantial refactoring.

The goal is to use Mark-LIV as an implementation source without importing it **as-is** into the ANZU architecture. However, renaming, formatting, or restructuring does **not** by itself remove upstream copyright/license obligations. Provenance and license status must remain explicit until a separate commercial license or replacement implementation covers that code.

Assets, prompts, branding, and other non-code material are tracked separately and are not assumed reusable merely because adjacent source code is.


### Upstream sync policy

Mark-LIV-derived components should be treated as **adapted upstream ports**, not forked files that must remain structurally identical to Mark-LIV.

For each adapted component:

- ANZU owns the local module boundary, API, naming, tests, and internal structure.
- Mark-LIV is tracked as an upstream/reference implementation for selected behavior.
- Upstream updates are reviewed at the referenced Mark-LIV component/function level.
- Relevant fixes or improvements are **ported into the ANZU implementation**, rather than overwriting the ANZU file with the new upstream file.
- Behavioral tests are the compatibility contract. ANZU does not need to preserve upstream class layout, function boundaries, comments, variable names, or file structure.
- If an upstream change no longer applies because ANZU already has a stronger implementation, record it as reviewed/not-applicable rather than forcing parity.
- Every substantial adapted component should have a mapping entry in the private provenance/chain-of-custody file linking upstream source -> ANZU destination -> adaptation notes -> last upstream review commit.

Example mapping:

```text
Upstream-reference: FatihMakes/Mark-LIV @ <commit>
Original-component: core/tts.py::KokoroTTSEngine
ANZU-component: <local ANZU path / symbol>
Adaptation: architecture port; interfaces/control flow restructured
Sync-policy: manually review upstream changes; port behavior, do not overwrite local module
```

This allows ANZU to keep working independently of Mark-LIV's internal restructuring while still making future upstream review and attribution straightforward.

### Preferred source order

When multiple implementations are available, use this order to minimize both engineering time and future migration cost:

1. Existing ANZU/Jarvis implementation that already meets or exceeds the requirement.
2. Permissively licensed implementation (MIT, BSD, Apache-2.0, similarly commercial-compatible) that can be adapted cheaply.
3. Mark-LIV code adapted under CC BY-NC 4.0 for the current personal-use phase.
4. Fresh implementation when reuse is slower, incompatible, or technically inferior.

### Future commercialisation gate

The project owner expects that a separate commercial license from FatihMakes can be obtained if/when Jarvis/ANZU becomes commercial. Therefore Mark-LIV-derived code does **not** need to be treated as throwaway by default.

Before commercial distribution, paid tiers, commercial SaaS, paid binaries, or other use incompatible with the current CC BY-NC terms:

- inventory every Mark-LIV-derived source fragment and asset;
- attach the applicable commercial permission/license to the provenance manifest, **or** replace the affected component with a commercial-compatible implementation;
- preserve behavior tests so licensed/replacement implementations can be swapped without regressions;
- run a dependency/license scan and produce a release manifest.

A commercial license, if obtained, should explicitly cover the adapted/derivative implementation actually used by ANZU, not only verbatim upstream files.

### Provenance requirement for copied/adapted code

Any substantial code adapted directly from Mark-LIV must be marked in either the source header or the repository provenance manifest. The marker should contain:

- upstream: `FatihMakes/Mark-LIV`;
- upstream commit: `476a9c09d64423e97b08958c4088fde29a1b1713`;
- original file path;
- original line range or function/class name where practical;
- adaptation type: `ported`, `refactored`, `restructured`, or `derived-behavior`;
- upstream license: `CC BY-NC 4.0` until superseded by documented commercial permission;
- local adaptation date;
- commercial-license status: `not-required-personal-use`, `pending`, `licensed`, or `replaced`.

Recommended source annotation:

```text
Upstream-source: FatihMakes/Mark-LIV @ 476a9c09d64423e97b08958c4088fde29a1b1713
Upstream-path: <file/function/lines>
Adaptation: refactored/restructured for ANZU architecture; not vendored as-is
License-status: CC BY-NC 4.0 / commercial permission pending
```

This provenance is intentional: it allows the project owner to tell the upstream author exactly what was used as source and how it was transformed, while keeping the implementation auditable.

---

## 1. Executive parity table

| Priority | Capability to adapt | Why Mark-LIV's approach is useful | Reference file | Stable source |
|---|---|---|---|---|
| P0 | Real-time voice interruption and bounded audio buffering | Stops speech quickly without allowing queued audio to continue after interrupt | `main.py` | [L914-L934](https://github.com/FatihMakes/Mark-LIV/blob/476a9c09d64423e97b08958c4088fde29a1b1713/main.py#L914-L934), [L1480-L1491](https://github.com/FatihMakes/Mark-LIV/blob/476a9c09d64423e97b08958c4088fde29a1b1713/main.py#L1480-L1491), [L1651-L1659](https://github.com/FatihMakes/Mark-LIV/blob/476a9c09d64423e97b08958c4088fde29a1b1713/main.py#L1651-L1659) |
| P0 | Long-lived voice session continuity + context compression | Reconnects without silently losing the conversation and prevents context-window death during long sessions | `main.py` | [L1020-L1036](https://github.com/FatihMakes/Mark-LIV/blob/476a9c09d64423e97b08958c4088fde29a1b1713/main.py#L1020-L1036), [L1470-L1478](https://github.com/FatihMakes/Mark-LIV/blob/476a9c09d64423e97b08958c4088fde29a1b1713/main.py#L1470-L1478) |
| P0 | Tunable end-of-speech/VAD | Exposes the latency-vs-pause tradeoff instead of hard-coding a single value | `main.py` | [L1060-L1089](https://github.com/FatihMakes/Mark-LIV/blob/476a9c09d64423e97b08958c4088fde29a1b1713/main.py#L1060-L1089) |
| P0 | One-pass vision tool injection | Captures screen/camera in the tool call and injects the frame before generation, avoiding a duplicate “blind” answer | `main.py` | [L1416-L1448](https://github.com/FatihMakes/Mark-LIV/blob/476a9c09d64423e97b08958c4088fde29a1b1713/main.py#L1416-L1448) |
| P0 | Self-describing action registry | New built-in actions become one-file additions rather than edits to a central dispatch switch | `core/action_loader.py` | [L1-L24](https://github.com/FatihMakes/Mark-LIV/blob/476a9c09d64423e97b08958c4088fde29a1b1713/core/action_loader.py#L1-L24), [L124-L220](https://github.com/FatihMakes/Mark-LIV/blob/476a9c09d64423e97b08958c4088fde29a1b1713/core/action_loader.py#L124-L220) |
| P0 | Plugin validation, collision isolation, runtime enable/disable | Bad extensions fail locally rather than breaking startup; plugin settings are self-describing | `core/plugin_loader.py` | [L1-L8](https://github.com/FatihMakes/Mark-LIV/blob/476a9c09d64423e97b08958c4088fde29a1b1713/core/plugin_loader.py#L1-L8), [L51-L137](https://github.com/FatihMakes/Mark-LIV/blob/476a9c09d64423e97b08958c4088fde29a1b1713/core/plugin_loader.py#L51-L137), [L155-L192](https://github.com/FatihMakes/Mark-LIV/blob/476a9c09d64423e97b08958c4088fde29a1b1713/core/plugin_loader.py#L155-L192), [L221-L284](https://github.com/FatihMakes/Mark-LIV/blob/476a9c09d64423e97b08958c4088fde29a1b1713/core/plugin_loader.py#L221-L284) |
| P0 | Human-only confirmation for irreversible actions | Prevents a model from forging its own confirmation token | `core/confirm.py` | [L1-L34](https://github.com/FatihMakes/Mark-LIV/blob/476a9c09d64423e97b08958c4088fde29a1b1713/core/confirm.py#L1-L34), [L82-L151](https://github.com/FatihMakes/Mark-LIV/blob/476a9c09d64423e97b08958c4088fde29a1b1713/core/confirm.py#L82-L151) |
| P0 | Reversibility-first undo stack | Avoids approval fatigue for reversible operations while still making voice mistakes recoverable | `core/undo.py` | [L1-L33](https://github.com/FatihMakes/Mark-LIV/blob/476a9c09d64423e97b08958c4088fde29a1b1713/core/undo.py#L1-L33), [L43-L114](https://github.com/FatihMakes/Mark-LIV/blob/476a9c09d64423e97b08958c4088fde29a1b1713/core/undo.py#L43-L114) |
| P0 | Memory core + index + on-demand recall | Separates storage capacity from prompt budget; model knows older facts exist without stuffing all values into every turn | `memory/memory_manager.py` | [L20-L42](https://github.com/FatihMakes/Mark-LIV/blob/476a9c09d64423e97b08958c4088fde29a1b1713/memory/memory_manager.py#L20-L42), [L194-L215](https://github.com/FatihMakes/Mark-LIV/blob/476a9c09d64423e97b08958c4088fde29a1b1713/memory/memory_manager.py#L194-L215), [L243-L324](https://github.com/FatihMakes/Mark-LIV/blob/476a9c09d64423e97b08958c4088fde29a1b1713/memory/memory_manager.py#L243-L324), [L327-L345](https://github.com/FatihMakes/Mark-LIV/blob/476a9c09d64423e97b08958c4088fde29a1b1713/memory/memory_manager.py#L327-L345) |
| P1 | Local wake word with zero-cost disabled state | Keeps optional always-on listening cheap, local, and isolated from the real-time audio callback | `core/wake_word.py` | [L1-L16](https://github.com/FatihMakes/Mark-LIV/blob/476a9c09d64423e97b08958c4088fde29a1b1713/core/wake_word.py#L1-L16), [L70-L104](https://github.com/FatihMakes/Mark-LIV/blob/476a9c09d64423e97b08958c4088fde29a1b1713/core/wake_word.py#L70-L104), [L109-L204](https://github.com/FatihMakes/Mark-LIV/blob/476a9c09d64423e97b08958c4088fde29a1b1713/core/wake_word.py#L109-L204) |
| P1 | Persistent browser sessions with profile fallback | Preserves sign-ins and avoids repeatedly opening throwaway browser state | `actions/browser_control.py` | [L444-L522](https://github.com/FatihMakes/Mark-LIV/blob/476a9c09d64423e97b08958c4088fde29a1b1713/actions/browser_control.py#L444-L522), [L574-L624](https://github.com/FatihMakes/Mark-LIV/blob/476a9c09d64423e97b08958c4088fde29a1b1713/actions/browser_control.py#L574-L624), [L627-L684](https://github.com/FatihMakes/Mark-LIV/blob/476a9c09d64423e97b08958c4088fde29a1b1713/actions/browser_control.py#L627-L684) |
| P1 | Companion pairing + persistent device token + phone mic | Strong UX pattern for phone-to-desktop continuity | `dashboard/server.py` | [L456-L512](https://github.com/FatihMakes/Mark-LIV/blob/476a9c09d64423e97b08958c4088fde29a1b1713/dashboard/server.py#L456-L512), [L568-L665](https://github.com/FatihMakes/Mark-LIV/blob/476a9c09d64423e97b08958c4088fde29a1b1713/dashboard/server.py#L568-L665), [L696-L720](https://github.com/FatihMakes/Mark-LIV/blob/476a9c09d64423e97b08958c4088fde29a1b1713/dashboard/server.py#L696-L720) |
| P1 | Authenticated phone↔PC file transfer | Useful companion UX with filename sanitization, size bounds, authenticated listing/download | `dashboard/server.py` | [L722-L808](https://github.com/FatihMakes/Mark-LIV/blob/476a9c09d64423e97b08958c4088fde29a1b1713/dashboard/server.py#L722-L808) |
| P1 | Audio-driven HUD/viseme synchronization with repaint throttling | Visual polish is tied to real playback timing while idle CPU use is reduced | `ui.py`, `main.py` | [ui.py L426-L460](https://github.com/FatihMakes/Mark-LIV/blob/476a9c09d64423e97b08958c4088fde29a1b1713/ui.py#L426-L460), [ui.py L542-L640](https://github.com/FatihMakes/Mark-LIV/blob/476a9c09d64423e97b08958c4088fde29a1b1713/ui.py#L542-L640), [main.py L1661-L1707](https://github.com/FatihMakes/Mark-LIV/blob/476a9c09d64423e97b08958c4088fde29a1b1713/main.py#L1661-L1707) |
| P1 | TTS warmup + synth/playback overlap | Reduces first-utterance and multi-sentence latency for local TTS | `core/tts.py` | [L214-L308](https://github.com/FatihMakes/Mark-LIV/blob/476a9c09d64423e97b08958c4088fde29a1b1713/core/tts.py#L214-L308), [L310-L350](https://github.com/FatihMakes/Mark-LIV/blob/476a9c09d64423e97b08958c4088fde29a1b1713/core/tts.py#L310-L350) |
| P2 | Dependency self-diagnosis for local voice | Detects known Kokoro/Transformers breakage and provides a deterministic recovery path | `core/tts.py` | [L139-L194](https://github.com/FatihMakes/Mark-LIV/blob/476a9c09d64423e97b08958c4088fde29a1b1713/core/tts.py#L139-L194) |
| P2 | Context-aware proactive checks with silence/cooldown gates | Avoids constant interruptions and deliberately rotates the reason for initiating | `actions/proactive.py` | [L1-L59](https://github.com/FatihMakes/Mark-LIV/blob/476a9c09d64423e97b08958c4088fde29a1b1713/actions/proactive.py#L1-L59), [L62-L127](https://github.com/FatihMakes/Mark-LIV/blob/476a9c09d64423e97b08958c4088fde29a1b1713/actions/proactive.py#L62-L127) |

---

## 2. Detailed ANZU requirements

### FATIH-PARITY-001 — Voice response cancellation must be immediate

ANZU shall expose a single cancellation primitive for spoken output. Cancellation must:

1. mark the active response as interrupted;
2. discard queued, not-yet-played audio;
3. reset lip-sync/viseme state;
4. stop visual “speaking” state;
5. immediately return the front-end to listening;
6. discard late audio packets from the interrupted generation.

Reference behavior: Mark-LIV drains its queued audio and resets speech/viseme state on interrupt [main.py L914-L934](https://github.com/FatihMakes/Mark-LIV/blob/476a9c09d64423e97b08958c4088fde29a1b1713/main.py#L914-L934), then ignores incoming audio while the interruption flag is active [main.py L1480-L1491](https://github.com/FatihMakes/Mark-LIV/blob/476a9c09d64423e97b08958c4088fde29a1b1713/main.py#L1480-L1491).

**Acceptance criteria**
- Manual stop-to-silence p95 <= 250 ms.
- No stale speech resumes after cancellation.
- A new user turn can start before the cancelled model turn finishes server-side.
- Cancellation works identically from desktop, companion app, hotkey, and voice front-end.

### FATIH-PARITY-002 — Separate transport continuity from durable memory

Voice-provider reconnects must not behave as a new conversation unless explicitly requested. The realtime adapter shall preserve any provider-supported resume handle and shall support bounded/sliding context when the provider exposes it.

Reference: [main.py L1020-L1036](https://github.com/FatihMakes/Mark-LIV/blob/476a9c09d64423e97b08958c4088fde29a1b1713/main.py#L1020-L1036) and resume-handle capture at [L1470-L1478](https://github.com/FatihMakes/Mark-LIV/blob/476a9c09d64423e97b08958c4088fde29a1b1713/main.py#L1470-L1478).

ANZU-specific rule: provider session resumption is an optimization only. Durable chat/project state remains in ANZU's own stores and must survive provider changes.

### FATIH-PARITY-003 — Voice turn detection must be user-tunable

Expose a latency profile rather than one fixed VAD configuration. At minimum:

- **Fast:** short end-of-speech silence, aggressive end sensitivity.
- **Balanced:** default.
- **Patient:** longer silence for users who pause while speaking.
- Optional advanced controls: end silence ms, prefix padding, start sensitivity, end sensitivity.

Mark-LIV demonstrates direct tuning of these parameters at [main.py L1060-L1089](https://github.com/FatihMakes/Mark-LIV/blob/476a9c09d64423e97b08958c4088fde29a1b1713/main.py#L1060-L1089).

### FATIH-PARITY-004 — Vision must not create a blind intermediate answer

When an agent requests “look at my screen/camera”, the tool result and captured frame must be delivered into the same reasoning turn before user-facing generation. The assistant must not speak a speculative answer and then correct itself after the image arrives.

Mark-LIV explicitly fixes this round-trip problem at [main.py L1416-L1448](https://github.com/FatihMakes/Mark-LIV/blob/476a9c09d64423e97b08958c4088fde29a1b1713/main.py#L1416-L1448).

Also label capture provenance (`screen`, `camera:<id>`, `mobile-camera:<device>`) in structured metadata so the model cannot confuse a UI screenshot with a camera photograph.

### FATIH-PARITY-005 — Actions shall self-register from manifests

ANZU built-in actions must not require edits to a central hard-coded dispatch table. Each action package/module declares:

- stable action ID;
- description;
- JSON input schema;
- handler;
- reversibility class;
- approval class;
- concurrency/serialization policy;
- optional scheduling/re-entry policy;
- capability permissions;
- version.

Mark-LIV's one-file action discovery pattern is documented at [core/action_loader.py L1-L24](https://github.com/FatihMakes/Mark-LIV/blob/476a9c09d64423e97b08958c4088fde29a1b1713/core/action_loader.py#L1-L24) and validates/isolates collisions at [L124-L220](https://github.com/FatihMakes/Mark-LIV/blob/476a9c09d64423e97b08958c4088fde29a1b1713/core/action_loader.py#L124-L220).

ANZU must extend this with its existing semantic action firewall and permission model; Mark-LIV's registry is a structural reference, not the security boundary.

### FATIH-PARITY-006 — Plugins shall fail closed and remain hot-toggleable

A malformed plugin must not prevent ANZU from starting. Validation failures, duplicate IDs, missing dependencies, or runtime errors are scoped to that plugin and surfaced in the plugin manager.

Required behavior:
- deterministic discovery order;
- schema validation before registration;
- reserved-name/collision detection;
- enable/disable without process restart where feasible;
- plugin-generated settings schema rendered by the host UI;
- actionable missing-dependency errors.

Reference: runtime enable state and settings schemas [core/plugin_loader.py L51-L137](https://github.com/FatihMakes/Mark-LIV/blob/476a9c09d64423e97b08958c4088fde29a1b1713/core/plugin_loader.py#L51-L137); validation [L155-L192](https://github.com/FatihMakes/Mark-LIV/blob/476a9c09d64423e97b08958c4088fde29a1b1713/core/plugin_loader.py#L155-L192); failure isolation/collision handling [L221-L284](https://github.com/FatihMakes/Mark-LIV/blob/476a9c09d64423e97b08958c4088fde29a1b1713/core/plugin_loader.py#L221-L284).

### FATIH-PARITY-007 — Irreversible approval must originate outside the model

Never treat an LLM-generated `confirmed=true` argument as human approval. The executor shall mint approval state only from a trusted UI/companion interaction bound to a specific proposed action.

Reference: Mark-LIV explains the failure of model-supplied confirmation and moves confirmation authority to the UI at [core/confirm.py L1-L34](https://github.com/FatihMakes/Mark-LIV/blob/476a9c09d64423e97b08958c4088fde29a1b1713/core/confirm.py#L1-L34). Its pending request is executed only after UI resolution at [L82-L151](https://github.com/FatihMakes/Mark-LIV/blob/476a9c09d64423e97b08958c4088fde29a1b1713/core/confirm.py#L82-L151).

ANZU approval tokens shall bind:
- action ID;
- canonicalized parameters/hash;
- requesting agent/task;
- user/session/device;
- expiry;
- one-time nonce.

### FATIH-PARITY-008 — Prefer undo over approval when an operation is genuinely reversible

For reversible actions, execute without a blocking confirmation when policy permits and register a reverse operation/transaction. Reserve confirmation for destructive or materially irreversible effects.

Reference philosophy and implementation: [core/undo.py L1-L33](https://github.com/FatihMakes/Mark-LIV/blob/476a9c09d64423e97b08958c4088fde29a1b1713/core/undo.py#L1-L33), bounded thread-safe history [L43-L114](https://github.com/FatihMakes/Mark-LIV/blob/476a9c09d64423e97b08958c4088fde29a1b1713/core/undo.py#L43-L114).

ANZU should use its durable execution journal rather than in-memory closures for important operations. Undo entries should survive app restart when technically possible.

### FATIH-PARITY-009 — Memory prompt budget shall be independent of memory storage size

Do not dump the entire personal memory store into every system prompt.

Required prompt assembly:
1. small mandatory identity/session core;
2. recent/high-value items within a strict token budget;
3. compact index/manifest indicating what additional memories exist;
4. retrieval tool for on-demand values.

Mark-LIV separates storage and prompt budgets [memory/memory_manager.py L20-L42](https://github.com/FatihMakes/Mark-LIV/blob/476a9c09d64423e97b08958c4088fde29a1b1713/memory/memory_manager.py#L20-L42), builds core/recent/index memory [L194-L324](https://github.com/FatihMakes/Mark-LIV/blob/476a9c09d64423e97b08958c4088fde29a1b1713/memory/memory_manager.py#L194-L324), and provides cheap recall scoring [L327-L345](https://github.com/FatihMakes/Mark-LIV/blob/476a9c09d64423e97b08958c4088fde29a1b1713/memory/memory_manager.py#L327-L345).

ANZU should use its existing semantic memory stack for actual retrieval; the useful parity concept is the **core + index + recall** split.

### FATIH-PARITY-010 — Wake word shall be local, optional, and off the realtime callback

When disabled, the wake-word feature should consume essentially no runtime resources. When enabled:
- microphone callback only performs a non-blocking enqueue/copy;
- inference runs on a dedicated worker;
- backlog is bounded and may drop frames instead of stalling realtime audio;
- wake phrase inference is local;
- one-click dependency/model installation is allowed only with explicit user action.

Reference design goals: [core/wake_word.py L1-L16](https://github.com/FatihMakes/Mark-LIV/blob/476a9c09d64423e97b08958c4088fde29a1b1713/core/wake_word.py#L1-L16). Worker/queue implementation: [L109-L204](https://github.com/FatihMakes/Mark-LIV/blob/476a9c09d64423e97b08958c4088fde29a1b1713/core/wake_word.py#L109-L204).

### FATIH-PARITY-011 — Browser automation shall preserve user state without depending on it

ANZU browser sessions should:
- maintain a persistent automation profile per browser/persona/workspace;
- optionally attach/use a real profile only when safe and explicitly enabled;
- fall back cleanly when a real profile is locked;
- keep sign-ins in the dedicated automation profile;
- reuse a live browser context rather than launching a process per action;
- recover when the current page closes.

Reference: session loop/context reuse [actions/browser_control.py L444-L522](https://github.com/FatihMakes/Mark-LIV/blob/476a9c09d64423e97b08958c4088fde29a1b1713/actions/browser_control.py#L444-L522), persistent fallback profile [L574-L624](https://github.com/FatihMakes/Mark-LIV/blob/476a9c09d64423e97b08958c4088fde29a1b1713/actions/browser_control.py#L574-L624), page recovery/navigation [L627-L684](https://github.com/FatihMakes/Mark-LIV/blob/476a9c09d64423e97b08958c4088fde29a1b1713/actions/browser_control.py#L627-L684).

Security note: ANZU should default to its own isolated profile. Reusing a person's real browser profile creates a much larger credential and session-cookie blast radius.

### FATIH-PARITY-012 — Companion pairing should feel instant but use explicit trust state

Useful UX patterns from Mark-LIV:
- short-lived pairing key;
- QR auto-login;
- persistent device identity for subsequent reconnects;
- token refresh without re-pairing;
- revoke-known-devices action;
- authenticated websocket for remote commands/audio.

Reference pairing flow: [dashboard/server.py L568-L665](https://github.com/FatihMakes/Mark-LIV/blob/476a9c09d64423e97b08958c4088fde29a1b1713/dashboard/server.py#L568-L665). Phone microphone websocket: [L696-L720](https://github.com/FatihMakes/Mark-LIV/blob/476a9c09d64423e97b08958c4088fde29a1b1713/dashboard/server.py#L696-L720).

ANZU shall implement this through its existing cluster/node identity model. Persistent paired devices should hold device keypairs rather than relying only on bearer secrets where possible.

### FATIH-PARITY-013 — Companion file transfer shall be first-class

Phone/desktop transfer should support authenticated upload, listing, and download; sanitize file names; apply configurable size limits; use duplicate-safe naming; and publish a transfer event into the task/chat UI.

Reference: [dashboard/server.py L722-L808](https://github.com/FatihMakes/Mark-LIV/blob/476a9c09d64423e97b08958c4088fde29a1b1713/dashboard/server.py#L722-L808).

For ANZU, route accepted files into the project/chat artifact layer rather than an unstructured global uploads folder.

### FATIH-PARITY-014 — Visual state must be driven by the actual audio timeline

The avatar/HUD should reflect audio that is actually scheduled for playback, not just transcript arrival or a generic “speaking” flag.

Required:
- waveform and mouth use the same playback-derived level source;
- viseme/phoneme schedule anchored to playback time;
- cancellation resets the schedule;
- UI rendering decoupled from realtime audio threads;
- heavy painting throttled while idle/hidden.

Reference: Mark-LIV's viseme schedule and shared amplitude source [ui.py L426-L460](https://github.com/FatihMakes/Mark-LIV/blob/476a9c09d64423e97b08958c4088fde29a1b1713/ui.py#L426-L460), audio/viseme stepping and repaint throttling [L542-L640](https://github.com/FatihMakes/Mark-LIV/blob/476a9c09d64423e97b08958c4088fde29a1b1713/ui.py#L542-L640), playback-derived schedule [main.py L1661-L1707](https://github.com/FatihMakes/Mark-LIV/blob/476a9c09d64423e97b08958c4088fde29a1b1713/main.py#L1661-L1707).

### FATIH-PARITY-015 — Local TTS must warm ahead and overlap synthesis with playback

For local neural TTS:
- initialize/warm the selected engine before the first user-visible utterance when resources allow;
- prefer GPU when available, but cap CPU worker usage;
- stream/chunk synthesis into a bounded queue;
- synthesize chunk N+1 while chunk N is playing;
- implement backpressure rather than unbounded audio buffering.

Reference: initialization/warmup [core/tts.py L214-L308](https://github.com/FatihMakes/Mark-LIV/blob/476a9c09d64423e97b08958c4088fde29a1b1713/core/tts.py#L214-L308), producer/consumer synthesis/playback overlap [L310-L350](https://github.com/FatihMakes/Mark-LIV/blob/476a9c09d64423e97b08958c4088fde29a1b1713/core/tts.py#L310-L350).

### FATIH-PARITY-016 — Voice dependency failures should be diagnosed, not silently fallback

Mark-LIV explicitly detects a known Kokoro/Transformers incompatibility and attempts a targeted recovery [core/tts.py L139-L194](https://github.com/FatihMakes/Mark-LIV/blob/476a9c09d64423e97b08958c4088fde29a1b1713/core/tts.py#L139-L194).

ANZU should generalize this as a **Voice Health Check**:
- verify selected engine really loaded;
- record provider/engine/version/device;
- run a short synthetic probe;
- surface whether audio came from selected engine or a fallback;
- never silently relabel Windows SAPI or another fallback as the requested neural voice;
- offer a deterministic repair action when a known dependency mismatch is detected.

This requirement directly addresses the historical issue where a configured voice can appear selected while the actual runtime falls back to a robotic system voice.

### FATIH-PARITY-017 — Proactivity must use explicit interruption budgets

A proactive assistant should not simply “check every N minutes.” It must gate initiation on silence, cooldown, context, and usefulness. Mark-LIV uses silence + cooldown and rotates its focus to reduce repetition [actions/proactive.py L1-L59](https://github.com/FatihMakes/Mark-LIV/blob/476a9c09d64423e97b08958c4088fde29a1b1713/actions/proactive.py#L1-L59), then includes memory/monitor/recent-turn context and permits silence when nothing useful exists [L62-L127](https://github.com/FatihMakes/Mark-LIV/blob/476a9c09d64423e97b08958c4088fde29a1b1713/actions/proactive.py#L62-L127).

ANZU adaptation:
- per-personality interruption budget;
- quiet hours;
- room/device occupancy signal when available;
- user activity awareness;
- deduplication against recent proactive messages;
- importance threshold;
- “do not speak if not useful” outcome;
- companion push notification as a lower-interruption alternative to speech.

---

## 3. Reuse rules: copy when cheaper, replace where ANZU is stronger

1. **Direct source adaptation is allowed in the present personal/non-commercial phase when it saves meaningful engineering effort.** Prefer refactoring/restructuring into ANZU-owned abstractions instead of dropping upstream files in unchanged. Keep provenance and current license status attached to that code.
2. **Prefer permissively licensed equivalents when the implementation cost is similar.** This reduces future commercial migration work.
3. **Do not downgrade stronger ANZU architecture merely to match Mark-LIV.** Copy/adapt the useful implementation detail while retaining ANZU's stronger interfaces, security model, persistence, and routing.
4. **Do not use an LLM's own arguments as approval.** Keep ANZU's stronger approval/action-firewall model.
5. **Do not treat a real browser profile as the default automation environment.** Use an ANZU-owned persistent profile and make real-profile use opt-in.
6. **Do not auto-run package upgrades during normal inference without a user-authorized maintenance policy.** Mark-LIV's Kokoro self-repair can be adapted as a diagnostic/repair workflow rather than copied as an uncontrolled runtime mutation.
7. **Do not replace ANZU's semantic memory with Mark-LIV's simpler lexical memory search.** Reuse code only where it contributes value; preserve ANZU's richer retrieval layer.
8. **Do not replace ANZU's scheduler/automation system with Mark-LIV's simple daily monitor.** Its implementation can be mined for inexpensive helpers, but ANZU's durable scheduler remains authoritative.
9. **Do not reproduce Mark-LIV/JARVIS branding or distinctive artwork as ANZU product identity.** Functional UI code may be adapted where licensed, but ANZU keeps its own identity/personality system.
10. **Every Mark-LIV-derived module must be replaceable behind an ANZU-owned interface.** This is the key requirement for later commercialisation.

---

## 4. Integration with existing ANZU/Jarvis specs

This parity document should be implemented as amendments/tests against the existing architecture, not as a parallel subsystem. In particular, reconcile with:

- `docs/rfcs/0033-reliable-realtime-voice-io.md`
- `docs/rfcs/0036-interaction-latency-and-streaming-talkback.md`
- `docs/rfcs/0064-companion-realtime-voice.md`
- `docs/rfcs/0098-browser-use-deepen.md`
- `docs/rfcs/0099-openviking-ragflow-memory.md`
- `docs/rfcs/0101-pipecat-realtime-voice-pipeline.md`
- `docs/rfcs/0110-chatgpt-style-approval-popup.md`
- `docs/rfcs/0111-kokoro-real-runtime.md`
- `docs/rfcs/0112-voice-preview-exact-profile.md`
- `docs/rfcs/0123-companion-reachability-and-anti-impersonation.md`
- `docs/rfcs/0125-companion-hud-lan-pair.md`
- `docs/rfcs/0132-supermemory-semantic-recall-sidecar.md`

Where an existing RFC is stronger, keep the stronger ANZU design and add Mark-LIV parity only as a behavior/acceptance requirement.

---

## 5. Suggested implementation order

**Milestone A — interaction correctness**
- FATIH-PARITY-001 interruption
- FATIH-PARITY-002 session continuity
- FATIH-PARITY-003 VAD profiles
- FATIH-PARITY-004 one-pass vision
- FATIH-PARITY-007 trusted confirmation
- FATIH-PARITY-008 durable undo

**Milestone B — extension and memory architecture**
- FATIH-PARITY-005 action manifests
- FATIH-PARITY-006 plugin isolation/settings
- FATIH-PARITY-009 core/index/recall memory

**Milestone C — companion and browser**
- FATIH-PARITY-010 wake word
- FATIH-PARITY-011 persistent browser contexts
- FATIH-PARITY-012 pairing/device trust
- FATIH-PARITY-013 file transfer

**Milestone D — polish**
- FATIH-PARITY-014 audio-timeline HUD
- FATIH-PARITY-015 TTS pipelining
- FATIH-PARITY-016 voice health/repair
- FATIH-PARITY-017 interruption-budgeted proactivity

---

## 6. Definition of parity

“Fatih LIV parity” does **not** require an identical UI or implementation. It is met when ANZU provides equivalent or better user-observable behavior for the selected capabilities while preserving ANZU's stronger goals: local-first operation, swarm routing, explicit security boundaries, durable execution, modular personalities, and companion clients.

During the current personal-use phase, parity may be reached through direct adaptation of Mark-LIV code where that is the cheapest sound path. Adapted code should be renamed and restructured to fit ANZU's architecture and should be explicitly marked as derived/refactored from Mark-LIV rather than vendored as-is. This architectural transformation does not itself change licensing obligations; provenance remains attached so a future commercial license can be documented cleanly, or the component can be replaced without redesigning the surrounding system.
