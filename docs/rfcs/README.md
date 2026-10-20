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

PC first-response latency (P0): [0230](0230-pc-first-response-latency.md) — measured breakdown (box + VRPC, sources per number), per-turn latency trace + one-command PC repro (S0), first audible word ≤ 1.5 s target, STT/front/worker-load/TTS/reflex slices (**accepted**; first on shared files; reuses #648/#649).

| RFC | Concern |
| --- | --- |
| [0111](0111-kokoro-real-runtime.md) | Kokoro as real runtime (work package A) |
| [0112](0112-voice-preview-exact-profile.md) | Voice preview exact profile (B) |
| [0113](0113-admin-settings-submenu-1-4.md) | Admin > Settings 1.4 IA deltas (C); RFC-0094 already implemented |
| [0114](0114-context-overflow-preflight-recovery.md) | Context overflow preflight + recovery (D) |
| [0115](0115-ornith-orchestrator-router-complexity.md) | Ornith orchestrator-router + complexity tiers + visible handoff (E+F) (**implemented**, #377) |

Interesting integrations **in** 1.4: [0107](0107-obsidian-linked-memory-brain.md)–[0110](0110-chatgpt-style-approval-popup.md). Bulk catalog **0095–0104** stays later ([`INTEGRATION_SPECS.md`](../../INTEGRATION_SPECS.md)). Post-1.4 optional accelerators: [0116](0116-typesafe-jev-optional-decision-tier.md) TypeSafe Jev decision tier (**implemented**: Settings + `has_feature` Plus + real probe; Jev is publicly usable per RFC-0171 but still requires opt-in + probe; live TypeSafe account is desktop sign-off), [0117](0117-tiny-front-chat-responder.md) tiny front-chat responder for first visible/audible replies.

**Numbering:** two files share **0117** — [tiny front-chat responder](0117-tiny-front-chat-responder.md) (**implemented**) and [durable-state journal](0117-durable-state-journal-rollback.md) (**implemented**, #380). Do not reuse 0117. **0119 is reserved** for a parallel license-package entitlements RFC — do not take it from this pack.

Taco goals memo (decision, not an implement ticket): [0118](0118-taco-goals-highest-leverage.md). Follow-on implement contracts: [0120](0120-coding-and-3d-real-tools.md) coding+3D real tools (**implemented**, #378); [0121](0121-projects-folder-chats-db-media-placement.md) projects folder + chats-in-DB + media placement (**implemented**, #381). [0109](0109-media-file-video-upload-phone-and-pc.md) amended for explicit OCR. [0123](0123-companion-reachability-and-anti-impersonation.md) companion LAN / port-forward / mobile-relay + anti-impersonation (accepted). [0125](0125-companion-hud-lan-pair.md) companion HUD render + Wi‑Fi pair request (implemented). [0108](0108-phone-companion-offline-ai-model.md) amended 2026-09-18 for pinned pack URL + Leader cache + post-pair popup, and 2026-10-08 by [0204](0204-android-anzu-standalone-upgrade.md) (abliterated on-device pack permitted; Instruct packs remain the fallback). [0124](0124-clean-install-reinstall-owned-path-wipe.md) owner Clean Install / Reinstall + owned-path wipe (accepted; P0; layer on RFC-0093). [0136](0136-zombie-kill-setup-next-and-start.md) zombie-kill on Setup installation-method Next and before `start-jarvis.ps1` binds 4780 (accepted; extends RFC-0093; does not rewrite 0124).

**Jarvis 1.4.1 priority bugfix (specs first; do not block RFC-0108):** [0122](0122-ingress-size-gate-spill-and-trajectory-cap.md) ingress size-gate, DB spill (optional Obsidian mirror), trajectory quality cap. RFC-0114 recovery stays; this fixes **what enters** the budget.

Memory recall follow-up: [0132](0132-supermemory-semantic-recall-sidecar.md) adds an optional self-hosted Supermemory semantic sidecar while keeping ContextRepo authoritative, native fallback mandatory, and Obsidian as the owner-editable linked vault.

**2026-09-28 Instagram batch** (next free after [0182](0182-context-and-segmented-agentic-tasks.md) was **0183**): [0183](0183-obsidian-agent-skills-pack.md)–[0191](0191-pentest-harness-catalog-sibling.md). Comment-scrape follow-up: [0192](0192-strands-harness-sdk-evaluation.md) (Strands Harness SDK; not in the 36-URL grid). Living impact order: [`INTEGRATION_SPECS.md`](../../INTEGRATION_SPECS.md). Does not replace the 0095–0116 ladder. Voice alternatives: [0193](0193-voice-alternatives-and-installer-choices.md). Presence idle restore: [0194](0194-restore-presence-idle-and-framing.md) (**implemented** #466; idle-hide + 680∶480 primary stage **superseded** by [0195](0195-visual-acceptance-and-presence-stage.md)). Visual acceptance contract: [0195](0195-visual-acceptance-and-presence-stage.md) (**accepted**; not implemented). Settings split restore: [0094](0094-settings-menu-information-architecture.md) 2026-09-30 amend. Cyber/LTA: [0198](0198-blue-re-lta-protected-folder.md) LTA protected folder; [0200](0200-rea-mcp-local-investigation.md) REA MCP local investigation (**accepted**); [0201](0201-reverse-engineer-anything.md) reverse-engineer anything (**accepted**). Fast-path consolidation: [0203](0203-fast-path-lane-consolidation.md) (**accepted**). Graceful context scaling: [0202](0202-graceful-context-scaling.md) (**landed** #549). Android ANZU standalone upgrade: [0204](0204-android-anzu-standalone-upgrade.md) (**accepted**; amends 0108). DeepHat Red 7B auto-start: [0205](0205-deephat-auto-start.md) (**accepted**). Every-turn Jev/Laya arbitration: [0206](0206-jev-laya-every-turn-arbitration.md) (**accepted**). Jarvis Architect reverse-engineering specs: [0207](0207-apk-reverse-sidecar.md) APK reverse sidecar and [0208](0208-ffs-dump-self-ingest.md) FFS dump self-ingest (both on `development`). Autonomous memory capture: [0209](0209-autonomous-memory-capture.md) (**accepted**). Performance Compass: [0214](0214-performance-compass.md) (**accepted**; backlog behind RE). Android settings slices (secure screen, off-grid, STT, TTS, downloads): [0216](0216-android-settings-secure-offgrid-voice-downloads.md) (**accepted**). Persona UI layouts A/B/C + intent-driven auto persona switch: [0218](0218-persona-surfaces-and-intent-switch.md) (**accepted**). Chrome website connector: [0217](0217-chrome-website-connector.md) (**landed** #627).

**2026-10-17 ANZU bug + feature batch (Taco; specs 2026-10-20, priority order, bugs first):** [0225](0225-local-engine-coexistence-and-resilient-api.md) local engine coexistence + resilient local-API connection (P0, bug 2; **accepted**, this PR #652); [0226](0226-reliable-kokoro-and-voice-fallback.md) reliable Kokoro load + automatic visible voice fallback (P0, bug 1; amends RFC-0092 intent-preserving; **landed** #653, `89c1dd3e`); [0227](0227-model-chooser-and-dropdown-persistence.md) model chooser popup responsiveness/frequency + HUD dropdown persistence (P1, bugs 3–4; **landed** #654, `9f48ec77`); 0228 installer Update mode, Defiant-Fable 9B default with idle unload, installed/greyed + "can be updated to" (P2, items 5–7; **reserved**, open specs-only [PR #655](https://github.com/Daan298261/Jarvis/pull/655), not yet on `development`, so not linked as a file); [0229](0229-anzu-manager-debug-and-process-monitor.md) ANZU Manager debug logger, button feedback, spawned-process monitor (P2, items 8–9; **landed** #656, `273b1b09`; errata #667, `a44da353`). The Architect turns 0228 into a file link after #655 merges. **Numbering:** 0219–0222 are on `development`. [0223](0223-startup-model-selection-stability.md) (#648, `d214b6d`) and [0224](0224-responsive-conversation-and-durable-task-prompts.md) (#649, `ee786dc`) have **landed**. Open #650 still carries a second `0223-android-solar-context-and-live-replies.md` and must be renumbered before it lands. 0229's errata landed with #667 (`a44da353`). [0230](0230-pc-first-response-latency.md) has **landed** (#666, `94a62fa`). Reserved by open PRs: **0231** #665, **0232** #664, **0233** #668, **0234** #650 (Astra), **0235** #671. **Next free is 0236.**
