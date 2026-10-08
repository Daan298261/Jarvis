# Jarvis Windows installer

Ships **sources** that produce `AnzuSetup.exe` on a Windows machine. The cloud/Linux CI cannot compile or sign the `.exe`; desktop sign-off is required.

## What it does

1. **AnzuSetup.exe** (Inno Setup) copies the repo into `%LOCALAPPDATA%\Jarvis` (default), excluding `.venv`, `node_modules`, `models/`, `runtime/`, `data/`, `logs/`, local `release/` bundles, `_release_upload/`, and `.git`. Bundled weights are installed separately: the Ornith bootstrap GGUF under `models\bootstrap` and the **Qwen3.5-2B Q4_K_M** front model under `models\Qwen3.5-2B-GGUF`. The installed desktop binary stays `desktop\Jarvis.exe`. The wizard, Start menu, and Programs and Features name are **ANZU**.
2. Runs **`bootstrap.ps1`** once: installs Python/Node via `winget` if needed, creates `.venv`, installs backend packages, Playwright Chromium, builds the portal, and prepares llama.cpp, the bootstrap GGUF, and the voice models you checked in Setup (household butler is bundled; the other four shared neural packs are optional). If the installer already copied the Qwen3.5-2B front GGUF, bootstrap leaves that file in place and does not download it again.
3. Adds **Start ANZU** / **Stop ANZU** shortcuts (Desktop + Start Menu) that call `start-jarvis.ps1` and `stop-jarvis.ps1`.
4. Uninstall removes shortcuts; **does not** delete `data/` by default.

## Existing installations

When Jarvis is already installed, Setup compares the installed version with the installer version:

- A newer installer offers an in-place **Upgrade** and keeps settings, models, task data, logs, and connections.
- The same version offers **Repair** with the same preservation behavior.
- **Reinstall and keep custom files** removes the old application files before reinstalling while leaving generated files in place.
- **Semi-clean reinstall** removes chats, tasks, routines, memory, logs, and most settings while keeping downloaded models, runtime binaries, your private key, and license files.
- Upgrade, repair, and semi-clean keep the bundled Ornith bootstrap weights and the bundled Qwen3.5-2B front weights the same way: both live under `models\` and are recopied from the installer payload.
- **Clean reinstall** removes the application and all custom files only after a separate permanent-deletion confirmation.
- An older installer is blocked to prevent an accidental downgrade.

## Build `AnzuSetup.exe` (Windows)

Prerequisites:

- [Inno Setup 6](https://jrsoftware.org/isinfo.php) (`iscc` on PATH, or installed to `Program Files (x86)\Inno Setup 6\`)
- PowerShell 5.1+

From the repository root:

```powershell
.\installer\windows\build-installer.ps1
```

Output: `installer\windows\dist\AnzuSetup.exe`

Every build also copies the customer deliverables into the gitignored repo folder `release\` (repo root): the installer executable (and `AnzuSetup-*.bin` slices), the issued license when one was produced, the vendor license manager when it was built, and a companion APK if one is sitting in `dist`. Source archives are not copied. The same `release\` folder receives the companion APK from `scripts/build_android.py` and from the Linux Android companion workflow, and the Tauri NSIS setup exe from `scripts/build-windows-release.ps1`. The portal `npm run build` output stays in `frontend\dist`; it is an installer input, not a separate customer package.

To also fill an external drop such as the Google Drive **Jarvis Releases** folder, pass `-DriveReleasesPath`. The script copies the files it just wrote under `release\` into that path. Omit the parameter and only `release\` is updated.

```powershell
.\installer\windows\build-installer.ps1 -DriveReleasesPath "G:\My Drive\Jarvis Releases"
```

The installer bundles the **Qwen3.5-2B Q4_K_M** front model (`models\Qwen3.5-2B-GGUF\Qwen3.5-2B-Q4_K_M.gguf`) so a fresh install has a warm front lane without a separate download. `build-installer.ps1` stages it with `stage-front-model.ps1` after the Ornith bootstrap model. Developer builds can omit it; release cuts cannot:

```powershell
.\installer\windows\build-installer.ps1 -SkipFrontModel
```

## Release cuts (required)

Every **shipped** `AnzuSetup.exe` must also emit an owner unrestricted license beside Setup (not inside the Inno payload):

- `installer\windows\dist\Jarvis-unrestricted.jarvis-license`

Jarvis **1.4.6** was cut without this file. Following releases must generate it as part of the installer build.

Signing keys are created once under gitignored `.vendor/license-issuer/` (or `JARVIS_LICENSE_ISSUER_DIR`). They are not stored under `%LOCALAPPDATA%\Jarvis` (that folder is the Inno `{app}` and was wiping keys on upgrade).

```powershell
.\installer\windows\ensure-vendor-issuer.ps1
$env:JARVIS_VENDOR_RELEASE = "1"
.\installer\windows\build-installer.ps1 -Release
```

The `-Release` switch **fails the cut** if the license file is missing, unsigned, or could not be issued. Do not ship a GitHub/stable build without that file.

Release builds run `stage-voice-default.ps1` to bundle **Kokoro-82M** under `models/tts/kokoro-82m` so the default household butler speaks out of the box (RFC-0070). Developer escape hatch:

```powershell
.\installer\windows\build-installer.ps1 -SkipVoicePack
```

On the target PC, Setup shows checkboxes for the five shared neural voices. All five are checked by default so an upgrade still prepares every persona pack. Uncheck Chatterbox (or any other pack) to skip that download; you can install it later from the Persona or Voice menu. If a selected voice download fails, setup logs it and the menu can retry that pack later.

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

A public git clone without GGUFs starts as a **household voice chatbot** (Kokoro only). Pass `-InstallLocalLLM` to download llama.cpp + 9B.

Optional speech and voice systems:

```powershell
# Whisper STT base model + faster-whisper
.\installer\windows\bootstrap.ps1 -InstallWhisper

# debpalash/voicestudio clone and local integration
.\installer\windows\bootstrap.ps1 -InstallVoiceStudio

# Pocket TTS lightweight CPU neural voice
.\installer\windows\bootstrap.ps1 -InstallPocketTTS
```

## Desktop sign-off

- Compile `AnzuSetup.exe` on Windows.
- Run installer on a clean Windows 11 + NVIDIA machine.
- Confirm first boot via **Start ANZU** opens http://127.0.0.1:4780.

Manual install steps remain in [`docs/INSTALL.md`](../../docs/INSTALL.md).
