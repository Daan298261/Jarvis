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

# Collection runs while the spec is evaluated, before Analysis applies --paths.
# Make the actual app package visible to the collector, including lazy imports.
$backendImportPath = Join-Path $Root "backend"
$env:PYTHONPATH = $backendImportPath + [IO.Path]::PathSeparator + $env:PYTHONPATH

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
    --hidden-import app.main `
    --hidden-import aiosqlite `
    --hidden-import kokoro `
    --collect-all kokoro `
    --hidden-import soundfile `
    --collect-all soundfile `
    --collect-data language_tags `
    --collect-all espeakng_loader `
    --collect-all misaki `
    --collect-all phonemizer `
    --collect-submodules app `
    --collect-all app `
    $entry
if ($LASTEXITCODE -ne 0) { throw "PyInstaller failed with exit code $LASTEXITCODE" }

$exe = Join-Path $OutDir "$name\$name.exe"
if (-not (Test-Path $exe)) {
    throw "PyInstaller finished but $exe is missing"
}

# Default voice is Kokoro. A green sidecar that cannot import it ships a
# degraded header. Fail the build instead of discovering that on the desktop.
& $exe --verify-frozen-imports
if ($LASTEXITCODE -ne 0) {
    throw "Frozen backend cannot import kokoro/soundfile. The desktop voice would stay degraded."
}

# Namespace-package collection can omit on-demand REA assets. Stage these
# explicitly beside the frozen package so setup and skill loading work installed.
$reaSource = Join-Path $Root "backend\app\reverse_engineering"
$reaAssets = Join-Path $OutDir "$name\_internal\app\reverse_engineering"
New-Item -ItemType Directory -Force -Path $reaAssets | Out-Null
Get-ChildItem -LiteralPath $reaSource -File | Where-Object { $_.Extension -in ".json", ".sh", ".mjs" } |
    Copy-Item -Destination $reaAssets -Force
Copy-Item -LiteralPath (Join-Path $reaSource "skill") -Destination $reaAssets -Recurse -Force

# Copy into Tauri resources for bundling
$tauriSidecar = Join-Path $Root "frontend\src-tauri\sidecars"
New-Item -ItemType Directory -Force -Path $tauriSidecar | Out-Null
$tauriSidecarTarget = Join-Path $tauriSidecar $name
if (-not $tauriSidecarTarget.StartsWith($Root + [IO.Path]::DirectorySeparatorChar, [StringComparison]::OrdinalIgnoreCase)) {
    throw "Sidecar target is outside the repository: $tauriSidecarTarget"
}
if (Test-Path $tauriSidecarTarget) {
    Remove-Item -LiteralPath $tauriSidecarTarget -Recurse -Force
}
Copy-Item -Recurse -Force (Join-Path $OutDir $name) (Join-Path $tauriSidecar $name)

Write-Host "OK: $exe" -ForegroundColor Green
Write-Host "Also copied to frontend\src-tauri\sidecars\$name" -ForegroundColor Green
Write-Host "Note: Playwright browsers / Office / GPU runtimes remain optional host capabilities." -ForegroundColor DarkGray
