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
| [0115](0115-ornith-orchestrator-router-complexity.md) | Ornith orchestrator-router + complexity tiers + visible handoff (E+F) (**implemented**, #377) |

Interesting integrations **in** 1.4: [0107](0107-obsidian-linked-memory-brain.md)–[0110](0110-chatgpt-style-approval-popup.md). Bulk catalog **0095–0104** stays later ([`INTEGRATION_SPECS.md`](../../INTEGRATION_SPECS.md)). Post-1.4 optional accelerators: [0116](0116-typesafe-jev-optional-decision-tier.md) TypeSafe Jev decision tier (**implemented**; availability assumptions updated by [0171](0171-system-one-reflex-lane-jev-laya-priority.md) — public Jev still needs real probe + cloud opt-in; local Reflex + Laya preferred), [0117](0117-tiny-front-chat-responder.md) tiny front-chat responder for first visible/audible replies.

**Numbering:** two files share **0117** — [tiny front-chat responder](0117-tiny-front-chat-responder.md) (**implemented**) and [durable-state journal](0117-durable-state-journal-rollback.md) (**implemented**, #380). Do not reuse 0117. **0119 is reserved** for a parallel license-package entitlements RFC — do not take it from this pack.

Taco goals memo (decision, not an implement ticket): [0118](0118-taco-goals-highest-leverage.md). Follow-on implement contracts: [0120](0120-coding-and-3d-real-tools.md) coding+3D real tools (**implemented**, #378); [0121](0121-projects-folder-chats-db-media-placement.md) projects folder + chats-in-DB + media placement (**implemented**, #381). [0109](0109-media-file-video-upload-phone-and-pc.md) amended for explicit OCR. [0123](0123-companion-reachability-and-anti-impersonation.md) companion LAN / port-forward / mobile-relay + anti-impersonation (accepted). [0125](0125-companion-hud-lan-pair.md) companion HUD render + Wi‑Fi pair request (implemented). [0108](0108-phone-companion-offline-ai-model.md) amended 2026-09-18 for pinned pack URL + Leader cache + post-pair popup. [0124](0124-clean-install-reinstall-owned-path-wipe.md) owner Clean Install / Reinstall + owned-path wipe (accepted; P0; layer on RFC-0093). [0136](0136-zombie-kill-setup-next-and-start.md) zombie-kill on Setup installation-method Next and before `start-jarvis.ps1` binds 4780 (accepted; extends RFC-0093; does not rewrite 0124).

**Jarvis 1.4.1 priority bugfix (specs first; do not block RFC-0108):** [0122](0122-ingress-size-gate-spill-and-trajectory-cap.md) ingress size-gate, DB spill (optional Obsidian mirror), trajectory quality cap. RFC-0114 recovery stays; this fixes **what enters** the budget.

Memory recall follow-up: [0132](0132-supermemory-semantic-recall-sidecar.md) adds an optional self-hosted Supermemory semantic sidecar while keeping ContextRepo authoritative, native fallback mandatory, and Obsidian as the owner-editable linked vault.
