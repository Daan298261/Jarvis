#Requires -Version 5.1
<#
.SYNOPSIS
  Compile AnzuSetup.exe with Inno Setup (iscc).

.DESCRIPTION
  Run from the repository root or from installer/windows.
  By default the build first stages the Ornith 1.5 9B Q4_K_M bootstrap model
  and the Qwen3.5-2B Q4_K_M front-lane model, producing an installer that can
  start with local inference and a warm front lane without those downloads
  on the target PC.

  Output: installer/windows/dist/AnzuSetup.exe.

.PARAMETER SkipBootstrapModel
  Developer-only escape hatch. Builds an installer without the large offline
  bootstrap payload; first-run local inference may then require a download.

.PARAMETER SkipVoicePack
  Skip bundling the default Kokoro-82M household butler voice weights.

.PARAMETER Release
  Product release cut. Creates gitignored `.vendor/license-issuer` keys if
  needed and writes Jarvis-unrestricted.jarvis-license beside AnzuSetup.exe.
  1.4.6 shipped without this file; later releases must not.

.PARAMETER SkipDesktopShell
  Skip building/staging Jarvis Desktop (Tauri). Release cuts require the desktop shell.

.PARAMETER SkipFrontModel
  Developer-only escape hatch. Builds an installer without the bundled
  Qwen3.5-2B front-lane weights. Forbidden with -Release.

.PARAMETER DriveReleasesPath
  Optional external folder, such as the Google Drive "Jarvis Releases"
  directory. Every build copies customer deliverables into the gitignored
  repo folder <repoRoot>\release\ (installer exe, issued license, license
  manager, companion APK when present). When -DriveReleasesPath is set, that
  same set is copied from release\ into this path. When the parameter is
  omitted, only the in-repo release\ copy runs.
#>
param(
    [switch]$SkipBootstrapModel,
    [switch]$SkipVoicePack,
    [switch]$SkipDesktopShell,
    [switch]$SkipFrontModel,
    [switch]$Release,
    [string]$DriveReleasesPath = ""
)

$ErrorActionPreference = "Stop"

$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$Root = (Resolve-Path (Join-Path $ScriptDir "..\..")).Path
$Iss = Join-Path $ScriptDir "Jarvis.iss"
$OutDir = Join-Path $ScriptDir "dist"
$BootstrapModel = Join-Path $ScriptDir "payload\models\bootstrap\Ornith-1.5-9B-Q4_K_M.gguf"
$FrontModel = Join-Path $ScriptDir "payload\models\Qwen3.5-2B-GGUF\Qwen3.5-2B-Q4_K_M.gguf"
$FrontModelBytes = 1280835840
$VoiceModelMarker = Join-Path $ScriptDir "payload\models\tts\kokoro-82m\.jarvis_staged_ok"

function Find-Iscc {
    $cmd = Get-Command iscc -ErrorAction SilentlyContinue
    if ($cmd) { return $cmd.Source }

    $candidates = @(
        "$env:LOCALAPPDATA\Programs\Inno Setup 6\ISCC.exe",
        "${env:ProgramFiles(x86)}\Inno Setup 6\ISCC.exe",
        "$env:ProgramFiles\Inno Setup 6\ISCC.exe"
    )
    foreach ($path in $candidates) {
        if (Test-Path $path) { return $path }
    }
    return $null
}

$iscc = Find-Iscc
if (-not $iscc) {
    throw @"
Inno Setup compiler (iscc) not found.
Install Inno Setup 6 from https://jrsoftware.org/isinfo.php
Then re-run: .\installer\windows\build-installer.ps1
"@
}

