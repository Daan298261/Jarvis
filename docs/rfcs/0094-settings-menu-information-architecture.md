# RFC-0094: Settings menu information architecture

**Status:** implemented
**Queue item:** (none — no new §58 checkbox; implement is a Desktop HUD + Settings IA follow-up after CoS names it)
**Author:** Jarvis Architect
**Date:** 2026-09-16

**Related (do not rewrite):** RFC-0050 presence / presentation (Appearance concepts). RFC-0061/0062 speak toggle + voice catalog (picker **layout** only). RFC-0074 companion pairing. RFC-0079 computer-use permissions. RFC-0086 HexStrike suite (**do not** redesign). **RFC-0092 neural TTS default / no silent SAPI** stays Sol-priority — this RFC must **not** fold it (no TTS engine, default, catalog ranking, or speak-filter changes). RFC-0093 installer force-stop is unrelated.

This PR is **specs-only**. Product code is a follow-up implement ticket. Do not edit `frontend/src/` or backend in this PR.

## Problem

The Daybreak / portal Settings screen is a **heap of random settings**. On tip (`9ecf9bd`, includes `#263` `8884b7d`), `frontend/src/pages/Settings.tsx` stacks License, Autonomy, Agent profiles, Pair phone, Guest portals, Voice & speech, Advisor, Trajectories, Coding isolation, Security & Remote Access, Inference server, Core Execution (autonomy **again** mixed with model profile / vision), computer-use permissions, self-dev budget, and the launch queue as sequential cards. There is no category nav, no last-pane memory, and no deep-link (`/settings` only — `App.tsx` has a single route).

Dedicated pages already exist beside that dump: `/model` (LM Studio catalog + `RuntimeProfilesSection`), `/mcp` (`IntegrationSetup` Gmail/WhatsApp + advanced MCP), `/companion-pairing`, `/phone`, `/license`, `/system`, `/agents`, `/guest-portals`, `/advisor`, `/trajectories`, `/coding`. Settings often **re-embeds** or **re-links** them instead of grouping by job.

Appearance does not live on Settings at all. `#263` restored **Appearance + Voice** on the Daybreak HUD left-bar (`AppearancePresenceControls` in `HudChatHome`: voice profile list, Classic / Neural / Humanoid / Particle, Rendering, Attention, Motion) as **one combined dump**, not two first-class groups. Settings has the heavier `VoiceProfilePicker` + **Speak chat replies**, but no presentation controls. Desktop HUD (`HudShell`) and portal Settings are two incomplete surfaces, not one IA. Entry today: HudShell `ADMIN_QUICK` Settings, classic rail Settings, HudHealthRail Away → `/settings`.

Owners cannot find Voice vs Inference vs pairing without scrolling a server-console dump (`PORTAL_UX.md` already wants Settings findable, not a console).

## Decision

Replace the flat Settings dump with a **clear submenu IA**: category list (left nav or equivalent) + one content pane. This RFC is **IA / layout only**.

**Surfaces in scope (same IA, not portal-only):**

- Main Settings / menu screen (`Settings.tsx`, classic rail, HudShell Settings link).
- **Daybreak left-bar** Voice & Appearance area (`AppearancePresenceControls` in `HudChatHome`).
- **Desktop HUD** (Daybreak `HudShell` / `uiMode === "hud"` on the Windows desktop) — organized the same way as the portal Settings screen. A portal-only regroup of `/settings` that leaves the desktop HUD as a heap is a **fail**.

**Voice** and **Appearance** are **first-class submenu groups** on every surface above. They must not be buried in a flat heap, a single combined “Appearance & voice” dump, or nested under Advanced / Models.

### 1. Top-level groups (canonical ids)

| Id | Label | Intent |
| --- | --- | --- |
| `voice` | Voice | Speak-chat toggle, voice profile picker / install links. **Not** neural-engine work. |
| `appearance` | Appearance | Theme / presence / shell / rendering / attention / motion — same concepts as `AppearancePresenceControls`. |
| `models` | Models / Inference | Model profile, vision, inference backend/host/port/key (write-only; never dump saved secrets), links to `/model` (LM Studio + runtime profiles). |
| `network` | Network / Companion | Private key / auth / LAN, phone pairing, companion APK / `/phone` entry. |
| `integrations` | Integrations | Gmail / WhatsApp MCP setup — deep-link `/mcp` (do not duplicate the heavy forms). |
| `advanced` | Advanced | Autonomy, agent interview, queue, computer-use permissions, worktrees / coding isolation, license, advisor, trajectories, self-dev, System escape. |

