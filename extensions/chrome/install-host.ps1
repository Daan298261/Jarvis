param(
    [Parameter(Mandatory = $true)]
    [ValidatePattern('^[a-p]{32}$')]
    [string]$ExtensionId,
    [string]$PythonExecutable = (Get-Command python -ErrorAction Stop).Source,
    [switch]$Uninstall
)
$ErrorActionPreference = 'Stop'
$hostRoot = Join-Path $env:LOCALAPPDATA 'ANZU\chrome-connector'
$registryPath = 'HKCU:\Software\Google\Chrome\NativeMessagingHosts\com.anzu.website_connector'
if ($Uninstall) {
    if (Test-Path -LiteralPath $registryPath) { Remove-Item -LiteralPath $registryPath }
    Write-Output 'Native host unregistered. Remove the extension in chrome://extensions.'
    exit
}
$pythonPath = (Resolve-Path -LiteralPath $PythonExecutable).Path
if ($pythonPath -match '["%\r\n]' -or $hostRoot -match '["%\r\n]') { throw 'Unsupported launcher path' }
New-Item -ItemType Directory -Path $hostRoot -Force | Out-Null
Copy-Item -LiteralPath (Join-Path $PSScriptRoot 'native_host.py') -Destination (Join-Path $hostRoot 'native_host.py') -Force
$launcher = Join-Path $hostRoot 'host.cmd'
$launcherText = "@echo off`r`n`"$pythonPath`" -u `"$(Join-Path $hostRoot 'native_host.py')`" %*`r`n"
[IO.File]::WriteAllText($launcher, $launcherText, [Text.Encoding]::Default)
$manifestPath = Join-Path $hostRoot 'host-manifest.json'
$manifest = @{
    name = 'com.anzu.website_connector'
    description = 'ANZU selected website tab connector'
    path = $launcher
    type = 'stdio'
    allowed_origins = @("chrome-extension://$ExtensionId/")
} | ConvertTo-Json
[IO.File]::WriteAllText($manifestPath, $manifest, [Text.UTF8Encoding]::new($false))
New-Item -Path $registryPath -Force | Out-Null
Set-Item -LiteralPath $registryPath -Value $manifestPath
Write-Output 'ANZU native host registered for this extension. Open a website, click the extension, then Share this tab.'
