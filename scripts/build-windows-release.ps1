#Requires -Version 5.1
<#
.SYNOPSIS
  One-command Windows release build for Jarvis desktop + installer.

.DESCRIPTION
  Optional Tauri desktop shell (not the landed product installer):
  1) Frontend npm ci + build
  2) Backend PyInstaller sidecar
  3) Tauri NSIS bundle (native window + sidecar)

  The landed end-user .exe path remains Inno Setup:
    .\installer\windows\build-installer.ps1 → JarvisSetup.exe

  Requires Windows + Rust toolchain + Node + Python.
  Linux CI cannot produce the .exe — desktop sign-off required.
#>
param(
    [switch]$SkipSidecar,
    [switch]$SkipFrontend
)

$ErrorActionPreference = "Stop"
$Root = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
Set-Location $Root

Write-Host "Jarvis Windows release build" -ForegroundColor White
Write-Host "Root: $Root" -ForegroundColor DarkGray

if (-not $SkipFrontend) {
    Write-Host "==> Frontend install + build" -ForegroundColor Cyan
    Push-Location (Join-Path $Root "frontend")
    if (Test-Path "package-lock.json") { npm ci } else { npm install }
    npm run build
    Pop-Location
}

if (-not $SkipSidecar) {
    Write-Host "==> Backend sidecar" -ForegroundColor Cyan
    & powershell -NoProfile -ExecutionPolicy Bypass -File (Join-Path $Root "scripts\build-backend-sidecar.ps1")
}

Write-Host "==> Tauri NSIS bundle" -ForegroundColor Cyan
Push-Location (Join-Path $Root "frontend")
if (-not (Get-Command cargo -ErrorAction SilentlyContinue)) {
    throw "Rust/cargo is required for Tauri builds. Install https://rustup.rs/"
}
npm run tauri build
Pop-Location

$bundle = Join-Path $Root "frontend\src-tauri\target\release\bundle\nsis"
Write-Host ""
Write-Host "Build complete." -ForegroundColor Green
Write-Host "Installer output (typical): $bundle" -ForegroundColor Green
Write-Host "Copy/rename the NSIS setup exe to JarvisSetup.exe for distribution if desired." -ForegroundColor DarkGray
Write-Host "User data (data/, models/, runtime/, logs/) remains outside the install binaries and survives upgrades." -ForegroundColor DarkGray
Write-Host "Auto-update / code signing: enable Tauri updater later with signing keys — not required for this RFC." -ForegroundColor DarkGray
