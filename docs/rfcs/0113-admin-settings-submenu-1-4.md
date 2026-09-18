# RFC-0113: Admin > Settings submenu structure for 1.4

**Status:** accepted  
**Queue item:** (none — no new §58 checkbox; implement is a named follow-up after CoS names it)  
**Author:** Jarvis Architect  
**Date:** 2026-09-17

**Parent / living spec:** [`JARVIS_1.4_SPECS.md`](../../JARVIS_1.4_SPECS.md) work package **C** (§5) + Settings tests in §12 (11–15) / DoD §14.  
**Related (do not rewrite):** [RFC-0094](0094-settings-menu-information-architecture.md) — **implemented** (#265 specs + #267 implement). Six-group IA is already on `development`: Voice, Appearance, Models / Inference, Network / Companion, Integrations, Advanced; Daybreak left-bar Voice + Appearance **split**; `/settings/:submenu` + last-submenu persistence. **This RFC is the remaining 1.4 IA deltas / routes / redirects**, not a duplicate rewrite of 0094.

This PR is **specs-only**. Product code is a follow-up implement ticket. Full intent; **no stubs / soft-fail** (leaving Phone Pairing only on `/companion-pairing` with no Settings home, breaking `/settings/voice` bookmarks, or undoing the Daybreak Voice/Appearance HUD split, is a fail).

**Recommended implement model:** Composer 2.5 (1.4 §2 — routing/component composition + backwards-compatible redirects).

## Problem

RFC-0094 organized the Settings **heap** into six first-class groups and split Daybreak’s mixed “Appearance & voice” dump. That landed. 1.4 still wants a **cleaner Admin > Settings tree** than tip:

```text
Admin
└── Settings
    ├── Appearance & Voice
    ├── Phone Pairing
    ├── Models & Inference
    ├── Network & Swarm
    ├── Integrations
    └── Advanced
```

Tip (`frontend/src/settings/settingsSubmenus.ts`) still has **separate** `voice` and `appearance` Settings ids; pairing lives as a Network deep-link to `/companion-pairing` (`NetworkSettingsPane`); there is no Settings-owned Phone Pairing pane; Network is labeled “Network / Companion”, not Network & Swarm; canonical paths are `/settings/voice` and `/settings/appearance`, not `appearance-voice`. 1.4 needs composed Appearance & Voice, first-class Phone Pairing under Settings, Network & Swarm naming, and **redirects so existing URLs keep working**.

RFC-0094 remains in force for:

- Daybreak left-bar / Desktop HUD: **Voice** and **Appearance** stay **first-class split groups** (do **not** re-merge the HUD into one “Appearance & voice” dump).
- Shared pane components (`AppearanceSettingsPane`, `VoiceSettingsPane`).
- Last-submenu persistence, hash/`?section=` aliases, no secret dumps, no HexStrike redesign, RFC-0092 not folded into IA.

## Decision

Reuse the current Settings submenu infrastructure (`settingsSubmenus.ts`, `SettingsNav`, pane components, `/settings/:submenu`). Do **not** replace it. Apply the 1.4 nav deltas below. Architect picks **one** routing convention and uses it consistently.

### 1. Top-level Settings groups (1.4)

| Id | Label | Intent |
| --- | --- | --- |
| `appearance-voice` | Appearance & Voice | Composed Settings pane: existing Appearance controls + Voice & Speech. **HUD** still shows Voice and Appearance as two first-class groups (RFC-0094). |
| `phone-pairing` | Phone Pairing | First-class Settings home for companion pairing. Reuse existing pairing component/page logic. **Do not** duplicate pairing state or APIs. |
| `models` | Models & Inference | Same intent as RFC-0094 `models` (profile, vision, inference host/port/key write-only, deep-link `/model`). |
| `network` | Network & Swarm | LAN / auth / private key (today’s Network pane minus pairing). Deep-link existing `/swarm` — do **not** re-embed the Swarm admin page. Guest portals stay a deep-link. |
| `integrations` | Integrations | Unchanged intent (deep-link `/mcp`). |
| `advanced` | Advanced | Unchanged intent (autonomy, permissions, license, …). |

RFC-0094 ids `voice` and `appearance` **cease to be primary Settings nav ids**. They remain **redirect aliases** (section 3). HUD compact Voice / Appearance components stay; they may deep-link to `/settings/appearance-voice` (and optionally `#voice` / `#appearance` inside the composed pane).

### 2. Canonical routes

**Preferred** if cheap given existing Admin chrome in `App.tsx`:

```text
/admin/settings/appearance-voice
/admin/settings/phone-pairing
/admin/settings/models
/admin/settings/network
/admin/settings/integrations
/admin/settings/advanced
```

**Minimum acceptable** if `/admin/...` is disproportionately invasive (tip already uses `/settings/:submenu`):

```text
/settings/appearance-voice
/settings/phone-pairing
/settings/models
/settings/network
/settings/integrations
/settings/advanced
```

Choose **one** family. If `/admin/settings/...` is canonical, `/settings/...` still redirects into it. Do not ship two parallel trees.

### 3. Backwards-compatible redirects (required)

Existing routes must keep working:

```text
/settings/voice
  -> canonical Appearance & Voice (and focus Voice & Speech if a hash/anchor exists)

/settings/appearance
  -> canonical Appearance & Voice (focus Appearance if a hash/anchor exists)

/companion-pairing
  -> canonical Phone Pairing

/settings/network
  -> canonical Network & Swarm route (same id; still required so bookmarks/HUD Away targets do not 404)
```

Also keep RFC-0094 aliases that still make sense: `/settings#voice`, `?section=voice` → Appearance & Voice; `?section=appearance` → Appearance & Voice; `?section=network` → Network. Last-opened submenu persistence (`jarvis.settings.last_submenu`) **still works**: migrate stored `voice` / `appearance` → `appearance-voice`; unknown values fall back to Appearance & Voice (1.4 first visit). Do not drop persistence.

Bare `/settings` restores last pane; first visit with no memory opens **Appearance & Voice**.

### 4. Appearance + Voice composition

Create a composed pane, e.g. `frontend/src/settings/AppearanceVoiceSettingsPane.tsx`:

```tsx
export function AppearanceVoiceSettingsPane(...) {
  return (
    <>
      <AppearanceSettingsPane ... />
      <section className="settings-section">
        <h2>Voice & Speech</h2>
        <VoiceSettingsPane />
      </section>
    </>
  )
}
```

Reuse the existing panes. Do not fork TTS engine/default/speak-filter behavior (RFC-0092 / RFC-0111 / RFC-0112 own those). Voice status/preview in this pane must consume RFC-0111/0112 contracts when those have landed; this ticket does **not** implement them.

### 5. Phone Pairing

Reuse `CompanionPairingPanel` / `CompanionPairing.tsx` logic. Do not duplicate pairing state or APIs. Compact HUD/Network “pair phone” CTAs deep-link **Phone Pairing** (`/settings/phone-pairing` or `/admin/settings/phone-pairing`). `/companion-pairing` remains a functional URL via redirect (section 3). `/phone` APK/offline pair entry stays reachable (RFC-0108 chrome is a sibling ticket).

### 6. Network & Swarm

Rename the Network group. Keep auth / LAN / private-key controls in pane. Move pairing chrome to Phone Pairing (link back allowed). Add a **deep-link** to the existing Swarm page (`/swarm`). RFC-0094 still forbids absorbing Tools / Memory / Packs / Ads into Settings; 1.4 does **not** dump the whole admin rail into this submenu.

### 7. Admin chrome

Settings remains under **Admin**. If the implementer adopts `/admin/settings/...`, Admin nav / HudShell Settings / health-rail Settings targets must use the canonical family. A portal-only regroup that leaves Desktop HUD Settings as the old six ids without redirects is a fail.

**Will not:** undo RFC-0094 HUD Voice/Appearance split. Redesign HexStrike. Change TTS engines/defaults (RFC-0092/0111). Duplicate pairing APIs. Absorb the entire admin rail. Dump inference API keys. Rewrite PORTAL_UX.md.

## Acceptance criteria

- [ ] Specs-only in this PR (no product code)
- [ ] Settings nav shows Appearance & Voice, Phone Pairing, Models & Inference, Network & Swarm, Integrations, Advanced
- [ ] Appearance & Voice is a composed pane of existing Appearance + Voice components (not a new dump, not a HUD merge)
- [ ] Daybreak left-bar / Desktop HUD **keep** first-class Voice and Appearance groups (RFC-0094)
- [ ] Phone Pairing is reachable **under Settings**; pairing logic is reused, not forked
- [ ] Legacy `/settings/voice` redirects to Appearance & Voice (1.4 §12 test 11)
- [ ] Legacy appearance route redirects correctly (test 12)
- [ ] Existing `/companion-pairing` deep links remain functional via redirect (tests 13–14)
- [ ] `/settings/network` reaches the canonical Network & Swarm route
- [ ] Last-selected submenu persistence still works, including migration of stored `voice`/`appearance` (test 15)
- [ ] One routing convention (`/admin/settings/...` **or** `/settings/...`), used consistently; the other family redirects if both exist
- [ ] HexStrike left-bar / suite behavior unchanged; RFC-0092 not implemented here
- [ ] Implement follow-up: `python3 -m pytest`; `npm --prefix frontend run build` (and lint if TS changed)

## Likely files

| Area | Paths |
| --- | --- |
| Frontend | `frontend/src/settings/settingsSubmenus.ts`, `SettingsNav.tsx`, new `AppearanceVoiceSettingsPane.tsx`; `AppearanceSettingsPane.tsx`, `VoiceSettingsPane.tsx`, `NetworkSettingsPane.tsx`; `frontend/src/pages/Settings.tsx`, `App.tsx` (canonical routes + redirects); `frontend/src/pages/CompanionPairing.tsx`; `frontend/src/components/CompanionPairingPanel.tsx`; HudShell / health-rail Settings targets; `VoiceHudCompact.tsx` / `AppearancePresenceControls.tsx` deep-links |
| Backend | None required |
| Tests | route/redirect/persistence tests as the implement PR prefers |
| Docs | this RFC; `JARVIS_1.4_SPECS.md`; `JARVIS_MASTER_PLAN.md` §59 only |

## Out of scope

Product implementation in this PR. Re-doing RFC-0094 from scratch. RFC-0111/0112 TTS runtime/preview. RFC-0108 on-device model. Swarm protocol rewrite. HexStrike. Invented LE/Red/Purple gates. Exploit recipes.

## Notes

- 1.4 suggested implement order: **PR 6**.
- Tip evidence: `SETTINGS_SUBMENUS = voice | appearance | models | network | integrations | advanced`; `App.tsx` `/settings` + `/settings/:submenu`; pairing on `/companion-pairing`.
- Linux cloud can verify redirects, persistence migration, and nav labels. Live Daybreak desktop HUD remains desktop sign-off.
- Implement launch: this RFC only; branch from `development`; pytest + frontend build; do not edit Architect spec docs; PR against `development`; do not merge other PRs.
