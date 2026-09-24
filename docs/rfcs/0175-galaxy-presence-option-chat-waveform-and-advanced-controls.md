# RFC-0175: Galaxy presence option, chat voice waveform, and Advanced controls

**Status:** accepted  
**Queue item:** `JARVIS_MASTER_PLAN.md` §58 — RFC-0175 (unchecked; implement is a separate UX ticket after this PR merges)  
**Author:** Jarvis Architect  
**Date:** 2026-09-24

**Related (do not rewrite):** [RFC-0069](0069-presence-shape-catalog-and-morph-api.md) (morphable orb cloud, `buildFigure` / `buildField`, `uMorph`). [RFC-0137](0137-persona-presence-shape-and-voice-binding.md) (persona shapes and voice bind). [RFC-0138](0138-anzu-orb-custom-ui-generation.md) (custom presets; `hex_aegis` still wins while the suite is on). [RFC-0051](0051-humanoid-presence-runtime.md) (reduced motion). [RFC-0094](0094-settings-menu-information-architecture.md) / [RFC-0113](0113-admin-settings-submenu-1-4.md) (Settings groups, including `advanced`). [RFC-0061](0061-always-on-chat-tts-and-universal-personality.md) / [RFC-0067](0067-owner-chat-hide-plan-chrome-and-launch-greeting.md) / [RFC-0075](0075-natural-speak-path-and-reply-latency.md) (owner chat and the speak path). [RFC-0092](0092-neural-tts-default-no-silent-sapi.md) (neural TTS; this RFC does not change the engine). [RFC-0078](0078-hexstrike-cyber-suite.md) (`hex_aegis`).

This PR is **specs-only**. Product code is a **named follow-up** after CoS merges this PR. Full intent; **no stubs / soft-fail**.

### Quality bar

