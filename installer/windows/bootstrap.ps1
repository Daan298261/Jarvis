#Requires -Version 5.1
<#
.SYNOPSIS
  First-run setup for Jarvis on Windows (idempotent).

.DESCRIPTION
  Installs or verifies Python, Node.js, llama.cpp CUDA binaries, Python packages,
  Playwright Chromium, the portal build, bootstrap GGUF, and household voice.
  Safe to re-run: present files are skipped; anything missing is downloaded and installed.
  -SkipHeavyPrepare no longer bails out of setup.

.PARAMETER InstallLocalLLM
  Also download Qwen3.5-9B GGUF weights. llama.cpp is installed whenever llama-server.exe is missing.

.PARAMETER InstallExpert27B
  Also download the optional Expert 27B Q4_K_M model (large; not required).
  Implies -InstallLocalLLM.

.PARAMETER SkipModelDownload
  Skip extra Qwen GGUF downloads when those files already exist. Missing bootstrap
  or Kokoro weights are still downloaded.

.PARAMETER SkipLlamaDownload
  Ignored when llama-server.exe is missing; the runtime is downloaded and installed.

.PARAMETER SkipHeavyPrepare
  Upgrade/repair hint only. Missing runtimes, packages, llama.cpp, and models are still installed.
#>
param(
    [switch]$InstallLocalLLM,
    [switch]$InstallExpert27B,
    [switch]$SkipModelDownload,
    [switch]$SkipLlamaDownload,
    [switch]$SkipHeavyPrepare,
    [int]$StepTimeoutMinutes = 45
)

$ErrorActionPreference = "Stop"

# Repo root: installer lives at <root>/installer/windows/
$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$Root = (Resolve-Path (Join-Path $ScriptDir "..\..")).Path
Set-Location $Root

$BootstrapLogPath = Join-Path $Root "logs\bootstrap.log"
$logDir = Split-Path -Parent $BootstrapLogPath
if (-not (Test-Path $logDir)) {
    New-Item -ItemType Directory -Force -Path $logDir | Out-Null
}

function Write-BootstrapLog([string]$Message) {
    $line = "{0:yyyy-MM-dd HH:mm:ss} {1}" -f (Get-Date), $Message
    Add-Content -LiteralPath $BootstrapLogPath -Value $line -Encoding UTF8
}

function Write-Step([string]$Message) {
    Write-BootstrapLog "==> $Message"
    Write-Host ""
    Write-Host "==> $Message" -ForegroundColor Cyan
}

function ConvertTo-ProcessArgumentString([string[]]$Arguments) {
    $parts = @()
    foreach ($arg in $Arguments) {
        if ($null -eq $arg) { continue }
        $text = [string]$arg
        if ($text -match '[ \t"]') {
            $parts += '"' + ($text -replace '"', '\"') + '"'
        } else {
            $parts += $text
        }
    }
    return ($parts -join " ")
}

function Invoke-ProcessWithTimeout {
    param(
        [string]$Label,
        [string]$FilePath,
        [string[]]$Arguments = @(),
        [string]$WorkingDirectory = $Root,
        [int]$TimeoutMinutes = $StepTimeoutMinutes
    )
    Write-BootstrapLog "start step=$Label timeout=${TimeoutMinutes}m"
    $argString = ConvertTo-ProcessArgumentString $Arguments
    $psi = New-Object System.Diagnostics.ProcessStartInfo
    $psi.FileName = $FilePath
    $psi.Arguments = $argString
    $psi.WorkingDirectory = $WorkingDirectory
    $psi.UseShellExecute = $false
    $proc = New-Object System.Diagnostics.Process
    $proc.StartInfo = $psi
    if (-not $proc.Start()) {
        throw "${Label} failed to start ($FilePath)."
    }
    $timeoutMs = [Math]::Max(1000, $TimeoutMinutes * 60 * 1000)
    if (-not $proc.WaitForExit($timeoutMs)) {
        try { $proc.Kill() } catch { }
        Write-BootstrapLog "timeout step=$Label after ${TimeoutMinutes}m"
        throw "${Label} timed out after $TimeoutMinutes minutes (see logs\bootstrap.log)."
    }
    $code = $proc.ExitCode
    if ($code -ne 0) {
        Write-BootstrapLog "failed step=$Label exit=$code"
        throw "${Label} failed with exit code $code (see logs\bootstrap.log)."
    }
    Write-BootstrapLog "done step=$Label"
}

