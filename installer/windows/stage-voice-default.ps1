#Requires -Version 5.1
<#
.SYNOPSIS
  Stage default Kokoro-82M weights for the bundled household butler voice pack.

.DESCRIPTION
  Downloads hexgrad/Kokoro-82M into the installer payload. Safe to re-run when
  weights already exist. Use -SkipVoicePack on build-installer.ps1 for dev builds.
#>
param(
    [switch]$Force
)

$ErrorActionPreference = "Stop"
$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$Root = (Resolve-Path (Join-Path $ScriptDir "..\..")).Path
$Payload = Join-Path $ScriptDir "payload\models\tts\kokoro-82m"
$Marker = Join-Path $Payload ".jarvis_staged_ok"
$Repo = "hexgrad/Kokoro-82M"

if ((-not $Force) -and (Test-Path $Marker) -and (Get-ChildItem -Path $Payload -File -Recurse | Select-Object -First 1)) {
    Write-Host "Default Kokoro butler weights already staged: $Payload" -ForegroundColor Green
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
    throw "Python is required to stage the default Kokoro voice pack before building the installer."
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

Write-Host "Staging Kokoro-82M for default household butler..." -ForegroundColor Cyan
& $Hf download $Repo --local-dir $Payload
if ($LASTEXITCODE -ne 0) { throw "Kokoro-82M download failed." }

"ok" | Set-Content -Encoding ascii -Path $Marker
Write-Host "Default voice payload ready: $Payload" -ForegroundColor Green
