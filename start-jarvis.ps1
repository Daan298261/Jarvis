#Requires -Version 5.1
param(
    [switch]$NoBrowser,
    [switch]$SkipModelLoad,
    [string]$Prompt,
    [string]$PromptFile,
    [string]$PrivateKey,
    [string]$ExecutionMode = "balanced",
    [switch]$LanAccess,
    [switch]$Wait
)

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $Root

function Write-Step($message) { Write-Host "`n==> $message" -ForegroundColor Cyan }

Write-Step "Verifying dependencies"
$python = (Get-Command python).Source
$node = (Get-Command node).Source
$llama = Join-Path $Root "runtime\llama.cpp\llama-server.exe"
$q8 = Join-Path $Root "models\Qwen3.5-9B-abliterated-GGUF\Qwen3.5-9B-abliterated-Q8_0.gguf"
$q6 = Join-Path $Root "models\Qwen3.5-9B-abliterated-GGUF\Qwen3.5-9B-abliterated-Q6_K.gguf"
$q4 = Join-Path $Root "models\Qwen3.5-27B-GGUF\Qwen3.5-27B-Q4_K_M.gguf"

if (-not (Test-Path $llama)) { throw "llama-server.exe missing at $llama" }
$model = $null
if (Test-Path $q8) { $model = $q8 }
elseif (Test-Path $q6) { $model = $q6 }
elseif (Test-Path $q4) { $model = $q4 }
if (-not $model) {
    throw "No GGUF found. Download Qwen3.5-9B Abliterated Q8_0 (preferred) or keep Qwen3.5-27B Q4_K_M as Expert. See docs/INSTALL.md."
}
Write-Host "Python: $python"
Write-Host "Node: $node"
Write-Host "llama-server: $llama"
Write-Host "Model: $model"

Write-Step "Building web portal if needed"
$dist = Join-Path $Root "frontend\dist\index.html"
if (-not (Test-Path $dist)) {
    Push-Location (Join-Path $Root "frontend")
    if (-not (Test-Path "node_modules")) { npm install }
    npm run build
    Pop-Location
}

New-Item -ItemType Directory -Force -Path (Join-Path $Root "data"), (Join-Path $Root "logs"), (Join-Path $Root "data\queue\pending"), (Join-Path $Root "data\queue\processed"), (Join-Path $Root "data\queue\failed") | Out-Null
$pidFile = Join-Path $Root "data\jarvis.pids"

# Staging launch prompt if specified
if ($Prompt) {
    $ts = (Get-Date).ToString("yyyyMMdd_HHmmss_fff")
    $qFile = Join-Path $Root "data\queue\pending\launch_$ts.json"
    $taskDef = @{
        prompt = $Prompt
        autonomy = "autonomous"
        execution_mode = $ExecutionMode
        enqueued_at = (Get-Date).ToUniversalTime().ToString("o")
    } | ConvertTo-Json
    Set-Content -Path $qFile -Value $taskDef -Encoding UTF8
    Write-Host "Enqueued launch prompt to $qFile" -ForegroundColor Yellow
}
elseif ($PromptFile) {
    if (-not (Test-Path $PromptFile)) { throw "Prompt file not found at $PromptFile" }
    $ts = (Get-Date).ToString("yyyyMMdd_HHmmss_fff")
    $ext = [System.IO.Path]::GetExtension($PromptFile)
    $dest = Join-Path $Root "data\queue\pending\launch_$ts$ext"
    Copy-Item $PromptFile $dest
    Write-Host "Copied launch prompt file to $dest" -ForegroundColor Yellow
}

Write-Step "Starting Jarvis API"
$env:PYTHONPATH = Join-Path $Root "backend"
if ($SkipModelLoad) { $env:JARVIS_SKIP_MODEL = "1" }
if ($PrivateKey) { $env:JARVIS_PRIVATE_KEY = $PrivateKey }
$bindHost = if ($LanAccess) { "0.0.0.0" } else { "127.0.0.1" }
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
if ($LanAccess) {
    Write-Host "LAN Access is enabled (bound to 0.0.0.0). Private Key is required for API requests." -ForegroundColor Yellow
}

if ($Wait -and ($Prompt -or $PromptFile)) {
    Write-Step "Waiting for launch task completion..."
    $authHeaders = @{}
    $keyFile = Join-Path $Root "data\private_key.sec"
    if ($PrivateKey) {
        $authHeaders["X-Jarvis-Key"] = $PrivateKey
    } elseif (Test-Path $keyFile) {
        $authHeaders["X-Jarvis-Key"] = (Get-Content $keyFile -Raw).Trim()
    }

    $finished = $false
    while (-not $finished) {
        Start-Sleep -Seconds 3
        try {
            $tasks = Invoke-RestMethod -Uri "http://127.0.0.1:4780/api/tasks" -Headers $authHeaders
            if ($tasks -and $tasks.Count -gt 0) {
                $latest = $tasks[0]
                Write-Host "Task [$($latest.id)]: $($latest.status) - $($latest.stage) - $($latest.current_action)"
                if ($latest.status -in @("completed", "failed", "cancelled")) {
                    Write-Host "`nTask result: $($latest.result)" -ForegroundColor Cyan
                    if ($latest.verification) {
                        Write-Host "Verification: $($latest.verification)" -ForegroundColor Green
                    }
                    $finished = $true
                }
            }
        } catch {
            Write-Warning "Waiting on task poll: $_"
        }
    }
}
elseif (-not $NoBrowser) {
    Start-Process "http://127.0.0.1:4780"
}

Write-Host "Stop with .\stop-jarvis.ps1"
