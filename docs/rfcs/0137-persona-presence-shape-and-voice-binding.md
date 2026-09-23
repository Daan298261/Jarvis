# RFC-0137: Named persona presence shape and original voice binding

**Status:** accepted  
**Queue item:** (none — no new §58 checkbox)  
**Author:** Jarvis Architect  
**Date:** 2026-09-23

**Related (do not rewrite):** [RFC-0126](0126-personality-session-modes.md) and [RFC-0130](0130-session-personalities.md) stay **session modes** (HUD accent + prompt). They are not this catalog. [RFC-0069](0069-presence-shape-catalog-and-morph-api.md) (**implemented** — `registerPresenceShape`, `uMorph`). [RFC-0051](0051-humanoid-presence-runtime.md) (reduced motion). [RFC-0062](0062-selectable-voice-profile-catalog.md) / [RFC-0092](0092-neural-tts-default-no-silent-sapi.md) (original packs; no silent SAPI). [RFC-0078](0078-hexstrike-cyber-suite.md) already morphs to `hex_aegis` when the HexStrike suite profile is selected. [RFC-0106](0106-hexstrike-jarvis-full-operator-control.md) operator contract stays. [RFC-0104](0104-persona-candidates-pack.md) stays an unmerged hold.

**Numbering:** On `development` @ `62a87df`, the highest RFC id in `docs/rfcs/` is **0136**. **0137** is the next free id. Do not take ≤0136.

**Correction:** The first draft of this RFC bound `core` / `coding` / `research` / `concise`. That was wrong. Taco (via CoS): those session modes stay separate unless Taco later ties a mode to a named persona. This catalog is **named mythic personalities only**.

This PR is **specs-only**. Product code is a **named follow-up**. Full intent; **no stubs / soft-fail**. No LE / Red / Purple / ATO gates. No exploit recipes. Do not edit the RFC-0115 implement tree. Do not merge RFC-0104 `persona_candidate` trees.

## Problem

Jarvis has no selectable named persona. The presence figure does not change when the owner picks who Jarvis is, and the speaking voice does not change with that choice.

What exists on tip (`62a87df`), and what it is **not**:

- Session modes in `backend/app/persona/session_personality.py` are `core` (HUD label **Anzu / Core**; aliases `default` / `jarvis` / `anzu`), `coding`, `research`, and `concise`. They set `hud_theme`, a dialogue preset, and a prompt addendum. `coding` also stores `tts_voice_hint` `"jarvis-default"`, which is not a voice-pack id. `set_active_mode` does not call `set_active_voice_profile_id`. `GET`/`PUT /api/session-personality` and `POST /detect` only switch that mode. Settings copy in `frontend/src/personality/SessionPersonalityControls.tsx` is this mode list. **Leave this surface as HUD + prompt.** Do not hang presence or voice off it.
- A search of `docs/`, `JARVIS_MASTER_PLAN.md`, `backend/app/persona/`, RFC-0061, RFC-0104, and Settings / avatar strings found **no fuller Taco list**. The only in-tree name is that session-mode label “Anzu / Core”. RFC-0104 is a hold on third-party assistant repos, not a mythic roster. This catalog is therefore **exactly** the four names Taco gave: **Anzu, Eagir, Veles, Enki**. Do not add further gods from those pantheons in this ticket.
- Presence shapes in `frontend/src/presence/renderers/shapes/catalog.ts` are `humanoid_bust` (default; `avatarId` `jarvis_base`), `energy_core`, and `hex_aegis`. New figures join through `registerPresenceShape`. Morph is `frontend/src/presence/renderers/morphableOrbCloud.ts`: `uMorph` lerps figure samples 0..1. `HumanoidPresence` calls `morphTo` in the frame loop (`duration: 1.2`, or `immediate` when reduced motion is on). Remounting the cloud pops.
- `frontend/src/hud/HudChatHome.tsx` passes `shapeId` only while the HexStrike suite profile is selected (`hex_aegis` from RFC-0069 / RFC-0078). That suite shape **stays**. It is not a persona. This RFC does not give Daybreak a persona row and does not bind a suite voice.
- Original packs on disk (do not retarget `speaker_ref`):

