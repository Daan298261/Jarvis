#Requires -Version 5.1
<#
.SYNOPSIS
  Build JarvisLicenseManager.exe into installer/windows/dist (vendor-only).

.DESCRIPTION
  The License Manager GUI is not in this public repo. Vendor machines keep a
  private overlay (tools/license_manager or JARVIS_LICENSE_MANAGER_SRC) and set
  JARVIS_VENDOR_RELEASE=1. This output must NOT be added to Jarvis.iss [Files].
#>
param(
    [string]$OutDir = ""
)

$ErrorActionPreference = "Stop"

$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$RepoRoot = Resolve-Path (Join-Path $ScriptDir "..\..")
if (-not $OutDir) {
    $OutDir = Join-Path $ScriptDir "dist"
}

$overlay = [string]$env:JARVIS_LICENSE_MANAGER_SRC
$entry = ""
if ($overlay -and (Test-Path $overlay)) {
    if ((Get-Item $overlay).PSIsContainer) {
        $candidate = Join-Path $overlay "__main__.py"
        if (Test-Path $candidate) { $entry = $candidate }
    } else {
        $entry = $overlay
    }
}
if (-not $entry) {
    $inTree = Join-Path $RepoRoot "tools\license_manager\__main__.py"
    if (Test-Path $inTree) { $entry = $inTree }
}

$vendorRelease = [string]$env:JARVIS_VENDOR_RELEASE
if (-not $entry) {
    if ($vendorRelease -eq "1") {
        throw "JARVIS_VENDOR_RELEASE=1 but License Manager source is missing. Set JARVIS_LICENSE_MANAGER_SRC or keep a private tools/license_manager overlay."
    }
    Write-Host "Skipping JarvisLicenseManager (not in the public tree). Vendor machine: JARVIS_VENDOR_RELEASE=1 + private overlay." -ForegroundColor Yellow
    return
}

New-Item -ItemType Directory -Force -Path $OutDir | Out-Null

$py = Get-Command python -ErrorAction SilentlyContinue
if (-not $py) { $py = Get-Command python3 -ErrorAction SilentlyContinue }
if (-not $py) {
    throw "python not found; cannot build JarvisLicenseManager"
}

$pyinstaller = Get-Command pyinstaller -ErrorAction SilentlyContinue
if (-not $pyinstaller) {
    & $py.Source -m PyInstaller --version *> $null
    if ($LASTEXITCODE -eq 0) {
        $useModule = $true
    } else {
        $useModule = $false
    }
} else {
    $useModule = $false
}

$backend = Join-Path $RepoRoot "backend"
$managerApp = Join-Path $RepoRoot "backend\app\licensing\manager_app.py"
if (-not (Test-Path $managerApp)) {
    if ($vendorRelease -eq "1") {
        throw "backend/app/licensing/manager_app.py is missing. Restore the private vendor GUI overlay."
    }
    Write-Host "Skipping JarvisLicenseManager (manager_app.py not in the public tree)." -ForegroundColor Yellow
    return
}

if ($pyinstaller -or $useModule) {
    Write-Host "==> Building JarvisLicenseManager.exe (PyInstaller onefile)" -ForegroundColor Cyan
    $args = @(
        "--noconfirm",
        "--clean",
        "--onefile",
        "--windowed",
        "--name", "JarvisLicenseManager",
        "--paths", $backend,
        "--distpath", $OutDir,
        "--workpath", (Join-Path $OutDir "license-manager-build"),
        "--specpath", (Join-Path $OutDir "license-manager-build"),
        $entry
    )
    if ($useModule) {
        & $py.Source -m PyInstaller @args
    } else {
        & $pyinstaller.Source @args
    }
    if ($LASTEXITCODE -ne 0) { throw "PyInstaller failed with exit code $LASTEXITCODE" }
    $exe = Join-Path $OutDir "JarvisLicenseManager.exe"
    if (-not (Test-Path $exe)) { throw "Expected output not found: $exe" }
    Write-Host "Built: $exe (vendor-only; not in Jarvis.iss)" -ForegroundColor Green
    return
}

Write-Warning "PyInstaller not installed; writing JarvisLicenseManager.cmd launcher instead."
$cmdPath = Join-Path $OutDir "JarvisLicenseManager.cmd"
$cmd = @"
@echo off
setlocal
set "REPO=$RepoRoot"
set "PYTHONPATH=%REPO%\backend"
python -m app.licensing.manager_app
"@
Set-Content -Path $cmdPath -Value $cmd -Encoding ASCII
Write-Host "Wrote: $cmdPath (vendor-only; not in Jarvis.iss)" -ForegroundColor Yellow
