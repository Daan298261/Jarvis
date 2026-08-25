#Requires -Version 5.1
<#
.SYNOPSIS
  First-run setup for Jarvis on Windows (idempotent).

.DESCRIPTION
  Installs or verifies Python, Node.js, llama.cpp CUDA binaries, Python packages,
  Playwright Chromium, the portal build, and default Qwen3.5-9B GGUF weights.
  Safe to re-run; skips work when files already exist.

.PARAMETER InstallExpert27B
  Also download the optional Expert 27B Q4_K_M model (large; not required).

.PARAMETER SkipModelDownload
  Skip Hugging Face GGUF downloads (useful when models are copied manually).

.PARAMETER SkipLlamaDownload
  Skip llama.cpp binary download (useful when runtime is already present).
#>
param(
    [switch]$InstallExpert27B,
    [switch]$SkipModelDownload,
    [switch]$SkipLlamaDownload
)

$ErrorActionPreference = "Stop"

# Repo root: installer lives at <root>/installer/windows/
$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$Root = (Resolve-Path (Join-Path $ScriptDir "..\..")).Path
Set-Location $Root

function Write-Step([string]$Message) {
    Write-Host ""
    Write-Host "==> $Message" -ForegroundColor Cyan
}

function Write-Ok([string]$Message) {
    Write-Host "    OK: $Message" -ForegroundColor Green
}

function Write-Skip([string]$Message) {
    Write-Host "    (already done) $Message" -ForegroundColor DarkGray
}

function Test-Command([string]$Name) {
    return [bool](Get-Command $Name -ErrorAction SilentlyContinue)
}

function Ensure-WingetPackage {
    param(
        [string]$WingetId,
        [string]$FriendlyName,
        [string[]]$VersionPrefixes = @()
    )
    if (Test-Command $FriendlyName.ToLower()) {
        Write-Ok "$FriendlyName is already installed."
        return
    }
    if (-not (Test-Command winget)) {
        throw "$FriendlyName is not installed and winget is unavailable. Install $FriendlyName manually, then re-run setup."
    }
    Write-Host "    Installing $FriendlyName with winget (this may take a few minutes)..."
    $wingetArgs = @("install", "--id", $WingetId, "-e", "--accept-package-agreements", "--accept-source-agreements")
    if ($VersionPrefixes.Count -gt 0) {
        $wingetArgs += "--version"
        $wingetArgs += $VersionPrefixes[0]
    }
    & winget @wingetArgs | Out-Host
    if (-not (Test-Command $FriendlyName.ToLower())) {
        throw "winget finished but $FriendlyName is still not on PATH. Close this window, open a new one, and run setup again."
    }
    Write-Ok "$FriendlyName installed."
}

function Get-PythonExe {
    if (Test-Command python) { return (Get-Command python).Source }
    if (Test-Command py) {
        $py = & py -3.12 -c "import sys; print(sys.executable)" 2>$null
        if ($py) { return $py.Trim() }
        $py = & py -3.11 -c "import sys; print(sys.executable)" 2>$null
        if ($py) { return $py.Trim() }
    }
    return $null
}

function Ensure-Python {
    $exe = Get-PythonExe
    if ($exe) {
        $ver = & $exe --version 2>&1
        Write-Ok "Python found ($ver)."
        return $exe
    }
    Ensure-WingetPackage -WingetId "Python.Python.3.12" -FriendlyName "Python"
    $exe = Get-PythonExe
    if (-not $exe) { throw "Python installation did not succeed." }
    return $exe
}

function Ensure-Node {
    if (Test-Command node) {
        $ver = node --version
        Write-Ok "Node.js found ($ver)."
        return
    }
    Ensure-WingetPackage -WingetId "OpenJS.NodeJS.LTS" -FriendlyName "Node"
    if (-not (Test-Command node)) { throw "Node.js installation did not succeed." }
}

function Ensure-Venv([string]$PythonExe) {
    $venvPython = Join-Path $Root ".venv\Scripts\python.exe"
    if (Test-Path $venvPython) {
        Write-Skip "Python virtual environment (.venv)"
        return $venvPython
    }
    Write-Host "    Creating Python virtual environment..."
    & $PythonExe -m venv (Join-Path $Root ".venv")
    if (-not (Test-Path $venvPython)) { throw "Failed to create .venv" }
    Write-Ok "Virtual environment created."
    return $venvPython
}

