#Requires -Version 5.1
<#
.SYNOPSIS
  RFC-0124: Jarvis-owned path registry and safety gates for clean reinstall.
#>

$ErrorActionPreference = "Stop"

$script:JarvisOwnedPathsRegKey = "HKCU:\Software\Jarvis\OwnedPaths"
$script:LicenseIssuerLeaf = "license-issuer"

function Get-DefaultJarvisInstallDir {
    $local = [Environment]::GetFolderPath("LocalApplicationData")
    return Join-Path $local "Jarvis"
}

function Test-IsSafeJarvisInstallDir {
    param([Parameter(Mandatory = $true)][string]$Path)
    $candidate = $Path.TrimEnd('\') + '\'
    $defaultPath = (Get-DefaultJarvisInstallDir).TrimEnd('\') + '\'
    if ($candidate.Equals($defaultPath, [StringComparison]::OrdinalIgnoreCase)) {
        return $true
    }
    $start = Join-Path $Path "start-jarvis.ps1"
    $unins = Join-Path $Path "unins000.exe"
    $iss = Join-Path $Path "installer\windows\Jarvis.iss"
    return (Test-Path -LiteralPath $start) -and (Test-Path -LiteralPath $unins) -and (Test-Path -LiteralPath $iss)
}

function Test-IsUnderJarvisOwnedRoot {
    param(
        [Parameter(Mandatory = $true)][string]$Child,
        [Parameter(Mandatory = $true)][string]$Root
    )
    try {
        $childNorm = [System.IO.Path]::GetFullPath($Child).TrimEnd('\') + '\'
        $rootNorm = [System.IO.Path]::GetFullPath($Root).TrimEnd('\') + '\'
        return $childNorm.StartsWith($rootNorm, [StringComparison]::OrdinalIgnoreCase)
    } catch {
        return $false
    }
}

function Get-BlockedOwnerPathRoots {
    $profile = $env:USERPROFILE
    $blocked = @(
        $profile,
        [Environment]::GetFolderPath("Desktop"),
        [Environment]::GetFolderPath("MyDocuments"),
        [Environment]::GetFolderPath("Downloads"),
        [Environment]::GetFolderPath("LocalApplicationData")
    ) | Where-Object { $_ -and $_.Trim() }
    return @($blocked | Select-Object -Unique)
}

function Test-PathIsBlockedOwnerRoot {
    param([Parameter(Mandatory = $true)][string]$Path)
    $norm = try { [System.IO.Path]::GetFullPath($Path).TrimEnd('\') } catch { return $true }
    foreach ($blocked in Get-BlockedOwnerPathRoots) {
        $b = try { [System.IO.Path]::GetFullPath($blocked).TrimEnd('\') } catch { continue }
        if ($norm.Equals($b, [StringComparison]::OrdinalIgnoreCase)) {
            return $true
        }
    }
    return $false
}

function Read-OwnedPathsRegistry {
    $result = @{
        InstallRoot = ""
        DataDirectory = ""
        SetupExe = ""
    }
    if (-not (Test-Path -LiteralPath $script:JarvisOwnedPathsRegKey)) {
        return $result
    }
    $props = Get-ItemProperty -LiteralPath $script:JarvisOwnedPathsRegKey -ErrorAction SilentlyContinue
    if ($props) {
        $result.InstallRoot = [string]$props.InstallLocation
        $result.DataDirectory = [string]$props.DataDirectory
        $result.SetupExe = [string]$props.SetupExe
    }
    return $result
}

function Write-OwnedPathsRegistry {
    param(
        [Parameter(Mandatory = $true)][string]$InstallRoot,
        [string]$DataDirectory = "",
        [string]$SetupExe = ""
    )
    if (-not (Test-Path -LiteralPath "HKCU:\Software\Jarvis")) {
        New-Item -Path "HKCU:\Software\Jarvis" -Force | Out-Null
    }
    if (-not (Test-Path -LiteralPath $script:JarvisOwnedPathsRegKey)) {
        New-Item -Path $script:JarvisOwnedPathsRegKey -Force | Out-Null
    }
    Set-ItemProperty -LiteralPath $script:JarvisOwnedPathsRegKey -Name InstallLocation -Value $InstallRoot
    if ($DataDirectory) {
        Set-ItemProperty -LiteralPath $script:JarvisOwnedPathsRegKey -Name DataDirectory -Value $DataDirectory
    }
    if ($SetupExe) {
        Set-ItemProperty -LiteralPath $script:JarvisOwnedPathsRegKey -Name SetupExe -Value $SetupExe
    }
}

function Resolve-InstallRootCandidate {
    param([string]$InstallRoot = "")
    if ($InstallRoot -and (Test-Path -LiteralPath $InstallRoot)) {
        return (Resolve-Path -LiteralPath $InstallRoot).Path
    }
    $reg = Read-OwnedPathsRegistry
    if ($reg.InstallRoot -and (Test-Path -LiteralPath $reg.InstallRoot)) {
        return (Resolve-Path -LiteralPath $reg.InstallRoot).Path
    }
    $default = Get-DefaultJarvisInstallDir
    if (Test-Path -LiteralPath $default) {
        return (Resolve-Path -LiteralPath $default).Path
    }
    return $default
}

function Get-RegisteredOwnedJarvisRoots {
    param(
        [string]$InstallRoot = "",
        [string[]]$ExtraAllowedDirectories = @()
    )
    $roots = New-Object System.Collections.Generic.List[string]
    $install = Resolve-InstallRootCandidate -InstallRoot $InstallRoot
    if (Test-IsSafeJarvisInstallDir -Path $install) {
        $roots.Add($install)
    }
    $reg = Read-OwnedPathsRegistry
    if ($reg.DataDirectory) {
        $data = $reg.DataDirectory
        if ((Test-IsSafeJarvisInstallDir -Path $install) -and (Test-IsUnderJarvisOwnedRoot -Child $data -Root $install)) {
            if (-not $roots.Contains($data)) { $roots.Add($data) }
        }
    }
    foreach ($extra in $ExtraAllowedDirectories) {
        $trim = ([string]$extra).Trim()
        if (-not $trim) { continue }
        if (Test-PathIsBlockedOwnerRoot -Path $trim) { continue }
        if (-not (Test-IsSafeJarvisInstallDir -Path $install)) { continue }
        if (Test-IsUnderJarvisOwnedRoot -Child $trim -Root $install) {
            if (-not $roots.Contains($trim)) { $roots.Add($trim) }
        }
    }
    return @($roots | Select-Object -Unique)
}

function Get-LicenseIssuerPreservePath {
    param([Parameter(Mandatory = $true)][string]$InstallRoot)
    return Join-Path $InstallRoot $script:LicenseIssuerLeaf
}
