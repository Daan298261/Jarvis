#Requires -Version 5.1
<#
.SYNOPSIS
  Copy customer deliverables into <repo>\release\ and, optionally, an external Drive folder.

.DESCRIPTION
  Every build publishes the customer set into the gitignored repo folder
  <repoRoot>\release\, in addition to the build's existing output directory.

  The customer set is the self-contained package we ship:
    - AnzuSetup.exe and AnzuSetup-*.bin disk slices
    - older JarvisSetup.exe / JarvisSetup-*.bin builds, still accepted
    - Tauri NSIS *-setup.exe when that bundle directory is the source
    - issued *.jarvis-license files
    - JarvisLicenseManager.exe / .cmd when the vendor build produced them
    - companion *.apk files present in the source directory

  Source archives (.zip, .tar, .tar.gz, .tgz, .7z) are never copied.

  -DriveReleasesPath, when set, copies that same set from <repoRoot>\release\
  into the given folder (the Google Drive "Jarvis Releases" drop). When the
  parameter is omitted, only the in-repo release\ copy runs.

  -StageVersionedHotfix also writes the legacy Releases\r<version>\ notes
  folder (RELEASE.txt and ATTESTATION.md). Those notes stay out of release\.

.PARAMETER DriveReleasesPath
  Optional external directory. Files are copied from <repoRoot>\release\ into
  this path after the in-repo copy. Relative paths resolve from the repo root.

.PARAMETER StageVersionedHotfix
  Also stage Releases\r<version>\ with hotfix notes. Used by -Release cuts.
#>
param(
    [string]$Version = "",
    [string]$DistDir = "",
    [string]$ReleasesRoot = "",
    [string]$ReleaseDir = "",
    [string]$DriveReleasesPath = "",
    [switch]$StageVersionedHotfix
)

$ErrorActionPreference = "Stop"
$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$Root = (Resolve-Path (Join-Path $ScriptDir "..\..")).Path
if (-not $DistDir) { $DistDir = Join-Path $ScriptDir "dist" }
if (-not $ReleasesRoot) { $ReleasesRoot = Join-Path $Root "Releases" }
if (-not $ReleaseDir) { $ReleaseDir = Join-Path $Root "release" }

function Test-CustomerDeliverable {
    param([string]$Name)
    $lower = $Name.ToLowerInvariant()
    if ($lower.EndsWith(".zip") -or $lower.EndsWith(".tar") -or $lower.EndsWith(".tar.gz") -or $lower.EndsWith(".tgz") -or $lower.EndsWith(".7z")) {
        return $false
    }
    if ($lower.EndsWith(".jarvis-license")) { return $true }
    if ($lower -eq "anzusetup.exe" -or $lower -eq "jarvissetup.exe") { return $true }
    if ($lower.EndsWith("-setup.exe")) { return $true }
    if ($lower -eq "jarvislicensemanager.exe") { return $true }
    if ($lower -eq "jarvislicensemanager.cmd") { return $true }
    if ($lower.EndsWith(".apk")) { return $true }
    if (($Name.StartsWith("AnzuSetup-") -or $Name.StartsWith("JarvisSetup-")) -and $lower.EndsWith(".bin")) { return $true }
    return $false
}

function Get-CustomerDeliverables {
    param([string]$Dir)
    if (-not (Test-Path -LiteralPath $Dir)) {
        throw "Deliverable source folder not found: $Dir"
    }
    $found = New-Object System.Collections.Generic.List[System.IO.FileInfo]
    $seen = @{}
    foreach ($name in @("AnzuSetup.exe", "JarvisSetup.exe", "JarvisLicenseManager.exe", "JarvisLicenseManager.cmd")) {
        $path = Join-Path $Dir $name
        if (Test-Path -LiteralPath $path) {
            $item = Get-Item -LiteralPath $path
            if ((Test-CustomerDeliverable $item.Name) -and -not $seen.ContainsKey($item.Name)) {
                $seen[$item.Name] = $true
                $found.Add($item)
            }
        }
    }
    foreach ($filter in @("*-setup.exe", "AnzuSetup-*.bin", "JarvisSetup-*.bin", "*.jarvis-license", "*.apk")) {
        Get-ChildItem -LiteralPath $Dir -Filter $filter -File -ErrorAction SilentlyContinue | ForEach-Object {
            if ((Test-CustomerDeliverable $_.Name) -and -not $seen.ContainsKey($_.Name)) {
                $seen[$_.Name] = $true
                $found.Add($_)
            }
        }
    }
    foreach ($item in $found) { $item }
}

