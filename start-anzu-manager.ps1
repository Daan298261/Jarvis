#Requires -Version 5.1
param([switch]$NoWindow)
$ErrorActionPreference = 'Stop'
$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
$python = Join-Path $Root '.venv\Scripts\python.exe'
if (-not (Test-Path $python)) { $python = (Get-Command python -ErrorAction Stop).Source }
$health = 'http://127.0.0.1:4782/api/manager/v1/status'
$running = $false
try { $running = (Invoke-WebRequest -UseBasicParsing -TimeoutSec 2 $health).StatusCode -eq 200 } catch { }
if (-not $running) {
    $args = @('-m','uvicorn','app.manager.main:app','--host','127.0.0.1','--port','4782','--app-dir',(Join-Path $Root 'backend'))
    $log = Join-Path $Root 'logs\anzu-manager.log'; New-Item -ItemType Directory -Force (Split-Path $log) | Out-Null
    Start-Process -FilePath $python -ArgumentList $args -WorkingDirectory $Root -RedirectStandardOutput $log -RedirectStandardError ($log + '.err') -WindowStyle Hidden
}
$managerExe = Join-Path $Root 'desktop\AnzuManager.exe'
if (Test-Path $managerExe) {
    $env:JARVIS_MANAGER = '1'
    $env:JARVIS_ROOT = $Root
    if ($NoWindow) { $env:JARVIS_MANAGER_MINIMIZED = '1' }
    Start-Process -FilePath $managerExe -WorkingDirectory $Root
}