function Ensure-PipPackages([string]$VenvPython) {
    $req = Join-Path $Root "backend\requirements.txt"
    if (-not (Test-Path $req)) { throw "Missing $req" }
    Write-Host "    Installing Python packages (this may take several minutes)..."
    & $VenvPython -m pip install --upgrade pip --quiet
    & $VenvPython -m pip install -r $req
    Write-Ok "Python packages from requirements.txt installed."
}

function Ensure-Playwright([string]$VenvPython) {
    $marker = Join-Path $Root ".venv\.playwright-chromium-ready"
    if (Test-Path $marker) {
        Write-Skip "Playwright Chromium"
        return
    }
    Write-Host "    Downloading Playwright Chromium for the browser tool..."
    & $VenvPython -m playwright install chromium
    New-Item -ItemType File -Force -Path $marker | Out-Null
    Write-Ok "Playwright Chromium installed."
}

function Ensure-FrontendBuild {
    $dist = Join-Path $Root "frontend\dist\index.html"
    if (Test-Path $dist) {
        Write-Skip "Portal build (frontend/dist)"
        return
    }
    Push-Location (Join-Path $Root "frontend")
    if (-not (Test-Path "node_modules")) {
        Write-Host "    Installing frontend packages (npm install)..."
        npm install
    }
    Write-Host "    Building portal (npm run build)..."
    npm run build
    Pop-Location
    if (-not (Test-Path $dist)) { throw "frontend build failed; dist/index.html missing" }
    Write-Ok "Portal built."
}

function Get-LlamaReleaseAssets {
    # Prefer the pinned build from docs/INSTALL.md; fall back to newest CUDA 13.3 Windows zip.
    $pinnedServer = "llama-b10516-bin-win-cuda-13.3-x64.zip"
    $pinnedCudart = "cudart-llama-bin-win-cuda-13.3-x64.zip"
    $base = "https://github.com/ggml-org/llama.cpp/releases/download"
    return @{
        ServerUrl  = "$base/b10516/$pinnedServer"
        CudartUrl  = "$base/b10516/$pinnedCudart"
        ServerName = $pinnedServer
        CudartName = $pinnedCudart
    }
}

function Expand-ZipToFolder {
    param(
        [string]$ZipPath,
        [string]$DestFolder
    )
    Add-Type -AssemblyName System.IO.Compression.FileSystem
    [System.IO.Compression.ZipFile]::ExtractToDirectory($ZipPath, $DestFolder)
}

function Ensure-LlamaCpp {
    $llamaExe = Join-Path $Root "runtime\llama.cpp\llama-server.exe"
    if (Test-Path $llamaExe) {
        Write-Skip "llama-server.exe"
        return
    }
    if ($SkipLlamaDownload) {
        throw "llama-server.exe is missing and -SkipLlamaDownload was set."
    }

    $runtimeDir = Join-Path $Root "runtime\llama.cpp"
    $tempDir = Join-Path $env:TEMP "jarvis-llama-setup"
    New-Item -ItemType Directory -Force -Path $runtimeDir, $tempDir | Out-Null

    $assets = Get-LlamaReleaseAssets
    $serverZip = Join-Path $tempDir $assets.ServerName
    $cudartZip = Join-Path $tempDir $assets.CudartName

    Write-Host "    Downloading llama.cpp CUDA 13.3 binaries..."
    Invoke-WebRequest -Uri $assets.ServerUrl -OutFile $serverZip -UseBasicParsing
    Invoke-WebRequest -Uri $assets.CudartUrl -OutFile $cudartZip -UseBasicParsing

    Write-Host "    Extracting into runtime\llama.cpp..."
    Expand-ZipToFolder -ZipPath $serverZip -DestFolder $runtimeDir
    Expand-ZipToFolder -ZipPath $cudartZip -DestFolder $runtimeDir

    if (-not (Test-Path $llamaExe)) {
        throw "llama-server.exe still missing after extract. Re-run setup or install manually (see docs/INSTALL.md)."
    }
    Write-Ok "llama-server.exe ready."
}

function Invoke-HfDownload {
    param(
        [string]$VenvPython,
        [string]$RepoId,
        [string[]]$Includes,
        [string]$LocalDir
    )
    New-Item -ItemType Directory -Force -Path $LocalDir | Out-Null
    $includeArgs = @()
    foreach ($inc in $Includes) {
        $includeArgs += "--include"
        $includeArgs += $inc
    }
    $env:HF_XET_HIGH_PERFORMANCE = "1"
    & $VenvPython -m huggingface_hub.cli.hf download $RepoId @includeArgs --local-dir $LocalDir
}

