#Requires -Version 5.1
<#
.SYNOPSIS
  Emit Jarvis-unrestricted.jarvis-license beside JarvisSetup.exe (RFC-0119).

.DESCRIPTION
  Non-interactive vendor issuer output for owner/dev release cuts.
  Uses the vendor signing key under JARVIS_LICENSE_ISSUER_DIR / LOCALAPPDATA.
  Hard-fails when the artifact is missing, incomplete, or unsigned.
#>
param(
    [Parameter(Mandatory = $true)]
    [string]$OutDir
)

$ErrorActionPreference = "Stop"

$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$RepoRoot = Resolve-Path (Join-Path $ScriptDir "..\..")
$Backend = Join-Path $RepoRoot "backend"

$py = Get-Command python -ErrorAction SilentlyContinue
if (-not $py) { $py = Get-Command python3 -ErrorAction SilentlyContinue }
if (-not $py) {
    throw "python not found; cannot issue unrestricted license"
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
