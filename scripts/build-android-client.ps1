#Requires -Version 5.1
<#
.SYNOPSIS
  Build a Jarvis Android APK preconfigured with a one-time pairing link.

.DESCRIPTION
  Uses the Capacitor scaffold under mobile/android-client. The generated APK
  never contains the long-lived Jarvis private key; it contains a one-time
  pairing URL that expires after ten minutes and is consumed on first use.

  If Android build tools are unavailable, Jarvis' Phone page remains installable
  as a zero-config PWA and the script explains what is missing.
#>
param(
    [string]$JarvisUrl = "http://127.0.0.1:4780",
    [switch]$InstallBuildTools
)

$ErrorActionPreference = "Stop"
$Root = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$Client = Join-Path $Root "mobile\android-client"
$Config = Join-Path $Client "www\config.json"
$OutDir = Join-Path $Root "data\setup"
$OutApk = Join-Path $OutDir "JarvisPhone.apk"

function Test-Command([string]$Name) { return [bool](Get-Command $Name -ErrorAction SilentlyContinue) }

if (-not (Test-Command node) -or -not (Test-Command npm)) {
    if (-not (Test-Command winget)) { throw "Node.js is required to build the Android client." }
    winget install --id OpenJS.NodeJS.LTS -e --accept-package-agreements --accept-source-agreements
}

$keyFile = Join-Path $Root "data\private_key.sec"
$headers = @{}
if (Test-Path $keyFile) {
    $key = (Get-Content $keyFile -Raw).Trim()
    if ($key) { $headers["X-Jarvis-Key"] = $key }
}

Write-Host "Requesting a one-time pairing link from Jarvis..." -ForegroundColor Cyan
try {
    $pair = Invoke-RestMethod -Method Post -Uri "$JarvisUrl/api/mobile/pairing" -Headers $headers -ContentType "application/json" -Body "{}"
} catch {
    throw "Jarvis must be running before the APK can be paired. Start Jarvis and retry. $($_.Exception.Message)"
}
if (-not $pair.urls -or $pair.urls.Count -lt 1) { throw "Jarvis did not return a phone pairing URL." }
$pairUrl = [string]$pair.urls[0]
New-Item -ItemType Directory -Force -Path (Split-Path $Config -Parent), $OutDir | Out-Null
@{ pairUrl = $pairUrl } | ConvertTo-Json | Set-Content -Path $Config -Encoding UTF8

Push-Location $Client
try {
    if (Test-Path "package-lock.json") { npm ci } else { npm install }
    if (-not (Test-Path "android")) { npx cap add android }
    npx cap sync android

    if (-not (Test-Command java)) {
        if ($InstallBuildTools -and (Test-Command winget)) {
            winget install --id Microsoft.OpenJDK.21 -e --accept-package-agreements --accept-source-agreements
        }
    }
    if (-not (Test-Command java)) {
        throw "Java is missing. Re-run with -InstallBuildTools or install JDK 21. The Jarvis Phone PWA is already usable without an APK."
    }

    $sdk = $env:ANDROID_HOME
    if (-not $sdk) { $sdk = $env:ANDROID_SDK_ROOT }
    if (-not $sdk) {
        $candidate = Join-Path $env:LOCALAPPDATA "Android\Sdk"
        if (Test-Path $candidate) { $sdk = $candidate }
    }
    if (-not $sdk -or -not (Test-Path $sdk)) {
        if ($InstallBuildTools -and (Test-Command winget)) {
            winget install --id Google.AndroidStudio -e --accept-package-agreements --accept-source-agreements
        }
        $candidate = Join-Path $env:LOCALAPPDATA "Android\Sdk"
        if (Test-Path $candidate) { $sdk = $candidate }
    }
    if (-not $sdk -or -not (Test-Path $sdk)) {
        throw "Android SDK is missing. Install Android Studio once, or use the installable Jarvis Phone PWA instead."
    }
    $env:ANDROID_HOME = $sdk
    $env:ANDROID_SDK_ROOT = $sdk

    Push-Location "android"
    try {
        & .\gradlew.bat assembleDebug
        if ($LASTEXITCODE -ne 0) { throw "Gradle Android build failed." }
    } finally { Pop-Location }

    $built = Join-Path $Client "android\app\build\outputs\apk\debug\app-debug.apk"
    if (-not (Test-Path $built)) { throw "Gradle completed but app-debug.apk was not found." }
    Copy-Item -Force $built $OutApk
} finally { Pop-Location }

Write-Host "Android client ready: $OutApk" -ForegroundColor Green
Write-Host "The embedded pairing link expires in about 10 minutes and can be used once." -ForegroundColor Yellow
Write-Host "Download it from Jarvis > Phone or /api/mobile/apk while this file remains on the PC." -ForegroundColor Green
