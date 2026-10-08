#Requires -Version 5.1
<#
.SYNOPSIS
  Stage the bundled Qwen3.5-2B Q4_K_M front-lane model before compiling JarvisSetup.exe.

.DESCRIPTION
  Downloads unsloth/Qwen3.5-2B-GGUF (Qwen3.5-2B-Q4_K_M.gguf) into the installer
  payload. The binary is not committed to Git. A staged file is reused only
  after its size and SHA-256 match; the result is cached in a marker so reruns
  do not hash the file again.

  A verified local copy is copied instead of downloaded when either of these
  exists and matches the expected hash:
    - $env:JARVIS_FRONT_2B_GGUF (full path to the GGUF)
    - <repo>\models\Qwen3.5-2B-GGUF\Qwen3.5-2B-Q4_K_M.gguf
#>
param(
    [switch]$Force
)

$ErrorActionPreference = "Stop"
$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$Root = (Resolve-Path (Join-Path $ScriptDir "..\..")).Path
$Payload = Join-Path $ScriptDir "payload\models\Qwen3.5-2B-GGUF"
$Canonical = Join-Path $Payload "Qwen3.5-2B-Q4_K_M.gguf"
$Marker = Join-Path $Payload ".jarvis_front_2b_verified"
$Repo = "unsloth/Qwen3.5-2B-GGUF"
$Include = "Qwen3.5-2B-Q4_K_M.gguf"
# Official unsloth/Qwen3.5-2B-GGUF Q4_K_M (1,280,835,840 bytes).
$ExpectedBytes = 1280835840
$ExpectedSha = "aaf42c8b7c3cab2bf3d69c355048d4a0ee9973d48f16c731c0520ee914699223"

function Get-FrontSha256([string]$Path) {
    return (Get-FileHash -Algorithm SHA256 -LiteralPath $Path).Hash.ToLowerInvariant()
}

function Write-FrontVerifiedMarker {
    New-Item -ItemType Directory -Force -Path $Payload | Out-Null
    Set-Content -LiteralPath $Marker -Value $ExpectedSha -Encoding ascii -NoNewline
}

function Assert-ExpectedFrontFile([string]$Path, [string]$Label) {
    if (-not (Test-Path -LiteralPath $Path)) {
        throw "$Label is missing: $Path"
    }
    $length = [int64](Get-Item -LiteralPath $Path).Length
    $hash = Get-FrontSha256 $Path
    if ($length -ne $ExpectedBytes -or $hash -ne $ExpectedSha) {
        throw @"
$Label failed verification: $Path
Expected $ExpectedBytes bytes and SHA-256 $ExpectedSha
Actual   $length bytes and SHA-256 $hash
"@
    }
}

function Test-ReusableFrontFile([string]$Path) {
    if (-not $Path -or -not (Test-Path -LiteralPath $Path)) { return $false }
    $length = [int64](Get-Item -LiteralPath $Path).Length
    if ($length -ne $ExpectedBytes) {
        Write-Warning "Ignoring $Path (size $length, expected $ExpectedBytes)."
        return $false
    }
    $hash = Get-FrontSha256 $Path
    if ($hash -ne $ExpectedSha) {
        Write-Warning "Ignoring $Path (SHA-256 $hash does not match the bundled Qwen3.5-2B Q4_K_M)."
        return $false
    }
    return $true
}

function Same-Path([string]$Left, [string]$Right) {
    if (-not $Left -or -not $Right) { return $false }
    $a = [System.IO.Path]::GetFullPath($Left)
    $b = [System.IO.Path]::GetFullPath($Right)
    return [string]::Equals($a, $b, [StringComparison]::OrdinalIgnoreCase)
}

function Install-VerifiedFrontFile([string]$SourcePath) {
    New-Item -ItemType Directory -Force -Path $Payload | Out-Null
    if (-not (Same-Path $SourcePath $Canonical)) {
        Copy-Item -Force -LiteralPath $SourcePath -Destination $Canonical
    }
    Assert-ExpectedFrontFile $Canonical "Staged Qwen3.5-2B front model"
    Write-FrontVerifiedMarker
}

