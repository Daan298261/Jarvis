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

99 focused Python checks passed; four Node extension protocol/revocation checks passed. Real Chromium smoke covered loaded Manifest V3 popup, page snapshot/find/click/fill, password exclusion, stale-target rejection, expiration, and actual ad-request block/unblock. A real stdio native-host process round trip passed. The PowerShell installer parsed without errors. Live ANZU tool calls enumerated 18 Windows application windows and fetched a public HTTPS page. Full local pytest stalled at 28% in async fixture setup; process inspection showed an asyncio wait and idle aiosqlite worker. The stalled run was stopped and is not a full-suite pass. Installed ANZU, owner's normal Chrome profile/registry registration, and live model-driven desktop control are not signed off by these checks. Browser smoke skips explicitly on CI hosts without Chromium; Node protocol checks run in PR CI.