$items = @(Get-CustomerDeliverables $DistDir)
if ($items.Count -eq 0) {
    throw "No customer deliverables in $DistDir. Expected AnzuSetup.exe, a *-setup.exe installer, a companion APK, an issued license, or the license manager."
}

New-Item -ItemType Directory -Force -Path $ReleaseDir | Out-Null
$publishedNames = New-Object System.Collections.Generic.List[string]
foreach ($item in $items) {
    if (-not (Test-CustomerDeliverable $item.Name)) {
        throw "Refusing to publish non-customer artifact: $($item.Name)"
    }
    Copy-Item -LiteralPath $item.FullName -Destination (Join-Path $ReleaseDir $item.Name) -Force
    $publishedNames.Add($item.Name)
}
Write-Host "Customer deliverables copied to $ReleaseDir ($($publishedNames.Count))" -ForegroundColor Green

$drive = ""
if ($DriveReleasesPath) { $drive = $DriveReleasesPath.Trim() }
if ($drive) {
    if (-not [System.IO.Path]::IsPathRooted($drive)) {
        $drive = Join-Path $Root $drive
    }
    New-Item -ItemType Directory -Force -Path $drive | Out-Null
    foreach ($name in $publishedNames) {
        $src = Join-Path $ReleaseDir $name
        if (-not (Test-Path -LiteralPath $src)) {
            throw "Expected deliverable missing from release folder: $src"
        }
        Copy-Item -LiteralPath $src -Destination (Join-Path $drive $name) -Force
    }
    Write-Host "Customer deliverables copied from $ReleaseDir to $drive" -ForegroundColor Green
}

if (-not $StageVersionedHotfix) {
    return
}

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

$setup = Join-Path $DistDir "AnzuSetup.exe"
if (-not (Test-Path $setup)) {
    $setup = Join-Path $DistDir "JarvisSetup.exe"
}
if (-not (Test-Path $setup)) {
    throw "Missing AnzuSetup.exe - run installer\windows\build-installer.ps1 first."
}

Copy-Item -Force $setup (Join-Path $out (Split-Path -Leaf $setup))
foreach ($sliceFilter in @("AnzuSetup-*.bin", "JarvisSetup-*.bin")) {
    Get-ChildItem -Path $DistDir -Filter $sliceFilter -ErrorAction SilentlyContinue | ForEach-Object {
        Copy-Item -Force $_.FullName (Join-Path $out $_.Name)
    }
}
$license = Join-Path $DistDir "Jarvis-unrestricted.jarvis-license"
if (Test-Path $license) {
    Copy-Item -Force $license (Join-Path $out "Jarvis-unrestricted.jarvis-license")
}

$git = ""
try { $git = (git -C $Root rev-parse HEAD 2>$null) } catch { }
$stamp = (Get-Date).ToString("yyyy-MM-dd HH:mm")
$releaseTxt = @"
ANZU $Version (hotfix)
git: $git
built: $stamp
portal: Start ANZU opens http://127.0.0.1:4780 (LAN when enabled in Settings)
desktop: optional - .\start-jarvis.ps1 -Desktop or Start Menu ANZU Desktop
payload: AnzuSetup.exe (+ spanning .bin slices if present), unrestricted license when built with -Release
"@
Set-Content -Path (Join-Path $out "RELEASE.txt") -Value $releaseTxt -Encoding UTF8

$attestation = @"
# Functional attestation - ANZU $Version

## Verified in CI / dev (automated)
- python -m pytest (full suite)
- npm --prefix frontend run build

## Owner-facing behavior (manual sign-off on Windows)
- [ ] Start ANZU opens browser portal on :4780
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
