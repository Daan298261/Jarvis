# Visual acceptance + Settings IA pointer — 2026-09-30

**Audience:** CoS / UX / Desktop implementers  
**Scope:** Specs amends only (PR onto `development`). No product code. No ledger Status → implemented.

Canonical contracts:

- Visual: [`docs/rfcs/0195-visual-acceptance-and-presence-stage.md`](../rfcs/0195-visual-acceptance-and-presence-stage.md) (**accepted**)
- Settings IA: [`docs/rfcs/0094-settings-menu-information-architecture.md`](../rfcs/0094-settings-menu-information-architecture.md) Amend 2026-09-30 (**accepted restore**; #267 land stays implemented)

Related gap list (do not duplicate): [`2026-09-30-intent-vs-land-gaps.md`](2026-09-30-intent-vs-land-gaps.md).

## Supersessions (implementers)

| Do not ship | Source that is now void as primary | Follow |
| --- | --- | --- |
| Idle free-float that **hides** the persona (`uMorph` 0 / Ref A live rest) | RFC-0175 idle rule; RFC-0194 Decision 1 | RFC-0195 rest tightness ∈ [0.72, 0.92]; humanoid/winning-figure silhouette at rest |
| 920px / 680∶480 as the **primary** stage | RFC-0194 Decision 3 | Viewport-fill; HUD chrome overlays; keep AABB crop-protection |
| Neural / Humanoid / Particle bust / Galaxy / APEX as competing stages; APEX as humanoid ref | RFC-0050 mode cards; RFC-0136 copy drift | One renderer + style/profile; APEX = public orb-and-graph |
| Settings nav `appearance-voice` as canonical | RFC-0113 §1/§4; RFC-0175 SETTINGS_SUBMENUS lock | RFC-0094 split `appearance` + `voice`; HUD already split |
| Umi on Nabu `memory_rings` | Product side-inject | `opus_tide` unique ocean/Opus silhouette |
| Static marks as the only persona **selector** thumbnail | `SpecialistShapeMark` | Deterministic WebGL shape+profile capture |

Desktop soak AC stay **unchecked**. Do not tick RFC-0195 implemented from Linux CI.

## Queued harden (out of scope / next seats)

After this specs land, CoS implement queue (do **not** write new full RFCs unless CoS names them):

- (a) Model-status hot path: cached background monitor
- (b) Silhouette / framing / bloom **implement** of RFC-0195 (UX/Desktop, **Grok 4.6**)
- (c) RFC-0117 dedicated tiny seat (already specified)

## Lanes

- Visual implement: UX + Desktop soak (Grok 4.6)
- Settings IA restore: UX (Composer 2.5)
- Architect: ledger ticks only after named tickets + Desktop soak where visual
