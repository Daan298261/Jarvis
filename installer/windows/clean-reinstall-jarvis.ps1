#Requires -Version 5.1
<#
.SYNOPSIS
  RFC-0124: Owner Clean Install / Reinstall — force-stop, owned-path wipe, relaunch Setup.

.DESCRIPTION
  Detached helper used by Settings → Advanced and JarvisSetup Clean (mode 3).
  Never reports success when lockers remain or owned files could not be deleted.
#>
param(
    [string]$InstallRoot = "",
    [string]$SetupExePath = "",
    [ValidateSet("Portal", "Inno")]
    [string]$Mode = "Portal",
    [switch]$SkipConfirm,
    [int]$MaxWaitSeconds = 90
)

$ErrorActionPreference = "Stop"

$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
. (Join-Path $scriptDir "owned-paths.ps1")

$tempLog = Join-Path ([System.IO.Path]::GetTempPath()) "Jarvis-clean-reinstall.log"
$statusPath = Join-Path ([System.IO.Path]::GetTempPath()) "Jarvis-clean-reinstall.status.json"
$exitReason = "unknown"
$setupLaunchPath = ""

function Write-CleanStatus {
    param(
        [string]$Status,
        [string]$ExitReason = ""
    )
    $payload = @{
        status      = $Status
        exit_reason = $ExitReason
        log_path    = $tempLog
        updated_at  = (Get-Date).ToUniversalTime().ToString("o")
    }
    try {
        $payload | ConvertTo-Json -Compress | Set-Content -LiteralPath $statusPath -Encoding UTF8
    } catch {
        Write-Host "status write failed: $($_.Exception.Message)"
    }
}

function Exit-CleanReinstall {
    param(
        [int]$Code,
        [string]$Reason
    )
    if ($Reason -eq "ok") {
        Write-CleanStatus -Status "succeeded" -ExitReason $Reason
    } else {
        Write-CleanStatus -Status "failed" -ExitReason $Reason
    }
    exit $Code
}

function Write-CleanLog {
    param([string]$Message)
    $line = "{0:yyyy-MM-dd HH:mm:ss} {1}" -f (Get-Date), $Message
    Add-Content -LiteralPath $tempLog -Value $line -Encoding UTF8
    Write-Host $line
    $install = Resolve-InstallRootCandidate -InstallRoot $InstallRoot
    if (Test-IsSafeJarvisInstallDir -Path $install) {
        $appLog = Join-Path $install "logs\clean-reinstall.log"
        $logDir = Split-Path -Parent $appLog
        if (-not (Test-Path -LiteralPath $logDir)) {
            New-Item -ItemType Directory -Force -Path $logDir | Out-Null
        }
        Add-Content -LiteralPath $appLog -Value $line -Encoding UTF8
    }
}

function Resolve-ForceStopScript {
    param([string]$AppDir)
    # Prefer the copy beside this helper (Inno extracts both to {tmp}) so a hotfix
    # Setup does not run the already-installed buggy force-stop from {app}.
    $repoCandidate = Join-Path $scriptDir "force-stop-jarvis.ps1"
    if (Test-Path -LiteralPath $repoCandidate) { return $repoCandidate }
    $candidate = Join-Path $AppDir "installer\windows\force-stop-jarvis.ps1"
    if (Test-Path -LiteralPath $candidate) { return $candidate }
    return ""
}

function Invoke-ForceStopAllRoots {
    param(
        [string[]]$Roots,
        [switch]$CheckOnly
    )
    foreach ($root in $Roots) {
        $forceScript = Resolve-ForceStopScript -AppDir $root
        if (-not $forceScript) {
            Write-CleanLog "abort: force-stop-jarvis.ps1 missing under $root"
            return $false
        }
        $logPath = Join-Path ([System.IO.Path]::GetTempPath()) "Jarvis-installer-stop.log"
        $rootLogDir = Join-Path $root "logs"
        if (Test-Path -LiteralPath $root) {
            if (-not (Test-Path -LiteralPath $rootLogDir)) {
                New-Item -ItemType Directory -Force -Path $rootLogDir | Out-Null
            }
            $logPath = Join-Path $rootLogDir "installer-stop.log"
        }
        $argList = @(
            "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", $forceScript,
            "-InstallRoot", $root, "-IncludeTray",
            "-MaxWaitSeconds", $(if ($CheckOnly) { "8" } else { "$MaxWaitSeconds" }),
            "-LogPath", $logPath
        )
        if ($CheckOnly) { $argList += "-CheckOnly" }
        $workDir = $scriptDir
        if (Test-Path -LiteralPath $root) { $workDir = $root }
        $proc = Start-Process -FilePath "powershell.exe" -ArgumentList $argList -WorkingDirectory $workDir -PassThru -WindowStyle Hidden -Wait
        if ($proc.ExitCode -ne 0) {
            if ($CheckOnly) {
                Write-CleanLog "locker recheck failed root=$root exit=$($proc.ExitCode)"
            } else {
                Write-CleanLog "force-stop failed for root=$root exit=$($proc.ExitCode)"
            }
            return $false
        }
        if (-not $CheckOnly) {
            Write-CleanLog "force-stop ok root=$root"
        }
    }
    return $true
}

