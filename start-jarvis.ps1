#Requires -Version 5.1
param(
    [switch]$NoBrowser,
    [switch]$SkipModelLoad
)

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $Root

function Write-Step($message) { Write-Host "`n==> $message" -ForegroundColor Cyan }

Write-Step "Verifying dependencies"
$python = (Get-Command python).Source
$node = (Get-Command node).Source
$llama = Join-Path $Root "runtime\llama.cpp\llama-server.exe"
$q4 = Join-Path $Root "models\Qwen3.5-27B-GGUF\Qwen3.5-27B-Q4_K_M.gguf"
$mmproj = Join-Path $Root "models\Qwen3.5-27B-GGUF\mmproj-F16.gguf"

if (-not (Test-Path $llama)) { throw "llama-server.exe missing at $llama" }
if (-not (Test-Path $q4)) { throw "Qwen3.5-27B Q4_K_M GGUF missing. See README.md to download." }
if (-not (Test-Path $mmproj)) { throw "Vision projector mmproj-F16.gguf missing." }
Write-Host "Python: $python"
Write-Host "Node: $node"
Write-Host "llama-server: $llama"
Write-Host "Model: $q4"

Write-Step "Building web portal if needed"
$dist = Join-Path $Root "frontend\dist\index.html"
if (-not (Test-Path $dist)) {
    Push-Location (Join-Path $Root "frontend")
    if (-not (Test-Path "node_modules")) { npm install }
    npm run build
    Pop-Location
}

New-Item -ItemType Directory -Force -Path (Join-Path $Root "data"), (Join-Path $Root "logs") | Out-Null
$pidFile = Join-Path $Root "data\jarvis.pids"

Write-Step "Starting Jarvis API"
$env:PYTHONPATH = Join-Path $Root "backend"
if ($SkipModelLoad) { $env:JARVIS_SKIP_MODEL = "1" }
$log = Join-Path $Root "logs\backend.log"
$backend = Start-Process -FilePath $python -ArgumentList "-m","uvicorn","app.main:app","--host","127.0.0.1","--port","4780","--app-dir","backend" -WorkingDirectory $Root -PassThru -WindowStyle Hidden -RedirectStandardOutput $log -RedirectStandardError (Join-Path $Root "logs\backend.err.log")
"$($backend.Id)" | Set-Content $pidFile
Write-Host "Backend PID $($backend.Id)"

Write-Step "Waiting for http://127.0.0.1:4780/api/health"
$ok = $false
for ($i = 0; $i -lt 180; $i++) {
    try {
        $response = Invoke-WebRequest -UseBasicParsing http://127.0.0.1:4780/api/health -TimeoutSec 3
        if ($response.StatusCode -eq 200) { $ok = $true; break }
    } catch {
        Start-Sleep -Seconds 2
    }
}
if (-not $ok) {
    Write-Host "Backend failed to start. Last backend error log:" -ForegroundColor Red
    Get-Content (Join-Path $Root "logs\backend.err.log") -ErrorAction SilentlyContinue | Select-Object -Last 40
    throw "Jarvis API did not become healthy."
}

Write-Host "Jarvis is running at http://127.0.0.1:4780" -ForegroundColor Green
if (-not $NoBrowser) {
    Start-Process "http://127.0.0.1:4780"
}
Write-Host "Stop with .\stop-jarvis.ps1"
