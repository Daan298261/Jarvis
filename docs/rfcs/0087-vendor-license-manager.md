# RFC-0087: Vendor license manager, sealed files, offline clock log

**Status:** accepted  
**Queue item:** Vendor-only license issuance; sealed `.jarvis-license`; UTC clock-rollback lock of licensed modules  
**Author:** Taco via Cursor  
**Date:** 2026-09-14

## Problem

RFC-0086 mints cyber ATO files on the Leader with a per-machine issuer key. That is not a vendor tool: there is no licensee record, no module catalog, no sealed PII, and no honest offline autorenew cap. A hardcoded symmetric “mint key” in Jarvis would be extractable. Clock checks today only look at `last_validated_at` (five-minute jump); a calendar rollback (September → January) should suspend **licensed modules** without taking down household chat, local files, or models on disk.

## Decision

1. **Vendor manager** (`JarvisLicenseManager`) lives beside `JarvisSetup.exe` in `installer/windows/dist/`, not inside the Inno customer payload. Tk + SQLite in `%LOCALAPPDATA%\Jarvis\license-issuer\`. Signing **private** Ed25519 never ships to customers.
2. **Jarvis verifies Ed25519** (env `JARVIS_ATO_PUBLIC_KEY`, `data/cyber-ato/trusted.pub`, Leader `issuer.pub`, then embedded default). Optional **X25519 seal** hides name/email at rest. Forgery still requires the signing key.
3. Sealed payload: licensee name + email (required) / address (optional), Jarvis version range, `law_enforcement`, `modules[]`, dates, `auto_renew` + `term_days` capped by signed `max_expires_at`. Red still requires LE. No exploit/payload registry.
4. **Daily UTC clock log** (`data/clock-log.jsonl`, machine-local HMAC). DST / timezone offset must not lock. UTC rollback more than one day behind the last trusted sample suspends licensed modules until UTC is consistent again. Do not delete data.

**Will not:** edit Architect spec docs; add offensive tools; put the manager EXE or signing key in `Jarvis.iss` `[Files]`.

## Acceptance criteria

- [ ] Cannot issue Red without LE; sealed file verifies; forged/unsigned file fails
- [ ] UTC-1-day (actually >1 day) rollback locks licensed modules; timezone offset-only does not
- [ ] `max_expires_at` caps autorenew
- [ ] `build-installer.ps1` copies the manager into `dist/`; Inno excludes it
- [ ] Unit tests pass (`python -m pytest`)

## Likely files

| Area | Paths |
| --- | --- |
| Backend | `backend/app/policy/cyber_ato.py`, `backend/app/licensing/clock_log.py`, `backend/app/licensing/seal.py`, `backend/app/licensing/modules.py`, `backend/app/licensing/vendor_issuer.py`, `backend/app/licensing/manager_app.py` |
| Installer | `installer/windows/build-installer.ps1`, `installer/windows/build-license-manager.ps1`, `installer/windows/Jarvis.iss` |
| Tools | `tools/license_manager/` |
| Docs | this RFC, `AGENTS.md` / `docs/PROCESS.md` (vendor-only note only) |
| Tests | `tests/test_cyber_ato.py`, `tests/test_license_clock_log.py`, `tests/test_installer.py` |

## Out of scope

Architect edits to `SECURITY_AGENTS.md` / `INSTALLER.md`; HexStrike payload proxy; PolitieGPT.

## Notes

Depends on RFC-0086 ATO runtime. Desktop sign-off: PyInstaller onefile on the Windows release machine.
