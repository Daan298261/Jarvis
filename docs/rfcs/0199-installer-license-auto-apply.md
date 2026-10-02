# RFC-0199: Installer license sidecar auto-apply

**Status:** accepted  
**Queue item:** (none — no §58 checkbox)  
**Author:** Jarvis Architect  
**Date:** 2026-10-02

**Related:** [RFC-0059](0059-installer-integration-onboarding.md) first-run Setup flow. [RFC-0087](0087-vendor-license-manager.md) sealed `.jarvis-license`. [RFC-0119](0119-license-package-entitlements-and-release-unrestricted.md) runtime gate + **vendor** `Jarvis-unrestricted.jarvis-license` in `dist/` (not customer payload). [RFC-0012](0012-local-license-byo-inference.md) commercial lease (separate from cyber package). [RFC-0086 ATO](0086-in-person-cyber-ato-license.md) install path: `data_dir()/cyber-ato/license.jarvis-license` via `install_license()`.

Specs-only sibling to [RFC-0196](0196-hexstrike-operator-chain-anzu-1.md) cyber package. **No ledger ticks.**

## Problem

Customers and field installs often receive a `.jarvis-license` file **beside** `JarvisSetup.exe` (USB stick, vendor email, enterprise folder). Today the owner must manually import via Model/License UI. That is friction and causes “installed but not entitled” support load. RFC-0119 covers **release-machine** unrestricted artifacts in `installer/windows/dist/`; it does **not** cover **per-customer** sidecar files next to the installer at install time.

## Decision

During **Windows Setup**, detect a license file in the **installer directory** (directory containing the running `JarvisSetup.exe`), copy it into the Jarvis **residence** (`{app}` / `%LOCALAPPDATA%\Jarvis`), and **apply** it on first backend start so entitlements are live without paste.

### 1. Detection rules

| Rule | Detail |
| --- | --- |
| Installer directory | `{src}` in Inno = folder of the executing setup EXE (spanned media: first disk folder) |
| Filename patterns | Exactly one match preferred: `*.jarvis-license`; if multiple, prefer `Jarvis.jarvis-license` then lexicographic first; surface chooser UI if >1 and no preferred name |
| Ignore | `Jarvis-unrestricted.jarvis-license` sitting in **dist** on vendor build machines must **not** auto-ship inside Inno (unchanged RFC-0119); this rule is for **customer-delivered** sidecars at install time |
| Upgrade | If valid license already installed, **do not overwrite** unless new sidecar has later `expires_at` or owner confirms replace (implement: default skip + log) |

### 2. Copy destinations

1. **Residence copy:** `{app}\license-sidecar\{original-filename}.jarvis-license` (audit trail of what Setup found).
2. **Active install:** invoke same path as manual install — `install_license()` → `data_dir()/cyber-ato/license.jarvis-license` (see `backend/app/policy/cyber_ato.py` `sealed_license_path()`).

Copy happens in Inno `[Code]` or `run-installer-bootstrap.ps1` **before** first backend start.

### 3. Apply timing

| When | Action |
| --- | --- |
| Setup `[Run]` bootstrap | If sidecar copied, write flag `{app}\data\license-pending-apply.json` with source path |
| First `start-jarvis.ps1` / backend lifespan | Read pending flag; call `install_license`; on success delete flag and emit audit `license_auto_applied` |
| Failure | Honest error in Setup log + License page banner (“Sidecar license invalid: …”); **do not** claim success |

**No soft-fail:** forged/unsigned sidecar must **not** set `license-pending-apply` success; invalid file leaves system unentitled with visible error.

### 4. Relationship to RFC-0119

| Artifact | Role |
| --- | --- |
| `installer/windows/dist/Jarvis-unrestricted.jarvis-license` | Vendor release cut only; not in Inno |
| Customer `*.jarvis-license` next to Setup | This RFC — auto-apply on install |
| Commercial RFC-0012 lease | Unchanged; may coexist; entitlements merge per RFC-0119 read model |

### 5. Implement anti-patterns

- Copying sidecar into git or Inno default `[Files]` payload
- Auto-applying without signature verification
- Silently ignoring invalid sidecar
- Overwriting good license with older sidecar on upgrade without prompt

## Acceptance criteria

Specs-only:

- [x] RFC-0199 accepted; cross-links 0059/0087/0119/0012
- [x] Detection, copy, apply, upgrade behavior documented
- [x] Distinction from vendor unrestricted artifact clear

Implement follow-up:

- [ ] Inno or bootstrap detects sidecar beside Setup EXE
- [ ] Copy to residence + pending apply flag
- [ ] Backend applies on first start; entitlements visible without manual paste
- [ ] Upgrade/replace rules; audit events
- [ ] `tests/test_installer.py` + `tests/test_cyber_ato.py` coverage with temp licenses
- [ ] **Windows soak**: Setup with sidecar → portal shows modules without manual import

## Likely files

| Area | Paths |
| --- | --- |
| Installer | `installer/windows/Jarvis.iss` `[Code]`, `installer/windows/run-installer-bootstrap.ps1` |
| Backend | `backend/app/policy/cyber_ato.py`, `backend/app/main.py` lifespan hook |
| Frontend | `frontend/src/pages/License.tsx` banner for apply failures |
| Tests | `tests/test_installer.py`, `tests/test_cyber_ato.py` |

## Out of scope

- Shipping `JarvisLicenseManager` or issuer private keys in customer payload (RFC-0087)
- Changing License Manager SKU catalog
- Linux/macOS installers

## Notes

- `Jarvis.iss` already excludes `*.jarvis-license` from the tree copy — sidecar is **external** to the payload by design.
- Cloud agents unit-test Python paths; Inno `[Code]` is desktop sign-off.
