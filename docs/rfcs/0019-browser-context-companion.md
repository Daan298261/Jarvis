# RFC-0019: Browser context companion

**Status:** accepted  
**Queue item:** Browser companion / page-context tools  
**Author:** ChatGPT competitor-watch synthesis  
**Date:** 2026-08-31

## Problem

Jarvis currently requires users to move information into Jarvis explicitly before agents can reason over it. Competitors reduce this friction by making the active browser tab itself available as context for summarization, extraction, rewriting, comparison, and action. Jarvis needs the same convenience without granting a browser extension unrestricted access to browsing history, credentials, or unrelated tabs.

## Decision

Add an optional Jarvis browser companion extension and a browser-context bridge. The extension exposes only user-approved page/tab context to Jarvis and can invoke bounded Jarvis actions from the current page.

The default interaction is explicit: the user opens the companion or invokes a command and Jarvis receives a sanitized snapshot of the active tab. Persistent site access, multi-tab access, DOM interaction, downloads, form filling, or browser automation require separate capabilities and policy grants.

Page context becomes a typed `BrowserContextSnapshot` with URL, title, selected text, readable text, structured metadata, optional DOM references, capture time, and source provenance. Secrets, password fields, payment fields, and browser-managed credentials are excluded.

## Acceptance criteria

- [ ] Browser extension can send the current tab URL, title, selected text, and readable page text to Jarvis after explicit user invocation.
- [ ] Context is represented as a typed `BrowserContextSnapshot` with timestamp and provenance.
- [ ] Password fields, payment fields, browser credential stores, cookies, auth headers, and extension-private data are never included in snapshots.
- [ ] Per-site permissions support `ask`, `allow`, and `deny`; `ask` is the default.
- [ ] Incognito/private-window access is disabled by default and requires an explicit browser-level opt-in plus Jarvis policy approval.
- [ ] Jarvis can summarize, extract structured data, answer questions, rewrite selected text, and hand page context to an existing workflow/agent.
- [ ] Any write/action against the page is a separate capability from read-only context and uses the existing approval/policy system.
- [ ] Snapshot size is bounded; large pages are chunked/indexed rather than injected wholesale into every prompt.
- [ ] UI clearly shows when browser context is attached to a request and allows removing it before execution.
- [ ] Audit records identify originating URL, capture time, invoking user, receiving agent/workflow, and actions taken.
- [ ] Tests cover permission denial, secret-field exclusion, oversized pages, stale snapshots, and context provenance.
- [ ] Unit tests pass (`python3 -m pytest`).
- [ ] Extension/frontend build passes where applicable.

## Likely files

| Area | Paths |
| --- | --- |
| Browser | new browser-extension package / manifest / content-script bridge |
| Backend | `backend/app/browser/...`, context ingestion, policy hooks |
| Frontend | active-context indicator and browser-companion settings |
| Tests | browser snapshot, permission, sanitization tests |
| Docs | browser companion privacy/capability documentation |

## Out of scope

Full autonomous Browser Use, CAPTCHA handling, stealth browsing, credential autofill, or unrestricted background scraping. Those require separate Browser Use/automation RFCs.

## Notes

Inspiration: Merlin browser-context workflow. Discovery date: 2026-08-31. Recommendation: **ADAPT STRONGLY**, but keep page-reading and page-acting capabilities separate and permission-scoped.
