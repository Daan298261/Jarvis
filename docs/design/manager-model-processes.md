# Manager emergency model controls

Scope: extend RFC-0196/RFC-0229 with the owner's requested local model process
window and per-process hard kill. Include ANZU-managed workers and recognized
external servers, even when model HTTP APIs or the core are down. No changes to
model selection, launch, idle-unload or restart policies.

The Manager reads psutil in a worker thread and presents executable, model
basename when available, PID, state and RSS. It reuses existing server
classification; generic Python and editor processes are excluded. Ollama serve
and runner processes are included, CLI clients excluded. Permission limitations
and detection scope are visible. Raw command lines and full model paths never
leave the inspector. Unsupported runtimes cannot be promised as detected.

Hard kill requires loopback, the Manager session token, Manager origin, and
explicit UI confirmation. A SHA-256 identity binds PID, executable name and
creation time; fresh enumeration and a second identity/classification read
precede kill. Kill waits at most five seconds for confirmed exit. No process
tree termination, automatic privilege elevation, or parent restart suppression.
Success and rejection/failure are audited using the existing redacted log.

Acceptance: managed and external model processes visible without core; direct
kill, confirmed exit, stale PID/permission/error paths; no editor targets; no
secret argv disclosure; remote/token/origin/confirmation rejection; real UI
inspection and controlled disposable process kill. Existing Manager controls
and model inventory remain operational.

Regression tests were written first and failed because the new inspector was
absent. Verification includes focused backend tests, existing Manager/model
regressions, JS checks, full suite and independent review/QA. Full-suite or
release gate failures block merge and must be reported honestly.
