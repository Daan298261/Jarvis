#Requires -Version 5.1
<#
.SYNOPSIS
  Jarvis system tray helper (Open portal, Start, Stop, Quit).

.DESCRIPTION
  Runs while Jarvis is active. Open portal uses the local URL only (127.0.0.1).
  Stop ends the backend and llama-server but keeps this tray icon running.
  Quit stops Jarvis and exits the tray helper.
#>
$ErrorActionPreference = "Stop"

$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$Root = (Resolve-Path (Join-Path $ScriptDir "..\..")).Path
$PortalUrl = "http://127.0.0.1:4780"
$StartScript = Join-Path $Root "start-jarvis.ps1"
$StopScript = Join-Path $Root "stop-jarvis.ps1"
$TrayPidFile = Join-Path $Root "data\jarvis-tray.pid"

Add-Type -AssemblyName System.Windows.Forms
Add-Type -AssemblyName System.Drawing

function Open-Portal {
    Start-Process $PortalUrl
}

function Start-Jarvis {
    Start-Process -FilePath "powershell.exe" -ArgumentList @(
        "-NoProfile",
        "-ExecutionPolicy", "Bypass",
        "-File", $StartScript,
        "-NoBrowser"
    ) -WorkingDirectory $Root -WindowStyle Hidden
}

function Stop-Jarvis {
    & $StopScript
}

function Quit-Tray {
    Stop-Jarvis
    $script:notify.Visible = $false
    $script:notify.Dispose()
    if (Test-Path $TrayPidFile) {
        Remove-Item $TrayPidFile -Force -ErrorAction SilentlyContinue
    }
    [System.Windows.Forms.Application]::Exit()
}

$script:notify = New-Object System.Windows.Forms.NotifyIcon
$script:notify.Icon = [System.Drawing.SystemIcons]::Application
$script:notify.Text = "Jarvis"
$script:notify.Visible = $true

$menu = New-Object System.Windows.Forms.ContextMenuStrip
$null = $menu.Items.Add("Open portal", $null, { Open-Portal })
$null = $menu.Items.Add("Start", $null, { Start-Jarvis })
$null = $menu.Items.Add("Stop", $null, { Stop-Jarvis })
$null = $menu.Items.Add("Quit", $null, { Quit-Tray })
$script:notify.ContextMenuStrip = $menu
$script:notify.Add_DoubleClick({ Open-Portal })

try {
    New-Item -ItemType Directory -Force -Path (Split-Path $TrayPidFile) | Out-Null
    $PID | Set-Content $TrayPidFile
} catch {
    # Non-fatal if the pid file cannot be written.
}

[System.Windows.Forms.Application]::EnableVisualStyles()
[System.Windows.Forms.Application]::Run()