if ($Force) {
    if (Test-Path -LiteralPath $Canonical) { Remove-Item -Force -LiteralPath $Canonical }
    if (Test-Path -LiteralPath $Marker) { Remove-Item -Force -LiteralPath $Marker }
} elseif ((Test-Path -LiteralPath $Canonical) -and (Test-Path -LiteralPath $Marker)) {
    $length = [int64](Get-Item -LiteralPath $Canonical).Length
    $cached = (Get-Content -LiteralPath $Marker -Raw).Trim().ToLowerInvariant()
    if ($length -eq $ExpectedBytes -and $cached -eq $ExpectedSha) {
        Write-Host "Front model already staged and hash-verified: $Canonical" -ForegroundColor Green
        exit 0
    }
}

if ((-not $Force) -and (Test-Path -LiteralPath $Canonical)) {
    if (Test-ReusableFrontFile $Canonical) {
        Write-FrontVerifiedMarker
        Write-Host "Front model already staged; verification cached: $Canonical" -ForegroundColor Green
        exit 0
    }
    Write-Warning "Staged front model failed size or SHA-256 check and will be replaced: $Canonical"
    Remove-Item -Force -LiteralPath $Canonical
    if (Test-Path -LiteralPath $Marker) { Remove-Item -Force -LiteralPath $Marker }
}

$candidates = @()
if ($env:JARVIS_FRONT_2B_GGUF) { $candidates += $env:JARVIS_FRONT_2B_GGUF }
$candidates += (Join-Path $Root "models\Qwen3.5-2B-GGUF\Qwen3.5-2B-Q4_K_M.gguf")
foreach ($candidate in $candidates) {
    if (Same-Path $candidate $Canonical) { continue }
    if (-not (Test-ReusableFrontFile $candidate)) { continue }
    Write-Host "Reusing verified local front model: $candidate" -ForegroundColor Cyan
    Install-VerifiedFrontFile $candidate
    $sizeGb = [math]::Round((Get-Item -LiteralPath $Canonical).Length / 1GB, 2)
    Write-Host "Front payload ready: $Canonical ($sizeGb GB)" -ForegroundColor Green
    exit 0
}

function Get-PythonExe {
    $venv = Join-Path $Root ".venv\Scripts\python.exe"
    if (Test-Path $venv) { return $venv }
    $python = Get-Command python -ErrorAction SilentlyContinue
    if ($python) { return $python.Source }
    $py = Get-Command py -ErrorAction SilentlyContinue
    if ($py) {
        $resolved = & $py.Source -3 -c "import sys; print(sys.executable)" 2>$null
        if ($resolved) { return $resolved.Trim() }
    }
    return $null
}

$Python = Get-PythonExe
if (-not $Python) {
    throw "Python is required to stage the Qwen3.5-2B front model before building the installer."
}

New-Item -ItemType Directory -Force -Path $Payload | Out-Null

Write-Host "Ensuring huggingface_hub is available..." -ForegroundColor Cyan
& $Python -m pip install --quiet --upgrade huggingface_hub
if ($LASTEXITCODE -ne 0) { throw "Could not install/update huggingface_hub." }

$Hf = Join-Path (Split-Path $Python -Parent) "hf.exe"
if (-not (Test-Path $Hf)) {
    $hfCmd = Get-Command hf -ErrorAction SilentlyContinue
    if ($hfCmd) { $Hf = $hfCmd.Source }
}
if (-not (Test-Path $Hf)) { throw "hf CLI is unavailable after installing huggingface_hub." }

$env:HF_XET_HIGH_PERFORMANCE = "1"
Write-Host "Staging Qwen3.5-2B Q4_K_M front model..." -ForegroundColor Cyan
& $Hf download $Repo --include $Include --local-dir $Payload
if ($LASTEXITCODE -ne 0) { throw "Qwen3.5-2B front model download failed." }

if (-not (Test-Path -LiteralPath $Canonical)) {
    $found = Get-ChildItem -Path $Payload -Recurse -File -Filter $Include |
        Where-Object { -not (Same-Path $_.FullName $Canonical) } |
        Select-Object -First 1
    if (-not $found) { throw "No $Include was found after downloading $Repo." }
    Copy-Item -Force -LiteralPath $found.FullName -Destination $Canonical
}

Assert-ExpectedFrontFile $Canonical "Downloaded Qwen3.5-2B front model"
Write-FrontVerifiedMarker

$sizeGb = [math]::Round((Get-Item -LiteralPath $Canonical).Length / 1GB, 2)
Write-Host "Front payload ready: $Canonical ($sizeGb GB)" -ForegroundColor Green
