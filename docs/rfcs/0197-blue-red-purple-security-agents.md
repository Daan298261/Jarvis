# RFC-0197: Blue, red, and purple security agents (tool-driving personas)

**Status:** accepted  
**Queue item:** (none — no §58 checkbox; implement after CoS wave)  
**Author:** Jarvis Architect  
**Date:** 2026-10-02

**Related:** [RFC-0196](0196-hexstrike-operator-chain-anzu-1.md) HexStrike operator chain. [RFC-0105](0105-cybersecurity-module.md) optional backends/harnesses. [RFC-0119](0119-license-package-entitlements-and-release-unrestricted.md) `blue-team` / `red-team` / `hexstrike` modules + `law_enforcement` for red. [RFC-0086 ATO](0086-in-person-cyber-ato-license.md) signed package fields (no new LE fiction). [RFC-0137](0137-persona-presence-shape-and-voice-binding.md) **Themis** (blue), **Veles** (red). [RFC-0126](0126-personality-session-modes.md) / [RFC-0130](0130-session-personalities.md) session modes (separate from security agents). [RFC-0079](0079-computer-use-permissions.md) permission flags. `backend/app/policy/computer_permissions.py` existing `gated="blue-team"` / `red-team`.

Specs-only PR. **No ledger ticks.**

**Hard constraint:** no exploit recipes, PoCs, payloads, or attack procedures in this RFC or agent prompts.

## Problem

Jarvis has license modules and permission **flags** for blue/red, a `security_role` column limited mainly to `blue-team` on tasks, and specialist routing hooks — but no **first-class security agent modes** that (1) bind to Anzu roster personas, (2) **drive** HexStrike/Daybreak and RFC-0105 connectors instead of narrating, (3) enforce **owner-authorized targets only**, and (4) support **purple** coordinated adversarial + defensive loops with explicit handoffs. RFC-0105 explicitly deferred authorization; this RFC supplies the **owner-scoped** authorization model without inventing law-enforcement gates beyond RFC-0119/0087.

## Decision

Introduce three **security agent modes** (product-facing; not session modes):

| Mode | Persona (RFC-0137) | License modules | Purpose |
| --- | --- | --- | --- |
| **Blue** | `themis` (default bind) | `blue-team` (+ `hexstrike` when using HexStrike chain) | Defensive operations on owner-attested scope |
| **Red** | `veles` (default bind) | `red-team` **and** `law_enforcement=true` on the **same** package (RFC-0087 issue rule) | Authorized offensive **assessment** against declared targets only |
| **Purple** | coordinated `themis` + `veles` (UI shows both; orchestrator is Anzu) | blue + red modules as above | Alternating defend / probe loop with handoff rules |

Selecting a security agent mode:

1. Sets `task.security_role` to `blue-team` | `red-team` | `purple-team` (new persisted value).
2. Suggests named persona morph + voice per table (owner may override voice in Appearance per RFC-0137).
3. Exposes the **tool set** for that mode (below) — not a prose-only “I would scan…” reply.

HexStrike suite profile (`hex_aegis`) still overrides **presence shape** while active; it does not disable security agent tooling.

### 1. Tool exposure by mode (must execute, not narrate)

| Mode | Required tool paths | Narration-only response |
| --- | --- | --- |
| Blue | `hexstrike_operator` / Daybreak operate APIs (RFC-0196), RFC-0105 defensive connectors when enabled, blue-gated computer-use flags | **Fail** if model answers without tool calls when user asked for an action |
| Red | Red-gated permission flags only; HexStrike operate **only** when entitled and target passes policy below | **Fail** if agent describes attacks without scoped tool invocation |
| Purple | Alternation per §3; both tool sets per phase | **Fail** if single monologue without phase handoff record |

Implementers add a **verification hook**: for managed cyber tasks, planner marks `requires_tool_execution=true`; loop rejects final assistant text that claims completion without a succeeded tool/job record (pattern similar to coding mission verify — details in implement ticket).

### 2. Owner-scoped target authorization

**Target registry** (new durable store under `data_dir()/security-targets.json` or equivalent):

| Field | Rule |
| --- | --- |
| `id` | uuid |
| `kind` | `hostname` \| `ipv4` \| `ipv6` \| `cidr` \| `local_path` \| `container_image` |
| `value` | normalized string |
| `owner_attested_at` | ISO timestamp |
| `notes` | optional owner label |

**Policy:**

