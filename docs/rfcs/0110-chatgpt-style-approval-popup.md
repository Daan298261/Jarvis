# RFC-0110: ChatGPT-style approval / review popup

**Status:** accepted  
**Queue item:** (none — no new §58 checkbox; implement is a follow-up after CoS names it)  
**Author:** Jarvis Architect  
**Date:** 2026-09-17

**Parent / index:** light pointer in [`INTEGRATION_SPECS.md`](../../INTEGRATION_SPECS.md) (does **not** reorder Taco ladder 0107–0109).  
**Related (do not rewrite):** RFC-0002 autonomy + approval-required actions. RFC-0027 semantic firewall `REQUIRE_APPROVAL`. RFC-0031 reversibility-first gates + unforgeable `ApprovalGrant`. RFC-0067 owner chat hides plan/approval chrome (implemented — keep default conversational). RFC-0079 computer-use permission selector (Allow once / Always / Don’t allow **catalog** for computer/network/cyber flags). RFC-0081 spoken grants. RFC-0107 durable brain (high-impact memory mutations still need a human decision — **this** is that UI).

This PR is **specs-only**. Product code is a follow-up implement ticket. Full intent; **no stubs / soft-fail** (a chip that auto-dismisses to allow, a modal that never parks the tool, or a persistent “Review or approval is required” gate on ordinary chat is a fail).

## Problem

Jarvis still feels gated on **ordinary owner chat**. HUD orb copy uses “Review or approval is required” (`frontend/src/hud/HudChatHome.tsx`) as an attention state; tasks park behind `waiting_for_confirmation` in ways that make daily conversation wait on a gate. RFC-0067 hid PLAN/ACCEPTANCE chrome, but the product still lacks the ChatGPT-style **modal that appears only when the model/tool flow actually needs a decision or typed input**.

RFC-0079 already specified Allow once / Always / Don’t allow for the **computer-use permission catalog**. That is not the same as a general review popup with optional free-text, and it must not become an always-on bar in front of every chat turn.

Taco’s add: a **ChatGPT-style approval / review popup** — Always allow / Allow this time / Deny, optional typed input, persist Always allow per tool/action class — and **natural daily chat stays ungated**.

## Decision

Ship one owner-facing **decision modal**. Show it **only** when the live model/tool flow needs a human choice or typed input. Stream ordinary replies with **no** approval gate.

### 1. When the modal appears

Show the popup if **and only if** at least one of these is true for the current step:

- Policy / RFC-0002 / RFC-0027 / RFC-0031 requires a human decision before a side-effecting tool/action runs (irreversible, destructive, credential, financial, external, or `REQUIRE_APPROVAL`).
- The tool/action class is in `ask` (not previously Always-allowed) and would actually execute.
- The model/tool flow needs **typed owner input** this step cannot invent (filename to keep, short instruction, clarification the policy marked as human-only, review note). A model-supplied `confirmed=true` argument is **not** typed owner input (RFC-0031).

Park the durable step (RFC-0029 / RFC-0031): release the worker/model while waiting; resume the **same** step on decide. Do not spend an extra model round-trip solely to re-ask.

### 2. When the modal must **not** appear

- Ordinary owner conversation: greetings, Q&A, streaming assistant text, RFC-0083 follow-ups, RFC-0085 direct replies, RFC-0067 launch greeting.
- Turns that do not execute a gated tool/action and do not need typed human input.
- Always-allowed tool/action class (section 4) on a repeat that matches the persisted scope — do not re-prompt.
- Debug “Show agent plan & approvals” (RFC-0067, default **off**) may show extra chrome; it must not re-introduce an always-on gate on default chat.

Default HUD/chat must **not** present “Review or approval is required” as the idle or ordinary-talk state. Attention copy is allowed **only while a real pending decision exists**.

### 3. Modal chrome (ChatGPT-like)

One modal (portal / Daybreak HUD / owner chat; companion should present the same three choices when a Leader-gated step is waiting). Not a persistent ticket board.

**Scoped choices (required):**

| Choice | Meaning |
| --- | --- |
| **Always allow** | Allow this invocation **and** persist for this **tool/action class** (section 4) so repeats do not re-prompt. |
| **Allow this time** | Allow **this** invocation only. Next time the class is gated again, ask again. |
| **Deny** | Reject this invocation. Cancel that parked step. Do not run the tool. |

**Review / typed input (required when the step needs it; optional otherwise):**

- A free-text field on the same modal (placeholder e.g. “Add a note or extra instruction”).
- Owner text is attached to the `ApprovalGrant` / denial record as `owner_note` (bounded length; never a secret dump in logs).
- If the step **requires** typed input, **Allow this time** / **Always allow** stay disabled until the field is non-empty (or a documented equivalent control is filled). Deny remains available.
- Voice: RFC-0081 spoken grants may fill the same three choices; typed text stays available.

Do **not** require a fourth “Allow this session” button in v1 (RFC-0079 may keep session grants **inside** the computer-use catalog). Unifying chrome is good; shipping two stacked always-on bars is a fail.

