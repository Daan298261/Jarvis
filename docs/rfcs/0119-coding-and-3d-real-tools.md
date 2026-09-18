# RFC-0119: Coding and 3D modelling — real tool calls

**Status:** accepted  
**Queue item:** (none — no new §58 checkbox; implement is a named follow-up after CoS names it)  
**Author:** Jarvis Architect  
**Date:** 2026-09-18

**Parent / index:** [RFC-0118](0118-taco-goals-highest-leverage.md) rank 3 (Taco goal 2).  
**Related (do not rewrite):** [RFC-0005](0005-isolated-parallel-coding-workers.md) (`implemented` — worktree isolation). [RFC-0107](0107-obsidian-linked-memory-brain.md) per-turn tool search. [RFC-0110](0110-chatgpt-style-approval-popup.md) (`implemented` — approvals when policy requires). [RFC-0115](0115-ornith-orchestrator-router-complexity.md) specialist/expert routing. Native tools: `filesystem`, `terminal`, `python`, `git`, `verify_code`. Optional `code_worker` (OpenHands). `PORTAL_UX.md` `/coding` page.

This PR is **specs-only**. Product code is a follow-up implement ticket. Full intent; **no stubs / soft-fail**.

## Problem

Taco needs Jarvis to **call real tools** for **coding** and **3D modelling**, not describe the work in chat.

Today:

- RFC-0005 isolates coding workers in Git worktrees. That is necessary and **not** sufficient.
- Native edit/run/test tools exist (`filesystem`, `terminal`, `python`, `git`, `verify_code`). Software-engineering exposure currently seeds `filesystem` / `terminal` / `python` / `git` and does not require those tools to actually run before a coding task may complete.
- `code_worker` delegates to OpenHands when installed; missing OpenHands already falls back to native tools in tests — that fallback must remain a **real** edit/run/test path, not a chat-only completion.
- There is **no** Blender, OpenSCAD, or documented local DCC tool in the registry. A 3D ask cannot execute.

A coding turn that “finishes” with pasted source and no tool call is a **fail**. A 3D turn that writes a `.blend` / `.stl` comment without invoking a local DCC CLI is a **fail**. A tool that returns success when the binary is missing is a **fail**.

## Decision

Add a **coding + 3D execution contract**: the agent must **search, pull, and call** real tools. Isolation (RFC-0005) and approvals (RFC-0110) stay. Ornith / `front_responder` must not be the coding or 3D worker (RFC-0115).

### 1. Coding — required tool loop

For a software-change ask (edit, fix, implement, refactor, add tests), the worker **must**:

1. **Search** installed and installable tools (RFC-0107 §7) and pull the matched schemas for this turn — not the whole catalog.
2. **Edit** via `filesystem` (and/or `git`) against the RFC-0005 worktree, not by dumping the only copy of the change into chat.
3. **Run** via `terminal` and/or `python` as the change requires (install, script, server, formatter).
4. **Test / verify** via `verify_code` (pytest when a Python layout exists) or the project’s documented test command through `terminal`. RFC-0005’s rule stands: a worker saying “tests pass” is not completion.
5. Record the diff, commands, and verifier output on the task. Integration still requires verifier or configured human approval (RFC-0005).

Optional OpenHands / other coding workers may run **inside** that loop. If they are missing, native tools **must** still edit, run, and verify. Chat-only code is not an acceptable shipped path.

### 2. 3D modelling — required local DCC path

Register at least one **real** 3D tool family, discovered by RFC-0107 search:

| Engine | Required v1 behavior when installed |
| --- | --- |
| **Blender CLI** | `blender --background --python <script>` (or documented equivalent) against an owner-allowed path; produce/modify a `.blend` / export (e.g. `.stl` / `.obj` / `.glb`) on disk; return the output path. |
| **OpenSCAD** | `openscad -o <out> <in>` (or documented equivalent) to compile a `.scad` into a mesh/export on disk. |
| **Documented local DCC** | If the owner has another local DCC with a **documented CLI** (FreeCAD, CadQuery headless, etc.), the same tool interface may call it. One shipped adapter in v1 is enough **in addition to** probing Blender and OpenSCAD. |

Missing binary: **stated install CTA** (RFC-0090 / Module Catalog when a pack exists) — not a fake mesh, not “done” with a markdown cube, not a silent skip. Do not vendor Blender/OpenSCAD into git. GPU-heavy DCC follows existing unload/checkpoint rules when it would fight the resident chat model.

3D outputs are RFC-0021 artifacts and, when a project is selected, live under RFC-0120 media/artifact placement — implement 0119 must not invent a second blob store.

### 3. Approvals and policy

Side-effecting writes, shell, and DCC execution go through existing RFC-0002 / RFC-0027 / RFC-0031 policy. RFC-0110 shows Always allow / Allow this time / Deny **only** when a gated step actually needs a decision. Ordinary “what does this function do?” stays ungated and does not require this loop.

**Will not:** stub 3D tools; treat RFC-0005 as the whole coding product; make OpenHands required; let Ornith/front_responder execute coding/3D; invent LE/Red/Purple gates; put exploit recipes in tool docs; rewrite RFC-0108.

## Acceptance criteria

- [ ] Specs-only in this PR
- [ ] Coding software-change tasks cannot complete without real **edit + run + test/verify** tool calls on the worktree (tests prove a chat-only completion is rejected)
- [ ] Missing OpenHands still uses native tools that actually write/run/verify
- [ ] Blender CLI and OpenSCAD (and/or one documented local DCC) are first-class tools; missing binary is an install CTA, not success
- [ ] RFC-0107 search pulls coding/3D tools for matching asks; unused catalog is not stuffed
- [ ] RFC-0110/policy still gate irreversible/shell/DCC as today; no new authorization theater
- [ ] RFC-0005 isolation unchanged
- [ ] Implement follow-up: `python3 -m pytest` (`tests/test_rfc0119_*.py`). Live Blender/OpenSCAD and Windows worktrees are desktop sign-off

## Likely files

| Area | Paths |
| --- | --- |
| Backend | `backend/app/tools/` (new DCC tool + registry); `backend/app/agent/tool_exposure.py`; `backend/app/agent/coding_workers.py`; `backend/app/agent/loop.py` completion rules; `verify_code` wiring |
| Frontend | `/coding` status only if needed; no fake 3D viewport required in v1 |
| Tests | `tests/test_rfc0119_*.py` — coding loop required calls; missing-DCC CTA; search pulls blender/openscad |
| Docs | this RFC; RFC-0118 pointer |

## Out of scope

Product implementation in this PR. RFC-0108. BlackGrid image/video gen (0096/0097). Cloud CAD. HexStrike. Swarm scheduling. PORTAL_UX rewrite.

## Notes

- Implement after RFC-0115 so specialist/expert routing exists. Recommended strong coding model for the implement ticket; Composer 2.5 may write tests under review.
- Linux cloud: unit-test the contract with fake CLIs on PATH. Live Blender/OpenSCAD is Windows/desktop sign-off.