| `voice_profile_id` | `display_name` | `engine_id` |
| --- | --- | --- |
| `butler_original_v1` | Household butler (original) | `kokoro` (`bm_george`) |
| `chatterbox_expressive_en_v1` | Household butler (expressive) | `chatterbox` |
| `dry_butler_original_v1` | Dry household butler (original) | `kokoro` (`bm_lewis`) |
| `tactical_aide_original_v1` | Tactical soft-spoken aide (original) | `kokoro` (`af_bella`) |
| `synthetic_command_original_v1` | Cold synthetic command (original) | `kokoro` (`am_michael`) |
| `windows_natural_en_v1` | Windows system (SAPI) | `system` |

`set_active_voice_profile_id` rejects an unknown or unavailable pack. RFC-0092 forbids SAPI audio while a neural profile was requested, and forbids preferring `windows_natural_en_v1` as a persona voice. `ip_guard.py` still rejects Codsworth, Cortana, Ultron, Fallout, Marvel, Disney, Iron Man, and the related strings. This RFC does not weaken that list and does not add those characters.

## Decision

A **named persona** is one of Anzu, Eagir, Veles, Enki. Selecting it sets `presence_shape_id` and `voice_profile_id` together and morphs the existing orb cloud. Reduced motion snaps.

Session modes do not select a persona, do not change `shapeId`, and do not call `set_active_voice_profile_id`. A later Taco request may tie a mode to a name. This RFC does not.

Ids are the lowercase Taco spellings: `anzu`, `eagir`, `veles`, `enki`. Display labels are Anzu, Eagir, Veles, Enki. Accept `aegir` and `ægir` as aliases of `eagir` only (Old Norse Ægir). Do not add another id.

Figures are particle samples in `buildFigure` (the layer `uMorph` lerps). `buildField` may add loose orbs; it is not the silhouette, because field geometry swaps instead of lerping. No mesh, no texture, no copyrighted creature. Wings, crest, coil, or reeds must read at HUD framing distance (`HudChatHome` size 760).

`chatterbox_expressive_en_v1` stays the owner’s explicit expressive pick (RFC-0092). It is not one of these four bindings. `windows_natural_en_v1` is never a persona voice and never a silent stand-in.

`humanoid_bust` remains the figure only when the persona id is missing or unknown. The default persona, when none is stored, is **`anzu`**.

While the HexStrike suite profile is active, the existing `hex_aegis` `shapeId` override stays in front of the persona figure. Turning the suite off morphs back to the selected persona’s shape. Suite on/off does **not** change the voice. Do not rewrite RFC-0106.

### Catalog

| Id | Origin (why this figure and voice) | Presence shape id | Visual intent | `voice_profile_id` | Display archetype |
| --- | --- | --- | --- | --- | --- |
| `anzu` | Mesopotamian Anzû: the lion-headed storm bird. Taco’s example is fixed: stormbird + household butler. | **`stormbird`** (NEW) | Thousands of glowing orbs flow into a stormbird silhouette. Wings and beak readable. | `butler_original_v1`. If that pack is unavailable **and** `dry_butler_original_v1` is available, activate the dry pack and report that id. If neither is available, the bind **fails**. | Household butler (original). Dry fallback: Dry household butler (original). |
| `eagir` | Old Norse **Ægir** (Taco spelling Eagir): jötunn of the ocean, host of the gods’ feast under the waves, brewer of ale. Deep calm host, not a tactical aide and not the world-serpent. | **`ocean_swell`** (NEW) | A rising swell: crest and trough readable. Brighter loose orbs along the crest read as foam. The swell is the silhouette. | `dry_butler_original_v1`. No other pack. | Dry household butler (original) |
| `veles` | Slavic Veles (also Volos): chthonic god of cattle, wealth, magic, and the underworld, often the serpent or dragon in the roots and wet earth, opposite the sky thunder-god. Colder than a household host. | **`root_coil`** (NEW) | A low earth-and-root mass with a serpent coil rising out of it. The coil reads in profile. Particle samples only — not a dragon mesh. | `synthetic_command_original_v1`. No other pack. | Cold synthetic command (original) |
| `enki` | Sumerian Enki: god of the freshwater Abzu, wisdom, crafts, and the *me* (the arts of civilization). Measured counsel, not a theatrical aside and not the cold underworld. | **`abzu_flow`** (NEW) | Vertical reed strokes and horizontal freshwater streams of orbs, plus a tighter bright cluster for the wisdom accent. Reads as water and reeds, not a statue. | `tactical_aide_original_v1`. No other pack. | Tactical soft-spoken aide (original) |

