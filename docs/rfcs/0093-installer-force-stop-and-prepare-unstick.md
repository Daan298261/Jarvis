# RFC-0093: Installer force-stop and prepare unstick

**Status:** implemented
**Queue item:** P0 — JarvisSetup 1.3.13 clean reinstall / upgrade freeze (Taco / CoS urgent)
**Author:** Jarvis Architect
**Date:** 2026-09-16

**Related (do not rewrite):** RFC-0059 installer integration onboarding (**implemented**). This RFC does **not** fold voice / TTS / RFC-0092. [RFC-0124](0124-clean-install-reinstall-owned-path-wipe.md) is the owner-facing Clean Install / Reinstall button + owned-path registry wipe **on top of this RFC** — do not rewrite 0093 there.

This PR is **specs-only**. Product code is a follow-up implement ticket. Do not edit `installer/windows/` in this PR.

## Problem

JarvisSetup **1.3.13** clean reinstall fails even after the owner runs `stop-jarvis.ps1`. Upgrade / reinstall then freezes on the Inno wizard screen:

> Preparing Jarvis, its AI model, Gmail and WhatsApp (this can take a while)…

with the progress bar already full. There is no cancel that surfaces a real error; the owner has to kill Setup from Task Manager.

Verified on tip (`0ebee9d`, in-tree `#define MyAppVersion "1.3.10"`; field report is 1.3.13):

