# RFC-0098: Browser-Use deepen (existing adapter)

**Status:** accepted  
**Queue item:** (none — no new §58 checkbox; implement is a follow-up after CoS names it)  
**Author:** Jarvis Architect  
**Date:** 2026-09-17

**Parent:** [RFC-0095](0095-instagram-jarvis-collection-module-catalog.md) ([PR #270](https://github.com/Daan298261/Jarvis/pull/270)).  
**Related (do not rewrite):** RFC-0019 browser context companion. RFC-0007 / RFC-0090 optional-worker Install now. `EXTERNAL_AGENT_INFRA_INTEGRATION_SPECS.md` §2.1. Playwright default (`backend/app/workers/browser.py`).

This PR is **specs-only**. Do not commit local clones.

## Instagram source

Taco Instagram `@tacotcr` Saved → **jarvis**. Architect box clone (already downloaded; **do not commit**):

| Repo | Canonical | Local path |
| --- | --- | --- |
| Browser Use | [browser-use/browser-use](https://github.com/browser-use/browser-use) | `/workspace/projects/rfc/browser-use` |

## Pipeline (RFC-0095 four-step)

| Step | Result (this RFC) |
| --- | --- |
| 1. Download | **Done locally** at `/workspace/projects/rfc/browser-use`. Not vendored. |
| 2. Usefulness review | **Score 4/5.** Primary bucket: `mas_integration`. Secondary: `skill`. |
| 3. Integrate decision | **`partial` / deepen** — complete the existing Jarvis adapter; do **not** replace Playwright as default. Taco can override. |
| 4. Implement | Later named ticket. |

## Problem

Jarvis already has a **partial** Browser Use worker: `backend/app/tools/browser_use.py` + `backend/app/workers/browser.py` (`BrowserUseBackend`). Playwright remains the deterministic default (`DEFAULT_BROWSER_BACKEND = "playwright"`). When the `browser_use` package is missing, the tool returns “not installed” and ingest/tool fallbacks use Playwright / `web_fetch`. The Instagram save is the same upstream (`browser-use/browser-use`). The adapter is thin: goal+url in, MIT package invoke, little session reuse, weak observability, and RFC-0090 Install now still leaves a shallow integration. Deepen is needed; a second browser product is not.

## Decision

**Deepen the existing adapter** (`partial`). Playwright **stays default** for known selectors and repetitive workflows.

1. Keep `browser` (Playwright) as the default tool. `browser_use` remains optional intelligent discovery for unfamiliar sites (existing description).
2. Deepen, do not replace: session/context reuse where upstream supports it; better structured results (URL, title, extracted text, action trace) for ingest (`backend/app/ingest/`); honor computer-use / network permission gates (`INTERNET_TOOLS`); surface Install now (RFC-0090) without changing the five-id allowlist except as already specified.
3. Failure still falls back to Playwright / `web_fetch` (existing `alternatives_for("browser_use", …)` contract).
4. Jarvis remains orchestrator. Do not make Browser Use the primary app (`docs/DEVELOPMENT.md`).

**Architect’s initial recommendation:** `partial` (deepen). Taco can override to `archive_only` (keep clone only) or `whole` (not recommended — would fight Playwright-default).

**Will not:** swap the default backend to Browser Use; vendor upstream; rewrite RFC-0019 extension; unrestricted stealth/CAPTCHA/credential fill; HexStrike; offensive crawl.

## Acceptance criteria

Pipeline steps below are **spec’d**, not implemented.

- [x] Download — spec’d (`/workspace/projects/rfc/browser-use`; clones not committed)
- [x] Usefulness review — spec’d (4/5, `mas_integration`)
- [x] Integrate decision — spec’d (`partial` deepen; Playwright default; Taco may override)
- [ ] Implement — later named ticket (not this PR)
- [ ] Existing `browser_use` tool/worker deepened; Playwright remains `DEFAULT_BROWSER_BACKEND`
- [ ] Missing package still reports not installed; fallbacks unchanged
- [ ] Specs-only in this PR
- [ ] Implement follow-up: `python3 -m pytest` (update `tests/test_workers.py` / ingest fallbacks as needed)

## Likely files

| Area | Paths |
| --- | --- |
| Backend (implement PR only) | `backend/app/tools/browser_use.py`; `backend/app/workers/browser.py`; `backend/app/ingest/fallbacks.py`; `backend/app/workers/install.py` (RFC-0090) |
| Frontend (implement PR only) | `frontend/src/pages/Tools.tsx` / OptionalWorkerRow — status copy only |
| Tests | `tests/test_workers.py`, `tests/test_external_ingest.py`, `tests/test_rfc0098_*.py` |
| Docs | this RFC; §59 batch line only |

## Out of scope

Product implementation in this PR. Making Browser Use the default or primary app. RFC-0019 rewrite. Firecrawl/Crawl4AI (RFC-0100). HexStrike. Offensive tools (LE-gated under RFC-0095).

## Notes

- Parent RFC-0095 reserved this number. Cloud VMs can unit-test fallbacks; live Browser Use is desktop sign-off.
- Implement launch: this RFC only; branch from `development`; pytest; do not edit Architect spec docs; PR against `development`.