function Ensure-DefaultModels([string]$VenvPython) {
    if ($SkipModelDownload) {
        Write-Host "    Skipping model download (-SkipModelDownload)."
        return
    }

    $modelDir = Join-Path $Root "models\Qwen3.5-9B-abliterated-GGUF"
    $q8 = Join-Path $modelDir "Qwen3.5-9B-abliterated-Q8_0.gguf"
    $q6 = Join-Path $modelDir "Qwen3.5-9B-abliterated-Q6_K.gguf"

    $need9b = (-not (Test-Path $q8)) -or (-not (Test-Path $q6))
    if ($need9b) {
        Write-Host "    Downloading Qwen3.5-9B Abliterated weights (several GB; one-time)..."
        $includes = @()
        if (-not (Test-Path $q8)) { $includes += "Qwen3.5-9B-abliterated-Q8_0.gguf" }
        if (-not (Test-Path $q6)) { $includes += "Qwen3.5-9B-abliterated-Q6_K.gguf" }
        Invoke-HfDownload -VenvPython $VenvPython `
            -RepoId "Abiray/Qwen3.5-9B-abliterated-GGUF" `
            -Includes $includes `
            -LocalDir $modelDir
        Write-Ok "9B model weights downloaded."
    } else {
        Write-Skip "Qwen3.5-9B GGUF weights"
    }

    if ($InstallExpert27B) {
        $dir27 = Join-Path $Root "models\Qwen3.5-27B-GGUF"
        $q4 = Join-Path $dir27 "Qwen3.5-27B-Q4_K_M.gguf"
        if (-not (Test-Path $q4)) {
            Write-Host "    Downloading optional Expert 27B weights (large; one-time)..."
            Invoke-HfDownload -VenvPython $VenvPython `
                -RepoId "unsloth/Qwen3.5-27B-GGUF" `
                -Includes @("Qwen3.5-27B-Q4_K_M.gguf") `
                -LocalDir $dir27
            Write-Ok "Expert 27B weights downloaded."
        } else {
            Write-Skip "Expert 27B Q4_K_M"
        }
    }
}

function Test-NvidiaDriver {
    if (-not (Test-Command nvidia-smi)) {
        Write-Host "    WARNING: nvidia-smi not found. Install an NVIDIA CUDA 13-capable driver for GPU inference." -ForegroundColor Yellow
        return
    }
    $smi = & nvidia-smi --query-gpu=name,driver_version --format=csv,noheader 2>$null
    if ($smi) { Write-Ok "NVIDIA GPU: $($smi.Trim())" }
}

# --- main ---
Write-Host ""
Write-Host "Jarvis setup" -ForegroundColor White
Write-Host "This window prepares Jarvis on your PC. You can close it when you see 'Setup complete'." -ForegroundColor DarkGray
Write-Host "Install folder: $Root" -ForegroundColor DarkGray

Write-Step "Checking NVIDIA driver (recommended)"
Test-NvidiaDriver

Write-Step "Checking Python"
$pythonExe = Ensure-Python

Write-Step "Checking Node.js"
Ensure-Node

Write-Step "Python environment and packages"
$venvPython = Ensure-Venv -PythonExe $pythonExe
Ensure-PipPackages -VenvPython $venvPython
Ensure-Playwright -VenvPython $venvPython

Write-Step "Web portal"
Ensure-FrontendBuild

Write-Step "llama.cpp inference server"
Ensure-LlamaCpp

Write-Step "AI model weights"
Ensure-DefaultModels -VenvPython $venvPython

Write-Step "Finishing"
New-Item -ItemType Directory -Force -Path `
    (Join-Path $Root "data"), `
    (Join-Path $Root "logs"), `
    (Join-Path $Root "data\queue\pending"), `
    (Join-Path $Root "data\queue\processed"), `
    (Join-Path $Root "data\queue\failed") | Out-Null

Write-Host ""
Write-Host "Setup complete." -ForegroundColor Green
Write-Host "Start Jarvis from the Desktop shortcut or run:" -ForegroundColor Green
Write-Host "  $Root\start-jarvis.ps1" -ForegroundColor White
Write-Host "Stop Jarvis with stop-jarvis.ps1 or the Stop Jarvis shortcut." -ForegroundColor DarkGray
Write-Host ""
