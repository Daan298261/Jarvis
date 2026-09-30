# RFC-0195: Visual acceptance — viewport presence, humanoid rest, one stage

**Status:** accepted  
**Queue item:** (none — no new §58 checkbox required; implement is a named UX/Desktop follow-up after CoS merges this PR)  
**Author:** Taco / Chief of Staff via Cursor cloud (specs only)  
**Date:** 2026-09-30  
**Quality bar:** **Anzu 1.0**. Full intent. No stubs / soft-fail.

**This RFC is the visual acceptance contract.** It does not add a new presence feature. It supersedes conflicting idle, framing, and mode rules so implementers cannot soft-fail to a small capped stage or an anonymous idle cloud.

**Related (do not rewrite wholesale):** [RFC-0050](0050-ui-v3-presence-architecture.md), [RFC-0051](0051-humanoid-presence-runtime.md), [RFC-0069](0069-presence-shape-catalog-and-morph-api.md), [RFC-0136 APEX orb-and-graph](0136-apex-ui-presence-option.md), [RFC-0137](0137-persona-presence-shape-and-voice-binding.md), [RFC-0138](0138-anzu-orb-custom-ui-generation.md), [RFC-0175](0175-galaxy-presence-option-chat-waveform-and-advanced-controls.md), [RFC-0176](0176-shared-dot-appearance-profiles.md), [RFC-0177](0177-shared-dot-persona-motion-cues.md), [RFC-0178](0178-adaptive-dot-rendering-and-framing.md), [RFC-0194](0194-restore-presence-idle-and-framing.md). Settings IA is a sibling amend on [RFC-0094](0094-settings-menu-information-architecture.md) / [RFC-0113](0113-admin-settings-submenu-1-4.md), not this file.

**Implement lane:** UX + Desktop soak. **Recommended implement model:** **Grok 4.6** (standard, not Fast) for silhouette / framing / bloom. Other tickets stay on Composer 2.5 unless named.

This PR is **specs-only**. No `frontend/` / `backend/` product code. Desktop soak acceptance boxes stay **unchecked**. Do **not** mark this RFC implemented from unit tests or a Linux cloud screenshot.

---

## Supersession (read this first)

| Prior rule | Where it lived | This RFC |
| --- | --- | --- |
| Idle / waiting / offline → `uMorph` 0 free-float cloud that is **not** a preformed bust (Ref A anonymous cloud) | RFC-0175 Amend 2026-09-25 § Lifecycle items 1–2, `uMorph` 0 = free-float; RFC-0194 Decision 1 and AC `lifecycleMorphTarget("idle") === 0` | **Overrides.** Rest state is a **recognizably humanoid (or winning-figure) silhouette**. Idle may loosen motion and density. Idle must **not** dissolve identity into an anonymous free cloud. |
| Neural / Humanoid presence host locked to **~680∶480** aspect, centered, `width: min(100%, 920px)` as the primary stage | RFC-0194 Decision 3 and AC “Neural presence host keeps ~680:480”; `humanoid-presence.css` / `apex-presence.css` 920×680∶480 | **Overrides as the primary stage contract.** Keep **crop-protection** (AABB span + geometric center from RFC-0194 Decision 2). The canvas **fills the available presence viewport**. HUD chrome overlays; it does not steal avatar space. |
| Neural / Humanoid / Particle bust / Galaxy / “APEX” as competing stage concepts (separate aspect boxes, separate bodies, APEX as the humanoid reference) | RFC-0050 mode cards; RFC-0175 Appearance row; RFC-0136 label without the “not the private humanoid” owner lock in product copy | **Overrides.** One shared WebGL renderer + style/profile controls with **accurate previews**. APEX is the **public orb-and-graph** look only ([RFC-0136](0136-apex-ui-presence-option.md) already excludes the private APEX humanoid). |
| RFC-0175 Ref A mood board as the live idle product target | RFC-0175 Visual acceptance targets table | **Overrides for idle.** Ref A remains a historical mood board. It is **not** permission to hide the persona at rest. Ref B still informs the **engaged** lattice. Ref C still informs the Galaxy **field ADD**. |
| Persona selector cards / specialist marks as static SVG samples alone (`SpecialistShapeMark`) | Product; not previously forbidden | **Overrides for selector cards.** Cards must use deterministic thumbnails from the **same WebGL shape + appearance-profile contract**. Static symbolic marks may sit beside a thumbnail; they are not the thumbnail. |
| Side-injected **Umi** reusing Nabu `memory_rings` | Product `named_persona.py` / `namedPersonas.ts` (not in the RFC-0137 13-row table) | **Overrides.** Umi must ship a unique ocean / Opus-inspired silhouette. Reusing `memory_rings` is a **fail**. Does **not** rewrite the canonical 13-count of RFC-0137. |

