# RFC-0137: Persona presence shape and original voice binding

**Status:** accepted  
**Queue item:** (none — no new §58 checkbox)  
**Author:** Jarvis Architect  
**Date:** 2026-09-23

**Related (do not rewrite):** [RFC-0126](0126-personality-session-modes.md) (session modes, HUD accents). [RFC-0130](0130-session-personalities.md) (**implemented** — prompt addenda, research/concise, settings selector). [RFC-0069](0069-presence-shape-catalog-and-morph-api.md) (**implemented** — shape catalog, `uMorph`). [RFC-0051](0051-humanoid-presence-runtime.md) (reduced motion). [RFC-0062](0062-selectable-voice-profile-catalog.md) / [RFC-0092](0092-neural-tts-default-no-silent-sapi.md) (original packs; no silent SAPI). [RFC-0078](0078-hexstrike-cyber-suite.md) (`hex_aegis` when the suite profile is selected). [RFC-0106](0106-hexstrike-jarvis-full-operator-control.md) (**implemented** — operator contract stays). [RFC-0104](0104-persona-candidates-pack.md) stays an unmerged hold.

**Numbering:** On `development` @ `62a87df`, the highest RFC id in `docs/rfcs/` is **0136**. **0137** is the next free id. Do not take ≤0136.

This PR is **specs-only**. Product code is a **named follow-up**. Full intent; **no stubs / soft-fail**. No LE / Red / Purple / ATO gates. No exploit recipes. Do not edit the RFC-0115 implement tree in that follow-up’s sibling work, and do not merge RFC-0104 `persona_candidate` trees.

## Problem

Selectable first-party session personalities change a HUD accent and a prompt addendum. They do not change the presence figure, and they do not change the speaking voice.

Verified on tip (`62a87df`):

- `backend/app/persona/session_personality.py` defines `core` (label **Anzu / Core**; aliases `default` / `jarvis` / `anzu`), `coding`, `research`, and `concise`. `SessionMode` carries `hud_theme`, `dialogue_preset`, `system_prefix_addendum`, and optional `tts_voice_hint`. Only `coding` sets a hint, and that hint is the string `"jarvis-default"`, which is not a `voice_packs/*/profile.json` id. `set_active_mode` persists the dialogue preset. It never calls `set_active_voice_profile_id`.
- `GET`/`PUT /api/session-personality` and `POST /api/session-personality/detect` return that mode dict (`backend/app/api/session_personality.py`). Chat ingress uses `maybe_switch_from_owner_message`.
- Settings copy in `frontend/src/personality/SessionPersonalityControls.tsx` says HUD accents update and that a full presence reskin is out of scope. The HUD writes `document.documentElement.dataset.sessionMode` (`frontend/src/hud/sessionPersonality.ts`) and nothing else.
- Presence shapes registered in `frontend/src/presence/renderers/shapes/catalog.ts` are `humanoid_bust` (default; `avatarId` `jarvis_base` maps here), `energy_core` (compact orb shell, framing `{ yaw: 0.2, position: [0, 0.1, 0] }`), and `hex_aegis`. New figures join through `registerPresenceShape`. Morph is the existing orb cloud: `frontend/src/presence/renderers/morphableOrbCloud.ts` lerps `aPos`→`bPos` with shader uniform `uMorph` (0..1). `HumanoidPresence` calls `morphTo` inside the frame loop (`duration: 1.2`, or `immediate` when reduced motion is on). A remount drops the cloud (`HumanoidPresence.tsx` comment on avatarId/shapeId).
- `frontend/src/hud/HudChatHome.tsx` passes `shapeId` only while the HexStrike suite profile is selected (`hex_aegis`). Otherwise `shapeId` is omitted, so the figure stays the avatar default (`humanoid_bust`).
- Original voice packs on disk:

| `voice_profile_id` | `display_name` | `engine_id` |
| --- | --- | --- |
| `butler_original_v1` | Household butler (original) | `kokoro` (`bm_george`) |
| `chatterbox_expressive_en_v1` | Household butler (expressive) | `chatterbox` |
| `dry_butler_original_v1` | Dry household butler (original) | `kokoro` (`bm_lewis`) |
| `tactical_aide_original_v1` | Tactical soft-spoken aide (original) | `kokoro` (`af_bella`) |
| `synthetic_command_original_v1` | Cold synthetic command (original) | `kokoro` (`am_michael`) |
| `windows_natural_en_v1` | Windows system (SAPI) | `system` |

