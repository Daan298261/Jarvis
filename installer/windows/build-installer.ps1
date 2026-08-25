#Requires -Version 5.1
<#
.SYNOPSIS
  Compile JarvisSetup.exe with Inno Setup (iscc).

.DESCRIPTION
  Run from the repository root or from installer/windows.
  Output: installer/windows/dist/JarvisSetup.exe (or dist/JarvisSetup.exe relative to .iss OutputDir).

.EXAMPLE
  .\installer\windows\build-installer.ps1
#>
$ErrorActionPreference = "Stop"

$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$Iss = Join-Path $ScriptDir "Jarvis.iss"
$OutDir = Join-Path $ScriptDir "dist"

function Find-Iscc {
    $cmd = Get-Command iscc -ErrorAction SilentlyContinue
    if ($cmd) { return $cmd.Source }

    $candidates = @(
        "$env:LOCALAPPDATA\Programs\Inno Setup 6\ISCC.exe",
        "${env:ProgramFiles(x86)}\Inno Setup 6\ISCC.exe",
        "$env:ProgramFiles\Inno Setup 6\ISCC.exe"
    )
    foreach ($path in $candidates) {
        if (Test-Path $path) { return $path }
    }
    return $null
}

$iscc = Find-Iscc
if (-not $iscc) {
    throw @"
Inno Setup compiler (iscc) not found.
Install Inno Setup 6 from https://jrsoftware.org/isinfo.php
Then re-run: .\installer\windows\build-installer.ps1
"@
}

New-Item -ItemType Directory -Force -Path $OutDir | Out-Null
Write-Host "Compiling $Iss ..."
& $iscc "/O$OutDir" $Iss
if ($LASTEXITCODE -ne 0) { throw "iscc failed with exit code $LASTEXITCODE" }

$exe = Join-Path $OutDir "JarvisSetup.exe"
if (-not (Test-Path $exe)) { throw "Expected output not found: $exe" }
Write-Host ""
Write-Host "Built: $exe" -ForegroundColor Green
