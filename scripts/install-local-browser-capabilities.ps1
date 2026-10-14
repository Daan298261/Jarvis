#Requires -Version 5.1
param([string]$InstallRoot = (Join-Path $env:LOCALAPPDATA 'Jarvis'))
$ErrorActionPreference = 'Stop'
$sourceRoot = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot '..')).Path
$targetRoot = (Resolve-Path -LiteralPath $InstallRoot).Path
if ($sourceRoot -eq $targetRoot) { throw 'Source and installed checkout must be different folders' }
if (-not (Test-Path -LiteralPath (Join-Path $targetRoot 'backend\app\main.py'))) { throw 'This updater needs a source-based ANZU installation' }
$files = @(
    'backend/app/agent/prompts.py','backend/app/api/tools.py','backend/app/policy/reversibility.py',
    'backend/app/tools/browser.py','backend/app/tools/chrome_connector.py','backend/app/tools/chrome_setup.py',
    'backend/app/workers/browser.py','backend/app/workers/computer.py','backend/app/workers/install.py',
    'backend/app/workers/isolated_entry.py','backend/app/workers/isolated_runtime.py',
    'frontend/src/pages/Tools.tsx','frontend/src/components/ChromeConnectorSetup.tsx',
    'extensions/chrome/manifest.json','extensions/chrome/background.js','extensions/chrome/ad-rules.js',
    'extensions/chrome/page.js','extensions/chrome/popup.html','extensions/chrome/popup.js',
    'extensions/chrome/native_host.py','extensions/chrome/install-host.ps1',
    'extensions/chrome/filters/easylist-domains.json','extensions/chrome/filters/NOTICE.md',
    'docs/chrome-connector.md','scripts/build-backend-sidecar.ps1','scripts/update-chrome-ad-list.py'
)
# Refuse to replace owner-modified source. Known baseline or this exact update only.
foreach ($relative in $files) {
    $target = Join-Path $targetRoot $relative
    $source = Join-Path $sourceRoot $relative
    if (-not (Test-Path -LiteralPath $source)) { throw "Missing update file: $relative" }
    if (-not (Test-Path -LiteralPath $target)) { continue }
    $installedHash = & git -C $sourceRoot hash-object -- $target
    $newHash = & git -C $sourceRoot hash-object -- $source
    & git -C $sourceRoot cat-file -e "91bd5e26^:$relative" 2>$null
    $baselineHash = if ($LASTEXITCODE -eq 0) { & git -C $sourceRoot rev-parse "91bd5e26^:$relative" } else { '' }
    if ($installedHash -ne $newHash -and $installedHash -ne $baselineHash) { throw "Installed file has separate changes; preserved without overwriting: $relative" }
}
$backup = Join-Path $env:LOCALAPPDATA ('ANZU\browser-update-backups\' + (Get-Date -Format 'yyyyMMdd-HHmmss'))
New-Item -ItemType Directory -Path $backup -Force | Out-Null
foreach ($relative in $files) {
    $target = Join-Path $targetRoot $relative
    if (Test-Path -LiteralPath $target) {
        $saved = Join-Path $backup $relative
        New-Item -ItemType Directory -Path (Split-Path $saved) -Force | Out-Null
        Copy-Item -LiteralPath $target -Destination $saved -Force
    }
    New-Item -ItemType Directory -Path (Split-Path $target) -Force | Out-Null
    Copy-Item -LiteralPath (Join-Path $sourceRoot $relative) -Destination $target -Force
}
$distSource = Join-Path $sourceRoot 'frontend\dist'
$distTarget = Join-Path $targetRoot 'frontend\dist'
if (Test-Path -LiteralPath $distTarget) { Copy-Item -LiteralPath $distTarget -Destination (Join-Path $backup 'frontend-dist') -Recurse -Force }
if (-not (Test-Path -LiteralPath (Join-Path $distSource 'index.html'))) { throw 'Build the frontend before installing this update' }
New-Item -ItemType Directory -Path $distTarget -Force | Out-Null
Get-ChildItem -LiteralPath $distSource | Copy-Item -Destination $distTarget -Recurse -Force
$native = Join-Path $sourceRoot 'runtime\chrome-native-host\anzu-chrome-host.exe'
if (Test-Path -LiteralPath $native) {
    $nativeTarget = Join-Path $targetRoot 'runtime\chrome-native-host'
    New-Item -ItemType Directory -Path $nativeTarget -Force | Out-Null
    Copy-Item -LiteralPath $native -Destination $nativeTarget -Force
}
@{ install_root = $targetRoot; backup = $backup; source_commit = (& git -C $sourceRoot rev-parse HEAD); files = $files } | ConvertTo-Json -Depth 3 | Set-Content -LiteralPath (Join-Path $backup 'update.json')
Write-Output "Installed browser capabilities. Previous files saved in $backup. Restart ANZU to activate the updated backend."