Architect may refine visible labels after implement review; **ids and intents stay**. **`voice` and `appearance` stay first-class** (never merged into one group, never demoted). Every **current** Settings control lands in **exactly one** primary submenu (table below). Prefer **deep-links** to existing dedicated pages over duplicating heavy UIs. Mixed cards (today’s Core Execution) **split** by intent; do not clone the same control into two panes.

### 2. Mapping — every current Settings control → one submenu

Verified against `Settings.tsx` on tip. “Keep in pane” = compact control stays in the Settings submenu. “Deep-link” = button/lede to the existing route; do not re-embed the full page.

| Current surface | Primary submenu | Placement |
| --- | --- | --- |
| Embedded `LicenseSettings` + lede link to `/license` | Advanced | Deep-link `/license` (status one-liner optional). Do not keep a second full license UI in Settings. |
| `AutonomySection` (stay-with-a-job, Away Mode, persistence / proactivity) | Advanced | Keep in pane **or** deep-link if the section stays huge; not duplicated on Voice/Appearance. |
| Agent profiles card → `/agents` | Advanced | Deep-link `/agents` (interview). |
| Pair phone + compact `CompanionPairingPanel` | Network / Companion | Compact panel **or** deep-link `/companion-pairing`. Full QR/walkthrough stays on that page. Link `/phone` for generic APK / offline pair. |
| Guest portals card → `/guest-portals` | Network / Companion | Deep-link `/guest-portals` (scoped remote share). |
| Voice & speech: `VoiceProfilePicker` | Voice | Keep in pane. Catalog/default/engine behavior is **RFC-0092**, not this ticket. |
| Voice & speech: **Speak chat replies** | Voice | Keep in pane (existing `updateTtsSettings({ speak_chat_replies })`). Do not change speak-filter or TTS defaults. |
| Advisor card → `/advisor` | Advanced | Deep-link `/advisor`. |
| Trajectories card → `/trajectories` | Advanced | Deep-link `/trajectories`. |
| Coding isolation card → `/coding` | Advanced | Deep-link `/coding`. |
| Security: `auth_required` | Network / Companion | Keep in pane. |
| Security: `lan_access` | Network / Companion | Keep in pane. |
| Private key show/hide, save browser, save server, generate | Network / Companion | Keep in pane. Still never echo inference API keys. |
| Inference server: backend, host, port, remote model name | Models / Inference | Keep in pane; “Open Model page” → `/model`. |
| Inference API key (password, write-only, stripped on GET) | Models / Inference | Keep write-only field; **no secrets in UI dumps**. |
| Core Execution: Ask before risky tools (`autonomy`) | Advanced | Move here (same setting as today’s second autonomy control — one widget, not two). |
| Core Execution: Execution mode, default timeout, retry limit | Advanced | Keep in pane. |
| Core Execution: Model profile (`fast` / `balanced` / `quality` / `expert`) | Models / Inference | Move here (split from the mixed card). |
| Core Execution: Vision mode + Load vision projector | Models / Inference | Move here. |
| Core Execution: Allowed directories | Advanced | Keep in pane. |
| Core Execution: Headless browser | Advanced | Keep in pane. |
| Core Execution: Create backups before overwrite | Advanced | Keep in pane. |
| `ComputerUsePermissions` (computer / network / HexStrike / blue / red) | Advanced | Keep in pane. **Do not** redesign HexStrike or RFC-0086 groups. |
| Self-development trial budget | Advanced | Keep compact **or** deep-link `/system` (System already shows self-dev). One primary home: Advanced. |
| Launch & Task Queue status | Advanced | Keep read-only status in pane. |

**Surfaces that must gain a Settings home (not in the heap today):**

