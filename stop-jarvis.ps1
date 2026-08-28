#Requires -Version 5.1
param(
    [switch]$IncludeTray
)

$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
$pidFile = Join-Path $Root "data\jarvis.pids"
$trayPidFile = Join-Path $Root "data\jarvis-tray.pid"

function Stop-Pid($processId) {
    try {
        $proc = Get-Process -Id $processId -ErrorAction Stop
        Stop-Process -Id $processId -Force -ErrorAction SilentlyContinue
        Write-Host "Stopped PID $processId ($($proc.ProcessName))"
    } catch {
        Write-Host "PID $processId already stopped"
    }
}

if (Test-Path $pidFile) {
    Get-Content $pidFile | ForEach-Object { if ($_ -match "^\d+$") { Stop-Pid ([int]$_) } }
    Remove-Item $pidFile -Force
}

Get-CimInstance Win32_Process | Where-Object {
    $_.Name -eq "llama-server.exe" -or
    ($_.Name -match "python" -and $_.CommandLine -match "uvicorn app.main:app")
} | ForEach-Object {
    Write-Host "Stopping $($_.Name) PID $($_.ProcessId)"
    Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue
}

if ($IncludeTray) {
    if (Test-Path $trayPidFile) {
        Get-Content $trayPidFile | ForEach-Object { if ($_ -match "^\d+$") { Stop-Pid ([int]$_) } }
        Remove-Item $trayPidFile -Force -ErrorAction SilentlyContinue
    }

    Get-CimInstance Win32_Process | Where-Object {
        $_.CommandLine -and $_.CommandLine -match "jarvis-tray\.ps1"
    } | ForEach-Object {
        Write-Host "Stopping tray helper PID $($_.ProcessId)"
        Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue
    }
}

Write-Host "Jarvis stopped."
