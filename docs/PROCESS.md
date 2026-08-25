# Jarvis development process

This document fixes the broken loop where vague prompts ("continue Jarvis development", "pick up priority tasks", "merge all PRs") caused workers to re-audit the tree, rewrite **Current State**, and open colliding branches.

**Canonical repo:** [Daan298261/Jarvis](https://github.com/Daan298261/Jarvis)  
**Integration branch:** `cursor/local-qwen-desktop-agent` (treat as default; `main` is stale)  
**Origin mirror:** `taco-1/Jarvis` may lag; always branch and PR against **Daan298261/Jarvis**.

---

## Roles

| Role | Does | Does not |
| --- | --- | --- |
| **Jarvis Architect** | Sole editor of `JARVIS_MASTER_PLAN.md`, `SWARM_ARCHITECTURE.md`, `ADAPTIVE_DOMAIN_ARCHITECTURE.md`, `ANDROID_CLIENT.md`, `JARVIS_2.0.md`, `HOME_IOT.md`, `SECURITY_AGENTS.md`, the `BLUE_TEAM.md` pointer, `INSTALLER.md`, `WINDOWS_SHELL.md`, and `PORTAL_UX.md`. Applies spec-change requests from Taco or Chief of Staff. | Execute product tickets; paste megabyte dumps into the master plan |
| **ChatGPT / Codex (design)** | Write RFCs under [`docs/rfcs/`](rfcs/) | Edit spec docs; rewrite `JARVIS_MASTER_PLAN.md`; paste megabyte spec updates into the master plan |
| **Cursor cloud worker (implement)** | Implement **one** named RFC or **one** named Development Queue item | Edit spec docs; "Continue all development"; merge unrelated PRs; re-audit the repo; rewrite §57 Current State |
| **Windows desktop session (sign-off)** | Live 9B/27B load, `tests/run_e2e.py`, GPU/tok/s harness | Cannot be done on Linux cloud VMs (see below) |

---

## One-ticket loop (implementers)

Every Cursor cloud run must be launched with a **named ticket**, for example:

> Implement RFC `docs/rfcs/0007-playwright-retry.md` on branch `cursor/playwright-retry-99ea` against `cursor/local-qwen-desktop-agent`.

or:

> Implement Development Queue item **P1 — Playwright reliability on the target PC** (code + tests only; live e2e is desktop sign-off).

### Steps

1. **Read the ticket** — the RFC file or the single queue item in `JARVIS_MASTER_PLAN.md` §58.
2. **Branch** from latest `cursor/local-qwen-desktop-agent`:
   ```bash
   git fetch origin cursor/local-qwen-desktop-agent
   git checkout cursor/local-qwen-desktop-agent
   git pull origin cursor/local-qwen-desktop-agent
   ```
   Then create your feature branch: `git checkout -b cursor/<short-slug>-99ea`
3. **Implement only that ticket** — touch files listed in the RFC; no drive-by refactors, no new architecture in the master plan.
4. **Test** — `python3 -m pytest`; if frontend changed, `npm --prefix frontend run build` (and `npm --prefix frontend run lint` if you touched TS).
5. **Do not edit spec docs.** Executing agents must not edit `JARVIS_MASTER_PLAN.md`, `SWARM_ARCHITECTURE.md`, `ADAPTIVE_DOMAIN_ARCHITECTURE.md`, `ANDROID_CLIENT.md`, `JARVIS_2.0.md`, `HOME_IOT.md`, `SECURITY_AGENTS.md`, `BLUE_TEAM.md`, `INSTALLER.md`, `WINDOWS_SHELL.md`, or `PORTAL_UX.md`. Note queue/status implications in the PR for Jarvis Architect. Spec-change requests come from Taco or Chief of Staff and are implemented only by Architect.
6. **Open one PR** against `cursor/local-qwen-desktop-agent` with the RFC id or queue item in the title.

### Forbidden prompts (do not use)

- "Continue Jarvis development"
- "Pick up priority tasks"
- "Merge all PRs"
- "Audit the repo and update the master plan"
- Any prompt without a **single** RFC path or queue item name

### Forbidden worker actions

- Merging or rebasing unrelated open PRs
- Closing PRs except when explicitly named in the ticket (or when documenting superseded PRs in process docs)
- Replacing §57 Current State with a full re-audit
- Editing `JARVIS_MASTER_PLAN.md`, `SWARM_ARCHITECTURE.md`, `ADAPTIVE_DOMAIN_ARCHITECTURE.md`, `ANDROID_CLIENT.md`, `JARVIS_2.0.md`, `HOME_IOT.md`, `SECURITY_AGENTS.md`, `BLUE_TEAM.md`, `INSTALLER.md`, `WINDOWS_SHELL.md`, or `PORTAL_UX.md` (Architect-only)
- Adding Jarvis 2.0 / swarm / Browser Use / model-stack work unless that is the named ticket
- Adding offensive / red / counter-response capability (tools, payloads, hack-back skills, enabling Red beyond the refuse-stub). **Hard guardrail:** only Taco (manual) or PolitieGPT (named LE bot, under the LE gate) may add it. Developers, PR fixer, CoS, generic cloud agents, and home Jarvis self-dev must not. See `SECURITY_AGENTS.md` §3.4.
- Overwriting `installer/windows/` files unless that is the named installer **implementation** ticket. Architect specs are `INSTALLER.md` / `WINDOWS_SHELL.md` (outcomes only).
- Editing voice backend files unless that is the named voice ticket (D1 owns the listen/system-message crash fix).

---

## Design handoff (RFCs)

New design lands in [`docs/rfcs/`](rfcs/), not in the master plan.

1. Copy [`docs/rfcs/TEMPLATE.md`](rfcs/TEMPLATE.md) → `docs/rfcs/NNNN-short-slug.md`.
2. Fill problem, decision, acceptance criteria, likely files.
3. Set status to `accepted` when ready for implementation.
4. Do not edit spec docs. Optionally note a matching §58 queue line in the RFC for Architect.
5. After merge, set RFC status to `implemented`. Jarvis Architect ticks the queue item.

See [`docs/rfcs/README.md`](rfcs/README.md).

---

## Linux cloud VM limits

Cloud agents run headless Linux **without GPU** and **without Windows COM/desktop tools**.

| Check | Cloud VM | Windows desktop session |
| --- | --- | --- |
| `python3 -m pytest` | Yes | Yes |
| Frontend build/lint | Yes | Yes |
| API with `JARVIS_SKIP_MODEL=1` | Yes | Yes |
| Load Qwen 9B/27B GGUF | No | Yes — **P0 sign-off** |
| `tests/run_e2e.py` / `tests/smoke_task.py` | No | Yes — **P0 sign-off** |
| Live harness tok/s / VRAM | No | Yes |
| Office / pywinauto desktop tool | No | Yes |

**Rule:** A cloud worker may implement and unit-test P0 code, but **cannot** mark P0 live-model or Windows e2e queue items as VERIFIED. Leave them `TODO` or `CODE PRESENT` and note "desktop sign-off required" in the PR.

---

## Cursor cloud worker defaults

| Setting | Value |
| --- | --- |
| **Base branch** | `cursor/local-qwen-desktop-agent` |
| **Default model** | **Composer 2.5** (standard — not Fast) for cost |
| **Grok 4.6** | Sparingly — only for genuinely difficult tasks named in the ticket |
| **Branch naming** | `cursor/<short-slug>-99ea` |

Worker bootstrap details: [`AGENTS.md`](../AGENTS.md).

---

## Superseded pull requests

| PR | Status | Action |
| --- | --- | --- |
| [#25 Reconcile canonical Jarvis stack](https://github.com/Daan298261/Jarvis/pull/25) | **Superseded** | **Closed — do not merge.** Integration branch already contains merged work; merging would reintroduce a large conflicting diff. |

If GitHub API access from a mirror is blocked, leave this table in place and mention the PR in your worker PR description.

---

## Quick prompts (copy/paste)

**ChatGPT — new design**

> Add an RFC under `docs/rfcs/` for [one concern]. Use `TEMPLATE.md`. Do not edit Architect-owned spec docs (`JARVIS_MASTER_PLAN.md`, `SWARM_ARCHITECTURE.md`, `ADAPTIVE_DOMAIN_ARCHITECTURE.md`, `ANDROID_CLIENT.md`, `JARVIS_2.0.md`, `HOME_IOT.md`, `SECURITY_AGENTS.md`, `BLUE_TEAM.md`, `INSTALLER.md`, `WINDOWS_SHELL.md`, `PORTAL_UX.md`).

**Cursor worker — implement**

> Implement `docs/rfcs/NNNN-slug.md` only. Branch from `cursor/local-qwen-desktop-agent` as `cursor/<slug>-99ea`. Run pytest. Do not edit spec docs. Open PR against `cursor/local-qwen-desktop-agent`. Do not merge other PRs. Composer 2.5 standard model.

**Desktop sign-off (human)**

> On Windows with GGUFs loaded: run `python tests\run_e2e.py`. If pass, ask Jarvis Architect to tick queue item [name] in §58.
