#Requires -Version 5.1
<#
.SYNOPSIS
  Emit Jarvis-unrestricted.jarvis-license beside JarvisSetup.exe (RFC-0119).

.DESCRIPTION
  Non-interactive vendor issuer for owner/dev release cuts.
  Keys live in the gitignored checkout overlay `.vendor/license-issuer/`
  (or JARVIS_LICENSE_ISSUER_DIR). Missing keys are created once and reused.
  Never commit issuer.key. The license file is also gitignored and is not
  copied into the Inno customer payload.
#>
param(
    [Parameter(Mandatory = $true)]
    [string]$OutDir,
    [switch]$Require
)

$ErrorActionPreference = "Stop"

$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$RepoRoot = Resolve-Path (Join-Path $ScriptDir "..\..")
$Backend = Join-Path $RepoRoot "backend"
$ensure = Join-Path $ScriptDir "ensure-vendor-issuer.ps1"

$py = Get-Command python -ErrorAction SilentlyContinue
if (-not $py) { $py = Get-Command python3 -ErrorAction SilentlyContinue }
if (-not $py) {
    if ($Require) {
        throw "python not found; cannot issue unrestricted license"
    }
    Write-Host "Skipping unrestricted license (python not found)." -ForegroundColor Yellow
    exit 0
}

if (Test-Path $ensure) {
    & powershell -NoProfile -ExecutionPolicy Bypass -File $ensure
    if ($LASTEXITCODE -ne 0) {
        if ($Require) { throw "ensure-vendor-issuer failed with exit code $LASTEXITCODE" }
        Write-Host "Skipping unrestricted license (could not create issuer keys)." -ForegroundColor Yellow
        exit 0
    }
}

New-Item -ItemType Directory -Force -Path $OutDir | Out-Null
$env:PYTHONPATH = $Backend

Write-Host "==> Issuing owner unrestricted license (vendor-only; not in Jarvis.iss)" -ForegroundColor Cyan
& $py.Source -m app.licensing.vendor_issuer issue-unrestricted --out-dir $OutDir
if ($LASTEXITCODE -ne 0) {
    throw "issue-unrestricted failed with exit code $LASTEXITCODE"
}

$stable = Join-Path $OutDir "Jarvis-unrestricted.jarvis-license"
if (-not (Test-Path $stable) -or (Get-Item $stable).Length -le 0) {
    throw "Expected unrestricted license not found: $stable"
}

Write-Host "Wrote: $stable" -ForegroundColor Green
