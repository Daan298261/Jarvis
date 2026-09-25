# RFC-0136: Zombie-kill on Setup Next and Start

**Status:** implemented  
**Queue item:** (none — no new §58 checkbox; Taco 2026-09-22 post-1.4.10 Start unblock)  
**Author:** Taco via Chief of Staff  
**Date:** 2026-09-22

**Related (do not rewrite):** [RFC-0093](0093-installer-force-stop-and-prepare-unstick.md) (**implemented**, #262 specs / #264 `force-stop-jarvis.ps1`) — this RFC **extends** that helper; it does not replace prepare timeouts or `SkipHeavyPrepare`. [RFC-0124](0124-clean-install-reinstall-owned-path-wipe.md) (**accepted**) is the owner **Clean Install / Reinstall** button plus an owned-path wipe. That stays a different action. This RFC does **not** amend 0124’s wipe allowlist, confirms, or Settings card.

**Numbering:** 0130–0135 are already taken (`0130-session-personalities.md` through `0135-competitor-watch-outstanding-recommendations.md`). CoS asked for a thin follow-on rather than folding this into 0124; **0136** is the next free id. Do not take ≤0135.

This PR is **specs-only**. Product code is a **named follow-up**. Full intent; **no stubs / soft-fail**. No LE / Red / Purple / ATO gates. No exploit recipes.

## Problem

After the **1.4.10** upgrade, Start failed with address-in-use (`Errno 10048` / `WSAEADDRINUSE`). A wedged uvicorn still held **4780**: many `CLOSE_WAIT` sockets, `/api/health` not OK. A **second** stuck `.venv` uvicorn was also present. The owner had to use Task Manager.

RFC-0093 already force-stops path-matched lockers in `PrepareToInstall` (Install click), not when the owner clicks **Next** on the installation-method page, and **`start-jarvis.ps1` never calls it** before binding 4780. A helper that exits 0 because nothing matched the install-path heuristic, while a Jarvis process still owns 4780, is a **fail**.

Verified on tip (`a3377e9`, in-tree 1.4.10):

- `installer/windows/force-stop-jarvis.ps1` `Test-ProcessUnderInstall` kills only when the executable path or command line sits under `-InstallRoot` (plus `jarvis-tray.ps1` when `-IncludeTray`). `llama-server` matches only if that exe path is under the root. python matches only if the exe path or command line contains the root. Exit 0 is the log line `force-stop complete: no lockers under install tree`. There is **no** TCP-table check, **no** health probe, and **no** `CLOSE_WAIT` handling. Process or TCP enumeration failure already returns 1 (`locker-scan-failed`); an empty path scan does **not**.
- `start-jarvis.ps1` starts uvicorn as `.venv\Scripts\python.exe -m uvicorn app.main:app --host … --port 4780 --app-dir backend` with `WorkingDirectory` = the install root. The command line does **not** contain the install path. If `ExecutablePath` is empty, the 0093 heuristic misses it. The script then `Start-Process` that uvicorn **immediately**. The health loop (`http://127.0.0.1:4780/api/health`, up to 180 tries) runs **after** the bind. Nothing clears a prior listener.
- `stop-jarvis.ps1` (polite) does match `uvicorn app.main:app` and every `llama-server.exe`, but `Stop-Process` failures are `SilentlyContinue` and it always prints `Jarvis stopped.` It does not check ports, companion **4781**, tray unless `-IncludeTray`, or `supermemory-server.exe`. Force-stop may run that polite script first; polite success is **not** the success signal. Start does not call either script.
- `installer/windows/Jarvis.iss` installation-method page is `ExistingInstallPage` (`InitializeWizard`: Upgrade/Repair, Reinstall, Semi-clean, Clean). `NextButtonClick` only confirms Clean (index 3) and Semi-clean (index 2). Upgrade/Repair returns True with **no** stop. Force-stop runs later in `PrepareToInstall` → `StopJarvisProcessesForPrepare` → `ForceStopJarvisUnder` (`-IncludeTray`, 90s). That is too late for this ticket, and it still uses the path-only helper.
- Companion **4781** is normally in-process on the same backend (`backend/app/mobile/connectivity.py`). A separate `python -m app.mobile.gateway` can also bind 4781 (`backend/app/mobile/gateway.py`). Same path-heuristic gap.
- `llama-server.exe` is spawned from `{InstallRoot}\runtime\llama.cpp`. `supermemory-server.exe` is spawned from `{InstallRoot}\runtime\supermemory` (RFC-0132). Both are killed today only when the exe path is visible and under the root.
- A second `.venv` python (another install copy, or a leftover whose path is not the `-InstallRoot` just passed in) is invisible to a single-root path scan even when its command line is `uvicorn app.main:app` and it owns 4780.

`CLOSE_WAIT` means the owning process is still alive and has not closed the socket. The listen socket stays until that PID exits. Killing “whatever matched the path” and ignoring the TCP owner is how Start still sees 10048.

## Decision

Reuse **`installer/windows/force-stop-jarvis.ps1`**. Extend it. Do not add a second killer. Both call sites below run **that** script and honor its exit code.

**Success (exit 0) only when all of these are true:**

- No Jarvis-identity process from the kill set below is still running.
- No still-living Jarvis-identity PID owns `Listen` or `CloseWait` on **4780** or **4781**.

Logging `force-stop complete` or `Jarvis stopped.` while either port is still owned by a Jarvis PID is a **fail** (exit non-zero). Callers must not continue.

If Win32_Process enumeration fails, or both TCP lookups fail, exit **non-zero**. Do not treat “could not check” as clear.

### 1. Who gets killed (Jarvis identity only)

Keep the existing install-root path and command-line matches. **Also** kill, even when the path is **not** under the current `-InstallRoot`:

| Target | Match |
| --- | --- |
| Backend | `python` / `pythonw` whose command line matches `uvicorn app.main:app` (covers relative `--app-dir backend` and a **second** `.venv`) |
| Companion | `python` / `pythonw` whose command line matches `app.mobile.gateway`, and any Jarvis backend PID that owns **4781** |
| Tray | `powershell` / `pwsh` whose command line matches `jarvis-tray.ps1` |
| Stuck starter | `powershell` / `pwsh` whose command line matches `start-jarvis.ps1`, **except** the current helper’s ancestor chain |
| llama-server | `llama-server.exe` under `{InstallRoot}\runtime\llama.cpp`, **or** whose parent is a Jarvis python already selected. Do not kill an `llama-server` the owner started outside Jarvis |
| Supermemory | `supermemory-server.exe` under `{InstallRoot}\runtime\supermemory`, **or** whose parent is a Jarvis python already selected |

**Ports.** Resolve owners of local **4780** and **4781** (`Get-NetTCPConnection`; if that cmdlet throws, parse `netstat -ano`). Any `Listen`, `CloseWait`, or `Established` owner that matches the table above is a kill target. `CloseWait` on those ports is the wedged-backend signal from the 1.4.10 report; the owner PID is what must die. `TimeWait` with no process (owning PID 0) is not a kill target.

**Do not kill** a non-Jarvis process that happens to hold 4780 or 4781. Exit non-zero with PID, image name, and port (`stranger-holds-port`). Setup and Start stop there.

**Protected (never kill):** this helper’s PID, its ancestor chain, `JarvisSetup.exe`, and command lines for the in-flight `force-stop-jarvis.ps1`, `clean-reinstall-jarvis.ps1`, and `reset-user-data.ps1`. Do **not** protect every `start-jarvis.ps1` on the machine.

Polite `stop-jarvis.ps1` may still run first inside the helper. It is **not** sufficient alone. A missing `force-stop-jarvis.ps1` is an **abort** at both call sites (same rule as RFC-0124). Do not fall back to polite stop and call that success.

Bounded wait stays in the existing `MaxWaitSeconds` family (default **90**). `Stop-Process -Force`, re-check, repeat until the deadline. Still present after the deadline → exit non-zero.

### 2. Health

Probe `GET http://127.0.0.1:4780/api/health` once, about **3s** timeout (the same URL `start-jarvis.ps1` already uses). This is **not** the 180-iteration ready loop.

- Nothing listening on 4780: no backend kill for that port.
- Jarvis owner and status is not HTTP **200** (timeout, connection error, or other status): **hung**. Kill it. This is the 1.4.10 case (listen socket up, health fail, `CLOSE_WAIT` piled up).
- Jarvis owner and HTTP **200**:
  - **Setup Next:** still stop it. A live backend must be gone before upgrade/install continues.
  - **Start:** do **not** spawn a second uvicorn. Continue to the tray helper and browser against the live server.
- Non-Jarvis owner: do not kill; fail as `stranger-holds-port`.

**4781.** If the owner is the same PID as 4780, one kill clears both. A separate Jarvis gateway process uses the same rules: no accept / no HTTP response within the short bound counts as hung. A stranger on 4781 fails the run; do not kill them.

### 3. Setup — installation-method Next

On `ExistingInstallPage` **Next** (`NextButtonClick` when `CurPageID = ExistingInstallPage.ID`), **after** the existing Clean / Semi-clean confirms (cancel = no-op, no kill):

1. Run `ForceStopJarvisUnder(ExistingInstallDir)` (script from `{tmp}` then the install tree, `-IncludeTray`, `-MaxWaitSeconds 90`), which must include §1–§2.
2. Missing script, non-zero exit, or a Jarvis PID still in `Listen` / `CloseWait` on 4780 or 4781 → `Result := False`. Stay on the page. Visible error in the existing family (“Jarvis is still running and could not be stopped…”) plus the log path. Do **not** advance to later pages, file replace, uninstall, reset, or bootstrap.
3. Upgrade/Repair (index 0) and Reinstall (index 1) get this gate too. They must not return True with no stop.
4. `PrepareToInstall` → `StopJarvisProcessesForPrepare` **stays** as a backstop (Install click, and Windows Settings → Apps → Modify, which has no method page). It must call the **same** stricter helper. It does not replace the Next gate.

### 4. Start — before bind on 4780

In `start-jarvis.ps1`, after dependency checks and **before** `Start-Process` of uvicorn on 4780:

1. Probe health **first** (§2). HTTP **200** from a Jarvis owner → do **not** call force-stop (that would kill the live backend, llama-server, and supermemory). Skip spawn. Continue with the tray helper and browser against the live server.
2. Otherwise run `installer\windows\force-stop-jarvis.ps1 -InstallRoot $Root -IncludeTray` (hung listener, `CLOSE_WAIT`, second `.venv`, tray, Jarvis llama-server, Jarvis supermemory).
3. Missing script, non-zero exit, or a Jarvis PID still owning `Listen` / `CloseWait` on 4780 or 4781 → `Show-StartupFailure`. Do **not** start uvicorn. Do **not** write a new `data\jarvis.pids` entry. Do **not** print that Jarvis is running.
4. Only then bind 4780.

Catching 10048 and continuing, or starting uvicorn anyway, is a fail.

### 5. Logs

Keep the RFC-0093 pair: `{InstallRoot}\logs\installer-stop.log` and `%TEMP%\Jarvis-installer-stop.log`. For each kill record PID, name, and reason (`path-locker`, `port-4780`, `port-4781`, `close-wait`, `health-fail`, `tray`, `llama-server`, `supermemory`, `second-venv`). Record the health probe result and the post-kill TCP recheck. Exit reason: `ok`, `port-still-owned`, `stranger-holds-port`, `scan-failed`, or `kill-failed`.

### 6. RFC-0124

0124 still calls this helper before its wipe. The stricter port check is in-scope for that call: if a Jarvis PID still holds 4780, 0124 already aborts **before** delete. This RFC does **not** change 0124’s owned-path allowlist, confirm copy, or portal card. Do not implement Clean Install here.

**Will not:** rewrite RFC-0093 prepare/bootstrap; rewrite RFC-0124; add a Settings wipe button; delete files; change default ports 4780/4781; kill non-Jarvis processes; ship license-issuer; fold tray/Quit (`WINDOWS_SHELL.md`) beyond killing `jarvis-tray.ps1` as a locker; LE/Red/Purple gates.

## Acceptance criteria

- [ ] Specs-only in this PR (no product edits under `installer/windows/`, `start-jarvis.ps1`, `stop-jarvis.ps1`, `frontend/`, `backend/`)
- [ ] Setup installation-method **Next** (Upgrade/Repair, Reinstall, Semi-clean, Clean) runs the extended force-stop **before** the wizard continues; cancel on Clean/Semi-clean does not kill; failure stays on the page with a visible error and log path
- [ ] `PrepareToInstall` still force-stops with the **same** helper (backstop for Install and Settings → Apps → Modify)
- [ ] `start-jarvis.ps1` probes health first; on failure it runs that helper **before** binding 4780; helper failure does not spawn uvicorn and does not report a running Jarvis
- [ ] Kill set includes hung Jarvis backends that hold 4780/4781 but fail health, including a second `.venv` uvicorn whose path is outside `-InstallRoot`, `CLOSE_WAIT` owners, `jarvis-tray.ps1`, Jarvis-started `llama-server.exe`, and Jarvis-started `supermemory-server.exe`
- [ ] Non-Jarvis port owners are not killed; the run fails with PID and name
- [ ] Exit 0 only when no Jarvis-identity kill-set process remains **and** no Jarvis PID owns `Listen` or `CloseWait` on 4780 or 4781; “no path lockers” while the port is occupied is a fail
- [ ] Healthy HTTP 200 on Start adopts the live server (no second bind); Setup Next still stops a healthy backend
- [ ] Missing `force-stop-jarvis.ps1` aborts; polite `stop-jarvis.ps1` alone is not success
- [ ] Implement follow-up (named ticket): `python3 -m pytest` (`tests/test_rfc0093_installer_force_stop.py`, `tests/test_installer.py`, `tests/test_windows_shell.py`, new `tests/test_rfc0136_*.py` string/contract tests). Live Setup Next + Start against a wedged uvicorn on 4780 is Windows desktop sign-off (Linux cloud cannot sign off)

## Likely files

| Area | Paths |
| --- | --- |
| Installer (implement PR only) | `installer/windows/force-stop-jarvis.ps1` (port/health/identity; still exit non-zero on failure); `installer/windows/Jarvis.iss` (`NextButtonClick` on `ExistingInstallPage` calls `ForceStopJarvisUnder` before continuing; `PrepareToInstall` unchanged in role) |
| Root scripts (implement PR only) | `start-jarvis.ps1` (call force-stop before the uvicorn `Start-Process`) |
| Tests | `tests/test_rfc0136_*.py`; extend RFC-0093 contract tests so exit-0 text is tied to a port recheck, not only an empty path scan |
| Docs | this RFC; `JARVIS_MASTER_PLAN.md` §59 line only |

## Out of scope

Product implementation in this PR. RFC-0124 Clean Install / Reinstall wipe, owned-path registry, Settings → Advanced card. RFC-0093 bootstrap timeouts, `SkipHeavyPrepare`, wizard copy, GPU/VRAM fork, no-WAN first-run. Changing bind ports. Killing unrelated `llama-server` or any non-Jarvis listener. Swarm / model-stack. Architect rewrites of `INSTALLER.md` / `WINDOWS_SHELL.md` / `PORTAL_UX.md`.

## Notes

- Taco 2026-09-22: HOLD lifted for **this ticket only**. Rest of the hold stays. Specs-only; do not merge; do not implement.
- Evidence in tree (do not treat as already fixed): path-only `Test-ProcessUnderInstall`; Start binds 4780 with no prior stop; method-page Next does not stop; polite stop prints `Jarvis stopped.` without a port recheck.
- Linux cloud VMs cannot sign off a live wedged uvicorn. Implement unit-tests the script/ISS/start-jarvis contracts (Next calls force-stop, Start calls it before `Start-Process`, 4780/4781/`CloseWait`/health/`supermemory-server`/`llama-server` appear in the helper, non-zero when the port stays owned).
- Implement launch: implement this RFC only; branch from `development`; pytest; do not edit Architect spec docs; PR against `development`; do not merge other PRs.

## Implementation note

Landed on `development` via #369 @ `45c7ea0c` (zombie-kill on Setup Next + `start-jarvis.ps1` before bind). Live wedged uvicorn on 4780 remains Windows desktop sign-off. Acceptance checkboxes left open for that sign-off and the original specs-only box.
