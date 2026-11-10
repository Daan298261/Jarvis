# RFC-0243: Readable HUD chat and reliable follow-up turns

**Status:** accepted
**Author:** Codex, requested by Daan
**Date:** 2026-10-28
**Amended 2026-11-10 (Jarvis Architect, CoS ticket answering UX blocker 4 on #683):** adds *Compact chat toggle*, its acceptance criteria and named tests. Records the CoS add-only ruling behind the PR fixer's Compact chat commit `6b095724`. The bounded column becomes the Compact layout, default on. Off restores development's classic HUD chat exactly.

## Problem

The humanoid stage stretches chat across the viewport, leaving opposite-side bubbles far apart and text over a busy canvas. Follow-ups can overlap their previous runner, and the live event stream replays old replies as if they belong to the new question.

## Decision

Keep the existing humanoid and center chat in a bounded column with tighter message spacing, as the Compact chat layout (default on; see *Compact chat toggle*). Add a persistent Chat background toggle for a translucent dark reading panel, without canvas backdrop filtering. Drain the prior task runner and its turn-owned background jobs before accepting a follow-up, preserve its committed history, and reset current-turn result/error state. Persist an owner-turn boundary atomically with the follow-up and scope live preview replay to that boundary. Keep the newest user message authoritative while retaining earlier context.

The supplied failure log also exposes ordinary worker continuations restarting durable model keys, a non-streaming deadline that omits output generation, and a server context limit differing from the local estimate. Continue model numbering for every worker continuation, fingerprint actual model inputs and reject mismatched cached model steps. Budget non-streaming calls for generation as well as prompt processing, with a bounded ceiling. Adopt explicit context limits from server overflow errors before retrying and retain the server diagnostic when recovery fails.

### Compact chat toggle (amended 2026-11-10; CoS add-only ruling)

The bounded column is a **Compact chat** mode. It is added alongside the classic HUD chat, never in place of it.

- **Default on.** `useChatCompact` (`frontend/src/chat/chatAppearance.ts`) reads `CHAT_COMPACT_KEY` = `"jarvis.chat.compact.v1"`. Only an explicit `"off"` turns it off; a missing value or unavailable storage means on.
- **One persisted state, one source of truth.**
  - Compact chat lives in exactly one storage key, `jarvis.chat.compact.v1`, with values `"on"` and `"off"`. Chat background likewise lives only in `CHAT_BACKGROUND_KEY` = `"jarvis.chat.background.v1"`.
  - Both keys are read and written only through one shared store in `chatAppearance.ts`, never through a separate `useState` copy. The store is a module-level external store read with `useSyncExternalStore`. Its setter writes storage and notifies every subscriber in the tab, and it subscribes to the window `storage` event for other tabs.
  - `useChatCompact` and `useChatBackground` are thin hooks over that store. Their setters are exported so tests can drive them. The present `usePersistedToggle` (`useState` plus `writeOnOff`) is replaced by the store.
- **Two places, one state.**
  - The toggle stays in the HUD chat tools row: the `.hud-chat-tools` button `.hud-chat-compact-toggle` ("Compact chat: On/Off", `aria-pressed`) in `HudChat`.
  - It also appears in the Settings Appearance pane (`AppearanceSettingsPane`, Settings submenu `appearance`), in a new `CollapsibleSection` titled "Chat" (`storageKey="appearance-chat"`). That section also holds the Chat background toggle.
  - Flipping either toggle updates the other live, with no reload.
  - The new section sits beside the existing sections. "Presence style", "Personality", "Persona", "Custom appearance" and "Rendering and motion" are not changed.
- **Compact on.**
  - `chatRootClassName(true)` gives the root `hud-chat chat-compact`.
  - Every compact rule in `frontend/src/hud/hud-v2.css` is scoped to `.hud-chat.chat-compact`:
    - the column is `min(820px, calc(100% - 24px))` with `max-width: 820px`, on `.hud-home > .hud-chat.chat-compact` and on the presence-stage column `.hud-home:has(.jarvis-presence-stage) > .hud-chat.chat-compact`;
    - the thread is capped at `max-height: min(40dvh, 420px)` with `mask-image: none`;
    - the `.hud-chat-thread` gap is 6 px;
    - bubble spacing and size are tighter.
- **Compact keeps the role bubble colours.** No `.chat-compact` rule sets `background` or `border-color` on `.hud-bubble` or on any role variant. Compact changes spacing, padding and font size only. So in both modes:
  - assistant bubbles keep `.hud-bubble`'s `rgb(7, 11, 17)`;
  - user bubbles keep `.hud-bubble-user`'s `rgba(24, 47, 59, 0.35)` and its border colour;
  - thought and internal bubbles keep `.hud-bubble-internal`/`.hud-bubble-thought`'s amber `rgba(20, 16, 8, 0.82)` and amber border.
- **Chat background only in Compact.**
  - The translucent reading panel (`background`, `box-shadow`, `border-color` on `.hud-thread`) is scoped to `.hud-chat.chat-compact[data-chat-background="on"] .hud-thread`.
  - With Compact chat off, both Chat background toggles (HUD and Settings) are disabled, titled "Chat background applies in Compact chat".
  - Its stored value is kept, so turning Compact back on restores the owner's choice.
- **Compact off restores the classic layout exactly (add-alongside).**
  - `chatRootClassName(false)` is `hud-chat`, so no compact rule matches and the classic rules apply unchanged.
  - These classic rules must stay untouched, with no selector, property or value edited or removed:
    - `.hud-chat` (`width: min(1000px, calc(100% - 64px))`, `gap: 14px`);
    - `.hud-home:has(.jarvis-presence-stage) > .hud-chat` (the presence-stage column);
    - `.hud-thread`: `max-height: min(30vh, 285px)`, `border: 0`, `background: transparent`, and the fade mask `mask-image: linear-gradient(to bottom, transparent 0, black 18px, black calc(100% - 12px), transparent 100%)`;
    - `.hud-bubble`, `.hud-bubble-user`, `.hud-bubble-internal`, `.hud-bubble-thought`;
    - the `max-width: 900px` and `max-width: 640px` media-query rules.
  - The only additions visible in classic mode are the `.hud-chat-tools` row and the `data-chat-compact`/`data-chat-background` attributes on the root, which no classic rule matches.
- **Live-UI reasoning pass.**
  - The CSS diff against development is append-only. Every new rule is either scoped to `.chat-compact` or styles only the new `.hud-chat-tools` row and its buttons.
  - With Compact off, the root's class list equals development's (`hud-chat`). The thread then matches only development's rules: same width, height cap, transparent background, no border and the same fade mask.
  - Bubbles match development's rules in both modes.
  - So Off reproduces development's live HUD chat, and the tools row is the one added element.
  - The Settings change adds a section and edits none.
- **Astra boundary.**
  - Persona, WebGL and presence systems belong to Astra and are out of scope. That covers the humanoid, `jarvis-presence-stage`'s contents, `AppearancePresenceControls` and the presence/persona sections of `AppearanceSettingsPane`.
  - Compact only uses `.jarvis-presence-stage` as the chat's parent context in a selector and styles nothing inside it.

## Acceptance criteria

- [ ] HUD chat stays together on wide, desktop and narrow screens; the humanoid stays intact.
- [ ] Chat background can be toggled and survives reload; translucent mode improves contrast without blur/compositor effects.
- [ ] A new prompt cannot run concurrently with or be overwritten by the old runner, and old completion callbacks cannot stop a newer heartbeat.
- [ ] Reconnecting during a follow-up cannot replay previous-turn replies as current output; completed history remains visible.
- [ ] Two distinct prompts reach inference in order, with the second answered as the current request.
- [ ] Ordinary worker follow-ups cannot reuse a previous question's durable model result; identical-input durable replay remains available.
- [ ] Non-streaming deadlines include the requested output budget, and overflow recovery respects a smaller explicitly reported server context.
- [ ] Targeted regressions, full backend CI, frontend build/lint and browser layout/interaction checks run. Installed-app verification is reported separately.

### Compact chat acceptance (checked at #683 head `38929ae2` on 2026-11-10)

Tests run in CI's `frontend-build` job: it runs `npm run build` and the step "Chat appearance compact/classic tests (RFC-0243)" (`npm run test:chat-appearance`). That script runs `frontend/chat-appearance.test.mjs` and the new JSDOM render file `frontend/chat-appearance-render.test.mjs`, set up the way `frontend/hud-model-selector-render.test.mjs` is.

- [x] **Default on.** With nothing stored, Compact chat is on and the root is `hud-chat chat-compact`. *Met:* `useChatCompact`/`readChatCompact` (only `"off"` disables). Tested by `frontend/chat-appearance.test.mjs` "compact chat defaults on and persists like the background toggle" and "compact on adds the chat-compact class and its rules carry the RFC-0243 caps".
- [ ] **Persisted round-trip.** Turning the toggle off through the exported setter writes `"off"` to `jarvis.chat.compact.v1`, a fresh read (reload) returns off, and turning it on writes `"on"`.
  - Test: `frontend/chat-appearance.test.mjs` "compact toggle writes off and a reload reads off".
  - *Open:* the head never exercises the write path. `writeOnOff` is private and the existing test only reads values it seeded into storage.
- [ ] **One state, two toggles in sync.** The Settings "Chat" section and the HUD `.hud-chat-compact-toggle` read one store. Clicking either flips the other and the HUD root class live, and a `storage` event from another tab updates both.
  - Tests in `frontend/chat-appearance-render.test.mjs`:
    - "settings and HUD compact toggles stay in sync";
    - "a storage event from another tab updates the compact toggle";
    - "clicking Compact chat flips the HUD root class and persists".
  - The third replaces the source-text grep "HudChat surfaces the Compact chat toggle beside the background toggle".
  - *Open:* at the head, `chatAppearance` is imported only by `HudChat`, and `AppearanceSettingsPane` has no Chat section. `usePersistedToggle` is a per-component `useState` with no shared store and no `storage` subscription.
- [ ] **Off matches the classic DOM, classes and mask.**
  - With Compact off, the HUD chat root's class is exactly `hud-chat`.
  - No rule outside `.chat-compact` sets the compact caps, `mask-image: none`, or a `background`, `box-shadow` or `border-color` on `.hud-thread`. `.hud-thread` keeps `max-height: min(30vh, 285px)`, `background: transparent` and the fade mask, and `.hud-chat` keeps `min(1000px, calc(100% - 64px))`.
  - Both Chat background toggles are disabled with the explanatory title.
  - Tests:
    - `frontend/chat-appearance.test.mjs` "compact off restores the classic layout and fade mask" (exists; layout and mask);
    - `frontend/chat-appearance.test.mjs` "classic mode has no chat background panel" (new);
    - `frontend/chat-appearance-render.test.mjs` "compact off renders the classic chat root and disables Chat background" (new).
  - *Open:* `hud-v2.css` has `.hud-chat[data-chat-background="on"] .hud-thread`, which is not scoped to `.chat-compact`. With Chat background on by default, it puts an 82 % dark panel and a shadow under the classic fade mask. The existing test doesn't catch it.
- [ ] **Compact keeps the role bubble colours.** No `.chat-compact` rule sets `background` or `border-color` on `.hud-bubble` or a role variant. In compact, user, thought and internal bubbles still differ from the plain assistant bubble with their classic colours.
  - Test: `frontend/chat-appearance.test.mjs` "compact keeps the role bubble colours".
  - *Open:* `.hud-chat.chat-compact .hud-bubble { background: rgba(7, 14, 22, 0.65) }` overrides the assistant, user, thought and internal backgrounds alike, because specificity 0,3,0 beats the 0,1,0 role rules.
- [x] **CI step.** `.github/workflows/pr-tests.yml` job `frontend-build` runs "Chat appearance compact/classic tests (RFC-0243)" (`npm run test:chat-appearance`) after "Build frontend". *Met* at the head. The new render file must join the same script.
- [x] **Add-only CSS and Astra boundary.**
  - The `hud-v2.css` diff against development is append-only: no existing selector or value is changed.
  - No persona, WebGL or presence file is touched.
  - *Met* at the head (UX numstat 53/0 and a file list check). The open fixes above must keep both true.

## Scope

`frontend/src/hud/HudChat.tsx`, HUD chat CSS, chat appearance preferences (Compact chat and Chat background, `frontend/src/chat/chatAppearance.ts`), the new "Chat" section of `frontend/src/settings/AppearanceSettingsPane.tsx`, `OwnerChatTranscript`, live preview, task continuation, event streaming, and focused regressions. No architect specifications, model-stack changes, security-gate changes, installer replacement or changes to the existing humanoid. Persona, WebGL and presence systems are Astra's and out of scope.

Failure-log follow-up scope: durable model runner, inference manager, context budgeting and call deadlines, the corresponding inference settings and regression tests. No model selection or security policy changes.
