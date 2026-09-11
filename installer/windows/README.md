# Jarvis Windows installer

Ships **sources** that produce `JarvisSetup.exe` on a Windows machine. The cloud/Linux CI cannot compile or sign the `.exe`; desktop sign-off is required.

## What it does

1. **JarvisSetup.exe** (Inno Setup) copies the repo into `%LOCALAPPDATA%\Jarvis` (default), excluding `.venv`, `node_modules`, `models/`, `runtime/`, `data/`, `logs/`, and `.git`.
2. Runs **`bootstrap.ps1`** once: installs Python/Node via `winget` if needed, creates `.venv`, `pip install -r backend/requirements.txt`, Playwright Chromium, `npm run build`, downloads llama.cpp CUDA 13.3 binaries and default **Qwen3.5-9B** GGUFs.
3. Adds **Start Jarvis** / **Stop Jarvis** shortcuts (Desktop + Start Menu) that call `start-jarvis.ps1` and `stop-jarvis.ps1`.
4. Uninstall removes shortcuts; **does not** delete `data/` by default.

## Existing installations

When Jarvis is already installed, Setup compares the installed version with the installer version:

- A newer installer offers an in-place **Upgrade** and keeps settings, models, task data, logs, and connections.
- The same version offers **Repair** with the same preservation behavior.
- **Reinstall and keep custom files** removes the old application files before reinstalling while leaving generated files in place.
- **Clean reinstall** removes the application and all custom files only after a separate permanent-deletion confirmation.
- An older installer is blocked to prevent an accidental downgrade.

## Build `JarvisSetup.exe` (Windows)

Prerequisites:

- [Inno Setup 6](https://jrsoftware.org/isinfo.php) (`iscc` on PATH, or installed to `Program Files (x86)\Inno Setup 6\`)
- PowerShell 5.1+

From the repository root:

```powershell
.\installer\windows\build-installer.ps1
```

Output: `installer\windows\dist\JarvisSetup.exe`

Release builds run `stage-voice-default.ps1` to bundle **Kokoro-82M** under `models/tts/kokoro-82m` so the default household butler speaks out of the box (RFC-0070). Developer escape hatch:

```powershell
.\installer\windows\build-installer.ps1 -SkipVoicePack
```

One-liner after Inno Setup is installed:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\installer\windows\build-installer.ps1
```

## Re-run setup without reinstalling

```powershell
cd $env:LOCALAPPDATA\Jarvis
.\installer\windows\bootstrap.ps1
```

Optional Expert 27B (large download):

```powershell
.\installer\windows\bootstrap.ps1 -InstallExpert27B
```

## Desktop sign-off

- Compile `JarvisSetup.exe` on Windows.
- Run installer on a clean Windows 11 + NVIDIA machine.
- Confirm first boot via **Start Jarvis** opens http://127.0.0.1:4780.

Manual install steps remain in [`docs/INSTALL.md`](../../docs/INSTALL.md).