Voice choices, so implementers do not swap the “or” pairs:

- **Eagir → dry butler, not tactical aide.** Ægir receives the gods. `dry_butler_original_v1` (`bm_lewis`, understated) is the deep calm host. The tactical aide is an operations register and is reserved for Enki so the four voices stay distinct.
- **Veles → cold synthetic, not dry butler.** A second butler would make the underworld sound like the sea host. `synthetic_command_original_v1` is the cold, humourless pack.
- **Enki → tactical aide, not Chatterbox.** Enki’s freshwater wisdom is precise counsel. `tactical_aide_original_v1` is that calm Kokoro voice. Chatterbox stays an owner override in the Voice menu after the persona is applied; selecting Enki must not require the Chatterbox install.

No cross-persona substitute except Anzu’s single dry-butler fallback above. If Eagir, Veles, or Enki’s pack is missing, the bind fails. Do not activate a different neural pack and do not activate SAPI.

### Apply path

New surface, not `/api/session-personality`:

- `GET /api/named-personas` → `{ "active": {…}, "personas": [ … four … ] }`
- `PUT /api/named-personas` with `{ "id": "eagir" }` (aliases allowed) applies the row

Each persona object includes `id`, `label`, `presence_shape_id`, `voice_profile_id` (the id actually activated), and `voice_profile_requested` when Anzu’s dry fallback was used.

On a successful apply:

1. Resolve the row, including Anzu’s dry fallback.
2. Call `set_active_voice_profile_id` with that id.
3. Only then persist the persona id and return it.

If the profile is unknown or unavailable, do **not** persist the new id, do **not** write `windows_natural_en_v1`, and do **not** claim the new voice. Surface the catalog error (`install_required` / `tts_unavailable`). Playback from `engine_id: "system"` while the API claims a neural persona voice is a **fail**.

Persist the persona id in settings (a dedicated field, not `presentation.avatarId` / `jarvis_base`). Process start re-applies the stored persona (default `anzu`) so shape and voice are paired again. An owner may change voice from `VoiceProfilePicker` afterwards; that override lasts until the next persona apply or the next process start, which re-binds the stored persona.

`HudChatHome` `shapeId`:

- HexStrike suite active → `hex_aegis` (existing)
- otherwise → the active named persona’s `presence_shape_id` (`anzu` → `stormbird`)

Do not leave `shapeId` unset for Anzu. Unset falls through to `humanoid_bust`.

Morph on the live cloud: `morphTo`, `uMorph` 0→1 over the current non-reduced **1.2s**. Do not remount `PresenceHost` / `HumanoidPresence`. A React `key` that includes the shape id or the persona id is a **fail**. Reduced motion (`reducedMotion === "reduce"`, or `"system"` while `prefers-reduced-motion: reduce`) snaps: `{ duration: 0, immediate: true }`.

### Settings selector

Add a **named persona** control on Appearance (the pane that already mounts `SessionPersonalityControls`, and the HUD Appearance menu). One select lists Anzu, Eagir, Veles, Enki. Copy says **shape and voice travel together**.

Keep the session-mode control. Its copy stays about coding / research / concise accents. It must not say it changes the figure or the voice, and it must not be the only picker.

The Voice menu may still list packs. Choosing a named persona still sets both.

### What a failed implement looks like

- Binding `core`, `coding`, `research`, or `concise` to a shape or a voice.
- Treating HexStrike / Daybreak / `hex_aegis` as a fifth persona, or changing voice when the suite toggles.
- Adding gods beyond Anzu, Eagir, Veles, Enki.
- A `tts_voice_hint` (including `"jarvis-default"`) used as the persona voice signal.
- Accent CSS with no `shapeId` change on persona select.
- Morph by remount (pop) instead of `uMorph`.
- Reduced motion still tweening.
- `windows_natural_en_v1` or any `engine_id: "system"` playback while a neural persona voice is claimed.
- A merged RFC-0104 tree, a rewritten RFC-0106 operator surface, or shape/voice strings that trip `contains_forbidden_ip_term`.

## Acceptance criteria