function Test-AnyLockersRemain {
    param([string[]]$Roots)
    return -not (Invoke-ForceStopAllRoots -Roots $Roots -CheckOnly)
}

function Clear-ReadOnlyTree {
    param([string]$Path)
    if (-not (Test-Path -LiteralPath $Path)) { return }
    try {
        cmd.exe /c "attrib -R -S -H `"$Path`" /S /D" | Out-Null
    } catch { }
}

function Remove-PathWithRetry {
    param(
        [Parameter(Mandatory = $true)][string]$Path,
        [int]$Attempts = 6
    )
    for ($i = 1; $i -le $Attempts; $i++) {
        if (-not (Test-Path -LiteralPath $Path)) { return $true }
        try {
            Clear-ReadOnlyTree -Path $Path
            Remove-Item -LiteralPath $Path -Recurse -Force -ErrorAction Stop
            if (-not (Test-Path -LiteralPath $Path)) { return $true }
        } catch {
            Write-CleanLog "wipe retry $i/$Attempts path=$Path error=$($_.Exception.Message)"
            Start-Sleep -Milliseconds (250 * $i)
        }
    }
    return -not (Test-Path -LiteralPath $Path)
}

function Get-OwnedLeftovers {
    param(
        [string]$Root,
        [string]$PreservePath
    )
    if (-not (Test-Path -LiteralPath $Root)) { return @() }
    return @(Get-ChildItem -LiteralPath $Root -Force -ErrorAction SilentlyContinue | Where-Object {
        -not ($PreservePath -and $_.FullName.Equals($PreservePath, [StringComparison]::OrdinalIgnoreCase))
    })
}

function Remove-OwnedRootTree {
    param(
        [Parameter(Mandatory = $true)][string]$Root,
        [string]$InstallRootForPreserve
    )
    if (-not (Test-Path -LiteralPath $Root)) {
        Write-CleanLog "wipe skip missing root=$Root"
        return $true
    }
    $preserve = Get-LicenseIssuerPreservePath -InstallRoot $InstallRootForPreserve
    $preserveExists = Test-Path -LiteralPath $preserve
    $preserveBackup = ""
    if ($preserveExists -and (Test-IsUnderJarvisOwnedRoot -Child $preserve -Root $Root)) {
        $preserveBackup = Join-Path ([System.IO.Path]::GetTempPath()) ("Jarvis-license-issuer-preserve-" + [guid]::NewGuid().ToString("n"))
        Write-CleanLog "preserving license-issuer to $preserveBackup"
        Copy-Item -LiteralPath $preserve -Destination $preserveBackup -Recurse -Force
    }

    if ($Root.Equals($InstallRootForPreserve, [StringComparison]::OrdinalIgnoreCase)) {
        $unins = Join-Path $Root "unins000.exe"
        if (Test-Path -LiteralPath $unins) {
            Write-CleanLog "running silent uninstall $unins"
            $proc = Start-Process -FilePath $unins -ArgumentList @("/VERYSILENT", "/SUPPRESSMSGBOXES", "/NORESTART") -WorkingDirectory $Root -PassThru -WindowStyle Hidden -Wait
            Write-CleanLog "uninstall exit code=$($proc.ExitCode) (exit 0 is not wipe success; leftover files are still deleted)"
        } else {
            Write-CleanLog "uninstall skip: unins000.exe missing (broken leftover tree); continuing owned wipe"
        }
    }

    $round = 0
    $maxRounds = 4
    while ($round -lt $maxRounds) {
        $round++
        if (-not (Test-Path -LiteralPath $Root)) { break }
        $children = Get-OwnedLeftovers -Root $Root -PreservePath $(if ($preserveExists) { $preserve } else { "" })
        if ($children.Count -eq 0) { break }
        foreach ($item in $children) {
            if ($preserveExists -and $item.FullName.Equals($preserve, [StringComparison]::OrdinalIgnoreCase)) {
                Write-CleanLog "wipe skip preserved path=$preserve"
                continue
            }
            if (Remove-PathWithRetry -Path $item.FullName) {
                Write-CleanLog "deleted $($item.FullName)"
            } else {
                Write-CleanLog "wipe still locked path=$($item.FullName)"
            }
        }
        $left = Get-OwnedLeftovers -Root $Root -PreservePath $(if ($preserveExists) { $preserve } else { "" })
        if ($left.Count -eq 0) { break }
        Write-CleanLog "wipe round $round leftover count=$($left.Count); re-running force-stop"
        [void](Invoke-ForceStopAllRoots -Roots @($Root))
        Start-Sleep -Milliseconds 400
    }

    $left = Get-OwnedLeftovers -Root $Root -PreservePath $(if ($preserveExists) { $preserve } else { "" })
    if ($left.Count -gt 0) {
        foreach ($item in $left) {
            Write-CleanLog "leftover path=$($item.FullName)"
        }
        Write-CleanLog "wipe error root=$Root leftover=$($left.Count)"
        return $false
    }

    if ($preserveBackup -and (Test-Path -LiteralPath $preserveBackup)) {
        if (-not (Test-Path -LiteralPath $Root)) {
            New-Item -ItemType Directory -Force -Path $Root | Out-Null
        }
        $dest = Get-LicenseIssuerPreservePath -InstallRoot $Root
        Copy-Item -LiteralPath $preserveBackup -Destination $dest -Recurse -Force
        Remove-Item -LiteralPath $preserveBackup -Recurse -Force -ErrorAction SilentlyContinue
        Write-CleanLog "restored license-issuer under $dest"
    }
    return $true
}

function Resolve-SetupExe {
    param(
        [string]$Requested,
        [string[]]$OwnedRoots
    )
    $candidates = @()
    if ($Requested) { $candidates += $Requested }
    $reg = Read-OwnedPathsRegistry
    if ($reg.SetupExe) { $candidates += $reg.SetupExe }
    $candidates += @(
        (Join-Path (Resolve-InstallRootCandidate -InstallRoot $InstallRoot) "installer\windows\dist\JarvisSetup.exe"),
        (Join-Path $scriptDir "dist\JarvisSetup.exe")
    )
    foreach ($path in $candidates) {
        if (-not $path) { continue }
        if (Test-Path -LiteralPath $path) {
            return (Resolve-Path -LiteralPath $path).Path
        }
    }
    return ""
}

function Stage-SetupOutsideOwnedRoots {
    param(
        [Parameter(Mandatory = $true)][string]$SetupPath,
        [string[]]$OwnedRoots
    )
    $setupNorm = (Resolve-Path -LiteralPath $SetupPath).Path
    foreach ($root in $OwnedRoots) {
        if (Test-IsUnderJarvisOwnedRoot -Child $setupNorm -Root $root) {
            $staged = Join-Path ([System.IO.Path]::GetTempPath()) ("JarvisSetup-clean-" + [guid]::NewGuid().ToString("n") + ".exe")
            Write-CleanLog "staging Setup.exe outside owned roots: $staged"
            Copy-Item -LiteralPath $setupNorm -Destination $staged -Force
            return $staged
        }
    }
    return $setupNorm
}

function Confirm-OwnerWipe {
    param([string[]]$Roots)
    if ($SkipConfirm) { return $true }
    $list = ($Roots | ForEach-Object { "  - $_" }) -join [Environment]::NewLine
    $msg = @"
Clean Install / Reinstall permanently removes Jarvis application files, models, chats, logs, and other Jarvis-owned data on this PC, then runs Setup again.

Owned roots to remove:
$list

This cannot be undone. Continue?
"@
    $first = [System.Windows.Forms.MessageBox]::Show(
        $msg,
        "Clean Install / Reinstall",
        [System.Windows.Forms.MessageBoxButtons]::YesNo,
        [System.Windows.Forms.MessageBoxIcon]::Warning,
        [System.Windows.Forms.MessageBoxDefaultButton]::Button2
    )
    if ($first -ne [System.Windows.Forms.DialogResult]::Yes) {
        return $false
    }
    $second = [System.Windows.Forms.MessageBox]::Show(
        "Final confirmation: permanently delete the paths listed and reinstall Jarvis?",
        "Clean Install / Reinstall",
        [System.Windows.Forms.MessageBoxButtons]::YesNo,
        [System.Windows.Forms.MessageBoxIcon]::Warning,
        [System.Windows.Forms.MessageBoxDefaultButton]::Button2
    )
    return ($second -eq [System.Windows.Forms.DialogResult]::Yes)
}

try {
    Add-Type -AssemblyName System.Windows.Forms -ErrorAction SilentlyContinue
} catch { }

Write-CleanStatus -Status "running" -ExitReason ""

$install = Resolve-InstallRootCandidate -InstallRoot $InstallRoot
if (-not (Test-IsSafeJarvisInstallDir -Path $install)) {
    $exitReason = "unsafe-install-root"
    Write-CleanLog "abort: install root failed safety gate: $install"
    Exit-CleanReinstall -Code 10 -Reason $exitReason
}

$ownedRoots = @(Get-RegisteredOwnedJarvisRoots -InstallRoot $install)
if ($ownedRoots.Count -eq 0) {
    $exitReason = "no-owned-roots"
    Write-CleanLog "abort: no registered owned roots"
    Exit-CleanReinstall -Code 11 -Reason $exitReason
}

foreach ($root in $ownedRoots) {
    Write-CleanLog "owned-root $root"
}

$setupResolved = Resolve-SetupExe -Requested $SetupExePath -OwnedRoots $ownedRoots
if (-not $setupResolved -and $Mode -eq "Portal") {
    $exitReason = "setup-not-found"
    Write-CleanLog "abort: JarvisSetup.exe not found before wipe"
    Exit-CleanReinstall -Code 3 -Reason $exitReason
}
if ($setupResolved) {
    $setupLaunchPath = Stage-SetupOutsideOwnedRoots -SetupPath $setupResolved -OwnedRoots $ownedRoots
    Write-CleanLog "setup path=$setupLaunchPath"
}

if (-not (Confirm-OwnerWipe -Roots $ownedRoots)) {
    $exitReason = "cancelled"
    Write-CleanLog "cancelled by owner"
    Exit-CleanReinstall -Code 0 -Reason $exitReason
}

if (-not (Invoke-ForceStopAllRoots -Roots $ownedRoots)) {
    $exitReason = "force-stop-failed"
    Exit-CleanReinstall -Code 1 -Reason $exitReason
}
if (Test-AnyLockersRemain -Roots $ownedRoots) {
    $exitReason = "force-stop-failed"
    Write-CleanLog "abort: lockers still hold owned roots"
    Exit-CleanReinstall -Code 1 -Reason $exitReason
}

foreach ($root in $ownedRoots) {
    if (-not (Remove-OwnedRootTree -Root $root -InstallRootForPreserve $install)) {
        $exitReason = "wipe-incomplete"
        Exit-CleanReinstall -Code 2 -Reason $exitReason
    }
}

if (Test-AnyLockersRemain -Roots $ownedRoots) {
    $exitReason = "wipe-incomplete"
    Write-CleanLog "abort: lockers still hold owned roots after wipe"
    Exit-CleanReinstall -Code 2 -Reason $exitReason
}

foreach ($root in $ownedRoots) {
    if (Test-Path -LiteralPath $root) {
        $issuer = Get-LicenseIssuerPreservePath -InstallRoot $install
        $filtered = Get-OwnedLeftovers -Root $root -PreservePath $issuer
        if ($filtered.Count -gt 0) {
            $exitReason = "wipe-incomplete"
            Write-CleanLog "abort: owned files remain under $root"
            Exit-CleanReinstall -Code 2 -Reason $exitReason
        }
    }
}

if ($Mode -eq "Inno") {
    $exitReason = "ok"
    Write-CleanLog "ok: inno wipe complete (Setup continues)"
    Exit-CleanReinstall -Code 0 -Reason $exitReason
}

if (-not $setupLaunchPath -or -not (Test-Path -LiteralPath $setupLaunchPath)) {
    $exitReason = "setup-not-found"
    Write-CleanLog "abort: Setup missing after wipe"
    Exit-CleanReinstall -Code 3 -Reason $exitReason
}

try {
    Write-CleanLog "launching Setup $setupLaunchPath"
    Start-Process -FilePath $setupLaunchPath -WindowStyle Normal | Out-Null
} catch {
    $exitReason = "setup-launch-failed"
    Write-CleanLog "setup launch failed: $($_.Exception.Message)"
    Exit-CleanReinstall -Code 4 -Reason $exitReason
}

$exitReason = "ok"
Write-CleanLog "ok: clean reinstall helper finished"
Exit-CleanReinstall -Code 0 -Reason $exitReason
