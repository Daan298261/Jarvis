#Requires -Version 5.1
# Idempotent Daybreak Blue bootstrap. Excludes mitmproxy, pwntools, angr, and Selenium browser automation.
[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [string]$InstallPath,

    [Parameter(Mandatory = $true)]
    [string]$Commit,

    [int]$Port = 8888
)

$ErrorActionPreference = 'Stop'
$ApprovedRemote = 'https://github.com/0x4m4/hexstrike-ai.git'
$ApprovedCommit = 'd689933ff579d839c676c82b231f8e98326c5f04'

if ($Commit -ne $ApprovedCommit) {
    throw "Refusing unreviewed HexStrike commit: $Commit"
}
if ($Port -lt 1 -or $Port -gt 65535) {
    throw "Invalid loopback port: $Port"
}

$ResolvedInstall = [System.IO.Path]::GetFullPath($InstallPath)
$RepoRoot = [System.IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..'))
$Requirements = Join-Path $RepoRoot 'config\hexstrike-defensive-requirements.txt'
$Compat = Join-Path $RepoRoot 'backend\app\security\hexstrike_compat.py'
$CreatedStaging = $false
$WorkingPath = $ResolvedInstall

Write-Output 'STAGE:validate'
if (Test-Path -LiteralPath $ResolvedInstall) {
    if (-not (Test-Path -LiteralPath (Join-Path $ResolvedInstall '.git'))) {
        throw "Install path exists but is not a managed Git clone: $ResolvedInstall"
    }
    $Origin = (& git -C $ResolvedInstall remote get-url origin).Trim()
    if ($LASTEXITCODE -ne 0 -or $Origin -notin @($ApprovedRemote, 'git@github.com:0x4m4/hexstrike-ai.git')) {
        throw "Refusing unknown HexStrike origin: $Origin"
    }
    $ExcludePath = Join-Path $ResolvedInstall '.git\info\exclude'
    $ExcludePatterns = @('hexstrike-env/', 'hexstrike.log', 'jarvis-bootstrap-health.log*', 'jarvis-state/', '__pycache__/')
    $ExistingExcludes = if (Test-Path -LiteralPath $ExcludePath) { Get-Content -LiteralPath $ExcludePath } else { @() }
    foreach ($Pattern in $ExcludePatterns) {
        if ($Pattern -notin $ExistingExcludes) { Add-Content -LiteralPath $ExcludePath -Value $Pattern }
    }
    $Dirty = & git -C $ResolvedInstall status --porcelain
    if ($LASTEXITCODE -ne 0 -or $Dirty) {
        throw 'Refusing to repair a dirty HexStrike clone. Preserve or discard those changes manually.'
    }
} else {
    $WorkingPath = "$ResolvedInstall.staging-$([guid]::NewGuid().ToString('N'))"
    $CreatedStaging = $true
    Write-Output 'STAGE:clone'
    & git clone --filter=blob:none --no-checkout $ApprovedRemote $WorkingPath
    if ($LASTEXITCODE -ne 0) { throw 'HexStrike clone failed.' }
}

Write-Output 'STAGE:checkout'
& git -C $WorkingPath fetch --depth 1 origin $ApprovedCommit
if ($LASTEXITCODE -ne 0) { throw 'HexStrike fetch failed.' }
& git -C $WorkingPath checkout --detach $ApprovedCommit
if ($LASTEXITCODE -ne 0) { throw 'HexStrike checkout failed.' }
$ActualCommit = (& git -C $WorkingPath rev-parse HEAD).Trim()
if ($ActualCommit -ne $ApprovedCommit) { throw "HexStrike commit verification failed: $ActualCommit" }

Write-Output 'STAGE:venv'
$VenvPath = Join-Path $WorkingPath 'hexstrike-env'
if (-not (Test-Path -LiteralPath (Join-Path $VenvPath 'Scripts\python.exe'))) {
    & python -m venv $VenvPath
    if ($LASTEXITCODE -ne 0) { throw 'HexStrike virtual environment creation failed.' }
}
$Python = Join-Path $VenvPath 'Scripts\python.exe'

Write-Output 'STAGE:dependencies'
& $Python -m pip install --disable-pip-version-check -r $Requirements
if ($LASTEXITCODE -ne 0) { throw 'HexStrike dependency installation failed.' }
& $Python -m pip uninstall -y mitmproxy pwntools angr selenium | Out-Null
if ($LASTEXITCODE -ne 0) { throw 'HexStrike excluded-dependency cleanup failed.' }
& $Python -m pip check
if ($LASTEXITCODE -ne 0) { throw 'HexStrike dependency verification failed.' }

Write-Output 'STAGE:health'
$Server = Join-Path $WorkingPath 'hexstrike_server.py'
$ExistingListener = Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue
if ($ExistingListener) { throw "Loopback health port is already in use: $Port" }
$LogDir = Join-Path $RepoRoot 'logs'
[System.IO.Directory]::CreateDirectory($LogDir) | Out-Null
$ServerLog = Join-Path $LogDir 'hexstrike-bootstrap-health.log'
$PreviousHost = $env:HEXSTRIKE_HOST
$PreviousPort = $env:HEXSTRIKE_PORT
$PreviousState = $env:JARVIS_HEXSTRIKE_STATE_DIR
$PreviousUtf8 = $env:PYTHONUTF8
$PreviousEncoding = $env:PYTHONIOENCODING
$env:HEXSTRIKE_HOST = '127.0.0.1'
$env:HEXSTRIKE_PORT = [string]$Port
$env:JARVIS_HEXSTRIKE_STATE_DIR = Join-Path $WorkingPath 'jarvis-state'
$env:PYTHONUTF8 = '1'
$env:PYTHONIOENCODING = 'utf-8'
$Process = $null
try {
    $Process = Start-Process -FilePath $Python -ArgumentList @($Compat, '--server', $Server, '--port', [string]$Port) -WorkingDirectory $WorkingPath -RedirectStandardOutput $ServerLog -RedirectStandardError "$ServerLog.error" -WindowStyle Hidden -PassThru
    $Ready = $false
    for ($Attempt = 0; $Attempt -lt 180; $Attempt++) {
        if ($Process.HasExited) { break }
        try {
            $Health = Invoke-RestMethod -Uri "http://127.0.0.1:$Port/health" -TimeoutSec 15
            if ($null -ne $Health) { $Ready = $true; break }
        } catch {
            Start-Sleep -Milliseconds 750
        }
    }
    if (-not $Ready) { throw 'HexStrike did not pass its loopback health check.' }
} finally {
    $ManagedProcesses = Get-CimInstance Win32_Process | Where-Object {
        $_.CommandLine -and
        $_.CommandLine.Contains($Compat) -and
        $_.CommandLine.Contains($Server)
    }
    $ManagedProcessIds = @($ManagedProcesses | ForEach-Object ProcessId)
    foreach ($ManagedProcess in $ManagedProcesses | Where-Object { $_.ParentProcessId -notin $ManagedProcessIds }) {
        & "$env:SystemRoot\System32\taskkill.exe" /PID $ManagedProcess.ProcessId /T /F | Out-Null
    }
    $env:HEXSTRIKE_HOST = $PreviousHost
    $env:HEXSTRIKE_PORT = $PreviousPort
    $env:JARVIS_HEXSTRIKE_STATE_DIR = $PreviousState
    $env:PYTHONUTF8 = $PreviousUtf8
    $env:PYTHONIOENCODING = $PreviousEncoding
}

if ($CreatedStaging) {
    Write-Output 'STAGE:activate'
    Move-Item -LiteralPath $WorkingPath -Destination $ResolvedInstall
}

Write-Output "RESULT:$ResolvedInstall"
Write-Output 'STAGE:ready'