The implement is **multibillion-company grade** and user-facing copy for the stretch is **Anzu 1.0**. The GitHub repository stays [`Daan298261/Jarvis`](https://github.com/Daan298261/Jarvis). Repo paths and existing `Jarvis` identifiers stay. This RFC does not rename them.

A Galaxy button that only swaps a CSS class, a waveform that loops while nobody is speaking, a star card with a hard edge, or an Advanced disclosure that deletes the control it was meant to hide is a **fail**. Production persistence, real speak/listen state, and the silhouette below are acceptance.

If the landed implement is below that bar, the notify path is **CoS → Taco**. That path is a review rule. It is not an API, a setting, a log line, or any other code path.

## Problem

Owners can already choose Classic, Neural HUD, Humanoid HUD, or Particle bust, and the humanoid path is a morphable cloud of glowing orbs (`frontend/src/presence/renderers/shapes/humanoidBust.ts`, RFC-0069). That cloud is not yet the desk-photo presence Taco pointed at on 2026-09-24: a dense particle bust whose back dissolves into a black star field, with an amber cranial core, fiber lines through the neck, and a quiet status line. There is no owner opt-in for that look. `PresentationSettings.requested_presence` is `Literal["none", "neural", "humanoid", "particle_bust"]` and the default in `backend/app/config.py` is `"neural"`.

Chat has no luxury voice meter. `frontend/src/tts/chatTtsPlayer.ts` plays real TTS on an `HTMLAudioElement` (`activeAudio`) and `useTaskSpeech` already reports speaking. Classic chat (`frontend/src/pages/Chat.tsx`) opens a real mic and posts `/api/voice/listen`. HUD chat (`frontend/src/hud/HudChat.tsx`) keeps `recording` stuck at `false` and never shows listen state. `frontend/src/presence/renderers/shapes/waveformLetters.ts` is a **presence shape** (orb rings and letter strokes). It is not a chat waveform.

Power controls sit in the open on several tabs (Agent rooms cost/privacy on the create form, Classic task helpers default-open). RFC-0094 already has an `advanced` Settings group. That group is not a license to bury Voice, Appearance, or the primary action of every other tab.

## Decision

Three additions. Each one layers onto what ships today.

### 1. Galaxy is an additional presence choice

Add `requestedPresence: "galaxy"` beside the modes that already exist. Default stays **`neural`**.

Appearance (`frontend/src/settings/AppearanceSettingsPane.tsx`, same control on the HUD Appearance menu) gains one more button in `.jarvis-presence-mode-row`:

| Button | Saved value | Behavior |
| --- | --- | --- |
| Classic | `shell: classic`, `requestedPresence: none` | Unchanged |
| Neural HUD | `hud` + `neural` | Unchanged |
| Humanoid HUD · built in | `hud` + `humanoid` | Unchanged figure, labels, and field |
| Particle bust · experimental | `hud` + `particle_bust` | Unchanged |
| HexStrike · Daybreak | suite activate still persists `humanoid` | Unchanged |
| **Galaxy** | `hud` + `galaxy` | This RFC |

Rules:

- Galaxy is off until the owner selects it. Do not migrate existing `none` / `neural` / `humanoid` / `particle_bust` values to `galaxy`. Do not change `DEFAULT_PRESENTATION_SETTINGS` or `PresentationSettings.requested_presence`’s default. A missing key stays `neural`. An unknown value is rejected by the existing literal; it is not coerced to `galaxy`.
- Persist `galaxy` on the same presentation object (`backend/app/config.py`, `presentation_requested_presence` in `backend/app/api/settings.py`, `frontend/src/presence/presenceTypes.ts`). Restart shows Galaxy only when that value was saved.
- Selecting Galaxy sets `shell: "hud"` the same way Neural and Humanoid do. Classic remains its own button.
- WebGL unavailable: Galaxy uses the same fallback as Humanoid (`PresenceHost` → effective `neural`, reason `renderer_unavailable`). The note tells the owner that. A flat image of the reference frames is a **fail**.
- While the HexStrike suite profile is active, `HudChatHome` keeps today’s live override (`requestedPresence: "humanoid"`, shape `hex_aegis`). That override does not rewrite a saved `galaxy` value. `activateHexStrike` still persists `humanoid`, as it does today. Suite off returns whatever was saved, including Galaxy.
- Shape precedence is unchanged: suite → `hex_aegis`; else the active RFC-0138 preset; else the RFC-0137 persona shape; else `humanoid_bust` (`resolvePresenceShapeId`). Persona shapes, morph (`uMorph`, non-reduced 1.2s), and custom presets stay on the same `PresenceHost`. Galaxy does not register a fourteenth persona and does not remove a shape.

The reference silhouette in §2 is the **`humanoid_bust` figure while Galaxy is the effective presence**. When a persona shape, a custom preset, or `hex_aegis` wins, that figure stays. Galaxy still adds the star field, the dissolve into that field, and the status line around it.

Non-Galaxy Humanoid HUD keeps today’s bust, today’s `buildField` terrain, and today’s “TEM // PRESENCE” / “JARVIS · NEURAL PRESENCE” chrome.

### 2. Humanoid silhouette when Galaxy is selected

Work the current humanoid cloud toward the three frames below. Same renderer (`HumanoidPresence`, `morphableOrbCloud`). Same `ParticleOrb` samples. No second canvas, no mesh, no GLTF.

**Hero angle.** Three-quarter / side profile, matching ref1 and ref2: face contour readable, back of the head open to the star field. The same cloud, seen more from the front, matches ref3 (fiber neck, amber face core, terrain streams). Pointer attention may still yaw the bust. Reduced motion holds the hero angle.

**Figure, only on the Galaxy + `humanoid_bust` path:**

- Dense particle bust: head and shoulders made of glowing points, cool cyan and blue in the majority. Not a solid skin.
- Warm orange/amber **brain core** inside the cranium (use the existing `gold` channel; concentrate it in the cranial volume). The core is a glow, not an orange helmet.
- One bright cyan-white point at the base of the neck / upper chest.
- Vertical **fiber lines** through the neck into the head, thinner and brighter than the dust, visible from the front and as interior structure in profile.
- **Soft dissolve** at the occipital edge: point size and alpha fall off into the star field. No clip plane and no hard card edge.

**Field (Galaxy only, every winning shape):**

- Deep black ground. Stars read as infinite: they exist past the frame and re-enter (wrap or regenerate). No hard rectangular star plate.
- `HudStarfield` (`frontend/src/hud/HudShell.tsx`) stays the far layer. Today’s count is `reduced ? 90 : min(420, max(160, area/9000))`. While Galaxy is effective, raise the non-reduced cap into the **2,400–4,000** range on a desktop HUD viewport, keep the wrap, and clear to near-black. When Galaxy is not effective, leave that formula alone.
- Add a separate 3D star/orb layer in `createMorphablePresenceSystem`. Today `figureBudget` is `82000 * density` and `fieldBudget` is `15000 * density`. **Do not lower either.** Galaxy stars are an extra budget (on the order of `24000 * density`) and do not enter `uMorph` figure samples. Morph still moves the figure.
- Optional digital terrain / nebula streams, as in ref3: ridgelines of cyan particles with gold highlights beside and behind the bust. They are more samples in this same field, not a second presence host. The humanoid shape’s existing `buildField` mountains stay available on non-Galaxy Humanoid; Galaxy may strengthen that stream language. It does not delete `buildField`.

**Color.** The Galaxy + `humanoid_bust` palette is the reference palette (cyan field, amber core, white-blue base point) so the frames below are recognizable. A named persona’s `accent_color` may tint the status label and a minority of highlight particles. It does not repaint the core away from amber or flatten the field to one hue.

**Motion.** Slow galactic drift and a living particle flow while motion is allowed. Phase may brighten the core (`thinking`, `speaking`, `executing`). Speaking may also follow real `snapshot.audioLevel` when the TTS graph provides it. Idle is a quiet drift with **STATUS · IDLE**, not a fake voice meter. Reduced motion (`prefers-reduced-motion` or `reducedMotion: reduce`): static points, `uMotion = 0`, status text still follows phase. The dissolve is a static falloff.

**Status chrome (Galaxy view only).** One discreet line, small, tracked, lux — not a stack of fake gauges and not the current “TEM // PRESENCE” block:

| Phase | Line |
| --- | --- |
| `idle`, `waiting` | STATUS · IDLE |
| `thinking` | STATUS · THINKING |
| `listening` | STATUS · LISTENING |
| `speaking` | STATUS · SPEAKING |
| `executing` | STATUS · WORKING |
| `approval` | STATUS · WAITING |
| `alert`, `error` | STATUS · ATTENTION |
| `offline` | STATUS · OFFLINE |

Corner placement is enough (ref3). The line announces the real `PresencePhase`. It does not invent a phase.

#### Visual acceptance targets

Three frames supplied by Taco via CoS on 2026-09-24. This RFC describes them. The binaries are **not** added to the repo. Match the presence on the display. Do not reproduce room clutter, webcams, keyboards, or social-app chrome.

- **ref1 — side profile, clean desk photo.** Ultrawide, near-black display. A left-facing head and shoulders built only from glowing particles. Cool cyan/blue dust draws the brow, nose, lips, and shoulder. A warm orange-amber core sits in the skull. The back of the head thins into a trail of stars; there is no hard outline. A single bright point glows at the base of the neck. The rest of the photo (keyboard, webcam, wall) is the room, not UI.
- **ref2 — same side-profile bust**, photographed inside a social post captioned “Humanoid final version.” Match the monitor image: the same cyan bust, amber core, base point, and dissolve into stars. Ignore the post chrome, captions, and engagement controls.
- **ref3 — front bust with terrain.** The figure faces the owner. Dense cyan particles, orange-amber face core, vertical fiber lines in the neck, and digital mountain / nebula streams in cyan and gold on both sides of a black field. Small status text sits in the display; it is not a dashboard. Ignore the social-app chrome around the photo.

Shipped Galaxy + `humanoid_bust` is accepted when a reviewer can set the hero angle and recognize ref1/ref2, and can face the bust and recognize ref3, on the real WebGL cloud. A screenshot collage, a video texture, or a single pre-baked PNG is a **fail**.

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

- [ ] Appearance offers Galaxy next to Classic, Neural HUD, Humanoid HUD, Particle bust, and HexStrike. Those five controls still select what they select today.
- [ ] Default `requested_presence` remains `neural`. Existing saved values are not rewritten to `galaxy`. Restart restores a saved `galaxy` choice and does not force it on anyone else.
- [ ] Galaxy + `humanoid_bust` matches the ref1/ref2 side profile and the ref3 front read on the live orb cloud: cyan particles, amber core, base point, neck fibers, occipital dissolve, infinite black star field, optional terrain streams.
- [ ] Figure budget and the shape’s own field budget are not reduced. Galaxy stars are additional. `uMorph` still morphs the winning shape. `hex_aegis`, custom presets, and persona shapes still win under the current precedence.
- [ ] Non-Galaxy Humanoid HUD still shows its current bust and its current “TEM // PRESENCE” chrome.
- [ ] Galaxy status line follows real phase (`STATUS · THINKING`, `STATUS · IDLE`, and the other rows). Reduced motion freezes drift and keeps a static glow.
- [ ] WebGL failure falls back to Neural with an honest note. No poster image of the references.
- [ ] Waveform is mounted on HUD and Classic composers, visible only during real TTS playback or an open mic, hidden when idle, driven by an analyser when one attaches, steady when it does not.
- [ ] HUD Speak uses the existing `/api/voice/listen` path and sets real `recording` state.
- [ ] `waveformLetters.ts` is unchanged as the chat meter.
- [ ] Settings submenu ids are unchanged. Voice and Appearance are not placed under Advanced. The per-tab Advanced disclosures in §4 exist, collapsed by default, and the visible controls in that table still work.
- [ ] Unit coverage for the new presence literal (default `neural`, `galaxy` round-trips, old values still parse) and for waveform visibility (idle hidden, speaking shown, listening shown, end hidden).
- [ ] `python3 -m pytest`
- [ ] `npm --prefix frontend run build` and `npm --prefix frontend run lint`

## Likely files

| Area | Paths |
| --- | --- |
| Presence | `frontend/src/presence/presenceTypes.ts`, `PresenceHost.tsx`, `renderers/HumanoidPresence.tsx`, `renderers/morphableOrbCloud.ts`, `renderers/shapes/humanoidBust.ts`, `frontend/src/hud/HudStarfield.tsx`, `frontend/src/hud/HudChatHome.tsx`, `frontend/src/settings/AppearanceSettingsPane.tsx` |
| Settings persistence | `backend/app/config.py` (`requested_presence` literal, default stays `neural`), `backend/app/api/settings.py` |
| Waveform | `frontend/src/chat/VoiceWaveformBar.tsx` (new), `frontend/src/hud/HudChat.tsx`, `frontend/src/pages/Chat.tsx`, `frontend/src/tts/chatTtsPlayer.ts`, `frontend/src/tts/useTaskSpeech.ts` |
| Advanced disclosures | `frontend/src/pages/Chat.tsx`, `frontend/src/pages/AgentRooms.tsx`, `frontend/src/pages/SkillForge.tsx`, `frontend/src/hud/HudHexStrikeSuite.tsx` |
| Tests | Presentation-settings tests; waveform visibility test |
| Docs | This RFC. Queue line in `JARVIS_MASTER_PLAN.md` §58. Decision in §59. |

## Out of scope

A second presence renderer. Removing or rewriting Classic, Neural, Humanoid, Particle bust, RFC-0069 morph, RFC-0137 shapes, or RFC-0138 presets. Changing HexStrike suite IA (RFC-0078 / RFC-0086) beyond an Advanced disclosure inside existing tabs. A new persona, voice pack, or GGUF. TTS engine choice, speak-filter, or RFC-0092. Using `waveformLetters.ts` as the chat bar. Android companion orb. Rewriting RFC-0094 groups. Agent-rooms websocket push (portal residual is already closed over REST by #417). Product code in this specs PR.

## Notes

- Tip when written: `development` @ `2cb6c0b2` (#417).
- Visual sign-off of the Galaxy bust against ref1–ref3 is a desktop/browser check. Cloud VMs have no GPU; they can still unit-test the literal, the visibility rules, and the frontend build.
- Subpar implement: CoS reviews and escalates to Taco. Do not encode that escalate as a runtime feature.
- Implement only after CoS merges this PR and names the UX ticket.