if (-not $SkipBootstrapModel) {
    Write-Host "==> Staging bundled bootstrap model" -ForegroundColor Cyan
    & powershell -NoProfile -ExecutionPolicy Bypass -File (Join-Path $ScriptDir "stage-bootstrap-model.ps1")
    if ($LASTEXITCODE -ne 0) { throw "Bootstrap model staging failed with exit code $LASTEXITCODE" }
    if (-not (Test-Path $BootstrapModel) -or (Get-Item $BootstrapModel).Length -le 0) {
        throw "Bootstrap payload not ready: $BootstrapModel"
    }
} else {
    Write-Warning "Building without bundled bootstrap model (-SkipBootstrapModel)."
}

if ($Release -and $SkipFrontModel) {
    throw "Release cuts cannot use -SkipFrontModel. The installer must ship the Qwen3.5-2B front model."
}
if (-not $SkipFrontModel) {
    Write-Host "==> Staging bundled Qwen3.5-2B front model" -ForegroundColor Cyan
    & powershell -NoProfile -ExecutionPolicy Bypass -File (Join-Path $ScriptDir "stage-front-model.ps1")
    if ($LASTEXITCODE -ne 0) { throw "Front model staging failed with exit code $LASTEXITCODE" }
    if (-not (Test-Path $FrontModel) -or (Get-Item $FrontModel).Length -ne $FrontModelBytes) {
        throw "Front model payload not ready: $FrontModel"
    }
} else {
    Write-Warning "Building without bundled Qwen3.5-2B front model (-SkipFrontModel)."
}

if (-not $SkipVoicePack) {
    Write-Host "==> Staging default Kokoro household butler voice pack" -ForegroundColor Cyan
    & powershell -NoProfile -ExecutionPolicy Bypass -File (Join-Path $ScriptDir "stage-voice-default.ps1")
    if ($LASTEXITCODE -ne 0) { throw "Default voice pack staging failed with exit code $LASTEXITCODE" }
    if (-not (Test-Path $VoiceModelMarker)) {
        throw "Default Kokoro voice payload not ready (missing marker): $VoiceModelMarker"
    }
} else {
    Write-Warning "Building without bundled default Kokoro voice pack (-SkipVoicePack)."
}

$DesktopMarker = Join-Path $ScriptDir "payload\desktop\.jarvis_desktop_staged_ok"
if (-not $SkipDesktopShell) {
    Write-Host "==> Staging Jarvis Desktop shell (Tauri)" -ForegroundColor Cyan
    $stageArgs = @()
    if ($Release) { $stageArgs += "-Require" }
    & powershell -NoProfile -ExecutionPolicy Bypass -File (Join-Path $ScriptDir "stage-desktop-shell.ps1") @stageArgs
    if ($LASTEXITCODE -ne 0) { throw "Desktop shell staging failed with exit code $LASTEXITCODE" }
    if (-not (Test-Path $DesktopMarker)) {
        throw "Desktop payload marker missing: $DesktopMarker"
    }
} elseif ($Release) {
    throw "Release cuts cannot use -SkipDesktopShell. The installer must ship Jarvis Desktop."
} else {
    Write-Warning "Building without Jarvis Desktop (-SkipDesktopShell). Obsidian embed requires the desktop shell."
}

