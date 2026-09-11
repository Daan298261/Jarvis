# Task status and approvals

## Approval policy

Jarvis automatically runs routine task operations when the active Agent Profile permits execution. It does not interrupt for ordinary reads, writes, commands, tests, builds, research, external requests, or other non-destructive work.

Destructive deletion is the exception. File or directory deletion, destructive cleanup, database deletion/truncation, disk formatting, and commands that discard local state pause in `WAITING_APPROVAL`. The exact pending tool call is stored and runs only after explicit approval. Rejecting it cancels that pending action.

This approval policy does not bypass capability denials, authentication, allowed-directory boundaries, task cancellation, the emergency stop, or hard Agent Profile prohibitions. Those remain enforcement boundaries rather than approval questions.

## Task status UI

Every task API response includes a normalized state, execution phase, start and elapsed time, current activity/tool, active worker, last progress time, heartbeat time/status, and a structured verification summary. Active phases are projected from the existing task and event stream; they do not create a second scheduler or invent percentage-complete estimates.

The portal shows this information in three places:

- The sidebar shows the current phase and heartbeat for active tasks.
- Task detail contains a compact expandable activity panel with the current activity, worker, timing, heartbeat/stale state, and recent actions.
- Task History shows phase, liveness, activity, timing, and worker for all tasks and refreshes while work is active.

The runtime emits an in-memory heartbeat every five seconds while a task coroutine is alive. A task left in an active database state after a restart, crash, or lost runner is marked stale. Waiting for an explicit destructive-delete decision is shown as waiting, not stale.
