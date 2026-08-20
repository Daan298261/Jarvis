#Requires -Version 5.1
$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
$pidFile = Join-Path $Root "data\jarvis.pids"

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

Write-Host "Jarvis stopped."