- `installer/windows/Jarvis.iss` sets `CloseApplications=no`. `[Code]` `StopJarvisProcesses` only `Exec`s `{app}\stop-jarvis.ps1 -IncludeTray` (`ewWaitUntilTerminated`). Missing script = silent skip. Non-zero `ResultCode` is logged and **ignored**. `PrepareToInstall` calls that polite stop, then Repair / Upgrade (index 0), Reinstall-keep (1), Semi-clean (2), or Clean (3, including `DelTree`). `[UninstallRun]` is the same polite stop.
- Post-copy `[Run]` launches `installer\windows\bootstrap.ps1` with `Flags: runhidden waituntilterminated`. Bundled-model builds use `-SkipModelDownload` and StatusMsg `Preparing Jarvis, Gmail and WhatsApp...`. Otherwise StatusMsg is the freeze string above. Inno waits forever if PowerShell never exits; stdout is hidden.
- `stop-jarvis.ps1` stops `data\jarvis.pids`, CIM `llama-server.exe`, python whose CommandLine matches `uvicorn app.main:app`, and optionally tray PID / `jarvis-tray.ps1`. It is **not** a force-kill of every locker under `%LOCALAPPDATA%\Jarvis` (other `.venv` python, `start-jarvis.ps1` PowerShell, Node under `mcp\` / `frontend\`, companion Gradle/Java locking `android\`, hung pip/npm/winget children).
- `installer/windows/bootstrap.ps1` always runs Gmail/WhatsApp `npm ci` (`Ensure-McpConnectors`), venv/pip, Playwright, frontend `npm ci` + `npm run build`, llama.cpp fetch, and model/voice downloads unless switches skip a subset. **No per-step timeout**, no durable log besides `Write-Host`, no cancel path. Idempotent skips exist for some files, but connector/frontend `npm ci` always runs.

File replace against a still-running tree plus an unbounded hidden `[Run]` is the hang. RFC-0059 added the integrations `[Run]` / Setup `step=integrations` path; it did not require force-stop or a bounded prepare.

## Decision

1. **Force-stop before file replace.** Every Repair, Upgrade, Reinstall-keep, Semi-clean, Clean, and uninstall/Modify path must **detect and force-stop** Jarvis-related processes **before** Inno copies files, runs `unins000.exe`, `reset-user-data.ps1`, or `DelTree`. Scope is the existing install dir (default `{localappdata}\Jarvis`): backend / uvicorn, tray, `start-jarvis.ps1` PowerShell, python/pythonw whose path or CommandLine is under that tree, `llama-server.exe` started from it, Node/npm under `mcp\` or `frontend\`, and companion build tools (Gradle/Java) locking `android\` in that tree. Polite `stop-jarvis.ps1 -IncludeTray` may run first; it is **not** sufficient alone. Do **not** rely on `CloseApplications=yes` as the only fix.

2. **“Force / kill if running” never hangs.** Bounded wait: polite stop, then force-kill remaining lockers, then re-check. If anything still holds the tree, Setup **fails clearly** (wizard error / `PrepareToInstall` Result string — same family as today's “Close Jarvis and try again.”) and **does not** proceed to copy or bootstrap. No infinite `Exec` wait. Uninstall uses the same force-stop.

3. **Unstick post-copy prepare.** The `[Run]` that shows the Gmail / WhatsApp / model StatusMsg must not wait forever:
   - Bootstrap (and/or the Inno wrapper) has **timeouts** on winget / `npm ci` / pip / Hugging Face / Playwright. A hung child is killed; the step fails.
   - Wait is **cancelable** from the wizard, or Setup uses a watchdog that treats overtime as failure. `runhidden waituntilterminated` with no bound is a fail.
   - **Skip heavy prepare** on Repair / Upgrade / Reinstall-keep / Semi-clean, and on Clean when models/venv/portal dist are **already present** after the chosen action: do not block Setup on Gmail/WhatsApp `npm ci`, full pip, or GGUF/voice re-download. Fresh first install and Clean-after-empty-tree still run prepare, **with timeouts**.
   - Failure **surfaces the real error** (dialog plus last lines of a durable log). Infinite “Preparing…” with a full bar is a fail.

4. **Log killed PIDs.** Installer and/or bootstrap write a durable log (e.g. `{app}\logs\installer-stop.log` and `{app}\logs\bootstrap.log`) listing each stopped PID, process name, and why (polite vs force). Inno `Log()` should echo the same. Owner and implementer can prove what was killed without ProcMon.

**Will not:** implement product scripts in this PR; rewrite RFC-0059 integrations UI/API; fold RFC-0092 / Kokoro / SAPI / Chatterbox; change `{app}` away from `%LOCALAPPDATA%\Jarvis`; ship license-issuer into the customer payload.

## Acceptance criteria

- [x] Clean reinstall from a **running** Jarvis completes without the owner using Task Manager to kill Setup, backend, or python — contracts in #264 (`force-stop-jarvis.ps1` before copy); live JarvisSetup remains Windows desktop sign-off
- [x] Upgrade / Repair / Reinstall-keep / Semi-clean do **not** freeze on “Preparing Jarvis, its AI model, Gmail and WhatsApp…” (or the shorter Gmail/WhatsApp StatusMsg) — #264 watchdog + `SkipHeavyPrepare`; live remains desktop sign-off
- [x] Force-stop runs **before** file replace on all five existing-install actions plus uninstall/Modify; kill failure aborts with a visible error (never hang)
- [x] Prepare/bootstrap has a finite timeout and surfaces the real error + log path instead of an infinite hidden wait
- [x] Heavy prepare is skipped when models/venv/portal are already present; first-install / empty Clean still prepares with timeouts
- [x] `installer-stop` / bootstrap log records which PIDs were killed (id + name)
- [x] Specs-only in this PR (no edits under `installer/windows/` product scripts, `stop-jarvis.ps1`, or `start-jarvis.ps1`) — specs PR #262
- [x] Implement follow-up: `python3 -m pytest` (`tests/test_installer.py`, `tests/test_windows_shell.py`, new `tests/test_rfc0093_*.py` string/contract tests). Live JarvisSetup is Windows desktop sign-off.

## Likely files

| Area | Paths |
| --- | --- |
| Installer (implement PR only) | `installer/windows/Jarvis.iss` (`StopJarvisProcesses`, `PrepareToInstall`, `[Run]`, `[UninstallRun]`, `CloseApplications`); `installer/windows/bootstrap.ps1`; optional new `installer/windows/force-stop-jarvis.ps1` |
| Root scripts (implement PR only) | `stop-jarvis.ps1` (force/kill-lockers switch); `start-jarvis.ps1` only if PID-file coverage must expand |
| Tests | `tests/test_installer.py`, `tests/test_windows_shell.py`, new `tests/test_rfc0093_*.py` |
| Docs | this RFC; `JARVIS_MASTER_PLAN.md` §59 Decision Log line only |

## Out of scope

Product implementation in this PR. Voice / TTS / RFC-0092. RFC-0059 Gmail/WhatsApp portal cards, IMAP/SMTP test, WhatsApp QR pairing UI. Wizard-copy / GPU-fork / no-WAN first-run leftover in `INSTALLER.md`. License manager (RFC-0087). Swarm / model-stack. Architect rewrites of `INSTALLER.md` / `WINDOWS_SHELL.md` beyond the ledger tick.

## Notes

- Taco / CoS urgent 2026-09-16. Architect + CoS assign this spec **accepted**. Implement is a **separate** named ticket; CoS/fixer land. Do not merge this specs PR as if it fixed Setup.
- Evidence in tree (do not treat as already fixed): `CloseApplications=no`; `StopJarvisProcesses` → `stop-jarvis.ps1 -IncludeTray` only; `[Run]` `runhidden waituntilterminated` + freeze StatusMsg; `stop-jarvis.ps1` PID-file + uvicorn/llama/tray; `bootstrap.ps1` unbounded `npm ci` / pip / winget / HF.
- Linux cloud VMs cannot sign off live Inno. Implement unit-tests the ISS/script contracts (force-stop call, timeout/skip switches, log path). Desktop: running Jarvis → Upgrade and Clean reinstall of the new Setup.exe.
- Implement launch: implement this RFC only; branch from `development`; pytest; do not edit Architect spec docs; PR against `development`; do not merge other PRs.

## Implementation note

Landed on `development` via implement **#264** @ `9ecf9bd` (`force-stop-jarvis.ps1`, bounded `run-installer-bootstrap.ps1` watchdog, `SkipHeavyPrepare`, `installer-stop.log` / `bootstrap.log`, contract tests). Specs PR **#262** @ `96d3421`. Live JarvisSetup on a running Jarvis (upgrade + clean reinstall) remains Windows desktop sign-off. RFC-0092 untouched.
