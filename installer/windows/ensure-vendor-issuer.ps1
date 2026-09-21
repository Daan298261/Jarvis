#Requires -Version 5.1
<#
.SYNOPSIS
  Create gitignored Ed25519 issuer keys if this checkout has none.

.DESCRIPTION
  Writes issuer.key / issuer.pub under .vendor/license-issuer (gitignored).
  Safe to re-run. Does not print key material.
#>
$ErrorActionPreference = "Stop"

$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$RepoRoot = Resolve-Path (Join-Path $ScriptDir "..\..")
$Backend = Join-Path $RepoRoot "backend"

$py = Get-Command python -ErrorAction SilentlyContinue
if (-not $py) { $py = Get-Command python3 -ErrorAction SilentlyContinue }
if (-not $py) { throw "python not found; cannot create vendor issuer keys" }

$env:PYTHONPATH = $Backend
$output = & $py.Source -c "from app.licensing.vendor_issuer import issuer_data_dir, load_or_create_vendor_keys, vendor_private_path; existed = vendor_private_path().is_file(); load_or_create_vendor_keys(); print(issuer_data_dir()); print('existing' if existed else 'created')"
if ($LASTEXITCODE -ne 0) { throw "ensure-vendor-issuer python failed with exit code $LASTEXITCODE" }
$dir = $output[0]
$state = $output[-1]
Write-Host "Vendor issuer keys ($state): $dir" -ForegroundColor Green
Write-Host "This folder is gitignored. Do not copy issuer.key into git or JarvisSetup." -ForegroundColor DarkGray
