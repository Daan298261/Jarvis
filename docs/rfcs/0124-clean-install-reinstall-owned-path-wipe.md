# RFC-0124: Clean Install / Reinstall — owned-path wipe

**Status:** implemented  
**Queue item:** (none — no new §58 checkbox; **P0** for Taco local-install unblock; D1 implements after this spec lands)  
**Author:** Taco via Chief of Staff / Jarvis Architect  
**Date:** 2026-09-18

**Related (do not rewrite):** [RFC-0093](0093-installer-force-stop-and-prepare-unstick.md) (**implemented**, #262 specs / #264 `force-stop-jarvis.ps1`). This RFC is the **owner-facing Clean Install / Reinstall button** plus an **owned-path registry wipe** on top of 0093 — not a second force-stop. [RFC-0059](0059-installer-integration-onboarding.md) Setup `?step=integrations` (implemented). [RFC-0094](0094-settings-menu-information-architecture.md) / [RFC-0113](0113-admin-settings-submenu-1-4.md) Settings IA (`/settings/advanced`). [RFC-0087](0087-vendor-license-manager.md) vendor `license-issuer` must **not** be wiped. [RFC-0121](0121-projects-folder-chats-db-media-placement.md) owner Documents / Desktop / git projects are **not** owned roots. [`INSTALLER.md`](../../INSTALLER.md) / [`WINDOWS_SHELL.md`](../../WINDOWS_SHELL.md) outcomes only.

This PR is **specs-only**. Product code is a **named follow-up** (D1). Full intent; **no stubs / soft-fail**. Do **not** take ≤0123. No LE / Red / Purple / ATO gates. No exploit recipes.

## Problem

Taco is blocked on a **local install** that will not come up clean. RFC-0093 already force-stops lockers before Inno copy / uninstall (`installer/windows/force-stop-jarvis.ps1`, `PrepareToInstall` abort: “Close Jarvis and try again.” + `logs\installer-stop.log`). That is **not** an owner button.

Verified on tip:

- **Portal Settings** (`frontend/src/pages/Settings.tsx`, submenu `advanced` → `AdvancedSettingsPane.tsx`): License, Autonomy, Agent profiles, Advisor, Trajectories, Coding isolation, Core execution (including **Allowed directories**), computer-use permissions, self-dev budget, Launch queue. The Settings lede tells the owner to use **tray Stop** — it is **not** in this window. **No Clean Install / Reinstall control.**
- **`/setup`** (`Setup.tsx`) is first-run interview + RFC-0059 `?step=integrations`. Not a reinstall.
- **`/system`**: diagnostics (`data_directory`, `logs_directory`, …) + self-dev. Not a wipe.
- **JarvisSetup.exe** already has an existing-install page (`installer/windows/Jarvis.iss`): Upgrade/Repair (0), Reinstall-keep (1), Semi-clean (2, `reset-user-data.ps1` — keeps `models/`, `runtime/`, `data/private_key.sec`), **Clean** (3, `unins000.exe` then `DelTree(ExistingInstallDir)` after `IsSafeJarvisInstallDir` + “This cannot be undone”). Clean lives **only** in that wizard. Default `{app}` is `{localappdata}\Jarvis` (`DefaultDirName`).
- Polite `stop-jarvis.ps1` (repo root; optional `-ForceKillLockers` delegates to 0093) is **not** enough alone. `ForceStopJarvisUnder` still **falls back** to polite stop and can treat a missing `force-stop-jarvis.ps1` as success. Leaving lockers and claiming Clean Install succeeded is a **fail**.
- Wipe today is “whatever `{app}` is,” not an explicit **allowlist** of Jarvis-owned roots. `settings.allowed_directories`, owner Documents/Desktop/projects, and Android Studio’s SDK must never be implied.

A decorative button that runs polite Stop, `reset-user-data.ps1` (semi-clean), or `DelTree` while files stay locked is a **fail**.

## Decision

Add one **Clean Install / Reinstall** owner action. Same outcome from portal **and** from Setup.exe Clean. Reuse RFC-0093 force-stop. Add a **registry of directories Jarvis owns**. Delete **only** those. Then **force reinstall**. Soft-fail / leave locked files behind = **fail**.

### 1. Owner surface (cite existing UI; do not invent a third Settings IA)

**Primary:** Settings → **Advanced** (`/settings/advanced`, RFC-0113). New **danger** card: **Clean Install / Reinstall**. Not under Voice, Models, or Integrations. Do not dump this onto the Settings heap as a seventh top-level group.

**Copy (plain language):** permanently removes Jarvis application files, models, chats, logs, and other **Jarvis-owned** data on this PC, then runs Setup again. Two-step confirm (same gravity as `Jarvis.iss` Clean: path listed, “This cannot be undone,” default No). Show the resolved owned-root list before the second confirm.

**Also:** `/setup` may offer the **same** action as a recovery CTA when first-run/integrations is stuck — same helper, same registry, not a second wipe list. `/system` may deep-link Advanced; it must not grow a parallel wipe.

Windows **Settings → Apps → Jarvis → Modify** already enters `PrepareToInstall` (0093). That wizard Clean must call the **same** owned-path wipe as the portal button. Tray Stop (`WINDOWS_SHELL.md`) is **not** this ticket.

### 2. Sequence (hard; no polite hang)

A detached helper must outlive the portal/backend (force-stop kills them). Suggested name for implement: `installer/windows/clean-reinstall-jarvis.ps1`.

| Step | Must |
| --- | --- |
| 0. Resolve | Owned-root registry + **JarvisSetup.exe** path. If Setup cannot be launched after wipe, **abort before delete**. Copy Setup to `%TEMP%` if it currently lives under an owned root. |
| 1. Confirm | Two-step owner confirm (portal or Inno MsgBox). Cancel = no-op. |
| 2. Force-stop | **`force-stop-jarvis.ps1 -IncludeTray`** for **every** registered owned root (extend 0093’s single `-InstallRoot` if needed). Polite `stop-jarvis.ps1` may run first **inside** that script; it is **not** sufficient alone. Missing `force-stop-jarvis.ps1` = **abort** (do **not** use the ISS polite fallback as success). Bounded wait (existing `MaxWaitSeconds` family, default 90). |
| 3. Recheck | Any locker still holding an owned root → **abort**. Do not delete. Do not launch Setup. |
| 4. Wipe | Delete **only** files/dirs under registered owned roots. Re-check; leftover owned files (locked or access-denied) → **abort**. |
| 5. Reinstall | Launch JarvisSetup.exe so a **clean** install runs (empty tree → first-install prepare **with 0093 timeouts**; or wizard Clean equivalent). Unbounded hidden prepare remains a 0093 fail. |

**Abort** = visible error + durable log path. Never toast “Clean install complete” on a dirty tree.

### 3. Owned-path registry (allowlist)

Explicit allowlist. **Not** “everything under `%LOCALAPPDATA%`.” **Not** `settings.allowed_directories` (those are owner tool roots). **Not** vendor `%LOCALAPPDATA%\Jarvis\license-issuer\` (RFC-0087).

**Default owned roots** (verify in repo; do not invent conflicting paths):

| Root | Source |
| --- | --- |
| `{app}` / install dir, default `%LOCALAPPDATA%\Jarvis` | `Jarvis.iss` `DefaultDirName={localappdata}\Jarvis`; uninstall `InstallLocation`; `installer/windows/README.md` |
| Nested trees already under `{app}` | `data\`, `logs\`, `models\`, `runtime\`, `.venv\`, `frontend\`, `mcp\`, `android\` (incl. Gradle lockers 0093 already kills), `%LOCALAPPDATA%\Jarvis\android-sdk` when it lives **under** that Jarvis folder (`scripts/setup_android.ps1`) |
| Start Menu group created by Setup | `DefaultGroupName=Jarvis` icons (`Start Jarvis` / `Stop Jarvis` / Uninstall) — remove with uninstall / recreate on Setup |

**Record at install / first successful boot** (HKCU beside existing `JarvisUninstallKey` and/or a marker file **outside** the wipe set so the helper can still read it, e.g. `%TEMP%` snapshot at confirm time):

- Actual `{app}` if the owner did not use the default dir (still must pass `IsSafeJarvisInstallDir`: default path **or** `start-jarvis.ps1` + `unins000.exe` + `installer\windows\Jarvis.iss`).
- Custom **data directory** from `INSTALLER.md` §3 when that wizard lands (today `backend/app/config.py` `data_dir()` is `{app}\data`).
- Path to **this** `JarvisSetup.exe` so step 0 can find it.

**Never register / never delete:**

- `%USERPROFILE%`, Documents, Desktop, Downloads (except a Setup.exe we **copied out**, not the folder).
- Owner git repos / coding worktrees **outside** `{app}\data\worktrees`.
- RFC-0121 project **source** folders the owner created; `<data>/projects/` **inside** the Jarvis data dir **is** owned (it dies with Clean — that is the point).
- Android Studio / Google SDK paths **not** under the Jarvis folder.
- `%LOCALAPPDATA%` itself; other vendors’ AppData.
- `license-issuer` (vendor signing DB/key). If it sits under `{app}`, **exclude** it from the wipe set.

Each candidate root must pass a safety gate equivalent to `IsSafeJarvisInstallDir` (or “is a child of a root that already passed”). A path that fails the gate is **skipped and logged**, not deleted. Deleting a skipped path “to be thorough” is a fail.

`reset-user-data.ps1` remains **Semi-clean only**. This button must not call it as the wipe.

`DelTree({app})` after uninstall may stay as the Inno implementation **for `{app}`**, but only after force-stop succeeded **and** extra registered roots (if any) are cleared by the same helper. Extra roots must not be forgotten because Inno only `DelTree`s `ExistingInstallDir`.

### 4. Logs (0093 family)

Write `{app}\logs\clean-reinstall.log` **and** a copy that **survives** wipe (`%TEMP%\Jarvis-clean-reinstall.log`). Echo via Inno `Log()` when the wizard path is used. Record: each owned root, each force-killed PID (id + name + polite vs force — reuse `installer-stop.log` format), each delete, each leftover path/PID, Setup.exe path, exit reason (`ok` / `force-stop-failed` / `wipe-incomplete` / `setup-not-found` / `setup-launch-failed`).

Owner and implementer must be able to prove what happened without ProcMon.

### 5. Force reinstall

Success means Setup **actually started** a clean install, not “files gone.” If Setup exits before copy with an error, that error + log is the result — do not report portal success. After a successful wipe, do not leave the owner with no app and no running Setup.

**Will not:** rewrite RFC-0093; use polite `stop-jarvis.ps1` alone; treat Semi-clean as Clean; wipe `allowed_directories` / Documents / Desktop / vendor `license-issuer`; fold WINDOWS_SHELL tray; fold `INSTALLER.md` wizard-copy / GPU-fork leftovers; ship license-issuer into the customer payload; LE/Red/Purple gates.

## Acceptance criteria

- [ ] Specs-only in this PR (no product edits under `installer/windows/`, `frontend/src/`, `backend/`)
- [ ] Owner can start Clean Install / Reinstall from **Settings → Advanced**, with two-step confirm listing owned roots
- [ ] Same helper / registry as JarvisSetup **Clean** (index 3); `/setup` recovery CTA if present uses that helper
- [ ] Force-stop is `force-stop-jarvis.ps1` (extend to all owned roots); polite stop alone is a fail; missing force-stop script aborts
- [ ] Wipe deletes **only** registered owned roots; never `%LOCALAPPDATA%` wholesale, never owner Documents/Desktop/projects, never `allowed_directories`, never `license-issuer`
- [ ] Leftover lockers or undeletable owned files → abort + log; no success toast
- [ ] JarvisSetup.exe resolved **before** wipe; clean Setup launched after wipe; missing Setup aborts **before** delete
- [ ] Durable log in 0093 family + `%TEMP%` copy that survives `{app}` deletion
- [ ] Implement follow-up (D1, named ticket): `python3 -m pytest` (`tests/test_installer.py`, `tests/test_rfc0093_installer_force_stop.py`, new `tests/test_rfc0124_*.py` string/contract tests). `npm --prefix frontend run build` if portal changed. Live JarvisSetup Clean + portal button on a **running** Jarvis = Windows desktop sign-off (Linux cloud cannot sign off)

## Likely files

| Area | Paths |
| --- | --- |
| Installer (implement PR only) | `installer/windows/clean-reinstall-jarvis.ps1` (new); `force-stop-jarvis.ps1` (multi-root if needed); `Jarvis.iss` (Clean uses registry; record Setup path; no polite-fallback success on this path); do **not** replace Semi-clean `reset-user-data.ps1` |
| Frontend (implement PR only) | `frontend/src/settings/AdvancedSettingsPane.tsx`; optional `frontend/src/pages/Setup.tsx` recovery CTA |
| Backend (implement PR only) | Detach-helper API (must not wait on the dying backend); owned-root snapshot |
| Tests | `tests/test_rfc0124_*.py`; extend installer contract tests |
| Docs | this RFC; `JARVIS_MASTER_PLAN.md` §59 line only |

## Out of scope

Product implementation in this PR. RFC-0093 rewrite. Semi-clean / keep-models. Tray / Quit (`WINDOWS_SHELL.md`). `INSTALLER.md` wizard copy, GPU/VRAM fork, no-WAN first-run. RFC-0094/0113 IA redesign. RFC-0087 issuer in the customer payload. Swarm / model-stack. Architect rewrites of `INSTALLER.md` / `WINDOWS_SHELL.md` / `PORTAL_UX.md` beyond the ledger tick.

## Notes

- Taco / CoS 2026-09-18: **P0 SPEC NOW** — owner blocked on local install. Architect + CoS assign **accepted**. Implement is **D1 after this lands**; do not block other in-flight PRs. Do not merge this specs PR as if it fixed Setup.
- Evidence in tree (do not treat as already fixed): no portal Clean button; ISS Clean = `unins000` + `DelTree` after 0093 force-stop; `reset-user-data.ps1` is semi-clean; `ForceStopJarvisUnder` polite fallback can still return success.
- Linux cloud VMs cannot sign off live Inno. Implement unit-tests the allowlist, abort-on-locker, Setup-found-before-wipe, and Advanced-button contracts.
- Implement launch: implement this RFC only; branch from `development`; pytest; do not edit Architect spec docs; PR against `development`; do not merge other PRs.

## Implementation note

Landed on `development` via #321 @ `b45e8f05` + #323 @ `b04ddbaa` (Clean Install / Reinstall owned-path wipe). Live Clean wipe on a running Jarvis remains Windows desktop sign-off. Acceptance checkboxes left open for that sign-off and the original specs-only box.
