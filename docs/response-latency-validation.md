# RFC-0247 validation

Implemented in `cursor/response-latency-99ea`, stacked on the MCP runtime fixes in PR #692. Keep that dependency when landing or installing this change.

## Behavior

Task completion and optional follow-up jobs are committed together. Completion is then published before trajectory learning, coding usage accounting, skill promotion and owner-chat speech dispatch. Two bounded serial async lanes keep slow learning from delaying subsequent delivery. Jobs have a 60-second timeout and up to three attempts with backoff. Interrupted pending jobs are recovered at startup; exhausted jobs remain marked failed with a sanitized error type. Completed payload snapshots are cleared.

Explicit owner memory-write requests still require a successful memory tool write before completion. Coding/security/REA verification, resource release and coding-route finalization retain their required ordering. Failure/cancellation paths retain existing behavior. This patch does not remove model verification passes or change the selected model.

The durable runner combines lease claim with the running marker, and result persistence with attempt completion: three state commits instead of five, followed by the existing durable event. No database transaction spans provider/tool execution. Crash-after-commit replay executes the operation once. Provider wall time is persisted when inference metadata is absent, and runner logs separate preparation, operation, commit and publication time. Task-event queries receive an upgrade-safe index. Native trajectory JSON/index file writes run in a thread.

## Automated verification

129 focused checks passed across separate processes: post-response (12), durable execution (9), trajectory (4), coding workers (10), coding contract (11), task workflow (31), verification loop (3), vault tools (6), action gate (16), MCP usability (22), trajectory/tool recall (3), and two deterministic launcher/file execution checks. The completion test holds memory writing blocked while asserting the completed event has already reached subscribers. Other checks cover recovery of an unpublished completion, interrupted work, transient retries, exhausted jobs, timeouts, duplicate handlers, rollback and subsequent response delivery during blocked learning.

The combined focused run stalled during Windows async fixture setup. A full `python -m pytest -x` attempt made partial progress and did not finish in the 75-second diagnostic window. The full task-execution-reliability file also timed out; its two relevant async execution cases passed independently. Full-suite success is unverified. Backend compile checks and `git diff --check` passed. No frontend changes.

## Desktop evidence and resume

The exact backend patch was checked against the installed runtime, originals were backed up, and it was activated through `JarvisElevatedBackend`. Backend health after restart was successful under a new PID (63328). The saved model remained loaded with 32768 context and Docker MCP tools remained exposed. Installed event lookup plans changed from a table scan to the new covering index; on this small 1687-event database the median query changed from about 0.070 ms to 0.003 ms. This is a scaling improvement, not evidence of a comparable overall response speedup.

Local reproducibility scripts, test logs, live task ID/results, installed backups and a resume checkpoint live in `C:/Users/daanv/Documents/Projects/Jarvis/anzu-mcp-checkpoint/response-latency`. A live model-selected MCP task is tracked there; its final result is recorded separately. Physical-phone and audible-playback timings remain unmeasured. Earlier overall task durations are single observations, not a controlled performance baseline.
