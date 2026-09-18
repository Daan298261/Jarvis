# RFCs (design → implementation handoff)

ChatGPT/Codex and human design work lands here as **short RFCs** — one concern per file. RFCs are the ticket Cursor cloud workers implement.

## Rules

1. **One concern per RFC.** Split large designs into multiple numbered files (`0001-…`, `0002-…`).
2. **Do not rewrite `JARVIS_MASTER_PLAN.md`.** The master plan stays architecture + Current State + Development Queue. Update it only **after** an RFC is merged (matching queue lines and state bullets).
3. **Keep RFCs small:** problem, decision, acceptance criteria, likely files. Target &lt; 2 pages.
4. **Product features** (Browser Use, swarm, P4/P5, model-stack migrations) get their own RFC; they do not belong in a process or hygiene RFC.

## Workflow

```
ChatGPT/Codex  →  docs/rfcs/NNNN-title.md  →  queue line in master plan (optional)
                                                      ↓
Cursor worker  →  branch from development  →  PR against development  →  merge
                                                      ↓
                                            promote development → main on explicit stable cut
                                                      ↓
                                            update §57–58 + decision log only
```

## Template

Copy [`TEMPLATE.md`](TEMPLATE.md) to `docs/rfcs/NNNN-short-slug.md` and fill it in.

## Naming

- `NNNN` — four-digit sequence (`0001`, `0002`, …).
- `short-slug` — kebab-case summary (`playwright-retry`, `auth-header-fix`).

## Status values

| Status | Meaning |
| --- | --- |
| `draft` | Design in progress; do not implement yet |
| `accepted` | Ready for a Cursor worker (named in the launch prompt) |
| `implemented` | Merged; master-plan queue/state updated |
| `superseded` | Replaced by another RFC; link the successor |

## Jarvis 1.4.0 pack

Living spec: [`JARVIS_1.4_SPECS.md`](../../JARVIS_1.4_SPECS.md). Implement tickets:

| RFC | Concern |
| --- | --- |
| [0111](0111-kokoro-real-runtime.md) | Kokoro as real runtime (work package A) |
| [0112](0112-voice-preview-exact-profile.md) | Voice preview exact profile (B) |
| [0113](0113-admin-settings-submenu-1-4.md) | Admin > Settings 1.4 IA deltas (C); RFC-0094 already implemented |
| [0114](0114-context-overflow-preflight-recovery.md) | Context overflow preflight + recovery (D) |
| [0115](0115-ornith-orchestrator-router-complexity.md) | Ornith orchestrator-router + complexity tiers + visible handoff (E+F) |

Interesting integrations **in** 1.4: [0107](0107-obsidian-linked-memory-brain.md)–[0110](0110-chatgpt-style-approval-popup.md). Bulk catalog **0095–0104** stays later ([`INTEGRATION_SPECS.md`](../../INTEGRATION_SPECS.md)). Post-1.4 optional accelerators (do **not** block 1.4.0): [0116](0116-typesafe-jev-optional-decision-tier.md) TypeSafe Jev decision tier (waitlist-gated), [0117](0117-tiny-front-chat-responder.md) tiny front-chat responder for first visible/audible replies.
