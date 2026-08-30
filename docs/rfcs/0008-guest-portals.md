# RFC-0008: Scoped guest portals

**Status:** implemented  
**Queue item:** External/customer access  
**Author:** ChatGPT competitor-watch synthesis  
**Date:** 2026-08-28

## Problem

Jarvis cannot safely expose a narrow project, agent, or result stream to a client/collaborator without exposing the broader installation.

## Decision

Add revocable Guest Portals using scoped capability tokens. A portal can grant read/query/approve permissions to specific workspace resources, agents, task results, or Decision Inbox items while denying filesystem, terminal, unrelated projects, settings, and administrative operations by default.

## Acceptance criteria

- [x] Portal tokens have scope, expiry, revocation, and optional single-use/session limits.
- [x] Default portal capability set is deny-all except explicitly granted resources/actions.
- [x] Every portal action is audited and attributable to a guest identity/session.
- [x] Owner can revoke access immediately.
- [x] UI previews effective guest permissions before issuing access.
- [x] Portal cannot traverse to unrelated agents, files, tools, or settings.
- [x] Tests cover scope isolation, expiry, and revocation.

## Likely files

| Area | Paths |
| --- | --- |
| Backend | auth/token service, portal API |
| Frontend | guest portal and owner management UI |
| Tests | authorization isolation tests |

## Out of scope

Full multi-tenant SaaS billing and organization management.

## Notes

Inspiration: Zoey portals. Recommendation: ADAPT.

Landed on `cursor/local-qwen-desktop-agent`: backend guest portals PR #71 (`63bb39d`); guest portal UI PR #76 (`f003c4e`).
