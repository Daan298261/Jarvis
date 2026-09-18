#Requires -Version 5.1
<#
.SYNOPSIS
  Emit Jarvis-unrestricted.jarvis-license beside JarvisSetup.exe (RFC-0119).

.DESCRIPTION
  Non-interactive vendor issuer for owner/dev release cuts.
  Requires an existing vendor signing key under JARVIS_LICENSE_ISSUER_DIR /
  LOCALAPPDATA\Jarvis\license-issuer. Does not create keys. Does not run on the
  public clone unless that key is already present, or JARVIS_VENDOR_RELEASE=1.
#>
param(
    [Parameter(Mandatory = $true)]
    [string]$OutDir
)

$ErrorActionPreference = "Stop"

$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$RepoRoot = Resolve-Path (Join-Path $ScriptDir "..\..")
$Backend = Join-Path $RepoRoot "backend"

$issuerDir = [string]$env:JARVIS_LICENSE_ISSUER_DIR
if (-not $issuerDir) {
    if ($env:LOCALAPPDATA) {
        $issuerDir = Join-Path $env:LOCALAPPDATA "Jarvis\license-issuer"
    } else {
        $issuerDir = Join-Path $HOME ".jarvis\license-issuer"
    }
}
$keyPath = Join-Path $issuerDir "issuer.key"
$vendorRelease = [string]$env:JARVIS_VENDOR_RELEASE

if (-not (Test-Path $keyPath)) {
    if ($vendorRelease -eq "1") {
        throw "JARVIS_VENDOR_RELEASE=1 but vendor issuer.key is missing at $keyPath"
    }
    Write-Host "Skipping unrestricted license (no vendor issuer.key). Public tree will not mint licenses." -ForegroundColor Yellow
    exit 0
}

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
