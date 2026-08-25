# Jarvis Windows installer

Ships **sources** that produce `JarvisSetup.exe` on a Windows machine. The cloud/Linux CI cannot compile or sign the `.exe`; desktop sign-off is required.

## What it does

1. **JarvisSetup.exe** (Inno Setup) copies the repo into `%LOCALAPPDATA%\Jarvis` (default), excluding `.venv`, `node_modules`, `models/`, `runtime/`, `data/`, `logs/`, and `.git`.
2. Runs **`bootstrap.ps1`** once: installs Python/Node via `winget` if needed, creates `.venv`, `pip install -r backend/requirements.txt`, Playwright Chromium, `npm run build`, downloads llama.cpp CUDA 13.3 binaries and default **Qwen3.5-9B** GGUFs.
3. Adds **Start Jarvis** / **Stop Jarvis** shortcuts (Desktop + Start Menu) that call `start-jarvis.ps1` and `stop-jarvis.ps1`.
4. Uninstall removes shortcuts; **does not** delete `data/` by default.

## Build `JarvisSetup.exe` (Windows)

Prerequisites:

- [Inno Setup 6](https://jrsoftware.org/isinfo.php) (`iscc` on PATH, or installed to `Program Files (x86)\Inno Setup 6\`)
- PowerShell 5.1+

From the repository root:

```powershell
.\installer\windows\build-installer.ps1
```

Output: `installer\windows\dist\JarvisSetup.exe`

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
