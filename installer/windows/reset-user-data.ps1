#Requires -Version 5.1
<#
.SYNOPSIS
  Remove Jarvis user-generated data (chats, routines, memory, logs) under an install root.

.DESCRIPTION
  Semi-clean reinstall: keeps downloaded models, runtime binaries, private key, and license
  material. Does not remove models/, runtime/, or data/private_key.sec.

.PARAMETER InstallRoot
  Jarvis installation directory (e.g. %LOCALAPPDATA%\Jarvis).
#>
param(
    [Parameter(Mandatory = $true)]
    [string]$InstallRoot
)

$ErrorActionPreference = "Stop"

function Clear-ReadOnlyTree([string]$Path) {
    if (-not (Test-Path -LiteralPath $Path)) { return }
    try { cmd.exe /c "attrib -R -S -H `"$Path`" /S /D" | Out-Null } catch { }
}

function Remove-PathRetry([string]$Path, [switch]$Recurse) {
    if (-not (Test-Path -LiteralPath $Path)) { return }
    $attempts = 6
    for ($i = 1; $i -le $attempts; $i++) {
        if (-not (Test-Path -LiteralPath $Path)) { return }
        try {
            Clear-ReadOnlyTree $Path
            if ($Recurse) {
                Remove-Item -LiteralPath $Path -Recurse -Force -ErrorAction Stop
            } else {
                Remove-Item -LiteralPath $Path -Force -ErrorAction Stop
            }
            if (-not (Test-Path -LiteralPath $Path)) { return }
        } catch {
            if ($i -eq $attempts) { throw }
            Start-Sleep -Milliseconds (250 * $i)
        }
    }
    if (Test-Path -LiteralPath $Path) {
        throw "Could not delete $Path after $attempts attempts"
    }
}

function Remove-TreeIfExists([string]$Path) {
    Remove-PathRetry $Path -Recurse
}

function Remove-FileIfExists([string]$Path) {
    Remove-PathRetry $Path
}

$root = (Resolve-Path -LiteralPath $InstallRoot).Path
$data = Join-Path $root "data"
$logs = Join-Path $root "logs"

$dataDirs = @(
    "queue",
    "workflows",
    "trajectories",
    "context-repos",
    "worktrees",
    "marketing",
    "autonomy-profiles",
    "self_dev",
    "guest-portals",
    "browser-profile",
    "downloads",
    "screenshots",
    "mobile",
    "setup",
    "worker-environments",
    "packs",
    "benchmarks",
    "agent-suite",
    "policy"
)

$dataFiles = @(
    "settings.json",
    "hexstrike-audit.jsonl",
    "perception_state.json",
    "identity_embeddings.enc",
    "identity_embeddings.key"
)

if (Test-Path -LiteralPath $data) {
    foreach ($name in $dataDirs) {
        Remove-TreeIfExists (Join-Path $data $name)
    }
    foreach ($name in $dataFiles) {
        Remove-FileIfExists (Join-Path $data $name)
    }
    Get-ChildItem -LiteralPath $data -Filter "jarvis.db*" -File -ErrorAction SilentlyContinue | ForEach-Object {
        Remove-Item -LiteralPath $_.FullName -Force
    }
}

Remove-TreeIfExists $logs

Write-Host "Jarvis user data reset complete under: $root" -ForegroundColor Green
Write-Host "Preserved: models/, runtime/, data/private_key.sec, data/licensing/, data/runtime-profiles/" -ForegroundColor DarkGray