| Surface | Primary submenu | Placement |
| --- | --- | --- |
| `AppearancePresenceControls` presentation: Classic / Neural / Humanoid / Particle, Rendering, Attention, Motion | Appearance | **Keep in pane** via the **same shared component** (or extract appearance-only half). This is the Settings home for presentation; it must not remain HUD-only. |
| `IntegrationSetup` (Gmail / WhatsApp) on `/mcp` | Integrations | Deep-link `/mcp`. Optional one-line status; do not fork the setup forms. Advanced MCP add-server stays on `/mcp`, not a seventh Settings group. |
| Model page LM Studio catalog + `RuntimeProfilesSection` | Models / Inference | Deep-link `/model`. |

Admin destinations that are **not** Settings controls today (Tools, Memory, Swarm, Packs, Ads, …) stay on existing nav. This RFC does **not** absorb the whole admin rail into Settings.

### 3. Daybreak left-bar + Desktop HUD (same first-class groups)

CoS/Taco addendum: **Voice** and **Appearance** must be first-class submenu groups on **both** the Daybreak left-bar **and** the main Settings/menu screen. Desktop HUD is in scope.

Today `HudChatHome` left-bar `AppearancePresenceControls` is one `<details>` summary **Appearance & voice** (`#263`) mixing a voice list with shell/presence/rendering/attention/motion. That combined dump is the same class of heap this RFC removes from Settings.

- **Required:** split that left-bar into **two first-class groups** — Voice and Appearance — matching Settings ids `voice` and `appearance`. Compact panes or a two-item category list are fine. Shared components with Settings are required so HUD and Settings are one IA. Deep-links (“Open full Voice settings” → `/settings/voice`, Appearance → `/settings/appearance`) are allowed **in addition**, not instead of first-class HUD groups.
- **Desktop HUD:** `HudShell`, health-rail Settings/Away targets, and any in-HUD menu must use the **same six-group IA** (at least Voice + Appearance as first-class; remaining groups reachable via Settings nav / deep-link). Do not ship a portal Settings IA while the desktop Daybreak chrome stays an ungrouped heap.
- **Forbidden:** one mixed “Appearance & voice” panel as the only HUD IA; burying Voice or Appearance under Advanced; HUD-only presentation settings that Settings Appearance cannot reach; a third taxonomy with different group names. Unavailable-profile copy “Install in Settings” must deep-link **Voice** (`/settings/voice` or `#voice`).
- HexStrike: `HudChatHome` still forces humanoid while the suite is active. **Do not** rewrite HexStrike / RFC-0086 in this ticket.

Composer **Speak chat replies** mute stays a chat-local shortcut into the same TTS setting; it is not a substitute for the Voice submenu.

### 4. Persistence and deep-links

- Canonical URL: **`/settings/:submenu`** with `submenu` ∈ `voice` \| `appearance` \| `models` \| `network` \| `integrations` \| `advanced`. Left nav marks the active group.
- Aliases that select the same pane: **`/settings#voice`** (etc.) and optional `?section=voice`. Hash/query must not invent a parallel tree.
- Persist **last-opened submenu** in `localStorage` (e.g. `jarvis.settings.last_submenu`). Bare **`/settings`** (HudShell, classic rail) restores last pane; first visit with no memory opens **`voice`**.
- HUD / health-rail later targets a submenu when the job is known (Away → `/settings/advanced`; pairing copy → `/settings/network`). Daybreak left-bar Voice / Appearance groups select those panes (HUD-local and/or `/settings/voice` | `/settings/appearance`).
- **Optional** backend preference for last-submenu (tiny PUT on existing `/api/settings`) is **not** required. localStorage + URL is enough for the owner portal / desktop HUD. If added, it must not store secrets.

**Will not:** change TTS defaults, engines, catalog ranking, speak-filter, or SAPI/Kokoro fallback (RFC-0092). Touch installer / RFC-0093. Redesign HexStrike. Add Settings groups beyond the six intents. Dump inference API keys. New backend APIs except the optional last-submenu preference. Portal-only IA that leaves Desktop HUD / Daybreak left-bar ungrouped.

## Acceptance criteria

