# RFC-0217: Chrome website connector

**Status:** accepted

**Author:** Codex for Daan

**Date:** 2026-10-14

## Problem

ANZU has Windows UI Automation, screenshots, Playwright with a separate persistent profile, HTTP fetch, and optional Browser Use/UFO/Cua workers. No connector can operate an owner-selected tab in their existing Chrome session. Browser Use is an optional dependency, not a replacement for deterministic browser tools.

## Decision

Add an optional Manifest V3 Chrome extension and a Windows native messaging host. Expose connector operations through the existing browser tool and its network and action-effect policy. The owner shares one tab through the extension, with site permission requested on demand. Provide visible-text snapshots, text search, observed-target click/fill, and reversible basic tab-scoped ad blocking. Native messaging uses local user files and Chrome's exact extension-origin allowlist; no web-accessible listener or owner API token is needed. Require an exact URL for every operation and reject navigated tabs, stale targets, expired commands, password fields, and arbitrary scripts. Page text is untrusted evidence.

## Acceptance criteria

- [x] Existing browser/desktop/web-fetch behavior stays available.
- [x] Extension is installable unpacked with a per-user native-host registration script.
- [x] Read/find/click/fill work only on the explicitly shared HTTP(S) tab.
- [x] Ad blocking uses session rules limited to that tab, with disable/revoke cleanup.
- [x] Disconnection, policy denial, navigation, expiration, and stale targets fail honestly.
- [ ] Focused Python and extension tests, full pytest, and diff checks run.

## Likely files

`backend/app/tools/browser.py`, `backend/app/tools/chrome_connector.py`, `backend/app/policy/reversibility.py`, `backend/app/agent/prompts.py`, `extensions/chrome/`, `tests/test_chrome_connector.py`, `docs/chrome-connector.md`, `.github/workflows/pr-tests.yml`.

## Out of scope

Chrome Web Store publication and bypassing site protections. Live Chrome installation and model-driven Windows end-to-end acceptance remain separate from source tests.

## Owner-approved completion scope (2026-10-14)

Daan requested implementation of the remaining listed capabilities, explicitly including optional Browser Use, UFO and Cua workers. Extend this ticket with open-shadow-DOM and permitted-frame controls, observed-link downloads and bounded owner-file uploads, built-in web search, broader filter-list ad blocking, stable extension identity and easier native-host setup, and working isolated optional-worker installation/runtime adapters. Keep private cookies/passwords out of snapshots, preserve per-site/tab sharing and existing approvals, and report closed shadow roots or inaccessible frames honestly. Configure workers for the local model and avoid changing ANZU's Python dependencies through worker installs.

Additional likely files: `backend/app/workers/{install,browser,computer}.py`, optional-worker runners and runtime helpers, `backend/app/api/tools.py`, browser connector setup API/UI, and their focused tests. Installer payload changes are authorized only if needed to deliver this ticket's connector; no stable promotion is requested.

## Validation

See `docs/chrome-connector.md` for expanded capability validation and remaining live acceptance limits. Expanded-head CI passed 3,170 backend tests (six skips), frontend build and installer compile. Focused Python checks (96), Node protocol checks (five), real Chromium features and compiled native-host integration passed. Full local Windows pytest was attempted but stalled at 14% in asyncio Proactor loop creation (socketpair/accept); no local full-suite pass is claimed.
