#Requires -Version 5.1
<#
.SYNOPSIS
  Idempotent HexStrike loopback bootstrap for Daybreak Blue (RFC-0086).

.DESCRIPTION
  Clones the reviewed upstream commit, creates hexstrike-env, and installs
  **core** server packages only. Does NOT install mitmproxy / pwntools / angr
  (Python 3.11 proxy extras are vulnerable and outside the defensive surface).
  Jarvis launches the server through app.security.hexstrike_compat.
#>
param(
    [string]$InstallRoot = "",
    [string]$Python = ""
)

$ErrorActionPreference = "Stop"
$PinnedCommit = "d689933ff579d839c676c82b231f8e98326c5f04"
$Remote = "https://github.com/0x4m4/hexstrike-ai.git"
$RepoRoot = Resolve-Path (Join-Path $PSScriptRoot "..")
if (-not $InstallRoot) {
    $InstallRoot = Join-Path $RepoRoot "runtime\hexstrike-ai"
}

$py = $Python
if (-not $py) {
    $cmd = Get-Command python -ErrorAction SilentlyContinue
    if ($cmd) { $py = $cmd.Source } else { $py = "python" }
}

New-Item -ItemType Directory -Force -Path (Split-Path $InstallRoot) | Out-Null

if (-not (Test-Path (Join-Path $InstallRoot ".git"))) {
    Write-Host "==> Cloning reviewed HexStrike commit $PinnedCommit" -ForegroundColor Cyan
    git clone --depth 1 $Remote $InstallRoot
}
Push-Location $InstallRoot
try {
    git fetch --depth 1 origin $PinnedCommit
    git checkout --detach $PinnedCommit
} finally {
    Pop-Location
}

$venvPython = Join-Path $InstallRoot "hexstrike-env\Scripts\python.exe"
if (-not (Test-Path $venvPython)) {
    Write-Host "==> Creating hexstrike-env" -ForegroundColor Cyan
    & $py -m venv (Join-Path $InstallRoot "hexstrike-env")
}

Write-Host "==> Installing core HexStrike deps (no mitmproxy/pwntools/angr)" -ForegroundColor Cyan
$core = @(
    "flask>=2.3.0,<4.0.0",
    "requests>=2.31.0,<3.0.0",
    "psutil>=5.9.0,<6.0.0",
    "fastmcp>=0.2.0,<1.0.0",
    "beautifulsoup4>=4.12.0,<5.0.0",
    "aiohttp>=3.8.0,<4.0.0"
)
& $venvPython -m pip install --upgrade pip
& $venvPython -m pip install @core
# Guard: never pull the audited-vulnerable proxy extra into the managed env.
& $venvPython -m pip uninstall -y mitmproxy pwntools angr 2>$null | Out-Null

Write-Host "HexStrike core environment ready at $InstallRoot" -ForegroundColor Green
Write-Host "Launch is fail-closed via python -m app.security.hexstrike_compat" -ForegroundColor DarkGray