### 4. Persist Always allow

Persist per **tool/action class**, not a global “never ask again”:

- Key: tool name and/or action class already used by policy (e.g. `filesystem.delete`, `computer.this_device`, a named worker). Narrower beats a blanket “all tools.”
- Store with actor/session, scope, timestamp, policy version; reversible from Settings (revoke Always allow).
- Reuse `data/computer-permissions.json` / `backend/app/policy/computer_permissions.py` **where the class already lives**; add a general grant store for classes RFC-0079 does not cover. One owner-visible Settings list; not two conflicting truths.
- Grants are **owner-channel only**. Model/tool arguments cannot create Always allow (RFC-0031).
- Deny is not persisted as a forever ban unless Settings already has an explicit disable; Deny means this invocation.

Repeats of an Always-allowed class skip the modal and execute (firewall/policy can still BLOCK; Always allow cannot weaken a deterministic deny).

### 5. Streaming chat stays ungated

Owner types → Jarvis **streams** the assistant reply (RFC-0061/0067/0075) with no interstitial approval.

If mid-stream the agent decides a gated tool is required: finish or pause visible streaming per existing speak-filter rules, **then** open this modal. Do not rewind the whole chat into a PLAN/ACCEPTANCE board. Do not hold the first token of a normal reply behind the popup.

### 6. Relationship to RFC-0079

RFC-0079 remains the **computer-use / network / cyber flag catalog** (More panel, spoken grants). This RFC is the **general** decision popup for any tool/action class that actually needs a human, including review text.

Implement should **extend** `frontend/src/chat/PermissionPrompt.tsx` (and HUD/classic/phone variants) into this modal rather than a second competing widget. RFC-0079 catalog rows still map to Always allow / Allow this time / Deny. Offensive/Red flags stay default-deny as already specified there; **this ticket does not invent LE/Red/Purple/ATO gates** and does **not** document exploits.

**Will not:** always-on chat gate; stub modal; auto-allow on timeout as the shipped path (timeout **cancels** the parked step unless Settings documents an explicit owner-chosen timeout policy); model self-confirm; rewrite RFC-0107/0108/0109; HexStrike operator rewrite.

## Acceptance criteria

- [ ] Specs-only in this PR (no product code)
- [ ] Ordinary owner chat streams replies with **no** approval modal and **no** idle “Review or approval is required” gate
- [ ] Modal appears only when a gated tool/action would run or typed owner input is required for that step
- [ ] Modal offers **Always allow**, **Allow this time**, **Deny**, plus optional/required free-text as specified
- [ ] Always allow persists per tool/action class; repeats of that class do not re-prompt; Settings can revoke
- [ ] Allow this time does not persist; Deny cancels the parked step
- [ ] Required free-text blocks Allow until filled; owner note is stored on the grant/denial; model `confirmed=true` cannot satisfy it
- [ ] Park/resume uses the same durable step; no extra model round-trip just to re-ask
- [ ] Always allow cannot override a deterministic policy/firewall deny
- [ ] Tests: ungated conversational turn; gated tool shows modal; Always allow skip on repeat; Allow this time re-asks; Deny does not execute; required text; no self-confirm via tool args
- [ ] Implement follow-up: `python3 -m pytest`; `npm --prefix frontend run build` (portal)

## Likely files

| Area | Paths |
| --- | --- |
| Backend (implement PR only) | `backend/app/policy/computer_permissions.py`, `backend/app/policy/authorize.py`, `backend/app/api/permissions.py`, `backend/app/agent/loop.py` (park `waiting_for_confirmation` **only** for real decisions), approval grant store, RFC-0031 provenance fields + `owner_note` |
| Frontend (implement PR only) | `frontend/src/chat/PermissionPrompt.tsx`, `permissionPrompt.css`, `OwnerChatTranscript.tsx`, `frontend/src/hud/HudChatHome.tsx` (idle copy must not claim approval is required), Settings grants list, Phone/companion pending decision |
| Tests | `tests/test_rfc0110_*.py` (and extend `tests/test_computer_permissions.py` / owner-chat greeting tests) |
| Docs | this RFC; light pointer in `INTEGRATION_SPECS.md`; `JARVIS_MASTER_PLAN.md` §59 only |

## Out of scope

Product implementation in this PR. New LE/Red/Purple/ATO product gates. Exploit recipes. RFC-0107 vault indexer. RFC-0108 on-device model. RFC-0109 media ingest. Replacing RFC-0002 / RFC-0027 / RFC-0031 policy engines. Guest-portal approval redesign. Timeout-as-silent-allow.

## Notes

- Source: Taco 2026-09-17 follow-up after RFC-0107–0109. Next free RFC number after 0109 is **0110**.
- Linux cloud can unit-test grant persistence + “conversational turn does not set `waiting_for_confirmation`.” Live HUD modal + TTS spoken grants remain Windows desktop sign-off.
- Implement launch: this RFC only; branch from `development`; pytest + frontend build; do not edit Architect spec docs; PR against `development`; do not merge other PRs.
