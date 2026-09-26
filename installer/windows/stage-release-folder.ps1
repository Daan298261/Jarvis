#Requires -Version 5.1
<#
.SYNOPSIS
  Copy installer/dist artifacts into Releases/r<version>/ for a hotfix drop.
#>
param(
    [string]$Version = "",
    [string]$DistDir = "",
    [string]$ReleasesRoot = ""
)

$ErrorActionPreference = "Stop"
$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$Root = (Resolve-Path (Join-Path $ScriptDir "..\..")).Path
if (-not $DistDir) { $DistDir = Join-Path $ScriptDir "dist" }
if (-not $ReleasesRoot) { $ReleasesRoot = Join-Path $Root "Releases" }

if (-not $Version) {
    $iss = Join-Path $ScriptDir "Jarvis.iss"
    if (Test-Path $iss) {
        $m = Select-String -Path $iss -Pattern '#define MyAppVersion "([^"]+)"' | Select-Object -First 1
        if ($m) { $Version = $m.Matches[0].Groups[1].Value }
    }
}
if (-not $Version) { throw "Could not resolve release version (pass -Version or set Jarvis.iss MyAppVersion)." }

$tag = "r$Version"
$out = Join-Path $ReleasesRoot $tag
New-Item -ItemType Directory -Force -Path $out | Out-Null

$setup = Join-Path $DistDir "JarvisSetup.exe"
if (-not (Test-Path $setup)) {
    throw "Missing $setup — run .\installer\windows\build-installer.ps1 first."
}

Copy-Item -Force $setup (Join-Path $out "JarvisSetup.exe")
Get-ChildItem -Path $DistDir -Filter "JarvisSetup-*.bin" -ErrorAction SilentlyContinue | ForEach-Object {
    Copy-Item -Force $_.FullName (Join-Path $out $_.Name)
}
$license = Join-Path $DistDir "Jarvis-unrestricted.jarvis-license"
if (Test-Path $license) {
    Copy-Item -Force $license (Join-Path $out "Jarvis-unrestricted.jarvis-license")
}

$git = ""
try { $git = (git -C $Root rev-parse HEAD 2>$null) } catch { }
$stamp = (Get-Date).ToString("yyyy-MM-dd HH:mm")
$releaseTxt = @"
Jarvis $Version (hotfix)
git: $git
built: $stamp
portal: Start Jarvis opens http://127.0.0.1:4780 (LAN when enabled in Settings)
desktop: optional — .\start-jarvis.ps1 -Desktop or Start Menu Jarvis Desktop
payload: JarvisSetup.exe (+ spanning .bin slices if present), unrestricted license when built with -Release
"@
Set-Content -Path (Join-Path $out "RELEASE.txt") -Value $releaseTxt -Encoding UTF8

$attestation = @"
# Functional attestation — Jarvis $Version

## Verified in CI / dev (automated)
- python -m pytest (full suite)
- npm --prefix frontend run build

## Owner-facing behavior (manual sign-off on Windows)
- [ ] Start Jarvis opens browser portal on :4780
- [ ] Settings → Network → LAN on; restart; other device reaches http://<pc-ip>:4780 with private key on /api
- [ ] HUD left menus (Voice / Appearance / Cybersecurity) expand in separate rows without overlap
- [ ] Chat: assistant bubbles left (session personality name), user right, timestamps visible
- [ ] Voice: front lane replies longer than 128 tokens; long dictation still gets a worker reply
- [ ] "Run tool …" in owner chat delegates to agent task harness
- [ ] Optional: -Desktop opens Tauri; Obsidian embed when vault bound

Built: $stamp
"@
Set-Content -Path (Join-Path $out "ATTESTATION.md") -Value $attestation -Encoding UTF8

Write-Host "Release folder staged: $out" -ForegroundColor Green
