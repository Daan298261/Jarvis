# RFC-0133: Argus intelligence personality, specialist routing, and persona workspaces

**Status:** accepted  
**Queue item:** Specialist personalities / adaptive model routing  
**Author:** ChatGPT implementation session  
**Date:** 2026-09-24

## Problem

Jarvis already has lightweight session modes and HUD themes, but they are prompt presets rather than durable specialist workspaces. Intelligence work needs a dedicated analyst identity, evidence/provenance discipline, direct access to the intelligence provider, its own conversation stream, and a dashboard-oriented HUD. More generally, Anzu needs a safe way to hand a request to an existing specialist without forcing the owner to select a persona manually. The current top drawers also compete for screen space and personality selection is buried in Settings.

## Research findings

Routing should be explicit and inspectable: classify a request, select a specialist, then route to the specialist workflow/model, with manual override. This follows the common routing/supervisor pattern rather than letting every persona independently seize control. Conversation memory should be partitioned by persona/session while selectively retrieving relevant cross-persona history; blindly injecting all history causes context pollution. For intelligence analysis, source provenance, freshness, uncertainty, competing hypotheses, and a distinction between reports and verified facts are mandatory design properties.

References:
- AWS Prescriptive Guidance, workflow for routing: https://docs.aws.amazon.com/prescriptive-guidance/latest/agentic-ai-patterns/workflow-for-routing.html
- Microsoft multi-agent memory reference architecture: https://microsoft.github.io/multi-agent-reference-architecture/docs/memory/Memory.html
- OpenAI Agents SDK memory isolation: https://openai.github.io/openai-agents-js/guides/sandbox-agents/memory/
- Crucix provider contract: RFC-0127.

## Decision

Add **Argus**, named for the many-eyed watchman of Greek mythology, as the intelligence specialist. Argus is additive; Anzu remains the main identity. Existing coding/research/concise modes remain available.

Extend `SessionMode` into a specialist descriptor with a short description, icon, accent, preferred model/task-class hints, auto-routing keywords and a manual-lock state. Anzu is the router. On each owner turn, explicit user switches win; otherwise, when automatic routing is enabled and the current persona is not manually locked, deterministic high-confidence classification selects the specialist. Ambiguous requests remain with Anzu. Routing emits a `session_mode` event so the HUD changes in the same turn. Model selection uses the existing model/profile manager: a specialist supplies a preferred profile hint, but unavailable models fall back to the current valid profile instead of failing the turn.

Argus prompt contract: intelligence questions use source-grounded collection and analysis; distinguish observation, report, inference and assessment; preserve source URL/timestamp/freshness where available; state confidence and material gaps; consider plausible competing hypotheses for consequential assessments; never invent attribution. Argus can use RFC-0127 `intelligence` tools through normal policy gates. The UI provides an Intelligence entry/dashboard link when available.

Create a persistent left-side **Personality Rail** in HUD mode. Its compact icon never overlaps top chrome. Opening it closes Activity/Projects/System/Admin/Help/model overlays through the existing single-overlay state. The drawer lists name + specialization and supports manual selection. Argus uses an added amber/gold multi-eye/constellation variation of the existing glowing-particle system; existing orb implementations are not replaced.

Conversation ownership becomes `persona_id + conversation_id`. Each persona gets its own visible history. Cross-persona access is retrieval, not automatic transcript injection: a specialist may request/search owner-visible history from other personas, with source persona/conversation metadata, bounded results and no hidden reasoning. Switching persona resumes that persona's most recent conversation or starts one. A routing handoff may include the current user request and a compact bounded handoff context, not the entire source transcript.

## Acceptance criteria

- [ ] Argus appears in the session-personality API with mythical identity, specialization, HUD theme, icon/accent and intelligence prompt contract.
- [ ] Explicit manual selection works and sets a manual lock; returning to Auto lets Anzu route subsequent turns.
- [ ] High-confidence intelligence prompts auto-route to Argus before worker inference; coding/research prompts continue to route to their specialists; ambiguous chat remains Anzu.
- [ ] A route event includes source, target, reason, confidence and whether it was manual/automatic; it is visible to the frontend and auditable.
- [ ] Specialist model/profile hints use existing model management and degrade to the loaded/default profile when unavailable.
- [ ] HUD has a left Personality Rail; opening it closes competing drawers/menus and CSS prevents drawer overlap at desktop and narrow widths.
- [ ] Argus adds a distinct glowing-dot/constellation visual theme without replacing NeuralOrb/ParticleOrb.
- [ ] Each persona has a separately keyed visible chat history and switching personas does not overwrite another persona's transcript.
- [ ] Cross-persona history retrieval is explicit, bounded, source-labelled, owner-scoped and excludes hidden reasoning.
- [ ] Argus can invoke the enabled intelligence provider through the normal tool/policy layer and renders provenance/freshness/uncertainty in intelligence output.
- [ ] Existing core/coding/research/concise behavior remains backward compatible.
- [ ] Unit tests cover classification precedence, manual lock, fallback, persona history isolation and cross-persona retrieval boundaries.
- [ ] `python3 -m pytest` passes.
- [ ] `npm --prefix frontend run build` passes.

## Likely files

| Area | Paths |
| --- | --- |
| Backend | `backend/app/persona/session_personality.py`, `backend/app/persona/owner_chat.py`, `backend/app/api/session_personality.py`, `backend/app/inference/*`, `backend/app/projects/portal_store.py` |
| Intelligence | `backend/app/tools/intelligence.py`, `backend/app/integrations/crucix/*` |
| Frontend | `frontend/src/hud/HudShell.tsx`, `frontend/src/hud/sessionPersonality.ts`, new personality rail, orb theme/CSS, chat view |
| Tests | `tests/test_session_personality.py`, persona-history/router tests |
| Docs | this RFC |

## Out of scope

Training/fine-tuning a new model; replacing the existing orb renderer; unrestricted sharing of hidden reasoning; autonomous consequential actions based solely on OSINT; deleting legacy UI; forcing Crucix installation when Argus is selected.

## Notes

Routing is a capability decision, not role-play. UI identity, system prompt, tool exposure and model preference must switch as one atomic route state. The router must remain cheap and deterministic for obvious cases; a model classifier can be added later behind the same interface for ambiguous cases.
