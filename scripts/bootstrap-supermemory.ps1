#Requires -Version 5.1
# RFC-0132: install the pinned official Supermemory Windows sidecar from GitHub Releases.
[CmdletBinding()]
param(
    [string]$InstallPath = ''
)

$ErrorActionPreference = 'Stop'
if ([string]::IsNullOrWhiteSpace($InstallPath)) {
    $InstallPath = Join-Path $PSScriptRoot '..\runtime\supermemory'
}
$Version = '0.0.8'
$Release = "server-v$Version"
$Asset = 'supermemory-server-windows-x64.exe'
$ExpectedSha256 = 'd8fb2ac0d52eeb230ad15dc8bf70dbc2ae481f0f8cfaeec70d97f7955ce71c47'
$BaseUrl = "https://github.com/supermemoryai/supermemory/releases/download/$Release"

$ResolvedInstall = [System.IO.Path]::GetFullPath($InstallPath)
$Binary = Join-Path $ResolvedInstall 'supermemory-server.exe'
$SourceRecord = Join-Path $ResolvedInstall 'source.json'

Write-Output 'STAGE:validate'
if (Test-Path -LiteralPath $Binary) {
    $ExistingSha = (Get-FileHash -LiteralPath $Binary -Algorithm SHA256).Hash.ToLowerInvariant()
    if ($ExistingSha -ne $ExpectedSha256) {
        throw "Refusing to overwrite unrecognized Supermemory binary at $Binary"
    }
    Write-Output "RESULT:$Binary"
    Write-Output 'STAGE:ready'
    return
}

[System.IO.Directory]::CreateDirectory($ResolvedInstall) | Out-Null
$Staging = Join-Path $ResolvedInstall (".$Asset.staging-" + [guid]::NewGuid().ToString('N'))

try {
    Write-Output 'STAGE:download'
    Invoke-WebRequest -UseBasicParsing -Uri "$BaseUrl/$Asset" -OutFile $Staging

    Write-Output 'STAGE:checksum'
    $ActualSha = (Get-FileHash -LiteralPath $Staging -Algorithm SHA256).Hash.ToLowerInvariant()
    if ($ActualSha -ne $ExpectedSha256) {
        throw "Supermemory checksum mismatch: $ActualSha"
    }

    Move-Item -LiteralPath $Staging -Destination $Binary
    @{
        repository = 'https://github.com/supermemoryai/supermemory'
        release = $Release
        asset = $Asset
        sha256 = $ExpectedSha256
        installed_at = [DateTimeOffset]::UtcNow.ToString('o')
    } | ConvertTo-Json | Set-Content -LiteralPath $SourceRecord -Encoding UTF8
} finally {
    if (Test-Path -LiteralPath $Staging) {
        Remove-Item -LiteralPath $Staging -Force
    }
}

Write-Output "RESULT:$Binary"
Write-Output 'STAGE:ready'
