# RFC-0102: LocalSend LAN share module

**Status:** accepted  
**Queue item:** (none — no new §58 checkbox; implement is a follow-up after CoS names it)  
**Author:** Jarvis Architect  
**Date:** 2026-09-17

**Parent:** [RFC-0095](0095-instagram-jarvis-collection-module-catalog.md) ([PR #270](https://github.com/Daan298261/Jarvis/pull/270)).  
**Related (do not rewrite):** RFC-0008 guest portals. RFC-0074 companion pairing. RFC-0094 Settings Network / Companion group. `ANDROID_CLIENT.md` (phone is a controller). Not swarm (`SWARM_ARCHITECTURE.md`).

This PR is **specs-only**. Do not commit local clones.

## Instagram source

Taco Instagram `@tacotcr` Saved → **jarvis**. Architect box clone (already downloaded; **do not commit**):

| Repo | Canonical | Local path |
| --- | --- | --- |
| LocalSend | [localsend/localsend](https://github.com/localsend/localsend) | `/workspace/projects/rfc/localsend` |

## Pipeline (RFC-0095 four-step)

| Step | Result (this RFC) |
| --- | --- |
| 1. Download | **Done locally** at `/workspace/projects/rfc/localsend`. Not vendored. |
| 2. Usefulness review | **Score 3/5.** Primary bucket: `module`. Secondary: `mas_integration`. |
| 3. Integrate decision | **`partial`** — LAN send/receive connector (protocol or sibling app), not a swarm node and not a Guest Portal replacement. Taco can override. |
| 4. Implement | Later named ticket. |

## Problem

Owners need to move files between the Jarvis Windows Leader, phones, and other PCs on the home LAN without cloud drives. Companion pairing (RFC-0074) is identity + control, not a general file drop. Guest portals (RFC-0008) are scoped web access, not AirDrop-class LAN share. Instagram-jarvis saves LocalSend (open, local-network file share, PIN, multi-platform). Jarvis has no LAN share module.

## Decision

Add a **LocalSend LAN share module** (`partial`).

1. **Nearby send/receive** of owner-approved files/folders on the LAN (discovery + transfer). Prefer interop with the LocalSend protocol/app so existing LocalSend clients on phone/PC can participate; a thin Jarvis connector is enough. Do not vendor the Flutter app into the portal.
2. **Surfaces:** Settings → Network / Companion (RFC-0094 `network` group) plus an optional Tools action. Companion/phone may receive a “save to this device” path later; v1 may be Leader-as-client talking to LocalSend peers.
3. **Policy:** owner confirm for receive (default ask); send only from allowed directories (existing filesystem allowlist). No WAN relay, no swarm placement, no guest-portal token reuse as a file dump.
4. Secrets/keys never travel inside shared archives by default (pack export already strips secrets; this module must not re-introduce them).

**Architect’s initial recommendation:** `partial`. Taco can override to `whole` (first-class worker) or `archive_only`.

**Will not:** make LocalSend a Jarvis Node / swarm member; replace companion pairing; expose Leader filesystem to the LAN without confirm; HexStrike; offensive tools.

## Acceptance criteria

Pipeline steps below are **spec’d**, not implemented.

- [x] Download — spec’d (`/workspace/projects/rfc/localsend`; clones not committed)
- [x] Usefulness review — spec’d (3/5, `module`)
- [x] Integrate decision — spec’d (`partial`; Taco may override)
- [ ] Implement — later named ticket (not this PR)
- [ ] LAN send/receive connector; receive asks; send respects filesystem allowlist
- [ ] Not a swarm node; not a guest-portal substitute
- [ ] Specs-only in this PR
- [ ] Implement follow-up: `python3 -m pytest`; if portal touched, `npm --prefix frontend run build`

## Likely files

| Area | Paths |
| --- | --- |
| Backend (implement PR only) | new `backend/app/tools/lan_share.py` or `backend/app/workers/localsend.py`; `backend/app/api/` Network settings; filesystem allowlist reuse |
| Frontend (implement PR only) | Settings `network` pane; optional Tools row |
| Tests | `tests/test_rfc0102_*.py` — allowlist, confirm-on-receive, no secret packing |
| Docs | this RFC; §59 batch line only |

## Out of scope

Product implementation in this PR. Swarm/P3 node discovery. Guest portal rewrite. Companion QR pairing (RFC-0074). HexStrike. Offensive tools (LE-gated under RFC-0095).

## Notes

- Parent RFC-0095 reserved this number. Cloud can unit-test policy; live multicast discovery is desktop/LAN sign-off.
- Implement launch: this RFC only; branch from `development`; pytest; do not edit Architect spec docs; PR against `development`.
