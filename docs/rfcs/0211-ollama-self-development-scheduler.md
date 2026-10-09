# RFC-0211 — ANZU-directed Ollama self-development

Status: accepted

## Problem
The owner wants to turn on Away Mode, or say “Hey, I'm AFK, go develop yourself,” and return to validated improvements and a new build. They should not have to select RFC revisions, operate worker controls, approve every merge, or translate that goal into engineering steps. Local Qwen through Ollama, repository and Drive backlog intake, real tool use, and computer vision support this flow.

## Decision
Provide an owner-controlled Away Mode backed by ANZU's existing scheduler. Enabling development Away Mode grants the controller standing authorization to select eligible backlog tasks, implement them, independently review and validate them, merge passing changes into `development`, and build the resulting revision. Do not ask for routine per-ticket or per-merge confirmation while this policy is active. Disabling Away Mode revokes future dispatch and publication authorization.

Execute one named RFC or development-queue item at a time in an isolated registered worktree pinned to a development revision. A separate process runs ANZU's existing tool/verification agent with local Ollama, without switching the owner's chat model. Require tools for the coder and tools plus vision for the screenshot model; route image-bearing turns to the latter. The worker produces changes and evidence; a separate trusted controller owns merge/build credentials and gates. Preserve tool authorization and do not let ticket content change the controller policy.

Drive supports owner imports and recurring refresh through explicitly configured read-only MCP search/fetch tools. A missing connector is an actionable state, never reported as continuous sync. Drive staging digests are reference material rather than automatically executable tickets. Work-item/revision design follows the work-item-bound sessions proposal in jarvis_specs and its 2026-10-09 adoption digest.

## Owner experience
- One visible **Away Mode — develop ANZU** switch, plus the conversational request “I'm AFK, go develop yourself,” activates the same persisted policy. “Stop developing,” “turn off away mode,” or “I'm back” pauses further work. Merely mentioning being AFK in a document or quoting that phrase cannot activate it.
- First activation explains the scope in one sentence: ANZU will work through the backlog, merge verified improvements into development, and prepare new builds. Technical configuration lives in advanced settings; the ordinary flow does not require selecting models, revisions, or worktrees.
- Show a simple state: working, reviewing, testing, building, waiting for priority work, paused, or needs attention. On return, summarize completed tasks, skipped/blocked tasks, test evidence, merged PRs, and downloadable build artifacts. Stay quiet for unchanged/non-actionable state.
- Returning stops new missions and merges. A running mission checkpoints and stops safely; an already-started atomic merge/build operation is reconciled rather than killed mid-write. No automatic installation or restart of the application the owner is using. Automatic development builds are authorized; promotion to `main` and a public stable release require a separate stable-cut instruction.

## Backlog selection and scheduling
- Ingest accepted repository RFCs, actionable items in `JARVIS_MASTER_PLAN.md` §58, and connected Drive tasks that map to this repository. Preserve source identity, content revision, dependencies, priority, completion status, and ticket ownership. Do not edit architect-owned specs to mark completion; record delivery in the task ledger and PR.
- Select automatically by explicit priority, satisfied dependencies, and available resources; use a deterministic oldest-first tie break. Exclude completed, superseded, assigned/claimed, blocked, vague, and conflicting tasks. Claim one exact revision and issue a launch prompt naming exactly one ticket. Refresh completion/ownership from PR and task evidence so an unchanged accepted RFC is not implemented again after merge.
- Each eligible revision inherits the Away Mode policy; manual revision selection is optional advanced control. Changed sources invalidate pending selection/review evidence and require reevaluation. Missing acceptance criteria or ambiguous Drive-to-repository mapping blocks that task rather than inventing scope.
- Dispatch immediately on activation, then continue to the next eligible task after the previous merge/build outcome is reconciled. Periodic scans discover fresh tasks; persist claims, attempts, reviews, merge SHA and build identity to resume without replaying edits or duplicate publication.
- Respect shared-resource ownership. Ollama and Antigravity currently belong to Grokbot's priority reverse-engineering work: keep the reservation active, display “waiting for priority work,” and do not infer availability merely because the model responds. Do not unload models, interrupt another worker, or take its tickets. Reservation release is explicit or comes from a trusted lease coordinator.