`set_active_voice_profile_id` (`backend/app/voice_profiles/catalog.py`) rejects an unknown id and an unavailable pack (`install_required` / `tts_unavailable`). It does not silently switch engines. RFC-0092 already forbids SAPI audio while a neural profile is the requested voice, and forbids preferring `windows_natural_en_v1` as a persona default. `backend/app/voice_profiles/ip_guard.py` still rejects Codsworth, Cortana, Ultron, Fallout, Marvel, Disney, Iron Man, and the related trademark strings. This RFC does not weaken that list.

## Decision

Each selectable first-party persona binds **one presence shape** and **one original voice profile**. Selecting it applies both. The figure morphs on the existing cloud. Reduced motion snaps.

Archetype **labels** below are the pack `display_name` strings already on disk. Do not invent a second marketing name. Do not add Codsworth, Fallout, Cortana, Microsoft, Ultron, Disney, Marvel, Iron Man, or F.R.I.D.A.Y clones, meshes, textures, or sample audio.

`chatterbox_expressive_en_v1` stays an explicit owner quality pick (RFC-0092). It is not a persona default. `windows_natural_en_v1` is never a persona default and never a silent stand-in.

### 1. Persona → presence shape → voice

| Persona / mode id | Presence shape id | Visual intent | `voice_profile_id` | Display archetype (`profile.json`) |
| --- | --- | --- | --- | --- |
| `core` (aliases `default`, `jarvis`, `anzu`; label Anzu / Core) | **`stormbird`** (NEW) | Thousands of glowing orbs flow into a **stormbird** silhouette. Wings and beak readable at HUD framing distance (`HudChatHome` size 760). Particle figure only: `buildFigure` samples, no mesh and no texture of a copyrighted character. Put the readable silhouette in `buildFigure` (the layer `uMorph` lerps). `buildField` may add loose particles; it is not the silhouette, because field geometry swaps instead of lerping. | `butler_original_v1`. If that pack is unavailable **and** `dry_butler_original_v1` is available, activate the dry pack and report it as the active id. If neither is available, the bind **fails**. | Household butler (original). Dry fallback display name is Dry household butler (original). |
| `coding` | **`code_lattice`** (NEW) | Orb lattice / schematic figure suggesting structured code and geometry. Same particle-figure rules. | `synthetic_command_original_v1`. No alternate pack. | Cold synthetic command (original) |
| `research` | **`research_lens`** (NEW) | Orb constellation / open-lens figure (knowledge exploration). Same particle-figure rules. | `dry_butler_original_v1`. No alternate pack. | Dry household butler (original) |
| `concise` | **`energy_core`** (existing) | Compact dense orb core. Tip framing already matches. Do **not** add `concise_core`. | `dry_butler_original_v1`. No alternate pack. | Dry household butler (original) |
| HexStrike suite / Daybreak **active** (runtime profile already detected by `useHexStrikeSuiteActive`) | **`hex_aegis`** (existing) | Keep the current HexStrike aegis figure. | `tactical_aide_original_v1`. If that pack is unavailable **and** `synthetic_command_original_v1` is available, activate synthetic and report it as the active id. If neither is available, the voice bind **fails**. The aegis figure still shows (RFC-0078). | Tactical soft-spoken aide (original). Synthetic fallback display name is Cold synthetic command (original). |
| No session shape (classic avatar; `avatarId` `jarvis_base` or unknown, and no mode payload) | **`humanoid_bust`** (existing) | Unchanged fallback figure. | Do not retarget. Active voice stays the RFC-0092 rule (`butler_original_v1` default). | — |

Register `stormbird`, `code_lattice`, and `research_lens` with `registerPresenceShape` next to the three built-ins in `catalog.ts`. Ids are exactly those strings. Labels stay original and free of `ip_guard` terms.

`energy_core` is the concise figure because its builder is already a compact shell (“Compact morph target”) with a tight framing. Reuse it.

### 2. Voice bind (no hint, no silent SAPI)

Replace `tts_voice_hint` on the session-mode contract. Coding’s `"jarvis-default"` must not survive as the voice signal.

On every successful mode apply (process start at `core`, `PUT /api/session-personality`, and `POST /detect` / `maybe_switch_from_owner_message`):