function Test-HeavyPrepareSkippable {
    # Kept for RFC-0093 contract tests. Install never uses this as a full bail-out:
    # each Ensure-* step downloads and installs whatever is still missing.
    $venv = Join-Path $Root ".venv\Scripts\python.exe"
    $dist = Join-Path $Root "frontend\dist\index.html"
    $llama = Join-Path $Root "runtime\llama.cpp\llama-server.exe"
    $voiceMarker = Join-Path $Root "models\tts\kokoro-82m\.jarvis_staged_ok"
    $modelsDir = Join-Path $Root "models"
    $hasModels = (Test-Path $voiceMarker) -or (
        (Test-Path $modelsDir) -and ((Get-ChildItem -Path $modelsDir -Recurse -File -ErrorAction SilentlyContinue | Select-Object -First 1))
    )
    return (Test-Path $venv) -and (Test-Path $dist) -and (Test-Path $llama) -and $hasModels
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

function Test-PythonImport {
    param(
        [string]$VenvPython,
        [string]$Code
    )
    $prev = $ErrorActionPreference
    $ErrorActionPreference = "Continue"
    try {
        & $VenvPython -c $Code 2>$null | Out-Null
        return ($LASTEXITCODE -eq 0)
    } finally {
        $ErrorActionPreference = $prev
    }
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
    Invoke-ProcessWithTimeout -Label "winget $FriendlyName" -FilePath "winget" -Arguments $wingetArgs -TimeoutMinutes $StepTimeoutMinutes
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
        $major = [int]($ver.TrimStart("v").Split(".")[0])
        if ($major -ge 24) {
            Write-Ok "Node.js found ($ver)."
            return
        }
        Write-Host "    Node.js $ver is too old for the Gmail and WhatsApp connectors. Updating..."
        if (-not (Test-Command winget)) {
            throw "Node.js 24 or newer is required. Install the current Node.js LTS release, then re-run setup."
        }
        Invoke-ProcessWithTimeout -Label "winget Node.js upgrade" -FilePath "winget" -Arguments @(
            "upgrade", "--id", "OpenJS.NodeJS.LTS", "-e", "--accept-package-agreements", "--accept-source-agreements"
        ) -TimeoutMinutes $StepTimeoutMinutes
        $ver = node --version
        $major = [int]($ver.TrimStart("v").Split(".")[0])
        if ($major -lt 24) {
            throw "Node.js 24 or newer is required. Restart Windows, then re-run setup."
        }
        Write-Ok "Node.js updated ($ver)."
        return
    }
    Ensure-WingetPackage -WingetId "OpenJS.NodeJS.LTS" -FriendlyName "Node"
    if (-not (Test-Command node)) { throw "Node.js installation did not succeed." }
}

function Ensure-McpConnectors {
    $packageFile = Join-Path $Root "mcp\package.json"
    $lockFile = Join-Path $Root "mcp\package-lock.json"
    if (-not (Test-Path $packageFile) -or -not (Test-Path $lockFile)) {
        throw "Jarvis connector package files are missing. Re-download the installer."
    }
    $mcpDir = Join-Path $Root "mcp"
    $modules = Join-Path $mcpDir "node_modules"
    if (Test-Path $modules) {
        Write-Skip "Gmail and WhatsApp connectors (mcp\\node_modules)"
        return
    }
    Write-Host "    Installing Gmail and WhatsApp connectors..."
    $env:PUPPETEER_SKIP_DOWNLOAD = "true"
    try {
        Invoke-ProcessWithTimeout -Label "mcp npm ci" -FilePath "npm" -Arguments @("ci", "--prefix", $mcpDir) -TimeoutMinutes $StepTimeoutMinutes
    } catch {
        Write-Host "    npm ci failed; downloading with npm install instead..."
        Invoke-ProcessWithTimeout -Label "mcp npm install" -FilePath "npm" -Arguments @("install", "--prefix", $mcpDir) -TimeoutMinutes $StepTimeoutMinutes
    } finally {
        Remove-Item Env:PUPPETEER_SKIP_DOWNLOAD -ErrorAction SilentlyContinue
    }
    if (-not (Test-Path $modules)) {
        throw "Gmail and WhatsApp connectors are still missing after npm install."
    }
    Write-Ok "Gmail and WhatsApp connectors installed."
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
    if (Test-PythonImport -VenvPython $VenvPython -Code "import uvicorn, fastapi") {
        Write-Skip "Python packages (uvicorn/fastapi present)"
        return
    }
    Write-Host "    Installing Python packages (this may take several minutes)..."
    Invoke-ProcessWithTimeout -Label "pip upgrade" -FilePath $VenvPython -Arguments @("-m", "pip", "install", "--upgrade", "pip", "--quiet") -TimeoutMinutes $StepTimeoutMinutes
    Invoke-ProcessWithTimeout -Label "pip requirements" -FilePath $VenvPython -Arguments @("-m", "pip", "install", "-r", $req) -TimeoutMinutes $StepTimeoutMinutes
    if (-not (Test-PythonImport -VenvPython $VenvPython -Code "import uvicorn, fastapi")) {
        throw "Python packages are still missing after pip install."
    }
    Write-Ok "Python packages from requirements.txt installed."
}

