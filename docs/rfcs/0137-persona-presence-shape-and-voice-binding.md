# RFC-0137: Named persona presence shape and original voice binding

**Status:** accepted  
**Queue item:** (none — no new §58 checkbox)  
**Author:** Jarvis Architect  
**Date:** 2026-09-23  
**Amended:** 2026-09-23 on `development` @ `ec5c8f8c` (PR #376). This file stays **0137**. Do not open RFC-0138 for the roster. Status stays **accepted**. Specs-only; **not implemented**.

**Related (do not rewrite):** [RFC-0126](0126-personality-session-modes.md) and [RFC-0130](0130-session-personalities.md) stay **session modes** (HUD accent + prompt). They are not this catalog. [RFC-0069](0069-presence-shape-catalog-and-morph-api.md) (**implemented** — `registerPresenceShape`, `uMorph`). [RFC-0051](0051-humanoid-presence-runtime.md) (reduced motion; existing phase machine). [RFC-0062](0062-selectable-voice-profile-catalog.md) / [RFC-0092](0092-neural-tts-default-no-silent-sapi.md) (original packs; no silent SAPI). [RFC-0078](0078-hexstrike-cyber-suite.md) already morphs to `hex_aegis` when the HexStrike suite profile is selected. [RFC-0106](0106-hexstrike-jarvis-full-operator-control.md) operator contract stays. [RFC-0104](0104-persona-candidates-pack.md) stays an unmerged hold.

**Supersedes:** the four-name catalog in this file as landed by #376 (`anzu`, `eagir`, `veles`, `enki`). Taco’s canonical **ANZU persona roster** (13 named specialists) replaces that table. Drop the id `eagir`. Drop Enki → `abzu_flow` + `tactical_aide_original_v1`. Drop Veles → `root_coil` as the canonical shape id.

This PR is **specs-only**. Product code is a **named follow-up**. Full intent; **no stubs / soft-fail**. Veles and Themis are persona labels and presence/voice UX only — do not invent LE / ATO / officer gates, exploit recipes, or offensive tool wiring. Existing HexStrike and cyber rules elsewhere stay untouched. Do not edit the RFC-0115 implement tree. Do not merge RFC-0104 `persona_candidate` trees.

## Problem

Jarvis has no selectable named persona. The presence figure does not change when the owner picks who is speaking, and the speaking voice does not change with that choice. #376 specified four names. Taco has since pasted the canonical roster of **13** specialists. UX will not implement until this amend is the catalog.

What exists on tip (`ec5c8f8c`), and what it is **not**:

- Session modes in `backend/app/persona/session_personality.py` are `core` (HUD label **Anzu / Core**; aliases `default` / `jarvis` / `anzu`), `coding`, `research`, and `concise`. They set `hud_theme`, a dialogue preset, and a prompt addendum. `coding` stores `tts_voice_hint` `"jarvis-default"`, which is not a voice-pack id. `set_active_mode` does not call `set_active_voice_profile_id`. `GET`/`PUT /api/session-personality` and `POST /detect` only switch that mode. Settings copy in `frontend/src/personality/SessionPersonalityControls.tsx` is this mode list. **Leave this surface as HUD + prompt.** Do not hang presence or voice off it.
- Presence shapes in `frontend/src/presence/renderers/shapes/catalog.ts` are `humanoid_bust` (default; `avatarId` `jarvis_base`), `energy_core`, and `hex_aegis`. #376 did not register persona shapes. New figures join through `registerPresenceShape`. Morph is `frontend/src/presence/renderers/morphableOrbCloud.ts`: `uMorph` lerps figure samples 0..1. `HumanoidPresence` calls `morphTo` in the frame loop (`duration: 1.2`, or `immediate` when reduced motion is on). Remounting the cloud pops.
- `frontend/src/presence/presenceState.ts` already derives one snapshot (`offline`, `idle`, `listening`, `thinking`, `executing`, `speaking`, `waiting`, `alert`) for `PresenceHost`. `failed`, `systemDegraded`, and `waiting_for_confirmation` currently collapse into `alert`. This RFC extends that machine. It does not add a second renderer.
- `frontend/src/hud/HudChatHome.tsx` passes `shapeId` only while the HexStrike suite profile is selected (`hex_aegis` from RFC-0069 / RFC-0078). That suite shape **stays**. It is not a persona. This RFC does not give Daybreak a persona row and does not bind a suite voice.
- Original packs on disk (do not retarget `speaker_ref`, do not add pack files in the specs PR or in the implement ticket):

| `voice_profile_id` | `display_name` | `engine_id` |
| --- | --- | --- |
| `butler_original_v1` | Household butler (original) | `kokoro` (`bm_george`) |
| `chatterbox_expressive_en_v1` | Household butler (expressive) | `chatterbox` |
| `dry_butler_original_v1` | Dry household butler (original) | `kokoro` (`bm_lewis`) |
| `tactical_aide_original_v1` | Tactical soft-spoken aide (original) | `kokoro` (`af_bella`) |
| `synthetic_command_original_v1` | Cold synthetic command (original) | `kokoro` (`am_michael`) |
| `windows_natural_en_v1` | Windows system (SAPI) | `system` |

`set_active_voice_profile_id` rejects an unknown or unavailable pack. RFC-0092 forbids SAPI audio while a neural profile was requested, and forbids preferring `windows_natural_en_v1` as a persona voice. `ip_guard.py` still rejects Codsworth, Cortana, Ultron, Fallout, Marvel, Disney, Iron Man, and the related strings. This RFC does not weaken that list, does not add those characters, and does not invent Marvel or Codsworth packs.

Several roster voices share one existing pack on purpose. Pitch, rate, colour, and motion distinguish them. A follow-on voice-pack RFC may add original packs later if an archetype still cannot be told apart. That follow-on is **out of scope** here. Do not add pack files to satisfy this ticket.

## Decision

A **named persona** is one of the 13 ids below. Selecting it sets `presence_shape_id`, `voice_profile_id`, and the default colours together, and morphs the existing orb cloud. Reduced motion snaps.

The default main interaction is **Anzu**. Fresh install and a missing stored id resolve to `anzu`.

Session modes do not select a persona, do not change `shapeId`, and do not call `set_active_voice_profile_id`. A later Taco request may tie a mode to a name. This RFC does not.

Ids are the lowercase display names. Spelling lock: **Aegir**. Canonical id is `aegir`. Accept `ægir` as an alias of `aegir`. **Drop** `eagir`. Do not list `eagir` in `GET /api/named-personas`.

Figures are particle samples in `buildFigure` (the layer `uMorph` lerps). `buildField` may add loose orbs; it is not the silhouette, because field geometry swaps instead of lerping. No mesh, no texture, no copyrighted creature. Each silhouette must read at HUD framing distance (`HudChatHome` size 760).

`windows_natural_en_v1` is never a persona voice and never a silent stand-in.

`humanoid_bust` remains the figure only when the persona id is missing or unknown **after** migration. Do not leave the main `shapeId` unset for a known persona. Unset falls through to `humanoid_bust`.

While the HexStrike suite profile is active, the existing `hex_aegis` `shapeId` override stays in front of the persona figure. Turning the suite off morphs back to the selected persona’s shape. Suite on/off does **not** change the voice. Do not rewrite RFC-0106.

### Catalog

Display archetype in the voice column is the **existing pack’s** display name, not a new pack. Default colours are the roster pair (orb + accent). Appearance may override them per persona; the shape id stays.

| # | Id | Role | Voice intent | `presence_shape_id` | Visual intent | `voice_profile_id` | Default colours |
| --- | --- | --- | --- | --- | --- | --- | --- |
| 1 | `anzu` | Main assistant, orchestration, swarm control | Calm, confident, low-mid neutral | `stormbird` | Large red-and-gold storm orb. Wing-like arcs. Slow electrical pulses. | `butler_original_v1` | crimson `#9B1B30` + gold `#D4A017` |
| 2 | `mestor` | Planning, missions and operations | Firm, measured operations | `command_facet` | Blue-white faceted command orb. Rotating hexagonal rings. | `tactical_aide_original_v1` | royal blue `#1E3A8A` + white `#F8FAFC` |
| 3 | `nabu` | Memory, research and knowledge | Warm, scholarly, precise | `memory_rings` | Amber/indigo orb. Layered memory rings, floating glyphs, text particles. | `dry_butler_original_v1` | amber `#D97706` + indigo `#312E81` |
| 4 | `enki` | Coding, engineering and automation | Energetic, practical technical | `code_cube` | Cyan orb inside a rotating wireframe cube. Flowing code-lines. | `synthetic_command_original_v1` | cyan `#22D3EE` + electric blue `#2563EB` |
| 5 | `veles` | Red Team, threat intelligence and adversarial analysis | Quiet, low, controlled | `serpent_orbit` | Dark violet/green orb. Serpent-like orbit. Intermittent shadow fractures. | `synthetic_command_original_v1` | violet `#5B21B6` + toxic green `#84CC16` |
| 6 | `themis` | Blue Team, defence, policy and auditing | Clear, clinical, evidence-led | `twin_shield` | White/ice-blue orb. Two balanced shield halos. Central status line. | `tactical_aide_original_v1` | ice blue `#E0F2FE` + white `#FFFFFF` |
| 7 | `aegir` | Media, communications, cameras and audio | Smooth, warm broadcast | `ocean_swell` | Teal liquid orb. Wave ripples, lens flares, flowing signal trails. | `chatterbox_expressive_en_v1` | teal `#0D9488` + deep ocean `#0C4A6E` |
| 8 | `bragi` | Writing, creativity, manuscripts and dialogue | Expressive storyteller | `waveform_letters` | Magenta/gold orb. Pulsing waveform rings. Drifting luminous letters. | `chatterbox_expressive_en_v1` | magenta `#C026D3` + gold `#EAB308` |
| 9 | `hermes` | Browser, messaging, APIs and fast communications | Bright, quick, responsive | `comet_trail` | Yellow/cyan comet-orb. Twin trails. Rapid orbiting particles. | `chatterbox_expressive_en_v1` | yellow `#FACC15` + cyan `#06B6D4` |
| 10 | `heimdall` | Monitoring, sensors, cameras and alerts | Alert but controlled watchkeeper | `eye_radar` | Orange/blue eye-shaped orb. Scanning rings. Radar sweeps. | `tactical_aide_original_v1` | orange `#F97316` + cobalt `#1D4ED8` |
| 11 | `eir` | Wellbeing, routines and household care | Gentle, reassuring, patient | `breath_leaf` | Soft mint/rose orb. Heartbeat pulses, leaf motifs, smooth breathing. | `dry_butler_original_v1` | mint `#6EE7B7` + soft rose `#FDA4AF` |
| 12 | `maia` | Marketing, social media and audience growth | Upbeat, persuasive, socially fluent | `star_social` | Coral/pink star-orb. Orbiting social nodes. Expanding signal rings. | `chatterbox_expressive_en_v1` | coral `#FB7185` + pink `#F472B6` |
| 13 | `vulcan` | Hardware, infrastructure and physical systems | Practical, grounded, slightly rugged | `forge_core` | Orange/red molten-core orb. Sparks, forge rings, heat shimmer. | `synthetic_command_original_v1` | molten orange `#EA580C` + red `#DC2626` |

Labels are Anzu, Mestor, Nabu, Enki, Veles, Themis, Aegir, Bragi, Hermes, Heimdall, Eir, Maia, Vulcan.

`stormbird` and `ocean_swell` keep the ids from #376. Refine Anzu’s visual to the red-gold wing arcs and electrical pulses in this table (the earlier “beak silhouette” line is withdrawn). `ocean_swell` moves from the dropped `eagir` id to `aegir`.

New shape ids: `command_facet`, `memory_rings`, `code_cube`, `serpent_orbit`, `twin_shield`, `waveform_letters`, `comet_trail`, `eye_radar`, `breath_leaf`, `star_social`, `forge_core`.

`code_cube` replaces #376 `abzu_flow` (Enki is coding, not Abzu water). `serpent_orbit` replaces #376 `root_coil`. If a store or branch already wrote `root_coil`, migrate it; do not keep `root_coil` as a second registered shape.

### Voice bind

Prefer the five neural packs above. Shared packs are the binding, not a fallback.

| Id | `voice_profile_id` | Why | Appearance distinction while the pack is shared |
| --- | --- | --- | --- |
| `anzu` | `butler_original_v1` | Main household host. Taco’s prior Anzu → butler lock. | Rate `1.00`, pitch `0`. |
| `mestor` | `tactical_aide_original_v1` | Firm measured ops. | Rate `0.96`, pitch `−1`. |
| `nabu` | `dry_butler_original_v1` | Warm-scholarly understated. | Rate `0.92`, pitch `0`. |
| `enki` | `synthetic_command_original_v1` | Practical technical / precise. #376 had wrongly paired Enki with `abzu_flow` and the tactical aide. | Rate `1.06`, pitch `+1`. |
| `veles` | `synthetic_command_original_v1` | Quiet, low, controlled. Same pack as Enki is allowed. | Rate `0.84`, pitch `−3` (lower than Enki). |
| `themis` | `tactical_aide_original_v1` | Clinical, evidence-led. Same pack as Mestor is allowed. | Rate `1.10`, pitch `+1` (faster than Mestor). Cooler read is the ice palette, not a different pack. |
| `aegir` | `chatterbox_expressive_en_v1` | Smooth warm broadcast. | Rate `0.98`, pitch `0`, animation intensity `0.60`. |
| `bragi` | `chatterbox_expressive_en_v1` | Expressive storyteller. Same pack as Aegir is allowed. | Rate `1.02`, pitch `+1`, animation intensity `0.90`. |
| `hermes` | `chatterbox_expressive_en_v1` | Bright, quick. Same pack is allowed. | Rate `1.22`, pitch `+2`. |
| `heimdall` | `tactical_aide_original_v1` | Alert controlled watchkeeper. | Rate `1.00`, pitch `0`. |
| `eir` | `dry_butler_original_v1` | Gentle, reassuring. Same pack as Nabu is allowed. | Rate `0.80`, pitch `−1`, glow `0.50`, animation intensity `0.35` (softer and slower than Nabu). |
| `maia` | `chatterbox_expressive_en_v1` | Upbeat, persuasive. | Rate `1.12`, pitch `+1`. |
| `vulcan` | `synthetic_command_original_v1` | Rugged, practical. Same pack as Enki and Veles is allowed. | Rate `0.90`, pitch `−2`. |

Rates are persona playback overrides in `0.75`–`1.35` (the existing `VoiceProfileTTS.speaking_rate` bounds). Pitch is semitones in `−6`..`+6`. Volume defaults to `1.0` (range `0`..`1`). Glow and animation intensity default to `0.70` and `0.60` except where the table sets them. Main orb scale defaults to `1.0` (`anzu` main scale `1.15`, `hermes` `0.92`, `vulcan` `1.05`). These numbers are the roster defaults, not new pack files.

**Anzu-only fallback.** If `butler_original_v1` is missing and `dry_butler_original_v1` is available, activate the dry pack and report that id (`voice_profile_id` is the pack actually set; `voice_profile_requested` is `butler_original_v1`). If neither is available, the bind **fails**.

**Everyone else.** If the required pack is missing or unavailable, the bind **fails closed**. Do not activate SAPI. Do not activate a different neural pack. Do not copy another persona’s pack. Leave the previous persona in place. Do not persist the new id.

`windows_natural_en_v1` is never selected by this catalog and never used to satisfy pitch, rate, or a missing neural pack.

Playback of a shared pack:

- Kokoro: pass the persona `speaking_rate` as the existing `speed` argument. Do not edit `pack.json` or `speaker_ref`.
- Chatterbox: keep the neural generate path. Apply rate by time-stretching that wav. Do not call `speak_sapi` to obtain a rate.
- Pitch and volume: apply on the neural PCM (pitch shift and gain) before playback, for every engine in this catalog. Do not route through `engine_id: "system"` to obtain pitch.

### Persist migration from #376

On read, before bind:

| Stored value | Becomes |
| --- | --- |
| persona id `eagir` | `aegir` |
| shape `abzu_flow` | `code_cube` |
| shape `root_coil` | `serpent_orbit` |

`ægir` resolves to `aegir` at request time and is stored as `aegir`. Unknown ids fail. After migration, `GET` returns the canonical id only.

### Apply path

New surface, not `/api/session-personality`:

- `GET /api/named-personas` → `{ "active": {…}, "personas": [ …13… ] }`
- `PUT /api/named-personas` with `{ "id": "aegir" }` (`ægir` allowed; `eagir` accepted only as the migration alias and stored as `aegir`) applies that row as the **main** persona

Each persona object includes `id`, `label`, `role`, `presence_shape_id`, `voice_profile_id` (the id actually activated), `voice_profile_requested` when Anzu’s dry fallback was used, `default_colors` (`orb`, `accent`), and the appearance block below.

On a successful main-persona apply:

1. Resolve the row, including migration and Anzu’s dry fallback.
2. Call `set_active_voice_profile_id` with the roster pack (or Anzu’s dry id).
3. Only then persist the persona id and return it.

If the profile is unknown or unavailable, do **not** persist the new id, do **not** write `windows_natural_en_v1`, and do **not** claim the new voice. Surface the catalog error (`install_required` / `tts_unavailable`). Playback from `engine_id: "system"` while the API claims a neural persona voice is a **fail**.

Persist the main persona id in settings (a dedicated field, not `presentation.avatarId` / `jarvis_base`). Process start re-applies the stored persona (default `anzu`) **including** persisted appearance overrides, so shape and voice are paired again. Re-selecting a persona restores roster shape, roster voice, and roster colours **only** when the owner asks to reset that profile. A normal select that finds existing overrides keeps them. Overrides must not replace a failed neural bind with SAPI: if an overridden `voice_profile_id` is missing, fall back to that persona’s roster pack when the roster pack is available; if the roster pack is also missing, fail closed and keep the last good neural bind.

`HudChatHome` `shapeId`:

- HexStrike suite active → `hex_aegis` (existing)
- otherwise → the active main persona’s `presence_shape_id` (`anzu` → `stormbird`)

Morph on the live cloud: `morphTo`, `uMorph` 0→1 over the current non-reduced **1.2s**. Do not remount `PresenceHost` / `HumanoidPresence`. A React `key` that includes the shape id or the persona id is a **fail**. Reduced motion (`reducedMotion === "reduce"`, or `"system"` while `prefers-reduced-motion: reduce`) snaps: `{ duration: 0, immediate: true }`.

### Shared visual states

Every persona uses one presence state machine on the RFC-0069 orb cloud. Extend `PresencePhase` and `derivePresenceSnapshot` in `frontend/src/presence/presenceState.ts`. Drive `HumanoidPresence` from that snapshot. Do not add a second canvas, a second host, or a per-persona renderer.

| State | Phase id | When (first match wins) | Visual on every shape |
| --- | --- | --- | --- |
| Offline | `offline` | `connected === false` | Dim. Broken ring. |
| Error | `error` (**new**) | `task.status === "failed"` | Irregular flicker. Warning colour, not the persona accent. |
| Waiting for approval | `approval` (**new**) | `waiting_for_confirmation` or the pending-approval queue | Locked ring + indicator. |
| Alert | `alert` | `systemDegraded` and not the two rows above | Red/orange pulse. Not the persona accent. |
| Speaking | `speaking` | TTS playing | Brightness and waveform follow `audioLevel`. |
| Listening | `listening` | recording / mic open | Ring moves toward the mic (existing attention vector). |
| Working | `executing` | `task.status === "running"` | Specialist motion in the table below. Display label **Working**. Keep the phase id `executing`. |
| Thinking | `thinking` | other non-terminal task, including queued work that is not an approval | Rotating / expanding rings. |
| Idle | `idle` | otherwise | Breathing scale. |

Today `failed`, degraded, and `waiting_for_confirmation` all become `alert`, and `deriveOrbMood` mirrors that. Split them so approval and error are visible. Queued work with no approval stays `thinking`, not the locked approval ring. The existing `waiting` phase must not be reused for approval.

Working motion (only while phase is `executing`; idle breathing remains the base layer):

| Id | Working motion |
| --- | --- |
| `anzu` | Wing arcs pulse; slow electrical sparks |
| `mestor` | Hexagonal rings rotate |
| `nabu` | Memory rings and glyph particles drift |
| `enki` | Code-lines flow along the cube |
| `veles` | Serpent orbit; intermittent shadow fractures |
| `themis` | Shield halos counter-rotate; status line ticks |
| `aegir` | Wave ripples and signal trails |
| `bragi` | Waveform rings pulse; letters drift |
| `hermes` | Twin trails and rapid particles |
| `heimdall` | Scanning rings and radar sweeps |
| `eir` | Heartbeat, leaf motifs, slower breath |
| `maia` | Social nodes orbit; signal rings expand |
| `vulcan` | Sparks, forge rings, heat shimmer |

Reduced motion snaps the morph and holds a static pose of the current state (no orbit, no flicker animation, no waveform travel). RFC-0051 still applies.

### Appearance and voice overrides

Per loaded persona profile (keyed by persona id), the owner can set:

- active persona (the main select)
- voice selection
- pitch
- speaking speed
- volume
- orb colour
- accent colour
- glow intensity
- animation intensity
- avatar / orb scale
- whether specialist personas can speak automatically (`specialists_auto_speak`, default **false**)

Selecting a persona the first time writes the roster defaults (shape, voice, colours, and the rate/pitch/glow/animation/scale numbers above). Later edits persist on that profile. They must not silently break the fail-closed voice bind:

- Voice selection may name another **available neural** pack. `windows_natural_en_v1` and any `engine_id: "system"` id are rejected; the previous neural bind stays.
- An unavailable pack does not stick and does not fall through to SAPI.
- Pitch, rate, volume, colour, glow, animation, and scale never change `voice_profile_id` by themselves.

`specialists_auto_speak` defaults **false** on every specialist. While it is false, specialist orbs are visual and the spoken line stays on the main persona’s bound neural voice. While it is true, that specialist’s own lines use that specialist’s bound pack, still fail-closed (missing pack → the line is not spoken; no SAPI; the main bind is unchanged). Anzu, as main host, speaks through the main bind; the flag does not mute Anzu.

### Product UX

- Default main interaction remains **Anzu** (main orb, main voice, `stormbird`).
- When another persona is active on a task, a specialist orb may appear beside the task card. The card uses the same shape samples at a small scale (about 72px), not a second renderer.
- Example copy, locked for the test: main `anzu` with specialists `enki` and `themis` on that task reads **“Anzu is coordinating. Enki is coding. Themis is verifying security.”**
- Function phrases, in roster order: coordinating, planning, researching, coding, analysing threats, verifying security, handling media, writing, messaging, watching, looking after the house, growing the audience, working the systems. Sentence shape: `"{Main} is coordinating."` plus `"{Label} is {phrase}."` for each specialist who is not the main persona. If the main persona is not Anzu, the first clause uses that label with **coordinating** only when Anzu is also attached; otherwise the first clause is `"{Main} is {main phrase}."` and specialists follow. The locked example above is the acceptance string.
- Attach specialists without replacing the main persona: `PUT /api/named-personas` may include `{ "id", "task_id", "as_specialist": true }`. That writes `specialist_persona_ids` on the task and does not call `set_active_voice_profile_id` unless `specialists_auto_speak` is true for that id (and the bind succeeds). Omitting `as_specialist` changes the main persona as in Apply path.
- Show the chip and sentence on the HUD task row (`frontend/src/hud/HudOpsRail.tsx`) and the HUD task detail (`frontend/src/hud/HudChatHome.tsx` caption when that task is current). This is a label and an orb. It is not a swarm router and not a new orchestrator.
- Settings: one named-persona `<select>` lists all 13. Copy says **shape and voice travel together**. Mount it from Appearance (`AppearanceSettingsPane`, which the HUD Appearance menu already hosts). Do not turn `SessionPersonalityControls` into this catalog.
- Keep the session-mode control. Its copy stays about coding / research / concise accents. It must not say it changes the figure or the voice.
- The Voice menu may still list packs. Choosing a named persona still sets both. A later voice pick is the per-persona override above.

### Red Team and Blue Team

Veles and Themis are the persona labels Taco gave for Red Team (threat intelligence and adversarial analysis) and Blue Team (defence, policy, and auditing) **as presence and voice**. This RFC does not add law-enforcement gates, ATO gates, officer roles, exploit recipes, payloads, or offensive tool wiring. HexStrike suite behaviour, RFC-0105, and RFC-0106 stay as they are.

### What a failed implement looks like

- Binding `core`, `coding`, `research`, or `concise` to a shape or a voice.
- Treating HexStrike / Daybreak / `hex_aegis` as a fourteenth persona, or changing voice when the suite toggles.
- Keeping `eagir` as a catalog id, or keeping the four-name table as the catalog.
- Leaving Enki on `abzu_flow` or the tactical aide, or leaving Veles on `root_coil` as the canonical shape.
- A `tts_voice_hint` (including `"jarvis-default"`) used as the persona voice signal.
- Accent CSS with no `shapeId` change on persona select.
- Morph by remount (pop) instead of `uMorph`.
- Reduced motion still tweening.
- `windows_natural_en_v1` or any `engine_id: "system"` playback while a neural persona voice is claimed, including as a pitch or rate stand-in.
- A missing Mestor/Nabu/Enki/Veles/Themis/Aegir/Bragi/Hermes/Heimdall/Eir/Maia/Vulcan pack that activates a different neural pack or SAPI.
- An appearance override that persists `windows_natural_en_v1` or drops a failed bind onto SAPI.
- A persona shape with no shared states (idle through error).
- A second presence renderer for specialists or for states.
- A merged RFC-0104 tree, a rewritten RFC-0106 operator surface, new voice-pack files, or shape/voice strings that trip `contains_forbidden_ip_term`.
- LE / ATO / officer gates or offensive tool wiring added for Veles or Themis.

## Acceptance criteria

- [ ] Catalog is exactly the 13 ids in roster order. `ægir` resolves to `aegir`. Stored `eagir` migrates to `aegir` and is not returned as its own row. Unknown ids fail.
- [ ] Fresh install and a missing stored id activate `anzu` → `stormbird` + `butler_original_v1` (dry butler only under the documented fallback, and `voice_profile_id` is the pack actually set).
- [ ] Each row binds the shape and voice in the catalog table, including Enki → `code_cube` + `synthetic_command_original_v1`, Veles → `serpent_orbit` + `synthetic_command_original_v1`, Aegir → `ocean_swell` + `chatterbox_expressive_en_v1`. Stored `abzu_flow` and `root_coil` migrate on read.
- [ ] `PUT /api/named-personas` calls `set_active_voice_profile_id` and persists the main id only after the voice bind succeeds. A missing required pack for any persona other than Anzu’s dry fallback leaves the previous persona in place and does not activate SAPI or a different neural pack.
- [ ] Shared visual states exist for every persona: idle (breathing), listening (ring toward mic), thinking (rotating/expanding rings), working (`executing`, specialist motion), speaking (brightness/waveform follows TTS), alert (red/orange pulse), waiting for approval (`approval`, locked ring), offline (dim + broken ring), error (irregular flicker + warning colour). They run on the existing orb cloud.
- [ ] Appearance overrides (voice, pitch, speaking speed, volume, orb colour, accent colour, glow, animation intensity, orb scale, `specialists_auto_speak`) persist per persona. They do not write SAPI. Pitch and rate are applied on the neural audio path.
- [ ] `PUT /api/session-personality` and phrase detect do not change `shapeId` and do not call `set_active_voice_profile_id`. Existing `tests/test_session_personality.py` assertions still pass.
- [ ] The Appearance persona select lists all 13, updates shape and voice together, and its copy says they travel together. The session-mode select does not.
- [ ] With main `anzu` and specialists `enki` and `themis` on a task, the card copy is “Anzu is coordinating. Enki is coding. Themis is verifying security.” and the main shape stays `stormbird` while `specialists_auto_speak` is false.
- [ ] Shape change animates `uMorph` on the existing cloud. Reduced motion snaps. No remount key on shape or persona id.
- [ ] With the HexStrike suite profile active, `shapeId` is `hex_aegis` and the persona voice is left as already bound. Suite off returns the persona figure. RFC-0106 payloads unchanged.
- [ ] Silhouettes are orb samples in `buildFigure` only.
- [ ] `python3 -m pytest` including new `tests/test_rfc0137_named_persona.py`. Stub catalog availability so cloud pytest does not speak. Assert the id passed into `set_active_voice_profile_id` for all 13 rows and for Anzu’s dry fallback. Assert a missing non-Anzu pack does not write `windows_natural_en_v1`. Assert a session-mode change does not. Assert the migration map and the card sentence.
- [ ] `npm --prefix frontend run build` and `npm --prefix frontend run lint`.

Live listening and a GPU capture of the morph are Windows desktop sign-off.

## Likely files

| Area | Paths |
| --- | --- |
| Backend | **New** `backend/app/persona/named_persona.py` (13-row map, migration, apply, per-persona appearance, specialist attach). **New** route module wired from `backend/app/main.py` at `/api/named-personas`, **or** a small router beside `backend/app/api/session_personality.py` that does not change that module’s contract. Call `set_active_voice_profile_id` from the main-persona apply only. **Do not** add shape or voice fields to `SessionMode`. Pitch/rate/volume on the neural PCM path in `backend/app/tts/synthesize.py` (no SAPI branch for these personas). |
| Frontend | `frontend/src/presence/renderers/shapes/` — `stormbird.ts`, `commandFacet.ts`, `memoryRings.ts`, `codeCube.ts`, `serpentOrbit.ts`, `twinShield.ts`, `oceanSwell.ts`, `waveformLetters.ts`, `cometTrail.ts`, `eyeRadar.ts`, `breathLeaf.ts`, `starSocial.ts`, `forgeCore.ts`. `catalog.ts` (`registerPresenceShape`). `frontend/src/presence/presenceTypes.ts` and `presenceState.ts` (add `approval` and `error`; working stays `executing`). `HumanoidPresence.tsx` (shared state visuals + persona colour/glow/scale). `frontend/src/hud/HudChatHome.tsx` (`shapeId`: suite `hex_aegis`, else the main persona). `frontend/src/hud/HudOpsRail.tsx` (specialist orb + sentence). **New** named-persona select and appearance overrides mounted from `frontend/src/settings/AppearanceSettingsPane.tsx`. Do not turn `SessionPersonalityControls` into the persona catalog. Do not set a React `key` from the shape or persona id. |
| Tests | `tests/test_rfc0137_named_persona.py`. Leave `tests/test_session_personality.py` green without shape assertions. |
| Docs | This RFC. §59 Decision line only. Do not add a §58 checkbox. |

## Out of scope

- Wiring RFC-0126 / RFC-0130 modes to these personas. Chat phrases such as “start a coding session” stay mode switches.
- A HexStrike / Daybreak persona, or a suite voice bind. Rewriting RFC-0106.
- A fourteenth name, or restoring `eagir` / `abzu_flow` / `root_coil` as canonical ids.
- New voice-pack files, speaker retargets, or a pack per persona. A later voice-pack RFC may add original packs if a shared archetype is still too close. Not this ticket.
- RFC-0115 Ornith / model-handoff files.
- RFC-0104 merges and anything under `projects/persona/`.
- Mesh / GLTF gods, licensed art, or a new avatar gallery. `avatarId` `jarvis_base` stays the unknown-id bust fallback.
- LE / ATO / officer gates, exploit recipes, offensive tool wiring. Swarm, Browser Use, model-stack work. Automatic assignment of specialists from tool names (attach is explicit via the API above).

## Recommended implement model

Taco named this implement ticket for **Grok 4.7** with **fast=false** (standard, not Fast). Other tickets stay on Composer 2.5 standard. The launch prompt should name this file only.

## Notes

Desktop sign-off: hear each bound pack once (shared packs still once each, then confirm pitch/rate differ for Veles vs Enki, Themis vs Mestor, Eir vs Nabu, Bragi vs Aegir, Hermes vs Aegir, Vulcan vs Enki), and watch a morph across several personas without a pop. With reduced motion on, the same switches snap and state motion holds still. Switching coding / research / concise does not move the figure or the voice. HexStrike profile on shows `hex_aegis` and keeps the current persona voice; profile off returns the persona figure. A missing Chatterbox install fails Aegir, Bragi, Hermes, and Maia closed.

#376’s four-name decision in §59 is superseded by the amendment decision recorded with this amend. Do not implement from the #376 table.