1. Resolve the row above, including the core dry-butler fallback.
2. Call `set_active_voice_profile_id` with that id (`PUT /api/voice-profiles/active` is the same function).
3. Only then commit `_active_mode` and the dialogue preset.

If the profile is unknown or unavailable, **do not** commit the mode, **do not** write `windows_natural_en_v1`, and **do not** leave the previous profile in place while the response claims the new persona voice. Surface the existing catalog error (`install_required` / `tts_unavailable`). A neural persona id that is “active” while playback is SAPI / `engine_id: "system"` is a **fail**, including the core and HexStrike fallbacks: the active id must be the pack that will actually speak.

The mode payload includes:

- `presence_shape_id` — shape to show
- `voice_profile_id` — id actually activated
- `voice_profile_requested` — mapped id when a documented fallback was used; omit or repeat `voice_profile_id` when they match

Do not retarget Kokoro `speaker_ref` values inside the packs. Do not add a pack.

HexStrike voice uses the same `set_active_voice_profile_id` call when `useHexStrikeSuiteActive().active` becomes true, and restores the **current session mode’s** voice when it becomes false. Add the voice id as a sibling of the existing `hex_aegis` shape constant (`frontend/src/hud/hexstrikeSuite.ts`, `backend/app/security/hexstrike.py` `HEXSTRIKE_SHAPE_ID` / `HexStrikeStatus.shape_id`). Do **not** change RFC-0106 operate, catalog, MCP, jobs, loopback, or install pinning.

An owner may still change voice from `VoiceProfilePicker` after a persona apply. That override lasts until the next mode apply or suite on/off, which re-binds the map. Process start applies `core` (or the suite row when that profile is selected) so a coding voice does not remain attached to the stormbird after restart. Mode storage stays in-process, as in RFC-0126; this RFC does not add a new persistence file.

### 3. Smooth morph on selection

`HudChatHome` must pass a `shapeId` whenever humanoid presence is up:

- suite active → `hex_aegis`
- otherwise → the active mode’s `presence_shape_id` (Anzu/core is `stormbird`, not “omit and hope `avatarId` stays the bust”)

`HumanoidPresence` already morphs when `shapeId` changes. Keep that path: `morphTo` on the live `morphableOrbCloud`, `uMorph` animated from 0 to 1 (current non-reduced duration **1.2s**). Do not remount `PresenceHost` / `HumanoidPresence`. A React `key` that includes the shape id is a **fail** (the cloud pops).

Reduced motion (`settings.reducedMotion === "reduce"`, or `"system"` while `prefers-reduced-motion: reduce`) keeps the existing snap: `morphTo(..., { duration: 0, immediate: true })`. Do not add a second tween that ignores RFC-0051 / RFC-0069.

Chat phrases that switch mode must morph too, because they call the same apply path and the HUD already refreshes session personality. Accent CSS (`data-session-mode`) may stay. It is not the presence change.

### 4. Settings selector

`SessionPersonalityControls` (Appearance settings, also mounted from the HUD Appearance menu in `AppearancePresenceControls`) remains the persona control. One select is enough. Its copy must say that **shape and voice travel together**. Remove the sentence that says a presence reskin is out of scope.

The Voice menu may keep listing packs. Choosing a persona still sets both. Do not add a second persona dropdown that changes only the accent.

There is no separate avatar gallery on tip. `presentation.avatarId` `jarvis_base` remains the `humanoid_bust` fallback when no session shape is applied. The live HUD figure is the `shapeId` prop from §3, which wins over `avatarId`.

### 5. What a failed implement looks like

Any of these is a **fail** (do not merge the implement PR):

- Accent-only theme (`data-session-mode` / HUD class) with no `presence_shape_id` change.
- A `tts_voice_hint` (or any other string) that does not call `set_active_voice_profile_id`.
- Morph implemented by remounting the presence tree (pop) instead of `uMorph`.
- Reduced-motion path that still tweens.
- `windows_natural_en_v1` or any `engine_id: "system"` playback while the UI or API claims a neural persona voice, including after a missing-pack error.
- A new `concise_core` shape, a rewritten RFC-0106 operator surface, or a merged RFC-0104 tree.
- Shape art or voice ids that trip `contains_forbidden_ip_term`.

## Acceptance criteria

