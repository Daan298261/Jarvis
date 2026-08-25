#Requires -Version 5.1
param(
    [switch]$NoBrowser,
    [switch]$SkipModelLoad
)

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $Root
try { $Host.UI.RawUI.WindowTitle = "Jarvis" } catch { }

function Write-Step($message) { Write-Host "`n==> $message" -ForegroundColor Cyan }

$launcher = Join-Path $Root "install-desktop-launcher.ps1"
if (Test-Path $launcher) {
    try {
        & $launcher -Quiet
        if ($LASTEXITCODE -notin 0, $null) {
            Write-Host "Desktop launcher refresh failed (Jarvis will still start)." -ForegroundColor Yellow
        }
    } catch {
        Write-Host "Desktop launcher refresh failed (Jarvis will still start): $($_.Exception.Message)" -ForegroundColor Yellow
    }
}

try {
    $health = Invoke-WebRequest -UseBasicParsing http://127.0.0.1:4780/api/health -TimeoutSec 2
    if ($health.StatusCode -eq 200) {
        Write-Host "Jarvis is already running at http://127.0.0.1:4780" -ForegroundColor Green
        if (-not $NoBrowser) { Start-Process "http://127.0.0.1:4780" }
        return
    }
} catch { }

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
$bindHost = "127.0.0.1"
try {
    $resolved = (& $python -c 'from app.security import uvicorn_bind_host_from_files; print(uvicorn_bind_host_from_files())').Trim()
    if ($resolved) { $bindHost = $resolved }
} catch {
    $bindHost = "127.0.0.1"
}
if ($bindHost -eq "127.0.0.1" -or $bindHost -eq "localhost") {
    $settingsFile = Join-Path $Root "data\settings.json"
    if ((Test-Path $settingsFile) -and -not [string]$env:JARVIS_AUTH_TOKEN) {
        try {
            $cfg = Get-Content $settingsFile -Raw | ConvertFrom-Json
            if ($cfg.lan_access) {
                Write-Host "LAN access is on in settings but JARVIS_AUTH_TOKEN is empty; binding 127.0.0.1 only." -ForegroundColor Yellow
            }
        } catch { }
    }
} else {
    Write-Host "Binding API to ${bindHost}:4780. llama-server stays on 127.0.0.1:8088."
    Write-Host "LAN clients must send Authorization: Bearer <JARVIS_AUTH_TOKEN> or X-Jarvis-Token."
    Write-Host "If Windows Firewall prompts, allow Private network only - not Public."
}
$log = Join-Path $Root "logs\backend.log"
$backend = Start-Process -FilePath $python -ArgumentList "-m","uvicorn","app.main:app","--host",$bindHost,"--port","4780","--app-dir","backend" -WorkingDirectory $Root -PassThru -WindowStyle Hidden -RedirectStandardOutput $log -RedirectStandardError (Join-Path $Root "logs\backend.err.log")
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
Write-Host 'Stop with .\stop-jarvis.ps1'
