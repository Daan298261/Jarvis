#Requires -Version 5.1
<#
.SYNOPSIS
  Stage Jarvis' bundled bootstrap model before compiling JarvisSetup.exe.

.DESCRIPTION
  Downloads the smallest official Ornith 1.5 model as a Q4_K_M GGUF into the
  installer payload. The large binary is intentionally not committed to Git.
  Safe to re-run; a non-empty staged canonical file is reused.
#>
param(
    [switch]$Force
)

$ErrorActionPreference = "Stop"
$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$Root = (Resolve-Path (Join-Path $ScriptDir "..\..")).Path
$Payload = Join-Path $ScriptDir "payload\models\bootstrap"
$Canonical = Join-Path $Payload "Ornith-1.5-9B-Q4_K_M.gguf"
$Repo = "ornith-ai/Ornith-1.5-9B-GGUF"
$Include = "*Q4_K_M*.gguf"

if ((-not $Force) -and (Test-Path $Canonical) -and ((Get-Item $Canonical).Length -gt 0)) {
    Write-Host "Bootstrap model already staged: $Canonical" -ForegroundColor Green
    exit 0
}

function Get-PythonExe {
    $venv = Join-Path $Root ".venv\Scripts\python.exe"
    if (Test-Path $venv) { return $venv }
    $python = Get-Command python -ErrorAction SilentlyContinue
    if ($python) { return $python.Source }
    $py = Get-Command py -ErrorAction SilentlyContinue
    if ($py) {
        $resolved = & $py.Source -3 -c "import sys; print(sys.executable)" 2>$null
        if ($resolved) { return $resolved.Trim() }
    }
    return $null
}

$Python = Get-PythonExe
if (-not $Python) {
    throw "Python is required to stage the bootstrap model before building the installer."
}

New-Item -ItemType Directory -Force -Path $Payload | Out-Null

Write-Host "Ensuring huggingface_hub is available..." -ForegroundColor Cyan
& $Python -m pip install --quiet --upgrade huggingface_hub
if ($LASTEXITCODE -ne 0) { throw "Could not install/update huggingface_hub." }

$Hf = Join-Path (Split-Path $Python -Parent) "hf.exe"
if (-not (Test-Path $Hf)) {
    $hfCmd = Get-Command hf -ErrorAction SilentlyContinue
    if ($hfCmd) { $Hf = $hfCmd.Source }
}
if (-not (Test-Path $Hf)) { throw "hf CLI is unavailable after installing huggingface_hub." }

$env:HF_XET_HIGH_PERFORMANCE = "1"
Write-Host "Staging Ornith 1.5 9B Q4_K_M bootstrap model..." -ForegroundColor Cyan
& $Hf download $Repo --include $Include --local-dir $Payload
if ($LASTEXITCODE -ne 0) { throw "Bootstrap model download failed." }

if (-not (Test-Path $Canonical)) {
    $found = Get-ChildItem -Path $Payload -Recurse -File | Where-Object { $_.Name -like $Include } | Select-Object -First 1
    if (-not $found) { throw "No Q4_K_M GGUF was found after downloading $Repo." }
    if ($found.FullName -ne $Canonical) {
        Copy-Item -Force $found.FullName $Canonical
    }
}

if (-not (Test-Path $Canonical) -or (Get-Item $Canonical).Length -le 0) {
    throw "Staged bootstrap model is missing or empty: $Canonical"
}

$sizeGb = [math]::Round((Get-Item $Canonical).Length / 1GB, 2)
Write-Host "Bootstrap payload ready: $Canonical ($sizeGb GB)" -ForegroundColor Green
