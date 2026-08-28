# Jarvis desktop packaging (Tauri 2)

Canonical Windows product build:

```powershell
.\scripts\build-windows-release.ps1
```

This produces the Tauri NSIS installer under `frontend/src-tauri/target/release/bundle/nsis/`.
Rename/copy to `JarvisSetup.exe` for distribution if desired.

## What the installed product contains

- `Jarvis.exe` — Tauri shell embedding the universal React UI
- Backend sidecar (`jarvis-backend`) — packaged FastAPI (no end-user Python/Node)
- Static portal assets
- Uninstaller

Large AI runtimes and GGUF models are **not** inside the installer. First-run setup downloads them into `models/` and `runtime/` beside user data.

## Data vs binaries

| Path | Survives upgrade | Removed on uninstall (default) |
| --- | --- | --- |
| Install dir binaries | replaced | yes |
| `data/` | yes | **no** |
| `models/` | yes | **no** |
| `runtime/` | yes | **no** |
| `logs/` | yes | **no** |

Uninstall must not delete user data by default. Optional “Remove Jarvis data, models and settings” can be offered later.

## Legacy Inno Setup path

`installer/windows/Jarvis.iss` + `bootstrap.ps1` remain as a **legacy source installer** (copies repo + winget Python/Node). Prefer the Tauri release path above. Bootstrap download URLs are reused by `/api/setup/install`.

## Auto-update (future)

Expose app version via diagnostics / `DesktopBridge.appVersion()`. Keep mutable data outside install binaries. Enable Tauri updater + signing when certificates exist — not required for RFC-0002.

## Desktop sign-off

Linux CI cannot verify the `.exe`. See RFC-0002 Windows sign-off checklist.