# Inno's broad runtime/dist exclusions also match nested first-party paths.
# Fail the build before compilation if the explicitly included launch files are absent.
$backendRuntime = Join-Path $Root "backend\app\runtime\elevation.py"
$portalIndex = Join-Path $Root "frontend\dist\index.html"
if (-not (Test-Path $backendRuntime)) { throw "Backend launch module missing: $backendRuntime" }
if (-not (Test-Path $portalIndex)) { throw "Portal build missing: $portalIndex" }
$portalHtml = Get-Content -LiteralPath $portalIndex -Raw
if ($portalHtml -notmatch '/assets/[^" ]+\.js') { throw "Portal index has no built JavaScript asset: $portalIndex" }
foreach ($asset in [regex]::Matches($portalHtml, '/assets/[^" ]+\.(?:js|css)')) {
    $assetPath = Join-Path (Join-Path $Root "frontend\dist") ($asset.Value.TrimStart('/') -replace '/', '\')
    if (-not (Test-Path $assetPath)) { throw "Portal asset missing: $assetPath" }
}

New-Item -ItemType Directory -Force -Path $OutDir | Out-Null
Write-Host "Compiling $Iss ..."
$defines = @()
if ($SkipBootstrapModel) { $defines += "/DSkipBootstrapModel=1" }
if ($SkipFrontModel) { $defines += "/DSkipFrontModel=1" }
if ($SkipVoicePack) { $defines += "/DSkipVoicePack=1" }
if ($SkipDesktopShell) { $defines += "/DSkipDesktopShell=1" }
& $iscc @defines "/O$OutDir" $Iss
if ($LASTEXITCODE -ne 0) { throw "iscc failed with exit code $LASTEXITCODE" }

$exe = Join-Path $OutDir "AnzuSetup.exe"
if (-not (Test-Path $exe)) { throw "Expected output not found: $exe" }
Write-Host ""
Write-Host "Built: $exe" -ForegroundColor Green
if (-not $SkipBootstrapModel) {
    Write-Host "Includes: Ornith 1.5 9B Q4_K_M bootstrap weights" -ForegroundColor Green
}
if (-not $SkipFrontModel) {
    Write-Host "Includes: Qwen3.5-2B Q4_K_M front-lane weights" -ForegroundColor Green
}
if (-not $SkipVoicePack) {
    Write-Host "Includes: Kokoro-82M default household butler voice" -ForegroundColor Green
}
if (-not $SkipDesktopShell) {
    Write-Host "Includes: ANZU Desktop (Tauri) + backend sidecar" -ForegroundColor Green
}

Write-Host "==> Vendor license manager JarvisLicenseManager (vendor machine only; skipped on the public tree)" -ForegroundColor Cyan
& powershell -NoProfile -ExecutionPolicy Bypass -File (Join-Path $ScriptDir "build-license-manager.ps1") -OutDir $OutDir
if ($LASTEXITCODE -ne 0) {
    throw "License manager build failed with exit code $LASTEXITCODE"
}

$licenseArgs = @("-OutDir", $OutDir)
if ($Release) {
    $env:JARVIS_VENDOR_RELEASE = "1"
    $licenseArgs += "-Require"
    Write-Host "==> Release cut: owner unrestricted license is a required build step" -ForegroundColor Cyan
} else {
    Write-Host "==> Owner unrestricted license (vendor-only; public clones skip without issuer.key)" -ForegroundColor Cyan
}
& powershell -NoProfile -ExecutionPolicy Bypass -File (Join-Path $ScriptDir "issue-release-unrestricted-license.ps1") @licenseArgs
if ($LASTEXITCODE -ne 0) {
    throw "Unrestricted license issuance failed with exit code $LASTEXITCODE"
}
$unrestricted = Join-Path $OutDir "Jarvis-unrestricted.jarvis-license"
if ($Release -and (-not (Test-Path $unrestricted) -or (Get-Item $unrestricted).Length -le 0)) {
    throw "Release cut must write $unrestricted. 1.4.6 shipped without a generated license file; following releases must issue it as a build step."
}

# Every build, not only -Release: customer deliverables also land in <repo>\release\.
# -DriveReleasesPath copies that same set from release\ to the external folder.
Write-Host "==> Publishing customer deliverables to release\" -ForegroundColor Cyan
$publishArgs = @()
if ($DriveReleasesPath) {
    $publishArgs += "-DriveReleasesPath"
    $publishArgs += $DriveReleasesPath
}
if ($Release) {
    $publishArgs += "-StageVersionedHotfix"
    Write-Host "==> Also staging Releases/r* hotfix notes" -ForegroundColor Cyan
}
& powershell -NoProfile -ExecutionPolicy Bypass -File (Join-Path $ScriptDir "stage-release-folder.ps1") @publishArgs
if ($LASTEXITCODE -ne 0) { throw "stage-release-folder.ps1 failed with exit code $LASTEXITCODE" }