- [ ] `core` / `anzu` / `default` / `jarvis` resolve to shape `stormbird` and voice `butler_original_v1` (dry butler only under the §2 fallback, with `voice_profile_id` equal to the pack actually set).
- [ ] `coding` → `code_lattice` + `synthetic_command_original_v1`. `research` → `research_lens` + `dry_butler_original_v1`. `concise` → `energy_core` + `dry_butler_original_v1`.
- [ ] HexStrike suite active → `hex_aegis` + `tactical_aide_original_v1` (synthetic only under the §2 fallback). Suite off restores the session mode’s shape and voice. RFC-0106 routes and payloads are unchanged.
- [ ] `PUT` and phrase detect both call `set_active_voice_profile_id`. A missing pack leaves the previous mode in place and does not activate `windows_natural_en_v1`.
- [ ] `tts_voice_hint` is gone from the mode contract. `"jarvis-default"` is not returned.
- [ ] Selecting a mode in `SessionPersonalityControls` updates shape and voice together; the note says they travel together.
- [ ] Shape change animates `uMorph` on the existing cloud. Reduced motion snaps. No remount key on the shape id.
- [ ] `stormbird` wings and beak are built only as orb samples in `buildFigure`.
- [ ] `python3 -m pytest` (extend `tests/test_session_personality.py`; add `tests/test_rfc0137_persona_presence_voice.py`). Stub catalog availability in unit tests so cloud pytest does not need a live Kokoro speak. Assert the id passed into `set_active_voice_profile_id`. Assert a missing pack does not write the SAPI id. Keep the existing prompt-addendum assertions.
- [ ] `npm --prefix frontend run build` and `npm --prefix frontend run lint`.

Live listening and a GPU frame capture of the stormbird morph are Windows desktop sign-off. Cloud pytest does not speak and does not require WebGL pixels.

## Likely files

| Area | Paths |
| --- | --- |
| Backend | `backend/app/persona/session_personality.py` (shape + voice ids; call `set_active_voice_profile_id`; drop `tts_voice_hint`). `backend/app/api/session_personality.py` (payload already returns `as_dict`). `backend/app/security/hexstrike.py` (voice id constant beside `HEXSTRIKE_SHAPE_ID` only). |
| Frontend | `frontend/src/presence/renderers/shapes/stormbird.ts`, `codeLattice.ts`, `researchLens.ts`. `frontend/src/presence/renderers/shapes/catalog.ts` (`registerPresenceShape`). `frontend/src/hud/HudChatHome.tsx` (`shapeId` for mode and suite). `frontend/src/hud/hexstrikeSuite.ts` (suite voice id; apply on active edge). `frontend/src/personality/SessionPersonalityControls.tsx` (copy). `frontend/src/hud/sessionPersonality.ts` (type fields). Do not set a React `key` from the shape id on `PresenceHost` / `HumanoidPresence`. |
| Tests | `tests/test_session_personality.py`, `tests/test_rfc0137_persona_presence_voice.py`. Voice cases belong with `tests/test_voice_profiles.py` only if they assert this map’s call into `set_active_voice_profile_id`. |
| Docs | This RFC. §59 Decision line only. Do not add a §58 checkbox. |

## Out of scope

- RFC-0115 Ornith router / model handoff files. Do not edit them in the implement PR.
- RFC-0104 `persona_candidate` merges, and any cloned assistant under `projects/persona/`.
- RFC-0106 operator contract (catalog, MCP, `/api/hexstrike` operate, jobs, loopback, install pin).
- Rewriting RFC-0118, RFC-0092, RFC-0069, RFC-0126, or RFC-0130.
- New voice packs, speaker retargets, Chatterbox as a persona default, SAPI as a persona default.
- A new avatar gallery, `concise_core`, mesh/GLTF characters, or licensed creature assets.
- LE / Red / Purple / ATO gates. Swarm, Browser Use, model-stack work.
- Persisting session mode to disk (still in-process). A later RFC may persist it; this ticket must not block on that.

## Recommended implement model

Taco named this implement ticket for **Grok 4.7** with **fast=false** (standard, not Fast). Other tickets stay on the Composer 2.5 standard default. The implement launch prompt should say Grok 4.7, fast=false, and should name this file only.

## Notes

Desktop sign-off: hear each bound pack once, and watch Anzu → coding → research → concise → Anzu morph without a pop. With reduced motion on, the same switches snap. HexStrike profile on morphs to `hex_aegis` and speaks the tactical pack; profile off returns to the session figure and voice.
