# Numbering note — main @ `ac18fb32` vs development

**Date:** 2026-09-24  
**Owner:** Jarvis Architect

## Collision

On **main** @ `ac18fb32` (PR #406), filenames `0139-*` and `0140-*` were reused for:

| Main filename (wrong on development) | Topic |
| --- | --- |
| `0139-skill-forge-verified-trace-to-reusable-skill.md` | Skill Forge |
| `0140-multi-agent-rooms-blackboard-deadlock-and-handoff.md` | Multi-agent rooms |

On **development**, those numbers are already taken by **implemented** Android companion RFCs:

| Development (canonical) | Topic | Status |
| --- | --- | --- |
| [RFC-0139](0139-android-companion-fancy-orb-humanoid-ui.md) | Fancy orb / humanoid presence | implemented (#401) |
| [RFC-0140](0140-companion-on-device-voice-models.md) | On-device STT/TTS packs | implemented (#403) |

**Do not** cherry-pick or overwrite development’s Android `0139` / `0140` files from main.

## Resolution on development (this PR)

| Topic | Development number | File |
| --- | --- | --- |
| Jev/Laya Reflex Lane (P0) | **RFC-0171** | `0171-system-one-reflex-lane-jev-laya-priority.md` |
| Fast computer-use (P0) | **RFC-0172** | `0172-reflex-first-browser-computer-use-fast-loop.md` |
| Skill Forge (from main’s false 0139) | **RFC-0173** | `0173-skill-forge-verified-trace-to-reusable-skill.md` |
| Multi-agent rooms (from main’s false 0140) | **RFC-0174** | `0174-multi-agent-rooms-blackboard-deadlock-and-handoff.md` |

Main still carries the wrong 0139/0140 filenames until a separate main renumber (Architect/CoS); development is source of truth for Android 0139/0140.

## Soft deps

RFC-0172 still conceptually depends on RFC-0145 / RFC-0151 (on main only today). Treat as soft on development until those are ported.
