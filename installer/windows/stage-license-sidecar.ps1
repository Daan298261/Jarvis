#Requires -Version 5.1
<#
.SYNOPSIS
  RFC-0199: Detect customer *.jarvis-license beside JarvisSetup.exe and stage pending apply.
#>
param(
    [Parameter(Mandatory = $true)]
    [string]$InstallerDir,

    [Parameter(Mandatory = $true)]
    [string]$AppRoot
)

$ErrorActionPreference = "Stop"
$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$Root = (Resolve-Path (Join-Path $ScriptDir "..\..")).Path
$logDir = Join-Path $Root "logs"
$logPath = Join-Path $logDir "installer-sidecar.log"
New-Item -ItemType Directory -Force -Path $logDir | Out-Null

function Write-SidecarLog([string]$Message) {
    $line = "{0:yyyy-MM-dd HH:mm:ss} {1}" -f (Get-Date), $Message
    Add-Content -LiteralPath $logPath -Value $line -Encoding UTF8
    Write-Host $line
}

function Resolve-PythonExe {
    $venv = Join-Path $Root ".venv\Scripts\python.exe"
    if (Test-Path $venv) { return $venv }
    $py = Get-Command python -ErrorAction SilentlyContinue
    if ($py) { return $py.Source }
    $py3 = Get-Command python3 -ErrorAction SilentlyContinue
    if ($py3) { return $py3.Source }
    return $null
}

$python = Resolve-PythonExe
if (-not $python) {
    Write-SidecarLog "License sidecar staging skipped: python not found."
    exit 0
}

$env:PYTHONPATH = Join-Path $Root "backend"
Write-SidecarLog "RFC-0199 stage sidecar InstallerDir=$InstallerDir AppRoot=$AppRoot"
& $python -m app.installer.license_sidecar stage --installer-dir $InstallerDir --app-root $AppRoot 2>&1 | ForEach-Object {
    Write-SidecarLog $_
    $_
}
$code = $LASTEXITCODE
if ($code -ne 0) {
    Write-SidecarLog "License sidecar staging failed with exit code $code (see $logPath)."
}
exit $code