1. **Default deny** for any target not in the registry (red **and** blue offensive-adjacent calls).
2. **Refuse** third-party systems the owner has not attested (no “scan google.com” unless explicitly attested — public-Internet scanning remains **out of product default** per RFC-0086 scope spirit).
3. **Red** invokes require `red-team` module + `law_enforcement` on package (existing vendor rule — do not invent new LE UI).
4. Every target add/remove and every denied invoke → **audit** (`data_dir()/cyber-ato/audit.jsonl` or sibling `security-audit.jsonl`).

Owner UX (Daybreak Cyber / HexStrike scope UI): merge RFC-0086 scope editor with this registry (one model — implement ticket).

### 3. Purple mode handoff rules

Purple runs **phased** loops:

```text
[Plan] → Blue harden/observe → handoff artifact → Red probe (scoped) → handoff artifact → Blue verify → …
```

| Rule | Detail |
| --- | --- |
| Phase owner | Each phase sets `task.phase` `blue` \| `red` in task metadata |
| Handoff artifact | Structured JSON: `findings[]`, `evidence_paths[]`, `open_questions[]` stored under Jarvis-owned job dir |
| No parallel red+blue tools | Single active phase; orchestrator switches phase only after job terminal state or owner command |
| Owner stop | Owner “stop purple” cancels active job and locks phase |

### 4. Entry UX

1. **Daybreak** Cyber left-bar or HexStrike HUD: mode selector **Blue | Red | Purple** (disabled when license missing).
2. **Owner chat**: “switch to blue team” / “red team assessment on my lab” sets mode + prompts for target attestation if missing.
3. **Named persona picker** (RFC-0137): choosing Themis/Veles may suggest matching security mode (not required).

### 5. Gates (honest only)

| Check | Source |
| --- | --- |
| Module entitlement | RFC-0119 |
| Red requires LE on package | RFC-0087 / `requires_law_enforcement("red-team")` |
| Per-action desktop consent | RFC-0079 / 0110 |
| Target in registry | This RFC |

**Do not** add password gates, officer checklists, or case-file workflows.

### 6. Implement anti-patterns (forbidden)

- Chat persona that roleplays red/blue without tools
- `security_role` set but tool exposure unchanged from default butler
- Purple without phase metadata or handoff artifacts
- Red tools enabled without `law_enforcement` on package
- Scanning/arbitrary targets without registry attestation

## Acceptance criteria

Specs-only:

- [x] RFC-0197 accepted; personas Themis/Veles cited; purple handoff rules documented
- [x] Owner-scoped target registry + deny third-party policy documented
- [x] Audit + license gates aligned with 0119/0087 (no invented LE)
- [x] No exploit/payload content

Implement follow-up:

- [ ] `purple-team` persisted on tasks; API to set security agent mode
- [ ] Target registry CRUD + enforce on HexStrike operate and red/blue tool paths
- [ ] Tool exposure maps per mode; verification rejects narration-only “completed” cyber tasks
- [ ] Daybreak UX for mode + targets; Themis/Veles default binds
- [ ] Purple phase machine + handoff artifacts
- [ ] Unit tests: deny unlisted target, deny red without LE, purple phase transitions, audit lines
- [ ] **Windows desktop soak**: attest lab target → blue defensive job via Themis → red scoped job via Veles (entitled) → purple handoff visible in UI

## Likely files

| Area | Paths |
| --- | --- |
| Backend | `backend/app/agent/loop.py`, `backend/app/agent/tool_exposure.py`, `backend/app/agent/planning.py`, `backend/app/api/tasks.py`, `backend/app/db/models.py`, `backend/app/policy/computer_permissions.py`, `backend/app/policy/cyber_ato.py`, new `backend/app/security/target_registry.py` |
| Frontend | `frontend/src/hud/HudCybersecurityModule.tsx`, `frontend/src/hud/HudHexStrikeSuite.tsx`, persona picker integration |
| Tests | `tests/test_rfc0197_*.py`, extend `tests/test_cyber_ato.py` |

## Out of scope

- blue.re integration / LTA archives ([RFC-0198](0198-blue-re-lta-protected-folder.md))
- New License Manager module ids (use existing catalog)
- PolitieGPT / law-enforcement case management
- Architect spec doc rewrites

## Notes

- RFC-0105 **Out of scope** gating is **superseded for owner-scoped cyber agents** by this RFC only; it does not reintroduce exploit documentation into 0105.
- Desktop soak unchecked on cloud VMs.
