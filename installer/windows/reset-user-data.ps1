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

function Remove-TreeIfExists([string]$Path) {
    if (-not (Test-Path -LiteralPath $Path)) { return }
    Remove-Item -LiteralPath $Path -Recurse -Force -ErrorAction Stop
}

function Remove-FileIfExists([string]$Path) {
    if (-not (Test-Path -LiteralPath $Path)) { return }
    Remove-Item -LiteralPath $Path -Force -ErrorAction Stop
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