**What RFC-0194 still owns (not superseded):** AABB fit scale in [0.45, 1.35], geometric-center offset so the silhouette sits on the camera look-at, yaw-frame fit offset harden, Galaxy as an ADD star layer (not a lifecycle gate). Crop-protection intent stays.

**What RFC-0175 still owns (not superseded):** Galaxy as an Appearance ADD (default `neural`), chat voice waveform fail-closed on real TTS/STT, per-tab Advanced disclosures, figure/field/star **budgets**, HexStrike `hex_aegis` override, one continuous presence (not three owner-picked looks), pointer / camera attract with fail-closed privacy (RFC-0050). Engage still **morphs / tightens**. The waveform and Advanced lands stay implemented.

**Statuses stay honest.** RFC-0175 and RFC-0194 remain **implemented** for the lands they shipped. This file is **accepted**. Desktop GPU / live WebGL soak against **this** contract stays residual until Taco Desktop signs it. Cloud VMs cannot sign it off.

---

## Problem

Owner intent on the glass is a **viewport-filling, identifiably humanoid presence**. Tip after RFC-0194 (#466) restored the RFC-0175 idle free-float and re-capped Neural/Humanoid to a **920px / 680∶480** stage so the bust would not crush. That crop-protection was right; the **primary stage** and **idle identity** were wrong:

1. **Idle hides the persona.** `lifecycleMorphTarget("idle") === 0` dissolves the winning figure into an anonymous cloud. At rest the owner cannot tell Anzu from Mestor from Nabu. Attract-to-pointer is allowed; erasing identity is not.
2. **The stage is a postage stamp.** HUD chrome and a 680∶480 aspect lock leave a small capped WebGL box while the orb zone is large. That is not “presence.”
3. **Readable silhouette lost to glow.** A Desktop capture of **Mestor** read as an overexposed slab despite **165 FPS / ~94k particles**. High FPS and high particle count are **not** acceptance if the silhouette is unreadable.
4. **Modes compete.** Classic / Neural / APEX / Humanoid / Particle bust / Galaxy present as alternate stages rather than one renderer with style/profile controls. APEX is easy to misread as the private humanoid reference RFC-0136 already forbade.
5. **Cards lie.** Persona selector tiles use static SVG samples (`SpecialistShapeMark`) that are not the live WebGL shape + profile.
6. **Umi clones Nabu.** Side-injected Umi binds `memory_rings`. Owner-facing uniqueness fails.

A Linux-green unit test that asserts `idle === 0` or `aspect-ratio: 680 / 480` is **not** this contract.

---

## Decision

### 1. Rest state is a humanoid silhouette

Every mounted presence avatar (Neural profile, Humanoid profile, Particle-bust profile, Galaxy ADD, HexStrike host, RFC-0137 persona shapes, RFC-0138 presets, side-injected **Umi**) keeps a **recognizably humanoid — or winning-figure — silhouette at rest**.

**Idle / waiting / offline (rest):**

- The winning `buildFigure` (shape precedence unchanged: suite → `hex_aegis`; else active RFC-0138 preset; else RFC-0137 / Umi shape; else `humanoid_bust`) remains **readable as that identity**.
- Motion and density **may loosen**: slower drift, slightly more field falloff, lower clump tightness, dimmer amber core than engage. This is rest, not dissolve.
- Pointer / face attract (RFC-0050 / RFC-0051 / RFC-0175 attract contract) may **bias** the cloud toward the pointer or a live face sample. Attract must not drive rest to an anonymous free cloud that erases the silhouette.
- Reduced motion and `attentionMode: "off"` hold a **static readable pose** of the rest silhouette. They do not hide the figure.

**Engage (thinking, listening, speaking, executing, alert, error, approval):**

- The same orbs **morph / tighten** into the engaged lattice (Ref B language for `humanoid_bust`; otherwise the winning figure at full tightness).
- Returning to rest **loosens** the morph; it does **not** reverse to `uMorph` 0 identity-hide.

**Morph contract (amends RFC-0175 / RFC-0194 idle rule; does not invent a second uniform):**

- Keep RFC-0069 `uMorph` lerp on the existing morphable orb cloud. No second canvas, mesh, or GLTF.
- Rest phases must **not** target `uMorph` 0 as the product rest. Rest targets a **rest tightness** in **[0.72, 0.92]** (implement picks one documented constant in that band; tests lock it). Engaged phases target **1.0**.
- RFC-0194 AC `lifecycleMorphTarget("idle") === 0` is **void**. Tests that require idle `=== 0` must change to the rest-tightness constant.
- Non-reduced morph duration stays 1.2s. Reduced motion snaps.

**Fail:** idle that looks like a nameless dust field; a pre-baked PNG; a yaw-only bust that is the wrong persona; a morph that only runs when Galaxy is selected; restoring Ref A as the live idle.

### 2. One viewport-filling WebGL stage

**Primary stage contract (overrides RFC-0194 Decision 3):**

- There is **one** presence stage. It fills the **available presence viewport** (HUD `.hud-orb-zone` or the equivalent host). Width and height follow the host box.
- **Forbidden as the primary contract:** `width: min(100%, 920px)`, `aspect-ratio: 680 / 480` (or 680∶480 centering that letterboxes a small canvas inside a large orb zone), a second capped inner stage for Neural vs Humanoid.
- HUD chrome (left-bar menus, captions, Galaxy status pill, HexStrike suite) **overlays** the stage. Overlay must not shrink the canvas allocation (“steal avatar space”).
- Classic `requestedPresence: "none"` still has no canvas. If a Classic surface actually mounts a presence avatar, that avatar uses this same stage contract.

**Crop-protection (kept from RFC-0194 Decision 2):**

- Fit uses AABB span + geometric center offset (not origin-symmetric `2 * max(|min|, |max|)`).
- Silhouette centers on the camera look-at / framing position.
- Scale stays in a documented safe band (RFC-0194 [0.45, 1.35] unless a viewport-fill pass needs a documented widening; widening must not recrop identity off-frame).
- Yaw-frame fit offset harden stays.

**Readable silhouette first, then FPS (overrides “high particle count / high FPS = done”):**

- Framing, bloom, and particle alpha are optimized so a stranger can name the persona from a still of the **rest** silhouette at HUD distance.
- **Mestor at 165 FPS / ~94k particles that reads as an overexposed slab fails acceptance.** Particle count and FPS are supporting evidence, not the bar.
- Bloom / emission / point scale (RFC-0176 profile) must preserve edge contrast. A wash of white/blue that erases `command_facet` hexagonal rings is a fail.
- RFC-0178 auto tiers may drop density, bloom, or pixel ratio under frame-time hysteresis. They **must not** change the selected persona, and they **must not** “save FPS” by blowing out the figure into a slab. Lowest tier may bypass bloom (already RFC-0178) — the silhouette must remain the silhouette, not a flat disc.

### 3. Collapse competing presence modes

Appearance still **persists** `requested_presence` literals (`neural`, `humanoid`, `particle_bust`, `galaxy`, Classic `none`) for compatibility. Those values are **style / profile ids** on **one** shared renderer (RFC-0069 morphable orb cloud + RFC-0176 appearance profile + RFC-0177 cues).

| Control (owner copy) | Stored value | What it actually is |
| --- | --- | --- |
| Classic portal | `shell: classic`, `requestedPresence: none` | No presence canvas (unless a surface mounts one). |
| **APEX UI · orb + graph** | `neural` | Public MIT APEX-UI **orb and reasoning graph** chrome **over** the shared avatar. **Not** the private APEX humanoid. Not the Jarvis humanoid reference. |
| Humanoid HUD · built in | `humanoid` | Shared renderer + Jarvis humanoid figure / TEM chrome. |
| Particle bust · experimental | `particle_bust` | Shared renderer + particle-bust **profile** (density / field), not a second stage. |
| Galaxy | `galaxy` | Shared renderer + RFC-0175 **starfield ADD**. |
| HexStrike · Daybreak | suite override | `hex_aegis` figure; suite rules unchanged. |

**Fail:** mounting a second WebGL body per mode; a Neural-only 680∶480 box vs a Humanoid full-bleed box; labeling APEX as “the humanoid”; preview tiles that show a CSS orb while the live stage is a bust (or the reverse).

**Previews:** every mode/profile control and every persona card shows a **deterministic capture of the live contract** (same `buildFigure`, same appearance profile, rest tightness). Accurate preview is acceptance. A symbolic mark alone is a fail for **selector cards**. Task-row specialist orbs (~72px) may keep a compact mark **in addition** to, not instead of, the selector-card thumbnail contract.

### 4. Per-persona golden captures

Acceptance requires **deterministic reference captures** for:

**Canonical 13 (RFC-0137, roster order):** Anzu (`stormbird`), Mestor (`command_facet`), Nabu (`memory_rings`), Enki (`code_cube`), Veles (`serpent_orbit`), Themis (`twin_shield`), Aegir (`ocean_swell`), Bragi (`waveform_letters`), Hermes (`comet_trail`), Heimdall (`eye_radar`), Eir (`breath_leaf`), Maia (`star_social`), Vulcan (`forge_core`).

**Plus side-injected Umi:** unique shape id **`opus_tide`** (locked). Visual intent: ocean / Opus-inspired reasoning current — deep indigo / violet tides, layered swell, slow intellectual pulse. **Must not** reuse Nabu `memory_rings`. **Must not** reuse Aegir `ocean_swell` (teal media waves). Palette may stay Umi’s violet/lilac (`#7C3AED` / `#A78BFA`) or a documented ocean-adjacent pair that still reads distinct from Aegir teal. Voice bind (`pocket_tts_alba_en_v1`) is unchanged by this RFC.

Capture rules:

- Same WebGL path as the HUD (shared engine, not a CSS fake).
- Fixed seed, rest phase + one engaged phase (`thinking`), viewport-fill framing, documented bloom / profile.
- Store under `docs/rfcs/assets/0195/` (rest + engaged per id) **or** a harness folder the RFC implement names in the PR — both must be bit-stable enough for CI to flag identity collapse (silhouette occupancy, centroid, edge contrast, bloom-overexposure ratio).
- **Confusion fail:** Umi vs Nabu; Mestor vs overexposed slab; idle rest vs anonymous cloud; two personas whose rest stills are interchangeable at HUD distance.

Harness: extend `frontend/presence-check.tsx` / presence unit tests so each registered persona + Umi can be selected and summarized (sample count, fit scale, rest tightness). CI cannot sign Desktop soak; it **can** fail a clone shape id and an idle `uMorph === 0` rest.

### 5. Tie-ins (strengthen, do not fork)

| RFC | What this contract adds |
| --- | --- |
| [RFC-0051](0051-humanoid-presence-runtime.md) | Silhouette, camera look-at, depth, bloom: **readable identity first**. Neural/humanoid **viewport-fill**, not “materially larger” inside a 920px cap. Camera still not opened by the humanoid runtime. |
| [RFC-0069](0069-presence-shape-catalog-and-morph-api.md) | Each shape declares **framing landmarks** (crown / chin / motif bounds) consumed by AABB + look-at. `buildFigure` remains the silhouette; `buildField` is not. |
| [RFC-0176](0176-shared-dot-appearance-profiles.md) | Profile (palette, glow, point scale, depth softness) **separated** from geometry. Profiles must not drop silhouette/motif. Previews use the profile. |
| [RFC-0178](0178-adaptive-dot-rendering-and-framing.md) | Framing + bloom **thresholds**: edge contrast and overexposure ratio are acceptance, not only FPS hysteresis. |
| [RFC-0137](0137-persona-presence-shape-and-voice-binding.md) / [RFC-0138](0138-anzu-orb-custom-ui-generation.md) | Uniqueness: 13 canonical silhouettes stay distinct; Umi `opus_tide` is unique; custom presets must not collide with a roster silhouette. |

### 6. What implementers must NOT do

- Hide the persona at idle (`uMorph` 0 free-float as the rest product).
- Ship **920px / 680∶480** as the primary stage.
- Treat 165 FPS / 94k particles as a pass when the still is an overexposed slab.
- Present APEX as the Jarvis humanoid or import the private APEX humanoid.
- Leave Umi on `memory_rings`.
- Keep Neural / Humanoid / Particle bust / Galaxy as competing stages or aspect boxes.
- Use static symbolic marks as the only persona-selector thumbnail.
- Flip RFC-0195 / soak rows to **implemented** without Taco Desktop soak.
- Implement the queued harden seats listed in Out of scope as part of this ticket.

---

## Acceptance criteria

Product-code rows stay **unchecked** in this specs PR. Desktop soak rows stay **unchecked** until live soak.

- [ ] **Supersession in tests:** no test requires `lifecycleMorphTarget("idle") === 0`. Rest phases target the documented rest tightness in [0.72, 0.92]; engaged target 1.0.
- [ ] **Rest identity:** at idle, waiting, and offline, a still of each of the 13 canonical personas plus Umi is identifiable as that persona (winning `buildFigure` readable). Idle may be looser than engage. Idle is not an anonymous free cloud.
- [ ] **Engage tighten:** leaving rest morphs/tightens on the same cloud (`uMorph` toward 1.0) without remounting the host. Returning to rest loosens; it does not identity-hide.
- [ ] **Viewport-fill:** the WebGL canvas fills the presence host (HUD orb zone). No primary `920px` cap. No primary `680 / 480` aspect lock. HUD chrome overlays and does not reduce canvas allocation.
- [ ] **Crop-protection kept:** AABB + geometric center; silhouette on look-at; no origin-symmetric crush.
- [ ] **Silhouette > FPS:** documented bloom / alpha / edge-contrast checks. A Mestor-like overexposure (washed slab, rings gone) **fails** even if FPS ≥ 60 and particle count is high.
- [ ] **One renderer:** Neural / Humanoid / Particle bust / Galaxy are profiles/chrome/ADD on the shared engine. Previews match the live WebGL look.
- [ ] **APEX copy:** Appearance label is the public **orb-and-graph** look; assistive text states Jarvis does **not** include APEX’s private humanoid. Saved `neural` still selects that profile.
- [ ] **Golden captures:** deterministic rest + engaged captures for the 13 + Umi exist and are wired to a harness. Umi shape id is `opus_tide`, not `memory_rings` or `ocean_swell`.
- [ ] **Selector cards:** persona picker cards use deterministic WebGL (or the same capture pipeline) thumbnails. `SpecialistShapeMark` SVG-alone is not the card.
- [ ] Attract / privacy unchanged: pointer baseline; camera only when already enabled; fail closed; no frames off-machine (RFC-0050).
- [ ] Reduced motion: snap; static readable rest pose; no chase.
- [ ] HexStrike `hex_aegis` override and RFC-0175 Galaxy ADD / waveform / Advanced **unchanged** except as this idle/stage override requires.
- [ ] `python3 -m pytest` and `npm --prefix frontend run build` (and lint if TS changed) on the **implement** PR.
- [ ] **Residual — Desktop soak (stay unchecked):** Taco Desktop GPU / live WebGL review of viewport-fill, rest identity for all 13 + Umi, Mestor not a slab, engage tighten, Galaxy ADD. Cloud VMs cannot sign this off.

---

## Likely files

| Area | Paths |
| --- | --- |
| Lifecycle | `frontend/src/presence/presenceLifecycle.ts` (`lifecycleMorphTarget` rest tightness) |
| Stage / CSS | `frontend/src/presence/renderers/humanoid-presence.css`, `apex-presence.css`, `MorphablePresenceStage.tsx`, `frontend/src/hud/hud-v2.css` (orb zone) |
| Framing / bloom | `frontend/src/presence/presenceQuality.ts`, `renderers/morphableOrbCloud.ts`, RFC-0176 profile fields |
| Shapes | `frontend/src/presence/renderers/shapes/` — landmarks; **new** `opusTide.ts`; Umi bind in `backend/app/persona/named_persona.py`, `frontend/src/persona/namedPersonas.ts` |
| Previews | `frontend/src/persona/NamedPersonaControls.tsx`, `SpecialistShapeMark.tsx` (no longer the selector thumbnail), `AppearanceSettingsPane.tsx` |
| Tests | `frontend/presence-lifecycle.test.mjs`, framing / uniqueness tests; goldens under `docs/rfcs/assets/0195/` or the harness path named in the implement PR |
| Docs | this RFC; amends on 0175 / 0194 / 0178 / 0051 / 0069 / 0176 / 0136 APEX / 0137 / 0138 |

## Out of scope

Product code in this specs PR. Rewriting RFC-0069’s morph API. Importing private APEX humanoid code/art. A fifteenth canonical roster row (Umi stays **side-injected** with a unique shape). New voice packs. Android companion APK visuals. RFC-0092 TTS engines. Flipping ledger Status to implemented.

**Queued harden (next seats — do not implement here; do not file new full RFCs for these unless CoS names them):**

- (a) Model-status hot path: cached background monitor (do not block owner chrome on a synchronous model probe).
- (b) Silhouette / framing / bloom **implement** of **this** RFC (UX/Desktop, Grok 4.6).
- (c) [RFC-0117](0117-tiny-front-chat-responder.md) dedicated tiny seat (already specified; residual is a real always-warm seat, not a new RFC).

## Notes

- Owner lock 2026-09-30 via CoS / Taco. Quality bar **Anzu 1.0**. Subpar implement: CoS → Taco. That path is a review rule, not a runtime feature.
- Historical RFC-0175 refs stay at `docs/rfcs/assets/0175/` for engage/field language only. Idle product target is this file.
- Pointer: [`docs/audits/2026-09-30-visual-acceptance-and-settings-ia.md`](../audits/2026-09-30-visual-acceptance-and-settings-ia.md).
