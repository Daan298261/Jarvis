# RFC-0212 — Collapsible menus and settings

Status: accepted

## Request
Make the HUD menus and settings/checkbox groups collapsible so the presence and conversation have more room.

## Decision
Provide a compact collapse toggle for the complete HUD menu rail. Each settings group has an accessible disclosure with independently remembered open state. Collapsing hides controls without changing settings, clearing drafts or invoking save handlers. Preserve keyboard access, meaningful headings, offline operation and small-screen layout.

## Acceptance
- The full Persona/Voice/Appearance/Cybersecurity rail can collapse and reopen.
- Settings cards and the HUD persona, voice and appearance control groups collapse independently and remember their state across reloads.
- Hidden checkboxes retain their value; disclosure actions never save or activate settings.
- Keyboard controls expose expanded state; collapsed controls leave the tab order. Storage failures do not prevent toggling.
- Frontend build/lint and actual rendered interaction verification pass.

## Scope
Shared disclosure component, settings cards, HUD presence controls and associated CSS. No inference, scheduler, installer or presence renderer changes.