- [x] Settings / menu screen is a category list + content pane (not a single scrolling heap of all cards)
- [x] **Voice** and **Appearance** are **first-class submenu groups** on the **main Settings/menu screen** (not nested, not a combined dump)
- [x] **Voice** and **Appearance** are **first-class submenu groups** on the **Daybreak left-bar** (today’s single “Appearance & voice” `<details>` heap is split; not buried)
- [x] **Desktop HUD** (`HudShell` / Daybreak) uses the **same organized IA** as Settings — not portal-only
- [x] Six groups present with the intents above; every tip Settings control appears in **exactly one** primary submenu per the mapping table
- [x] Mixed Core Execution card is split (model/vision → Models / Inference; autonomy/timeouts/dirs/browser/backup → Advanced)
- [x] Heavy UIs (`/license`, `/model`, `/mcp`, `/companion-pairing`, `/agents`, …) are deep-linked, not duplicated
- [x] HUD and Settings share Voice + Appearance components (or HUD deep-links into those Settings panes) — no second conflicting hierarchy
- [x] HexStrike left-bar / suite behavior unchanged
- [x] `/settings/voice` (and `#voice` / `?section=voice` aliases) opens Voice; same for the other ids; last submenu restored on bare `/settings`
- [x] RFC-0092 **not** implemented here: no TTS engine/default/speak-filter edits
- [x] Specs-only in this PR (no `frontend/src` / backend product edits) — specs PR #265
- [x] Implement follow-up: `python3 -m pytest`; `npm --prefix frontend run build` (and lint if TS changed)

## Likely files

| Area | Paths |
| --- | --- |
| Frontend (implement PR only) | `frontend/src/pages/Settings.tsx`; `frontend/src/App.tsx` (`/settings` + `/settings/:submenu`); `frontend/src/presence/AppearancePresenceControls.tsx`; `frontend/src/hud/HudChatHome.tsx`; `frontend/src/hud/HudShell.tsx`; `frontend/src/hud/HudHealthRail.tsx`; `frontend/src/tts/VoiceProfilePicker.tsx`; `frontend/src/pages/Autonomy.tsx`; `frontend/src/pages/ComputerUsePermissions.tsx`; `frontend/src/pages/License.tsx` (embed vs link); `frontend/src/components/CompanionPairingPanel.tsx`; `frontend/src/pages/Mcp.tsx` / `IntegrationSetup.tsx` (links only) |
| Backend | None required. Optional: last-submenu field on existing settings GET/PUT |
| Tests | `tests/test_rfc0094_*.py` if a preference field is added; otherwise frontend route/IA tests as the implement PR prefers |
| Docs | this RFC; `JARVIS_MASTER_PLAN.md` §59 Decision Log line only |

## Out of scope

Product implementation in this PR. **RFC-0092** neural TTS / no silent SAPI (Sol-priority; Voice submenu only **hosts** today’s speak toggle + picker — layout/IA, not engine quality). RFC-0093 installer. HexStrike defensive suite redesign (RFC-0086). New MCP/Gmail/WhatsApp APIs. Swarm / model-stack. Architect rewrites of `PORTAL_UX.md` beyond the ledger tick. Absorbing Tools / Memory / Swarm / Packs into Settings.

## Notes

- Taco / CoS 2026-09-16: Daybreak/settings is a heap — needs organized submenus. Addendum: Voice + Appearance first-class on **both** Daybreak left-bar **and** Settings; scope **Desktop HUD** (not portal-only). Architect + CoS assign this spec **accepted**. Implement is a **separate** named ticket after CoS names it; do not merge this specs PR as if the IA shipped.
- Tip evidence (do not treat as already grouped): `Settings.tsx` flat cards; `App.tsx` `path="/settings"` only; Daybreak left-bar one `Appearance & voice` details dump; `/mcp` + `/model` + `/companion-pairing` as sibling routes; HudShell / classic nav Settings → `/settings`.
- Linux cloud VMs can verify routes, last-submenu persistence, and that Appearance/Voice are first-class on Settings + HUD chrome. Live Daybreak desktop HUD is desktop sign-off.
- Implement launch: implement this RFC only; branch from `development`; pytest + frontend build; do not edit Architect spec docs; PR against `development`; do not merge other PRs.

## Implementation note

Landed on `development` via specs **#265** @ `01bd56e` + implement **#267** @ `73d93d2` (six-group Settings nav + panes, Daybreak Voice/Appearance split, `/settings/:submenu` + last-submenu persistence). RFC-0092 not folded (Voice pane hosts speak toggle + picker only). Live Daybreak desktop HUD chrome remains desktop sign-off.