## Coding and North Star gates
- Every mission reads `AGENTS.md`, `docs/PROCESS.md`, its named ticket, and the actual `ANZU_PRODUCT_NORTH_STAR.md`. Pin and record the North Star revision with the task. Missing guidance is an actionable blocker; no substitute generic quality prompt.
- Require a focused diff, no unrelated or architect-owned spec edits, appropriate meaningful regression tests, complete error/cancellation handling, preservation of user data and authorization boundaries, and dependency/security review when relevant. Reject stubs, canned success, weakened tests, unexplained test removal, or claims unsupported by execution evidence.
- Run `git diff --check`, focused tests and the full backend suite; run frontend build and lint for frontend changes. Check actual command exit status and test reports. A green CI job whose full-suite step uses `continue-on-error` does not satisfy this gate. Environmental failures remain failures requiring resolution or a blocked task; do not silently accept a baseline exception.
- Independently review the resulting diff and evidence against both RFC acceptance and the North Star: polished, luxurious, easy to use, capable, trustworthy. The implementer's own success assertion is insufficient. Record concrete review findings, repair them, rerun affected checks, and bind approval to the exact tested head SHA.
- For UI/product changes, exercise actual user flows and use screenshots/computer vision to verify presentation, responsiveness, recovery and visual consistency. For inference/tool/vision changes, require the relevant real provider/tool flow. Keep source, live-model, Windows desktop, installed-artifact and release acceptance distinct; missing necessary evidence blocks merge for that task.

## Merge and build
- Create a focused PR targeting `development`; the controller may merge only its own claimed task after all required checks and independent review pass. Do not merge unrelated existing PRs. A changed PR head, review finding, source revision, or relevant base change invalidates approval; reconcile and rerun validation before merge. Preserve branch protection, never bypass checks or force-push shared branches.
- After merge, build the actual resulting `development` merge SHA in a clean build checkout using the repository's Windows packaging pipeline. Produce a usable ANZU development artifact with revision, logs, checksums and location; a frontend bundle or the CI installer compile check with stub payloads is not a completed application build.
- Persist a durable build job keyed by merge SHA, handle failures/retries without repeating the merge, and keep the task in `merged / build failed` until a real artifact passes its packaging checks. Gate dependent tasks on the required delivery outcome. Build capacity must obey priority reservations too.
- Never expose vendor issuer material in public source/customer payloads. Do not alter the owner's installed application or consume stable-release credentials as part of a development build.

## Implementation status
The current PR implements revision-bound RFC intake, isolated Ollama workers, verification, scheduling and resource holds. Automatic backlog selection, the Away Mode owner flow, independent review gates, merge publication and post-merge application build orchestration are required additions. Existing `auto_merge=False` worker settings remain appropriate: only the trusted controller receives publication authority. This RFC must not be declared delivered until the complete Away Mode flow passes the acceptance below.

## Acceptance
- The owner can enable Away Mode with one switch or the direct AFK development request; this automatically claims and executes an eligible backlog ticket without per-ticket selection or routine merge confirmation.
- “I'm back” and emergency stop prevent new missions and publication, with safe checkpoint/reconciliation of in-flight work.
- Automatic selection respects priority, dependencies, ownership, source revisions, completed deliveries and Grokbot's resource reservation. A restart cannot repeat a completed ticket or merge/build.
- Due schedules serialize missions, survive restarts without replaying interrupted edits, and stop after consecutive failures or the emergency stop.
- Execution uses a development base, bounded duration, actual tool use and the coding verification contract. Worker-reported success alone is not accepted as verified delivery.
- Independent code and North Star review, actual full-suite results, appropriate visual/live-tool evidence, and exact-head CI gate merge. Tests demonstrate rejected review, stale head, failing baseline masked by green CI, and concurrent base changes cannot publish.
- A passing mission merges its focused PR into development and starts exactly one real application build for the merge SHA. A build failure is recoverable and never reported as a completed build or causes another merge.
- An end-to-end disposable-repository scenario exercises activate → pick backlog → implement → review/repair → validate → merge → artifact, followed by the next task. Real Windows/Ollama/tool/vision acceptance is separately recorded once the priority reservation is released.
- Image turns use an Ollama model advertising vision; text-only coder models are never given images.
- Source changes invalidate queued revisions; duplicate sources do not create duplicate execution.
- Repository and MCP intake are off the event loop where blocking; settings and supervisor writes are atomic.
- Focused tests and frontend build/lint; Windows local-model/tool/vision evidence recorded separately from source checks.

## Likely files
backend/app/agent/development_scheduler.py, development_worker.py, trusted development review/publication/build controller modules, backend/app/tools/self_development.py, backend/app/api/self_dev.py, backend/app/main.py, backend/app/agent/worktrees.py, frontend/src/pages/SelfDevelopment.tsx, frontend/src/App.tsx, development-build workflow and tests/test_rfc0211_*.py.
