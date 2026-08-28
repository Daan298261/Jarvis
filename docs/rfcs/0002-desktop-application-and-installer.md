# RFC-0002: Desktop application and installer

**Status:** accepted  
**Queue item:** P1 — Windows desktop application + installable product (Tauri shell, sidecar, first-run setup)  
**Author:** Cursor cloud worker  
**Date:** 2026-08-26

## Problem

Jarvis today is a FastAPI + React product launched via PowerShell (`start-jarvis.ps1`) that opens a browser to `http://127.0.0.1:4780`. End users must install Python and Node, and the existing Inno Setup installer still bootstraps a source tree rather than shipping a finished desktop application. The product does not feel like an installed Windows desktop app.

## Decision

Turn Jarvis into an installable Windows desktop application while preserving the existing FastAPI + React + SQLite architecture.

Architecture:

```text
JarvisSetup.exe
      |
      v
Jarvis Desktop Application
      |
      +-- Tauri 2 native shell
      |
      +-- existing React/Vite frontend (universal)
      |
      +-- Jarvis backend sidecar (PyInstaller one-folder)
      |
      +-- llama.cpp / remote inference
      |
      +-- Jarvis data/settings/models/runtime (outside install binaries)
```

**Will:**

- Embed the existing React portal in a Tauri 2 window (`Jarvis.exe`).
- Own backend lifecycle (health-check, start if needed, bounded restart).
- Package the FastAPI backend as a Windows sidecar so end users do not need Python/Node/npm.
- Add a first-run setup wizard in the universal React UI (hardware, role, resources, inference, downloads).
- Add a thin `DesktopBridge` for desktop-only capabilities with browser/PWA graceful degradation.
- Provide system tray controls, close-to-tray vs quit semantics, and diagnostics (redacted).
- Ship one canonical Windows release build command; migrate product packaging toward Tauri/NSIS while retaining bootstrap download logic.
- Keep models/runtimes outside the installer binary; preserve user data across upgrades; uninstall preserves data by default.

**Will not:**

- Create a separate Windows frontend or rewrite FastAPI / swarm / SQLite.
- Implement fake multi-node discovery/pairing (P3) unless already present.
- Implement a home-grown auto-updater or require code signing in this RFC.
- Mark Windows packaging or live GPU flows as VERIFIED from Linux CI.

## Acceptance criteria

- [ ] Tauri wraps the existing universal React frontend; browser/PWA still works
- [ ] Desktop shell manages backend lifecycle with bounded health/restart and status surfaces
- [ ] Backend packaged as sidecar; build script present; end users need no Python/Node at runtime
- [ ] First-run setup wizard with persisted setup state (recoverable downloads)
- [ ] Hardware/node detection, resource presets, role policy, inference choice, runtime/model GUI install
- [ ] Tray: Show/Hide, Start/Stop/Restart backend, Open logs, Quit; optional autostart (opt-in)
- [ ] Close-to-tray vs Quit semantics; only owned processes terminated
- [ ] One Windows release build command; data survives upgrades; uninstall preserves data by default
- [ ] Diagnostics with Copy (no secrets); automated tests for testable logic on Linux
- [ ] Unit tests pass (`python3 -m pytest`); frontend lint/build; `cargo check` for Tauri
- [ ] Windows-only items explicitly marked desktop sign-off required

## Likely files

| Area | Paths |
| --- | --- |
| RFC / docs | `docs/rfcs/0002-…`, `docs/INSTALL.md`, `installer/windows/README.md`, §57–58 lines |
| Backend | `backend/app/setup_state.py`, `runtime_install.py`, `diagnostics.py`, `api/setup.py`, `api/diagnostics.py`, hardware/recommend helpers |
| Frontend | `frontend/src/desktop/bridge.ts`, `pages/Setup.tsx`, `App.tsx`, `System.tsx`, `api.ts` |
| Tauri | `frontend/src-tauri/**` |
| Packaging | `scripts/build-backend-sidecar.ps1`, `scripts/build-windows-release.ps1`, sidecar entry |
| Tests | `tests/test_setup_*.py`, `test_diagnostics.py`, `test_desktop_bridge.py`, installer source checks |

## Out of scope

- P3 multi-node discovery, authenticated pairing, remote transport
- Code signing certificates and production auto-update channel
- Live GGUF load / e2e on Linux cloud VMs
- Cosmetic portal redesign unrelated to setup/status UX

## Notes

- Previous Inno Setup path (`installer/windows/Jarvis.iss` + `bootstrap.ps1`) remains as **legacy source installer** until Tauri release packaging covers the same downloads; bootstrap download URLs/logic are reused by the setup API.
- Desktop sign-off checklist (Windows 11): build `JarvisSetup.exe`, install, launch `Jarvis.exe` without browser, backend auto-start, health ready, model setup, restart survival, tray/close-to-tray/quit, uninstall preserves data.
