#Requires -Version 5.1
<#
.SYNOPSIS
  Build the Jarvis FastAPI backend as a PyInstaller one-folder Windows sidecar.

.DESCRIPTION
  Produces runtime/backend/jarvis-backend/ containing jarvis-backend.exe and deps.
  End users of the desktop app do not need Python installed.

  Desktop sign-off required: this script must be run on Windows.
#>
param(
    [string]$OutDir = ""
)

$ErrorActionPreference = "Stop"
$Root = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
Set-Location $Root

if (-not $OutDir) {
    $OutDir = Join-Path $Root "runtime\backend"
}

Write-Host "==> Building Jarvis backend sidecar (PyInstaller one-folder)" -ForegroundColor Cyan

$py = Join-Path $Root ".venv\Scripts\python.exe"
if (-not (Test-Path $py)) {
    $py = (Get-Command python -ErrorAction SilentlyContinue).Source
}
if (-not $py) { throw "Python not found. Create .venv or install Python 3.11+." }

& $py -m pip install --upgrade pip
& $py -m pip install -r (Join-Path $Root "backend\requirements.txt")
& $py -m pip install "pyinstaller>=6.0"

$work = Join-Path $env:TEMP "jarvis-pyinstaller"
New-Item -ItemType Directory -Force -Path $OutDir, $work | Out-Null

$entry = Join-Path $Root "backend\jarvis_sidecar.py"
$name = "jarvis-backend"

# one-folder (not --onefile) for faster start and clearer AV/debug behavior
& $py -m PyInstaller `
    --noconfirm `
    --clean `
    --onedir `
    --name $name `
    --paths (Join-Path $Root "backend") `
    --distpath $OutDir `
    --workpath $work `
    --specpath $work `
    --hidden-import uvicorn.logging `
    --hidden-import uvicorn.loops `
    --hidden-import uvicorn.loops.auto `
    --hidden-import uvicorn.protocols `
    --hidden-import uvicorn.protocols.http `
    --hidden-import uvicorn.protocols.http.auto `
    --hidden-import uvicorn.protocols.websockets `
    --hidden-import uvicorn.protocols.websockets.auto `
    --hidden-import uvicorn.lifespan `
    --hidden-import uvicorn.lifespan.on `
    --collect-all app `
    $entry

$exe = Join-Path $OutDir "$name\$name.exe"
if (-not (Test-Path $exe)) {
    throw "PyInstaller finished but $exe is missing"
}

# Copy into Tauri resources for bundling
$tauriSidecar = Join-Path $Root "frontend\src-tauri\sidecars"
New-Item -ItemType Directory -Force -Path $tauriSidecar | Out-Null
Copy-Item -Recurse -Force (Join-Path $OutDir $name) (Join-Path $tauriSidecar $name)

Write-Host "OK: $exe" -ForegroundColor Green
Write-Host "Also copied to frontend\src-tauri\sidecars\$name" -ForegroundColor Green
Write-Host "Note: Playwright browsers / Office / GPU runtimes remain optional host capabilities." -ForegroundColor DarkGray
