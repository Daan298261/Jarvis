# RFC-0103: RuView Wi‑Fi presence / home awareness

**Status:** accepted  
**Queue item:** (none — no new §58 checkbox; implement is a follow-up after CoS names it)  
**Author:** Jarvis Architect  
**Date:** 2026-09-17

**Parent:** [RFC-0095](0095-instagram-jarvis-collection-module-catalog.md) ([PR #270](https://github.com/Daan298261/Jarvis/pull/270)).  
**Related (do not rewrite):** `HOME_IOT.md` (house control). RFC-0053 social perception / ambient awareness. RFC-0054 household identity. RFC-0055 commentary policy. RFC-0069 presence **shape catalog** (orb HUD — **do not fork** `PresenceHost` for Wi‑Fi CSI). RFC-0078 / RFC-0086 HexStrike + ATO (**not this ticket**).

This PR is **specs-only**. Do not commit local clones.

## Instagram source

Taco Instagram `@tacotcr` Saved → **jarvis**. Architect box clone (already downloaded; **do not commit**):

| Repo | Canonical | Local path |
| --- | --- | --- |
| RuView | [ruvnet/RuView](https://github.com/ruvnet/RuView) | `/workspace/projects/rfc/ruview` |

## Pipeline (RFC-0095 four-step)

| Step | Result (this RFC) |
| --- | --- |
| 1. Download | **Done locally** at `/workspace/projects/rfc/ruview`. Not vendored. |
| 2. Usefulness review | **Score 4/5.** Primary bucket: `mas_integration` (home IoT / presence). Not HexStrike. Not a HUD shape. |
| 3. Integrate decision | **`partial`** — Wi‑Fi CSI presence events → Jarvis home-awareness / `HOME_IOT` / RFC-0053 structured observations. Taco can override. |
| 4. Implement | Later named ticket. |

## Problem

Mansion-JARVIS specs want house awareness (`HOME_IOT.md`) and ambient presence (RFC-0053) without always using cameras. Instagram-jarvis saves **RuView**: commodity Wi‑Fi → spatial intelligence / presence / (optional) vital-sign sensing **without video**. Jarvis has no Wi‑Fi-presence connector. Risk: treating RuView as HexStrike/RF offensive tooling, or as a rewrite of the Daybreak orb catalog (RFC-0069). It is home awareness, not red-team and not a particle-humanoid shape.

## Decision

Add a **RuView Wi‑Fi presence connector** (`partial`) for **home IoT / household awareness**.

1. **Role:** local RuView (or compatible CSI node) emits **presence / occupancy / motion** (and optionally coarse room-level location). Jarvis maps those to RFC-0053 `StructuredObservation` (e.g. `person_present`, `person_count`, `source: "wifi.ruview"`) and/or `HOME_IOT` device/scene state (“someone in kitchen”).
2. **Privacy:** no raw CSI dumps in chat, logs, or memory by default. Observations are bounded facts + confidence (RFC-0053 sanitizer, novelty, cooldown). Commentary still goes through RFC-0055 — sensing must not become creepy narration.
3. **Not HexStrike.** No RF exploit, no Wi‑Fi attack, no ATO, no Blue/Purple/Red tool registration. Unknown MACs may be **Blue-visible household events** later; this RFC does not add offensive capability (`SECURITY_AGENTS.md` §3.4).
4. **Not RFC-0069.** Do not register a RuView orb shape or fork `PresenceHost`. HUD presence stays the particle humanoid; Wi‑Fi presence is **sensor input**, not a renderer.
5. **Local-first:** sidecar on the LAN; owner opt-in. Missing RuView ⇒ perception/IoT unchanged.

**Architect’s initial recommendation:** `partial`. Taco can override to `archive_only` if CSI hardware is out of scope for v1.

**Will not:** HexStrike / red tooling; camera replacement mandate; vital-sign medical claims as product; fork presence morph API; persona merge.

## Acceptance criteria

Pipeline steps below are **spec’d**, not implemented.

- [x] Download — spec’d (`/workspace/projects/rfc/ruview`; clones not committed)
- [x] Usefulness review — spec’d (4/5, home IoT / presence)
- [x] Integrate decision — spec’d (`partial`; Taco may override)
- [ ] Implement — later named ticket (not this PR)
- [ ] Optional RuView → structured occupancy observations / home-awareness facts
- [ ] No HexStrike/offensive RF tools; no RFC-0069 `PresenceHost` fork
- [ ] RFC-0053 privacy boundary applies (no raw CSI in prompts/logs by default)
- [ ] Specs-only in this PR
- [ ] Implement follow-up: `python3 -m pytest` (`tests/test_rfc0103_*.py`)

## Likely files

| Area | Paths |
| --- | --- |
| Backend (implement PR only) | `backend/app/api/perception.py`; `backend/app/perception/`; new `backend/app/iot/ruview.py` (or `home/ruview.py`); do **not** edit `backend/app/security/hexstrike*.py` |
| Frontend (implement PR only) | Settings Network / Integrations status; **not** `frontend/src/presence/` shape catalog |
| Tests | `tests/test_rfc0103_*.py`, perception policy tests |
| Docs | this RFC; §59 batch line only (do not rewrite `HOME_IOT.md` in the implement PR unless Architect names it) |

## Out of scope

Product implementation in this PR. HexStrike / RFC-0086. RFC-0069 morph/catalog rewrite. Medical/vital-sign productization. Offensive tools (Strix / Pentagi / Claude-Red stay LE-gated under RFC-0095). Camera identity (RFC-0054) beyond using presence as a non-biometric occupancy hint.

## Notes

- Parent RFC-0095 reserved-child one-liner said “presence/visual”; **this child follows Taco’s mapping: Wi‑Fi home awareness, not HUD visuals.** Linux cloud cannot sign off live CSI hardware; unit-test the observation mapping.
- Implement launch: this RFC only; branch from `development`; pytest; do not add HexStrike tools; PR against `development`.
