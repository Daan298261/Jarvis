# RFC-0175: Galaxy presence option, chat voice waveform, and Advanced controls

**Status:** implemented
**Implemented:** #419 @ `444e50c9b48bc475d05b646ce6b47d36e3e35d47` (product code; Galaxy Appearance option, chat waveform, Advanced disclosures, figure/field budgets). Amend 2026-09-25 morph: #425 @ `063a5ee1e411ce5bb551f3edccd680f7ea71e7e9` (squash of head `9f86a14f`; one-presence free→humanoid morph on all avatars; idle attract).
**Specs:** #418 @ `5954f7ee1c2faf130a7ef1846f6671b40f449b9e`. Amend specs: #422 @ `893d6e2c5c6a2c6476cdc46fdfb0b081e49db7be`.
**Amend (2026-09-25):** **implemented** (#425 @ `063a5ee1`). Refs A/B/C are stages of **one** continuous presence. The free→humanoid morph and idle attract landed in product code. Product criteria for that lifecycle are checked below. Quality bar stays **Anzu 1.0**. Full intent. No stubs / soft-fail.
**Residuals:** Desktop GPU / live WebGL soak of the live morph against `docs/rfcs/assets/0175/` refs A/B/C **and** real webcam face attract. Taco Desktop soak. Not signed off in #425. Cloud VMs cannot sign this off.
**Queue item:** `JARVIS_MASTER_PLAN.md` §58 — RFC-0175 (checked; #419 implemented; amend 2026-09-25 morph implemented #425 @ `063a5ee1`; residual: Desktop GPU soak vs refs A/B/C + real webcam face attract)
**Author:** Jarvis Architect  
**Date:** 2026-09-24
**Amend date:** 2026-09-25

**Related (do not rewrite):** [RFC-0069](0069-presence-shape-catalog-and-morph-api.md) (morphable orb cloud, `buildFigure` / `buildField`, `uMorph`). [RFC-0050](0050-ui-v3-presence-architecture.md) (`attentionMode` `off` | `pointer` | `camera`; attention vector `source: "pointer" | "camera"`; camera frames stay local and ephemeral). [RFC-0051](0051-humanoid-presence-runtime.md) (pointer attention when enabled; the humanoid runtime does not itself open the camera; reduced motion). [RFC-0137](0137-persona-presence-shape-and-voice-binding.md) (persona shapes and voice bind). [RFC-0138](0138-anzu-orb-custom-ui-generation.md) (custom presets; `hex_aegis` still wins while the suite is on). [RFC-0094](0094-settings-menu-information-architecture.md) / [RFC-0113](0113-admin-settings-submenu-1-4.md) (Settings groups, including `advanced`). [RFC-0061](0061-always-on-chat-tts-and-universal-personality.md) / [RFC-0067](0067-owner-chat-hide-plan-chrome-and-launch-greeting.md) / [RFC-0075](0075-natural-speak-path-and-reply-latency.md) (owner chat and the speak path). [RFC-0092](0092-neural-tts-default-no-silent-sapi.md) (neural TTS; this RFC does not change the engine). [RFC-0078](0078-hexstrike-cyber-suite.md) (`hex_aegis`).

Product code for the Galaxy option, the waveform, and Advanced landed in #419 @ `444e50c9b48bc475d05b646ce6b47d36e3e35d47`. Specs landed in #418 @ `5954f7ee1c2faf130a7ef1846f6671b40f449b9e`. That land stays **implemented**. The 2026-09-25 lifecycle is **implemented** in #425 @ `063a5ee1e411ce5bb551f3edccd680f7ea71e7e9`. Specs for that amend landed in #422 @ `893d6e2c5c6a2c6476cdc46fdfb0b081e49db7be`. Quality bar stays full intent, **Anzu 1.0**, **no stubs / soft-fail**. Desktop GPU soak of the live morph against refs A/B/C and real webcam face attract remains residual.

### Quality bar

The implement is **multibillion-company grade** and user-facing copy for the stretch is **Anzu 1.0**. The GitHub repository stays [`Daan298261/Jarvis`](https://github.com/Daan298261/Jarvis). Repo paths and existing `Jarvis` identifiers stay. This RFC does not rename them.

A Galaxy button that only swaps a CSS class, a waveform that loops while nobody is speaking, a star card with a hard edge, or an Advanced disclosure that deletes the control it was meant to hide is a **fail**. Production persistence, real speak/listen state, and the silhouette below are acceptance.

If the landed implement is below that bar, the notify path is **CoS → Taco**. That path is a review rule. It is not an API, a setting, a log line, or any other code path.

## Amend (2026-09-25) — one presence, not three looks

Taco lock, 2026-09-25, via Chief of Staff. Mood-board refs A/B/C are **stages of one continuous presence**. They are not alternate UIs. They are not three modes to pick between. There is no control, preset, or `requestedPresence` value that swaps Ref A for Ref B for Ref C.

What #419 shipped stays shipped: Galaxy as an **ADD** Appearance option, default `neural`, HexStrike override rules, the chat waveform, and per-tab Advanced. This amend does not undo that land.

The lifecycle below is **implemented** via #425 @ `063a5ee1e411ce5bb551f3edccd680f7ea71e7e9` (squash of head `9f86a14f`). Specs for this amend landed in #422 @ `893d6e2c5c6a2c6476cdc46fdfb0b081e49db7be`. Product criteria are checked. The quality bar stays **Anzu 1.0**, full intent, **no stubs / soft-fail**. **Residual:** Desktop GPU / live WebGL soak of the live morph against refs A/B/C and real webcam face attract. Taco Desktop soak. Not signed off in the #425 PR body. Cloud VMs cannot sign that off.

### Lifecycle (acceptance)

Full intent. Anzu 1.0. No stubs. A CSS class swap, a pre-baked bust that only yaws, a video texture, three swappable looks, or a morph that runs only when `requestedPresence` is `galaxy` is a **fail**.

1. **Idle / attract (Ref A).** Orbs free-float in the stage. They are not a preformed bust. They are drawn to the mouse cursor (pointer). When webcam / person tracking is available and returns a real face sample, they are drawn to that face. If the camera is missing, permission is denied, the tracker cannot start, or confidence is zero, attract **fails closed** to the pointer. Mouse-only still works. Presence still renders. Do not invent a face, do not block the avatar on a camera error, and do not send frames off the machine.
2. **Engage / start (Ref B).** Leaving idle morph-clumps those same orbs into the humanoid silhouette (Ref B lattice, or the winning non-bust figure when shape precedence says so). Ref C is the field through both stages, especially the Galaxy starfield already specified. It is not a stage the owner selects. One morph. Same orbs. Returning to idle reverses the morph back to free-float.
3. **Scope.** This free→humanoid morph is required for **all** UI avatars / presence modes. It is **not** gated on `requestedPresence: "galaxy"`. Galaxy stays the ADD Appearance option for the starfield and the enrichment already specified (Ref C). The lifecycle is cross-cutting.

**Phases.** `idle`, `waiting`, and `offline` are the idle / attract stage. `thinking`, `listening`, `speaking`, `executing`, `alert`, `error`, and `approval` are the engaged stage. The transition is the morph. Phase drives the stage. The owner does not pick a stage.

**Morph contract (RFC-0069, do not rewrite that RFC).** Use the existing `uMorph` lerp (0..1) on the morphable orb cloud. Do not add a second morph uniform, a second canvas, a mesh, or a GLTF. Do not remount `HumanoidPresence` / `PresenceHost` to play the transition.

- `uMorph` 0 is the free-float cloud (idle).
- `uMorph` 1 is the winning figure (`buildFigure` of the shape precedence already in §1).
- Non-reduced motion uses the existing morph duration (1.2s). Reduced motion snaps (`uMotion = 0`) and does not chase.
- Field layers may swap rather than lerp, as RFC-0069 already allows. Galaxy star samples stay out of the figure `uMorph` budget (§2).

**Attract contract (RFC-0050 / RFC-0051, do not rewrite those RFCs).** Pointer and camera attention already exist. Reuse them. Do not add a second webcam stack, and do not persist landmarks, embeddings, or frames (RFC-0050: local and ephemeral; nothing enters prompts, memory, logs, or telemetry).

- Pointer attract uses the existing attention vector `source: "pointer"` from `createPresenceAttentionController` (`frontend/src/presence/presenceAttention.ts`). Idle orbs bias toward that point (the `uPointer` falloff in `morphableOrbCloud` is the mechanism to extend). A yaw-only bust that is already a head is not the idle stage.
- Face attract uses the existing camera path: `attentionMode: "camera"` plus `presenceCameraTrack` (MediaPipe face landmarks, `FaceDetector` fallback). Do not call `getUserMedia` unless that mode is already `camera`. “Available” means the owner has enabled camera attention and the tracker returns a face. It does not mean idle always opens a webcam. RFC-0051’s humanoid runtime still does not itself open the camera. Acquisition stays the attention controller. A usable sample has confidence above zero. Anything else fails closed to the pointer. Mouse attract still runs.
- `attentionMode: "off"` and reduced motion: free-float holds without a chase. Pointer mode with no camera is the baseline, not a degraded mode.

**Where it runs.** Every host that renders a presence avatar:

| Avatar | Idle | Engaged clump | What stays |
| --- | --- | --- | --- |
| Neural | Free-float attract | Humanoid lattice (Ref B) on the morphable cloud | Saved `neural`. Neural chrome. Fallback order. |
| Humanoid | Free-float attract | Humanoid lattice (Ref B) | “TEM // PRESENCE” chrome and `buildField`. |
| Particle bust | Free-float attract | Humanoid lattice (Ref B) | The Particle bust control still selects `particle_bust`. |
| Galaxy | Free-float attract | Humanoid lattice (Ref B) when `humanoid_bust` wins | Ref C starfield, extra star budget, status pill. ADD only. |
| HexStrike host | Free-float attract | Winning `hex_aegis` figure | Suite override and saved-value rules in §1. |
| Persona shapes and RFC-0138 presets | Free-float attract | That winning `buildFigure` | Shape precedence in §1. |
| Classic | Free-float attract **only where a presence avatar is actually mounted** | The figure that host shows | `shell: classic`, `requestedPresence: none`. No new Classic canvas. |

Neural and Particle bust do not keep a private non-morphing body. Their mode buttons still select those modes. The avatar body is this lifecycle. Skipping them because they are not Galaxy is a **fail**.

`requestedPresence: "none"` (Classic with no avatar) stays a shell with no orb cloud. The static `PresenceFallback` is not the morph. Do not force Classic onto the HUD so the morph has somewhere to run. If a Classic surface does mount Neural, Humanoid, Particle bust, Galaxy, HexStrike, or a persona avatar, that avatar runs the lifecycle.

Shape precedence is unchanged: suite → `hex_aegis`; else the active RFC-0138 preset; else the RFC-0137 persona shape; else `humanoid_bust`. The free cloud is the idle end in every case. The winning figure is the engaged end. A morph that only runs for `humanoid_bust`, or only when Galaxy is selected, is a **fail**.

**Ref C** is the field / ambience through both stages, especially while Galaxy is selected. It is not a third presence. The starfield, the 2,400–4,000 HUD cap, the extra star budget, and the status pill stay the Galaxy ADD already specified. Non-Galaxy modes keep their own fields and chrome and still run the morph.

## Problem

Owners can choose Classic, Neural HUD, Humanoid HUD, or Particle bust, and the humanoid path is a morphable cloud of glowing orbs (`frontend/src/presence/renderers/shapes/humanoidBust.ts`, RFC-0069). The 2026-09-24 lock asked for an owner opt-in that enriches that cloud toward three room frames (idle bust, lattice, starfield). #419 added `galaxy` for that opt-in. The live visual contract is the 2026-09-25 amend: those frames are stages of one presence, on every avatar. Default `requested_presence` stays `neural`.

Chat has no luxury voice meter. `frontend/src/tts/chatTtsPlayer.ts` plays real TTS on an `HTMLAudioElement` (`activeAudio`) and `useTaskSpeech` already reports speaking. Classic chat (`frontend/src/pages/Chat.tsx`) opens a real mic and posts `/api/voice/listen`. HUD chat (`frontend/src/hud/HudChat.tsx`) keeps `recording` stuck at `false` and never shows listen state. `frontend/src/presence/renderers/shapes/waveformLetters.ts` is a **presence shape** (orb rings and letter strokes). It is not a chat waveform.

Power controls sit in the open on several tabs (Agent rooms cost/privacy on the create form, Classic task helpers default-open). RFC-0094 already has an `advanced` Settings group. That group is not a license to bury Voice, Appearance, or the primary action of every other tab.

#419 shipped the Galaxy ADD, the waveform, and Advanced against an earlier reading that treated Ref A / Ref B / Ref C as Galaxy-selected looks of one bust. That reading is superseded. The **Amend (2026-09-25)** lifecycle — one presence, free-float attract, then a humanoid clump, on every avatar — is **implemented** in #425 @ `063a5ee1`. Desktop GPU soak against the mood boards and real webcam face attract stays residual.

## Decision

Three additions. Each one layers onto what ships today.

### 1. Galaxy is an additional presence choice

Add `requestedPresence: "galaxy"` beside the modes that already exist. Default stays **`neural`**.

Appearance (`frontend/src/settings/AppearanceSettingsPane.tsx`, same control on the HUD Appearance menu) gains one more button in `.jarvis-presence-mode-row`:

| Button | Saved value | Behavior |
| --- | --- | --- |
| Classic | `shell: classic`, `requestedPresence: none` | Saved value unchanged. No new canvas. Lifecycle only where an avatar is mounted. |
| Neural HUD | `hud` + `neural` | Saved value unchanged. Avatar body runs the lifecycle. Neural chrome stays. |
| Humanoid HUD · built in | `hud` + `humanoid` | Saved value unchanged. Lifecycle runs. TEM chrome and `buildField` stay. |
| Particle bust · experimental | `hud` + `particle_bust` | Saved value unchanged. Avatar body runs the lifecycle. |
| HexStrike · Daybreak | suite activate still persists `humanoid` | Override rules unchanged. The host still runs the lifecycle. |
| **Galaxy** | `hud` + `galaxy` | ADD starfield and enrichment. The lifecycle is not gated on this value. |

“Unchanged” on a saved value is the #419 rule for the control. It is not an exemption from the 2026-09-25 lifecycle.

Rules:

- Galaxy is off until the owner selects it. Do not migrate existing `none` / `neural` / `humanoid` / `particle_bust` values to `galaxy`. Do not change `DEFAULT_PRESENTATION_SETTINGS` or `PresentationSettings.requested_presence`’s default. A missing key stays `neural`. An unknown value is rejected by the existing literal; it is not coerced to `galaxy`.
- Persist `galaxy` on the same presentation object (`backend/app/config.py`, `presentation_requested_presence` in `backend/app/api/settings.py`, `frontend/src/presence/presenceTypes.ts`). Restart shows Galaxy only when that value was saved.
- Selecting Galaxy sets `shell: "hud"` the same way Neural and Humanoid do. Classic remains its own button.
- WebGL unavailable: Galaxy uses the same fallback as Humanoid (`PresenceHost` → effective `neural`, reason `renderer_unavailable`). The note tells the owner that. A flat image of the reference frames is a **fail**.
- While the HexStrike suite profile is active, `HudChatHome` keeps today’s live override (`requestedPresence: "humanoid"`, shape `hex_aegis`). That override does not rewrite a saved `galaxy` value. `activateHexStrike` still persists `humanoid`, as it does today. Suite off returns whatever was saved, including Galaxy.
- Shape precedence is unchanged: suite → `hex_aegis`; else the active RFC-0138 preset; else the RFC-0137 persona shape; else `humanoid_bust` (`resolvePresenceShapeId`). Persona shapes, morph (`uMorph`, non-reduced 1.2s), and custom presets stay on the same `PresenceHost`. Galaxy does not register a fourteenth persona and does not remove a shape.

Galaxy’s extra field (starfield, dissolve, status pill) wraps whatever figure wins. When a persona shape, a custom preset, or `hex_aegis` wins, that figure is the **engaged** clump target. The free→humanoid lifecycle is not a Galaxy-only silhouette. It is specified in **Amend (2026-09-25)** and in §2, and it runs for every presence avatar.

Non-Galaxy Humanoid HUD keeps today’s `buildField` terrain and today’s “TEM // PRESENCE” / “JARVIS · NEURAL PRESENCE” chrome. It does not keep a preformed idle bust that skips the lifecycle. Neural chrome and the Particle bust control stay. Galaxy still adds the star field, the dissolve into that field, and the status pill, and only Galaxy adds those.

### 2. One presence lifecycle, then the Galaxy field

Refs A, B, and C are three stages of the presence in **Amend (2026-09-25)**. Work every presence avatar toward that lifecycle. Same orb samples (`ParticleOrb`). No second canvas, no mesh, no GLTF. Neural and Particle bust join the morphable orb cloud (RFC-0069) so the morph is real geometry. A crossfade between two pictures is a **fail**.

The lifecycle is **not** gated on `requestedPresence: "galaxy"`. Galaxy does not turn it on. Leaving Galaxy does not turn it off.

**Hero angle.** Engaged bust is front-facing, as in Ref B. Reduced motion holds the front and does not chase. The crown and the sides dissolve into the field. There is no hard silhouette card. Idle is not this bust yet. Idle is the free cloud (Ref A).

**Idle / attract — Ref A** (`idle`, `waiting`, `offline`), every avatar in the Amend table:

- Cool blue orbs free-float. The dark ground shows through. Edges fall off into dust. There is no head-and-shoulders bust yet. The amber core stays dim or off. Neck fibers stay quiet.
- Orbs are drawn to the pointer. When a real camera face sample is present they are drawn to that face. Fail closed to the pointer when tracking is unavailable. Mouse-only still works.
- On Galaxy, the pill reads `STATUS: IDLE | ····· | SYN-01`. Other modes do not grow that pill just because they now share the idle cloud.

**Engage / start — Ref B** (`thinking`, `listening`, `speaking`, `executing`, `alert`, `error`, `approval`):

- The same orbs morph-clump into the winning figure. For `humanoid_bust` (Neural, Humanoid, Particle bust, and Galaxy when the bust wins) that figure is the Ref B lattice. Horizontal fiber lines run through the head. A warm orange/amber concentric core glows in the face (existing `gold` channel, cranial volume only — a glow, not a helmet). Thinner gold fibers run down the neck into the chest. The crown breaks into loose particles. Digital terrain / nebula streams (cyan ridges, gold highlights) sit beside the bust, in this same field, not in a second host.
- `hex_aegis`, a persona shape, or a custom preset, when it wins precedence, is the clump target instead of the default lattice. Idle is still the free cloud. The morph still plays.
- Speaking may also follow real `snapshot.audioLevel` when the TTS graph provides it. That brightens the core. It does not play a fake meter on the bust while idle, and it does not run during the free-float stage.

**Field through the lifecycle — Ref C** (especially Galaxy, every winning shape):

- Deep black ground packed with small cool stars, the way Ref C fills the glass. Stars read as infinite: they exist past the frame and re-enter (wrap or regenerate). No hard rectangular star plate. This field is present through idle and through the engaged clump. It is Galaxy ambience, including when a persona shape or `hex_aegis` is the figure in front of it. It is not a third presence and not a control that hides the lifecycle.
- `HudStarfield` (`frontend/src/hud/HudShell.tsx`) stays the far layer. Today’s count is `reduced ? 90 : min(420, max(160, area/9000))`. While Galaxy is effective, raise the non-reduced cap into the **2,400–4,000** range on a desktop HUD viewport, keep the wrap, and clear to near-black. When Galaxy is not effective, leave that formula alone.
- Add a separate 3D star/orb layer in `createMorphablePresenceSystem`. Today `figureBudget` is `82000 * density` and `fieldBudget` is `15000 * density`. **Do not lower either.** Galaxy stars are an extra budget (on the order of `24000 * density`) and do not enter `uMorph` figure samples. Morph still moves the figure.
- The humanoid shape’s existing `buildField` mountains stay available on non-Galaxy Humanoid. Galaxy may use that stream language for the Ref B terrain. It does not delete `buildField`.

**Color.** Cool cyan/blue particles, amber core only when the lattice is up. A named persona’s `accent_color` may tint the status pill and a minority of highlight particles. It does not repaint an alive core away from amber or flatten the field to one hue.

**Motion.** Slow drift while motion is allowed. Idle attract eases toward the pointer, or toward a live face sample. Reduced motion (`prefers-reduced-motion` or `reducedMotion: reduce`): static points, `uMotion = 0`, no attract chase, morph snaps, status text still follows phase. The dissolve is a static falloff.

**Status chrome (Galaxy view only).** One pill, bottom-center of the presence stage, small and low-contrast. Not a stack of gauges, and not the current “TEM // PRESENCE” block. Copy matches Ref A:

`STATUS: <PHASE> | ····· | SYN-01`

| Phase | `<PHASE>` |
| --- | --- |
| `idle`, `waiting` | IDLE |
| `thinking` | THINKING |
| `listening` | LISTENING |
| `speaking` | SPEAKING |
| `executing` | WORKING |
| `approval` | WAITING |
| `alert`, `error` | ATTENTION |
| `offline` | OFFLINE |

`SYN-01` is a fixed mark on this pill, as in Ref A. It is not a setting, not a second synth, and not a model name. The middle rule stays static unless speaking or listening and an analyser is attached; then those few marks may follow that real level. No looping decoration. The pill sits on the Galaxy field through both stages. Idle on the HUD home uses the full `STATUS: IDLE | ····· | SYN-01` form over the free cloud. The Ref C frame is mostly field; that frame is the ambience, not a mode that skips idle or the clump. One pill only.

#### Visual acceptance targets

Authoritative mood boards are the three room frames Taco sent after the earlier attach failed. Match the picture on the glass. Do not reproduce phone status bars, social-app chrome, usernames, keyboards, or hands. Earlier side-profile desk photos are not this target.

| Board | What to match |
| --- | --- |
| **Ref A** — idle / attract stage | Free-floating cool-blue orbs. Not a preformed head and shoulders. Dark ground shows through. Edges dissolve. No bright amber face. Orbs draw toward the pointer, and toward a face when tracking is live. On Galaxy, the bottom-center pill reads `STATUS: IDLE \| ····· \| SYN-01`. This is the idle stage of the one presence. |
| **Ref B** — engaged humanoid lattice | The same orbs, morph-clumped into the humanoid silhouette: horizontal fiber lines, a warm orange/amber concentric face core, gold fibers in the neck, crown dissolving into particles, terrain streams left and right. This is the engaged stage, not a second mode. |
| **Ref C** — field / ambience through the lifecycle | Deep black star field, especially while Galaxy is the Appearance option. The field is up during idle and during the clump. Not a third look, and not a control that hides the figure. A discreet status pill may sit on that field. The reference frame is mostly stars; the product still runs Ref A and Ref B on it. |

Mood boards are in-repo:

- [`docs/rfcs/assets/0175/ref-a-particle-idle.jpg`](assets/0175/ref-a-particle-idle.jpg)
- [`docs/rfcs/assets/0175/ref-b-neural-lattice.jpg`](assets/0175/ref-b-neural-lattice.jpg)
- [`docs/rfcs/assets/0175/ref-c-galaxy-field.jpg`](assets/0175/ref-c-galaxy-field.jpg)

The table above and those binaries are the acceptance contract for the lifecycle. They are one presence seen at three moments. They are not three looks to swap.

#419 shipped Galaxy as an Appearance ADD, the waveform, Advanced disclosures, and the star/figure budgets. #425 @ `063a5ee1` implements the lifecycle in product code (free cloud, `uMorph` to the winning figure, all mounted avatars, pointer attract, camera fail-closed). The visual bar stays **Anzu 1.0**: idle on every presence avatar reads as Ref A (free-float attract), an engaged phase reads as Ref B (humanoid lattice clump, or the winning non-bust figure when precedence says so), and the Galaxy ground reads as Ref C through both stages. A screenshot collage, a video texture, a single pre-baked PNG, three swappable looks, or a morph that runs only for Galaxy is a **fail**. Desktop GPU / live WebGL soak against these boards, and real webcam face attract, is residual (Taco Desktop). Not signed off in #425.

### 3. Chat voice waveform

Add one component, `frontend/src/chat/VoiceWaveformBar.tsx`, mounted **in or immediately above** the composer on both surfaces:

- HUD: `frontend/src/hud/HudChat.tsx`, inside `.hud-composer`, above the textarea.
- Classic: `frontend/src/pages/Chat.tsx`, inside `.composer-dock`, above the textarea.

**Visibility (fail closed).** The bar is in the document only while Jarvis is actually speaking (TTS playback started, not yet ended, stopped, muted, or failed) **or** the mic is actually open (MediaRecorder running / STT listen in progress). Idle unmounts it. A decorative loop, a CSS animation while both flags are false, or a bar that stays up after `onEnd` is a **fail**.

**Amplitude.** Tap the live graph. TTS: `AnalyserNode` on `activeAudio` in `chatTtsPlayer.ts`. Mic: analyser on the open `MediaStream` in Classic `toggleRecord`, and on the HUD listen path below. The ribbon samples that spectrum. If the node cannot attach, show a **steady** illuminated strip for the true duration of speaking or listening. Do not synthesize bounce.

**HUD listen.** Classic already has Speak → `/api/voice/listen`. HUD `recording` is hardcoded `false`. Add the same Speak / Stop control on the HUD composer (visible, not under Advanced) and drive `recording` from that real recorder so the bar and `onMoodChange` see listen state. Reuse the Classic listen request. Do not add a second STT engine.

**Look.** A thin Anzu 1.0 ribbon: cool cyan with a warm edge, height on the order of 28–36px, sitting in the composer chrome. `role="img"` and `aria-label` “Jarvis is speaking” or “Listening”. It does not take focus and it does not start audio by itself. Reduced motion: the steady strip, no traveling wave. Persona accent may tint the edge; the bar does not become a toy equalizer.

`waveformLetters.ts` stays a presence shape. Do not wire the chat bar to that shape.

### 4. Common controls stay visible; power controls sit under Advanced

RFC-0094’s Settings groups stay. `SETTINGS_SUBMENUS` in `frontend/src/settings/settingsSubmenus.ts` stays `appearance-voice`, `phone-pairing`, `models`, `network`, `integrations`, `advanced`. Do not add a group, rename a group, or move Voice, Appearance, Galaxy, or the persona picker under Advanced. Do not remove cards from `AdvancedSettingsPane`. HexStrike tab names (Runtime, Catalog, Operate, Jobs) stay.

On each tab below, add a collapsed **Advanced** disclosure (`<details>` or equivalent, label exactly **Advanced**) on that same tab. Primary actions stay outside it. Moving a control into Settings → Advanced, or deleting it, is a **fail**.

| Surface | Stays visible | Moves under that tab’s Advanced |
| --- | --- | --- |
| Chat, HUD and Classic | Composer, Send, Speak/mic, speak-replies mute, Cancel while running, media attach, thread, approval prompts. “Show work” stays the existing collapsed chevron on `OwnerChatTranscript`. | Classic `TaskActivityPanel`. `DelegationPanel` (helpers). Helpers are collapsed by default; today `helpersOpen` starts `true`. |
| Agent rooms (`AgentRooms.tsx`) | Goal, specialist roster, create, room list, participants, task graph, typed timeline, blackboard read, handoff, synthesize, terminate | Cost mode, privacy mode, raw message-kind composer, raw blackboard publish, audit replay dump, governor detail |
| Modules / Skills (`SkillForge.tsx`) | Decision Inbox, purpose summary, Approve, Activate, Reject, published name and status, search. Disable and rollback stay on the published row (owner safety). | Raw hash / provenance block, permission-preview matrix, quarantine import, sandbox/verify debug |
| HexStrike suite tabs | The tab’s primary actions: lifecycle status, catalog search/enable, operate, job list | Raw bind ids, budget numerics, debug payloads — inside the tab that already owns them |

Any other portal tab follows the same rule: the control that finishes that tab’s job stays visible; budgets, raw ids, governors, and diagnostic dumps sit in an Advanced disclosure on that tab.

## Acceptance criteria

Checked rows are the #419 land (Galaxy option, waveform, Advanced, budgets) and the #425 lifecycle land. They stay checked. The Desktop GPU soak row stays **unchecked**. Where a checked #419 row describes a preformed idle bust, the lifecycle supersedes that picture.

- [x] Appearance offers Galaxy next to Classic, Neural HUD, Humanoid HUD, Particle bust, and HexStrike. Those five controls still select what they select today.
- [x] Default `requested_presence` remains `neural`. Existing saved values are not rewritten to `galaxy`. Restart restores a saved `galaxy` choice and does not force it on anyone else.
- [x] Figure budget and the shape’s own field budget are not reduced. Galaxy stars are additional. `uMorph` still morphs the winning shape. `hex_aegis`, custom presets, and persona shapes still win under the current precedence.
- [x] Non-Galaxy Humanoid HUD keeps its “TEM // PRESENCE” chrome and its `buildField` (shipped #419). The preformed idle bust is not the 2026-09-25 idle stage.
- [x] Galaxy status pill follows real phase (`STATUS: THINKING | ····· | SYN-01`, `STATUS: IDLE | ····· | SYN-01`, and the other rows). Reduced motion freezes drift and keeps a static glow.
- [x] Galaxy status pill follows real phase (`STATUS: THINKING | ····· | SYN-01`, `STATUS: IDLE | ····· | SYN-01`, and the other rows). Reduced motion freezes drift and keeps a static glow.
- [x] WebGL failure falls back to Neural with an honest note. No poster image of the references.
- [x] Waveform is mounted on HUD and Classic composers, visible only during real TTS playback or an open mic, hidden when idle, driven by an analyser when one attaches, steady when it does not.
- [x] HUD Speak uses the existing `/api/voice/listen` path and sets real `recording` state.
- [x] `waveformLetters.ts` is unchanged as the chat meter.
- [x] Settings submenu ids are unchanged. Voice and Appearance are not placed under Advanced. The per-tab Advanced disclosures in §4 exist, collapsed by default, and the visible controls in that table still work.
- [x] Unit coverage for the new presence literal (default `neural`, `galaxy` round-trips, old values still parse) and for waveform visibility (idle hidden, speaking shown, listening shown, end hidden).
- [x] `python3 -m pytest`
- [x] `npm --prefix frontend run build` and `npm --prefix frontend run lint`

Lifecycle (implemented #425 @ `063a5ee1`; Desktop soak residual stays open):

- [x] One presence. Ref A, Ref B, and Ref C are stages of the same continuous presence. No control swaps among three looks.
- [x] Idle / attract on every presence avatar: orbs free-float (not a preformed bust) and are drawn to the pointer. When webcam/person tracking is available and returns a real face sample, they are drawn to that face. Camera missing, denied, or tracker failed fails closed to the pointer. Mouse-only still works. No fake face chase. No frames leave the machine (RFC-0050).
- [x] Engage / start: those orbs morph-clump into the humanoid silhouette (Ref B lattice; winning `hex_aegis` / persona / preset figure when precedence says so). Ref C field stays through the lifecycle where Galaxy is selected. The morph is RFC-0069 `uMorph` (0 = free cloud, 1 = winning figure) without remounting the host and without a second canvas. Returning to idle reverses to free-float.
- [x] The free→humanoid morph runs for Neural, Humanoid, Particle bust, Galaxy, the HexStrike host, persona shapes, and RFC-0138 presets, and for Classic only where a presence avatar is actually mounted. It is not gated on `requestedPresence: galaxy`. A Galaxy-only morph is a **fail**. Classic `requestedPresence: none` does not grow a new canvas.
- [x] Galaxy remains an ADD Appearance option. Default stays `neural`. HexStrike override rules, the waveform, and Advanced stay as the #419 land.
- [x] Reduced motion: no chase and no traveling morph. `attentionMode: off` stops the attract and does not remove the avatar.
- [x] Unit coverage for the lifecycle: idle is the free cloud, engage drives `uMorph` toward the winning figure, camera-unavailable attract stays on the pointer, and the morph is not skipped when `requestedPresence` is not `galaxy`.
- [ ] **Residual:** Desktop GPU / live WebGL soak of the live morph against `docs/rfcs/assets/0175/` refs A/B/C and real webcam face attract. Taco Desktop soak. Not signed off in #425. Cloud VMs cannot sign this off.

## Likely files

| Area | Paths |
| --- | --- |
| Presence (shipped #419) | `frontend/src/presence/presenceTypes.ts`, `PresenceHost.tsx`, `renderers/HumanoidPresence.tsx`, `renderers/morphableOrbCloud.ts`, `renderers/shapes/humanoidBust.ts`, `frontend/src/hud/HudStarfield.tsx`, `frontend/src/hud/HudChatHome.tsx`, `frontend/src/settings/AppearanceSettingsPane.tsx` |
| Lifecycle (implemented #425) | `renderers/NeuralPresence.tsx`, `renderers/ParticleBustPresence.tsx`, `morphableOrbCloud.ts` (`uMorph`, `uPointer`), `presenceAttention.ts`, `presenceCameraTrack.ts`. Same `PresenceHost`. No second morph API. |
| Settings persistence | `backend/app/config.py` (`requested_presence` literal, default stays `neural`), `backend/app/api/settings.py` |
| Waveform | `frontend/src/chat/VoiceWaveformBar.tsx` (new), `frontend/src/hud/HudChat.tsx`, `frontend/src/pages/Chat.tsx`, `frontend/src/tts/chatTtsPlayer.ts`, `frontend/src/tts/useTaskSpeech.ts` |
| Advanced disclosures | `frontend/src/pages/Chat.tsx`, `frontend/src/pages/AgentRooms.tsx`, `frontend/src/pages/SkillForge.tsx`, `frontend/src/hud/HudHexStrikeSuite.tsx` |
| Tests | Presentation-settings tests; waveform visibility test. Lifecycle coverage (landed #425) is free-cloud vs `uMorph` and pointer-fallback. Do not require a webcam in CI. |
| Docs | This RFC. Mood boards in-repo at `docs/rfcs/assets/0175/ref-a-particle-idle.jpg`, `ref-b-neural-lattice.jpg`, `ref-c-galaxy-field.jpg`. Queue line in `JARVIS_MASTER_PLAN.md` §58. Decision in §59. |

## Out of scope

A second presence renderer. A second morph uniform. A second webcam stack. Rewriting RFC-0069, RFC-0050, or RFC-0051. Removing Classic, Neural, Humanoid, Particle bust, persona shapes, or RFC-0138 presets as selectable modes. Changing HexStrike suite IA (RFC-0078 / RFC-0086) beyond the override already specified. A new persona, voice pack, or GGUF. TTS engine choice, speak-filter, or RFC-0092. Using `waveformLetters.ts` as the chat bar. Android companion orb. Rewriting RFC-0094 groups. Forcing Classic `requestedPresence: none` to mount a new canvas. Agent-rooms websocket push (portal residual is already closed over REST by #417). Product code in this specs amend. Treating Ref A / Ref B / Ref C as three looks the owner swaps.

## Notes

- Specs land: #418 @ `5954f7ee1c2faf130a7ef1846f6671b40f449b9e`. Product code: #419 @ `444e50c9b48bc475d05b646ce6b47d36e3e35d47` (Galaxy Appearance option, chat waveform, per-tab Advanced disclosures, budgets).
- **Amend (2026-09-25):** one-presence lifecycle is **implemented** via #425 @ `063a5ee1e411ce5bb551f3edccd680f7ea71e7e9` (squash of head `9f86a14f`). Specs amend #422 @ `893d6e2c5c6a2c6476cdc46fdfb0b081e49db7be`. Free→humanoid morph on all avatars, idle attract (pointer, face when camera attention is available, fail closed to the pointer). Quality bar stays **Anzu 1.0**. Full intent. No stubs / soft-fail.
- **Residual:** Desktop GPU / live WebGL soak of the live morph against Ref A / Ref B / Ref C and real webcam face attract. Mood boards stay at `docs/rfcs/assets/0175/ref-a-particle-idle.jpg`, `ref-b-neural-lattice.jpg`, and `ref-c-galaxy-field.jpg`. Taco Desktop soak. Not signed off in the #425 PR body. Cloud VMs have no GPU and cannot sign this off.
- Subpar implement: CoS reviews and escalates to Taco. Do not encode that escalate as a runtime feature.
