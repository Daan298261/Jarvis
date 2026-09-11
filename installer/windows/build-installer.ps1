#Requires -Version 5.1
<#
.SYNOPSIS
  Compile JarvisSetup.exe with Inno Setup (iscc).

.DESCRIPTION
  Run from the repository root or from installer/windows.
  By default the build first stages the Ornith 1.5 9B Q4_K_M bootstrap model,
  producing an installer that can start with local inference without a model
  download on the target PC.

  Output: installer/windows/dist/JarvisSetup.exe.

.PARAMETER SkipBootstrapModel
  Developer-only escape hatch. Builds an installer without the large offline
  bootstrap payload; first-run local inference may then require a download.

.PARAMETER SkipVoicePack
  Skip bundling the default Kokoro-82M household butler voice weights.
#>
param(
    [switch]$SkipBootstrapModel,
    [switch]$SkipVoicePack
)

$ErrorActionPreference = "Stop"

$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$Iss = Join-Path $ScriptDir "Jarvis.iss"
$OutDir = Join-Path $ScriptDir "dist"
$BootstrapModel = Join-Path $ScriptDir "payload\models\bootstrap\Ornith-1.5-9B-Q4_K_M.gguf"
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

New-Item -ItemType Directory -Force -Path $OutDir | Out-Null
Write-Host "Compiling $Iss ..."
$defines = @()
if ($SkipBootstrapModel) { $defines += "/DSkipBootstrapModel=1" }
if ($SkipVoicePack) { $defines += "/DSkipVoicePack=1" }
& $iscc @defines "/O$OutDir" $Iss
if ($LASTEXITCODE -ne 0) { throw "iscc failed with exit code $LASTEXITCODE" }

$exe = Join-Path $OutDir "JarvisSetup.exe"
if (-not (Test-Path $exe)) { throw "Expected output not found: $exe" }
Write-Host ""
Write-Host "Built: $exe" -ForegroundColor Green
if (-not $SkipBootstrapModel) {
    Write-Host "Includes: Ornith 1.5 9B Q4_K_M bootstrap weights" -ForegroundColor Green
}
if (-not $SkipVoicePack) {
    Write-Host "Includes: Kokoro-82M default household butler voice" -ForegroundColor Green
}