function Ensure-TtsPythonPackages([string]$VenvPython) {
    # RFC-0070: default butler speech needs Kokoro + soundfile in the post-install venv.
    $marker = Join-Path $Root ".venv\.jarvis-tts-python-ready"
    $check = @"
import importlib.metadata
required = {'kokoro': '0.9.4', 'soundfile': '0.14.0'}
wrong = []
for name, expected in required.items():
    try:
        actual = importlib.metadata.version(name)
    except importlib.metadata.PackageNotFoundError:
        actual = 'missing'
    if actual != expected:
        wrong.append(f'{name}={actual} (expected {expected})')
if wrong:
    raise SystemExit('; '.join(wrong))
"@
    if (Test-PythonImport -VenvPython $VenvPython -Code $check) {
        if (-not (Test-Path $marker)) {
            New-Item -ItemType File -Force -Path $marker | Out-Null
        }
        Write-Skip "Kokoro TTS Python packages (kokoro, soundfile)"
        return
    }
    Write-Host "    Ensuring Kokoro TTS packages (kokoro, soundfile)..."
    Invoke-ProcessWithTimeout -Label "pip kokoro tts" -FilePath $VenvPython -Arguments @(
        "-m", "pip", "install", "kokoro==0.9.4", "soundfile==0.14.0"
    ) -TimeoutMinutes $StepTimeoutMinutes
    & $VenvPython -c $check
    if ($LASTEXITCODE -ne 0) { throw "Kokoro TTS packages are still missing after pip install." }
    New-Item -ItemType File -Force -Path $marker | Out-Null
    Write-Ok "Kokoro TTS Python packages ready."
}

function Ensure-Playwright([string]$VenvPython) {
    $marker = Join-Path $Root ".venv\.playwright-chromium-ready"
    if (Test-Path $marker) {
        Write-Skip "Playwright Chromium"
        return
    }
    Write-Host "    Downloading Playwright Chromium for the browser tool..."
    Invoke-ProcessWithTimeout -Label "playwright chromium" -FilePath $VenvPython -Arguments @("-m", "playwright", "install", "chromium") -TimeoutMinutes $StepTimeoutMinutes
    New-Item -ItemType File -Force -Path $marker | Out-Null
    Write-Ok "Playwright Chromium installed."
}

function Ensure-FrontendBuild {
    $dist = Join-Path $Root "frontend\dist\index.html"
    if (Test-Path $dist) {
        Write-Skip "Portal build (frontend\\dist)"
        return
    }
    $frontend = Join-Path $Root "frontend"
    Write-Host "    Installing frontend packages..."
    try {
        Invoke-ProcessWithTimeout -Label "frontend npm ci" -FilePath "npm" -Arguments @("ci") -WorkingDirectory $frontend -TimeoutMinutes $StepTimeoutMinutes
    } catch {
        Write-Host "    npm ci failed; downloading with npm install instead..."
        Invoke-ProcessWithTimeout -Label "frontend npm install" -FilePath "npm" -Arguments @("install") -WorkingDirectory $frontend -TimeoutMinutes $StepTimeoutMinutes
    }
    Write-Host "    Building portal (npm run build)..."
    Invoke-ProcessWithTimeout -Label "frontend npm run build" -FilePath "npm" -Arguments @("run", "build") -WorkingDirectory $frontend -TimeoutMinutes $StepTimeoutMinutes
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
    Write-Host "    llama-server.exe is missing; downloading and installing llama.cpp..."

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
    $hfArgs = @("-m", "huggingface_hub.cli.hf", "download", $RepoId) + $includeArgs + @("--local-dir", $LocalDir)
    Invoke-ProcessWithTimeout -Label "huggingface download $RepoId" -FilePath $VenvPython -Arguments $hfArgs -TimeoutMinutes ($StepTimeoutMinutes * 2)
}

