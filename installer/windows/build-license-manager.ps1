#Requires -Version 5.1
<#
.SYNOPSIS
  Build JarvisLicenseManager.exe into installer/windows/dist (vendor-only).

.DESCRIPTION
  PyInstaller onefile when available. Otherwise writes a .cmd launcher next to
  JarvisSetup.exe. This output must NOT be added to Jarvis.iss [Files].
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

# Run as a package entry so manager_app relative imports resolve (not as a loose script).
$entry = Join-Path $RepoRoot "tools\license_manager\__main__.py"
$backend = Join-Path $RepoRoot "backend"

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
