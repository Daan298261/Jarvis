#Requires -Version 5.1
<#
.SYNOPSIS
  Build and stage Jarvis Desktop (Tauri) into installer/windows/payload/desktop for Inno.

.DESCRIPTION
  Produces payload/desktop/Jarvis.exe plus sidecars/jarvis-backend for a complete
  end-user install (native shell + Obsidian embed + backend sidecar).

.PARAMETER Require
  Fail if Rust/Tauri build cannot run (use for -Release installer cuts).
#>
param(
    [switch]$Require
)

$ErrorActionPreference = "Stop"
$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$Root = (Resolve-Path (Join-Path $ScriptDir "..\..")).Path
$PayloadDir = Join-Path $ScriptDir "payload\desktop"
$Marker = Join-Path $PayloadDir ".jarvis_desktop_staged_ok"

function FailOrWarn($message) {
    if ($Require) { throw $message }
    Write-Warning $message
    exit 0
}

if (-not (Get-Command cargo -ErrorAction SilentlyContinue)) {
    FailOrWarn "Rust/cargo not found — desktop shell not staged. Install https://rustup.rs/ or pass -SkipDesktopShell."
}
if (-not (Get-Command npm -ErrorAction SilentlyContinue)) {
    FailOrWarn "npm not found — cannot stage Jarvis Desktop."
}

Write-Host "==> Staging Jarvis Desktop (Tauri + backend sidecar)" -ForegroundColor Cyan

& powershell -NoProfile -ExecutionPolicy Bypass -File (Join-Path $Root "scripts\build-backend-sidecar.ps1")
if ($LASTEXITCODE -ne 0) { throw "Backend sidecar build failed with exit code $LASTEXITCODE" }

Push-Location (Join-Path $Root "frontend")
if (Test-Path "package-lock.json") { npm ci } else { npm install }
npm run build
if ($LASTEXITCODE -ne 0) { throw "frontend build failed" }
npm run tauri build
if ($LASTEXITCODE -ne 0) { throw "tauri build failed" }
Pop-Location

$releaseExe = Join-Path $Root "frontend\src-tauri\target\release\jarvis.exe"
if (-not (Test-Path $releaseExe)) {
    $releaseExe = Join-Path $Root "frontend\src-tauri\target\release\Jarvis.exe"
}
if (-not (Test-Path $releaseExe)) {
    throw "Tauri release binary not found under frontend\src-tauri\target\release\"
}

New-Item -ItemType Directory -Force -Path $PayloadDir | Out-Null
Copy-Item -Force $releaseExe (Join-Path $PayloadDir "Jarvis.exe")

$sidecarSrc = Join-Path $Root "frontend\src-tauri\sidecars\jarvis-backend"
if (-not (Test-Path $sidecarSrc)) {
    throw "Missing sidecar folder: $sidecarSrc"
}
$sidecarDest = Join-Path $PayloadDir "sidecars\jarvis-backend"
if (Test-Path $sidecarDest) { Remove-Item -Recurse -Force $sidecarDest }
New-Item -ItemType Directory -Force -Path (Split-Path $sidecarDest) | Out-Null
Copy-Item -Recurse -Force $sidecarSrc $sidecarDest

$stamp = (Get-Date).ToUniversalTime().ToString("o")
Set-Content -Path $Marker -Value $stamp -Encoding UTF8
Write-Host "Staged Jarvis Desktop -> $PayloadDir" -ForegroundColor Green