function Ensure-BootstrapGguf([string]$VenvPython) {
    $dir = Join-Path $Root "models\bootstrap"
    $gguf = Join-Path $dir "Ornith-1.5-9B-Q4_K_M.gguf"
    if ((Test-Path $gguf) -and ((Get-Item $gguf).Length -gt 0)) {
        Write-Skip "Ornith bootstrap GGUF"
        return
    }
    Write-Host "    Bootstrap GGUF is missing; downloading Ornith 1.5 9B Q4_K_M..."
    Invoke-HfDownload -VenvPython $VenvPython `
        -RepoId "ornith-ai/Ornith-1.5-9B-GGUF" `
        -Includes @("*Q4_K_M*.gguf") `
        -LocalDir $dir
    if (-not (Test-Path $gguf)) {
        $found = Get-ChildItem -Path $dir -Recurse -File -ErrorAction SilentlyContinue |
            Where-Object { $_.Name -like "*Q4_K_M*.gguf" } |
            Select-Object -First 1
        if ($found -and $found.FullName -ne $gguf) {
            New-Item -ItemType Directory -Force -Path $dir | Out-Null
            Copy-Item -Force $found.FullName $gguf
        }
    }
    if (-not (Test-Path $gguf) -or ((Get-Item $gguf).Length -le 0)) {
        throw "Ornith bootstrap GGUF is still missing after download."
    }
    Write-Ok "Ornith bootstrap GGUF ready."
}

function Ensure-DefaultModels([string]$VenvPython) {
    Ensure-BootstrapGguf -VenvPython $VenvPython
    if (-not $InstallLocalLLM) {
        Write-Host "    Skipping extra Qwen GGUF download (bootstrap model is enough). Re-run with -InstallLocalLLM to fetch 9B."
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

function Ensure-KokoroVoice([string]$VenvPython) {
    $dir = Join-Path $Root "models\tts\kokoro-82m"
    $marker = Join-Path $dir ".jarvis_staged_ok"
    $existing = Get-ChildItem -Path $dir -File -Recurse -ErrorAction SilentlyContinue | Select-Object -First 1
    if ((Test-Path $marker) -and $existing) {
        Write-Skip "Household voice (Kokoro-82M)"
        return
    }
    Write-Host "    Downloading the household voice (one-time)..."
    New-Item -ItemType Directory -Force -Path $dir | Out-Null
    Invoke-HfDownload -VenvPython $VenvPython `
        -RepoId "hexgrad/Kokoro-82M" `
        -Includes @() `
        -LocalDir $dir
    "ok" | Set-Content -Encoding ascii -Path $marker
    Write-Ok "Household voice ready."
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
if ($InstallExpert27B) { $InstallLocalLLM = $true }
Write-BootstrapLog "bootstrap start SkipHeavyPrepare=$SkipHeavyPrepare SkipModelDownload=$SkipModelDownload InstallLocalLLM=$InstallLocalLLM"
Write-Host ""
Write-Host "Jarvis setup" -ForegroundColor White
Write-Host "This window prepares Jarvis on your PC. You can close it when you see 'Setup complete'." -ForegroundColor DarkGray
Write-Host "Install folder: $Root" -ForegroundColor DarkGray
Write-Host "Log: $BootstrapLogPath" -ForegroundColor DarkGray

if ($SkipHeavyPrepare) {
    Write-BootstrapLog "SkipHeavyPrepare: still install any missing runtime, packages, llama.cpp, and models"
    Write-Host "Upgrade/repair: installing anything that is missing (already-present files are skipped)." -ForegroundColor DarkGray
}

Write-Step "Checking NVIDIA driver (recommended)"
Test-NvidiaDriver

Write-Step "Checking Python"
$pythonExe = Ensure-Python

Write-Step "Checking Node.js"
Ensure-Node

Write-Step "Gmail and WhatsApp connectors"
Ensure-McpConnectors

Write-Step "Python environment and packages"
$venvPython = Ensure-Venv -PythonExe $pythonExe
Ensure-PipPackages -VenvPython $venvPython
Ensure-TtsPythonPackages -VenvPython $venvPython
Ensure-Playwright -VenvPython $venvPython

Write-Step "Web portal"
Ensure-FrontendBuild

Write-Step "llama.cpp inference server"
Ensure-LlamaCpp

Write-Step "AI model weights"
Ensure-DefaultModels -VenvPython $venvPython
Ensure-KokoroVoice -VenvPython $venvPython

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
