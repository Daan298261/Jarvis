# RFC-0100: Firecrawl + Crawl4AI research connectors

**Status:** accepted  
**Queue item:** (none — no new §58 checkbox; implement is a follow-up after CoS names it)  
**Author:** Jarvis Architect  
**Date:** 2026-09-17

**Parent:** [RFC-0095](0095-instagram-jarvis-collection-module-catalog.md) ([PR #270](https://github.com/Daan298261/Jarvis/pull/270)).  
**Related (do not rewrite):** RFC-0098 Browser-Use deepen. RFC-0019 browser companion. `web_fetch` / `backend/app/ingest/`. Computer-use network permissions.

This PR is **specs-only**. Do not commit local clones.

## Instagram source

Taco Instagram `@tacotcr` Saved → **jarvis**. Architect box clones (already downloaded; **do not commit**):

| Repo | Canonical | Local path |
| --- | --- | --- |
| Firecrawl | [firecrawl/firecrawl](https://github.com/firecrawl/firecrawl) | `/workspace/projects/rfc/firecrawl` |
| Crawl4AI | [unclecode/crawl4ai](https://github.com/unclecode/crawl4ai) | `/workspace/projects/rfc/crawl4ai` |

## Pipeline (RFC-0095 four-step)

| Step | Result (this RFC) |
| --- | --- |
| 1. Download | **Done locally** at `/workspace/projects/rfc/{firecrawl,crawl4ai}`. Not vendored. |
| 2. Usefulness review | **Score 4/5.** Primary bucket: `mas_integration`. Secondary: `skill`. |
| 3. Integrate decision | **`partial`** — policy-bounded research crawl connectors beside `web_fetch` / ingest. Not unrestricted WAN scrape. Taco can override. |
| 4. Implement | Later named ticket. |

## Problem

Research tools today are `web_fetch` (HTTP get + extract) and Playwright / optional Browser Use. JS-heavy docs, multi-page crawls, and clean markdown extraction fail or dump noise. Instagram-jarvis saves name Firecrawl (crawl → clean markdown/JSON) and Crawl4AI (LLM-friendly local crawl) as research connectors. There is no adapter, and no policy that would stop an ordinary worker from turning them into unrestricted site-wide scrapers.

## Decision

Add **research crawl connectors** (`partial`).

1. **Firecrawl** — optional self-hosted or owner-configured endpoint for map/crawl/extract to markdown. Prefer local/self-hosted; cloud Firecrawl is opt-in with an owner API key in existing secrets storage (never git, never GET dumps).
2. **Crawl4AI** — optional local crawler for LLM-ready markdown when Firecrawl is absent.
3. **Policy:** same network gate as `web_fetch` / `browser` (`INTERNET_TOOLS`). Default: owner-allowlisted hosts / depth / page cap. No credential stuffing, no bypass of `ask` computer-use, no background scrape of the open web as a swarm job.
4. **Ingest:** new fallback tier in `backend/app/ingest/` after platform adapters and before last-resort Browser Use — or a dedicated `research_crawl` tool that returns an `ExternalContentArtifact`. Do not replace Playwright default browsing (RFC-0098).
5. Jarvis stays orchestrator. Connectors are tools, not the app.

**Architect’s initial recommendation:** `partial`. Taco can override to `archive_only` if license/SaaS lock-in is unacceptable.

**Will not:** unrestricted WAN scrape; stealth/CAPTCHA farms; offensive recon (that is LE-gated under RFC-0095, not this module); replace `web_fetch`; HexStrike.

## Acceptance criteria

Pipeline steps below are **spec’d**, not implemented.

- [x] Download — spec’d (paths above; clones not committed)
- [x] Usefulness review — spec’d (4/5, `mas_integration`)
- [x] Integrate decision — spec’d (`partial`; policy-bounded; Taco may override)
- [ ] Implement — later named ticket (not this PR)
- [ ] Firecrawl and/or Crawl4AI connectors; host/depth caps; network permission gate
- [ ] Missing sidecar degrades to `web_fetch` / Playwright; no crash
- [ ] Specs-only in this PR
- [ ] Implement follow-up: `python3 -m pytest` (`tests/test_rfc0100_*.py` — allowlist, depth cap, secret not echoed)

## Likely files

| Area | Paths |
| --- | --- |
| Backend (implement PR only) | `backend/app/tools/web_fetch.py` (sibling tool or tier); `backend/app/ingest/`; `backend/app/policy/computer_permissions.py`; new `backend/app/tools/research_crawl.py` |
| Frontend (implement PR only) | Tools/System optional-worker row; Settings Integrations deep-link only |
| Tests | `tests/test_rfc0100_*.py`, `tests/test_web_fetch.py` |
| Docs | this RFC; §59 batch line only |

## Out of scope

Product implementation in this PR. RFC-0098 Browser-Use deepen. Instagram scraper. Offensive crawl / Strix / Pentagi / Claude-Red (LE-gated under RFC-0095). HexStrike. Persona merge.

## Notes

- Parent RFC-0095 reserved this number. Cloud can unit-test allowlist + caps; live crawl is desktop/network sign-off.
- Implement launch: this RFC only; branch from `development`; pytest; do not edit Architect spec docs; PR against `development`.