- [ ] Catalog is exactly `anzu`, `eagir`, `veles`, `enki`. `aegir` / `ægir` resolve to `eagir`. Unknown ids fail. No fifth name.
- [ ] `anzu` → `stormbird` + `butler_original_v1` (dry butler only under the documented fallback, and `voice_profile_id` is the pack actually set).
- [ ] `eagir` → `ocean_swell` + `dry_butler_original_v1`. `veles` → `root_coil` + `synthetic_command_original_v1`. `enki` → `abzu_flow` + `tactical_aide_original_v1`.
- [ ] `PUT /api/named-personas` calls `set_active_voice_profile_id` and persists the id only after the voice bind succeeds. A missing Eagir/Veles/Enki pack leaves the previous persona in place and does not activate SAPI or a different neural pack.
- [ ] `PUT /api/session-personality` and phrase detect do not change `shapeId` and do not call `set_active_voice_profile_id`. Existing `tests/test_session_personality.py` assertions still pass.
- [ ] The Appearance persona select updates shape and voice together; its copy says they travel together. The session-mode select does not.
- [ ] Shape change animates `uMorph` on the existing cloud. Reduced motion snaps. No remount key on shape or persona id.
- [ ] With the HexStrike suite profile active, `shapeId` is `hex_aegis` and the persona voice is left as already bound. Suite off returns the persona figure. RFC-0106 payloads unchanged.
- [ ] Silhouettes are orb samples in `buildFigure` only.
- [ ] `python3 -m pytest` including new `tests/test_rfc0137_named_persona.py`. Stub catalog availability so cloud pytest does not speak. Assert the id passed into `set_active_voice_profile_id`. Assert a missing pack does not write `windows_natural_en_v1`. Assert a session-mode change does not.
- [ ] `npm --prefix frontend run build` and `npm --prefix frontend run lint`.

Live listening and a GPU capture of the morph are Windows desktop sign-off.

## Likely files

| Area | Paths |
| --- | --- |
| Backend | **New** `backend/app/persona/named_persona.py` (the four-row map, apply, persist). **New** route module wired from `backend/app/main.py` at `/api/named-personas`, **or** a small router beside `backend/app/api/session_personality.py` that does not change that module’s contract. Call `set_active_voice_profile_id` from the named-persona apply only. **Do not** add shape or voice fields to `SessionMode`. |
| Frontend | `frontend/src/presence/renderers/shapes/stormbird.ts`, `oceanSwell.ts`, `rootCoil.ts`, `abzuFlow.ts`. `frontend/src/presence/renderers/shapes/catalog.ts` (`registerPresenceShape`). `frontend/src/hud/HudChatHome.tsx` (`shapeId`: suite `hex_aegis`, else the named persona). **New** named-persona select mounted from `frontend/src/settings/AppearanceSettingsPane.tsx` (HUD Appearance menu picks that pane up). Do not turn `SessionPersonalityControls` into the persona catalog. Do not set a React `key` from the shape or persona id. |
| Tests | `tests/test_rfc0137_named_persona.py`. Leave `tests/test_session_personality.py` green without shape assertions. |
| Docs | This RFC. §59 Decision line only. Do not add a §58 checkbox. |

## Out of scope

- Wiring RFC-0126 / RFC-0130 modes to these personas. Chat phrases such as “start a coding session” stay mode switches.
- A HexStrike / Daybreak persona, or a suite voice bind.
- Names other than Anzu, Eagir, Veles, Enki.
- RFC-0115 Ornith / model-handoff files.
- RFC-0104 merges and anything under `projects/persona/`.
- RFC-0106 operate, catalog, MCP, jobs, loopback, or install pin.
- New voice packs, speaker retargets, Chatterbox as a bound persona voice, SAPI as a persona voice.
- Mesh / GLTF gods, licensed art, or a new avatar gallery. `avatarId` `jarvis_base` stays the unknown-id bust fallback.
- LE / Red / Purple / ATO gates. Swarm, Browser Use, model-stack work.

## Recommended implement model

Taco named this implement ticket for **Grok 4.7** with **fast=false** (standard, not Fast). Other tickets stay on Composer 2.5 standard. The launch prompt should name this file only.

## Notes

Desktop sign-off: hear each bound pack once, and watch Anzu → Eagir → Veles → Enki → Anzu morph without a pop. With reduced motion on, the same switches snap. Switching coding / research / concise does not move the figure or the voice. HexStrike profile on shows `hex_aegis` and keeps the current persona voice; profile off returns the persona figure.
