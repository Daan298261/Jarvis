# RFC-0008: Scoped guest portals

**Status:** accepted  
**Queue item:** External/customer access  
**Author:** ChatGPT competitor-watch synthesis  
**Date:** 2026-08-28

## Problem

Jarvis cannot safely expose a narrow project, agent, or result stream to a client/collaborator without exposing the broader installation.

## Decision

Add revocable Guest Portals using scoped capability tokens. A portal can grant read/query/approve permissions to specific workspace resources, agents, task results, or Decision Inbox items while denying filesystem, terminal, unrelated projects, settings, and administrative operations by default.

## Acceptance criteria

- [ ] Portal tokens have scope, expiry, revocation, and optional single-use/session limits.
- [ ] Default portal capability set is deny-all except explicitly granted resources/actions.
- [ ] Every portal action is audited and attributable to a guest identity/session.
- [ ] Owner can revoke access immediately.
- [ ] UI previews effective guest permissions before issuing access.
- [ ] Portal cannot traverse to unrelated agents, files, tools, or settings.
- [ ] Tests cover scope isolation, expiry, and revocation.

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
