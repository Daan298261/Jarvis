# Jarvis Windows installer

> **Canonical product installer:** build with `.\scripts\build-windows-release.ps1` (Tauri NSIS). See [`docs/DESKTOP.md`](../../docs/DESKTOP.md) and RFC-0002.

This folder retains the **legacy** Inno Setup source installer (`Jarvis.iss` + `bootstrap.ps1`) that copies the repo and bootstraps Python/Node. Prefer the Tauri desktop packaging path for end users (no Python/Node required at runtime).

## Legacy: build `JarvisSetup.exe` with Inno Setup (Windows)

Prerequisites:

- [Inno Setup 6](https://jrsoftware.org/isinfo.php) (`iscc` on PATH, or installed to `Program Files (x86)\Inno Setup 6\`)
- PowerShell 5.1+

From the repository root:

```powershell
.\installer\windows\build-installer.ps1
```

Output: `installer\windows\dist\JarvisSetup.exe`

## What the legacy installer does

1. Copies the repo into `%LOCALAPPDATA%\Jarvis` (default), excluding `.venv`, `node_modules`, `models/`, `runtime/`, `data/`, `logs/`, and `.git`.
2. Runs **`bootstrap.ps1`** once: installs Python/Node via `winget` if needed, creates `.venv`, pip, Playwright Chromium, `npm run build`, downloads llama.cpp + default 9B GGUFs.
3. Adds **Start Jarvis** / **Stop Jarvis** shortcuts.
4. Uninstall removes shortcuts; **does not** delete `data/` by default.

Bootstrap download logic is reused by the first-run setup API (`/api/setup/install`).

## Desktop sign-off

- Prefer verifying the Tauri release build from `scripts/build-windows-release.ps1`.
- Confirm `Jarvis.exe` shows the UI without opening a browser; backend starts; setup wizard works; uninstall preserves data.
