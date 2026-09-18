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
$exitReason = "unknown"
$setupLaunchPath = ""

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
    $candidate = Join-Path $AppDir "installer\windows\force-stop-jarvis.ps1"
    if (Test-Path -LiteralPath $candidate) { return $candidate }
    $repoCandidate = Join-Path $scriptDir "force-stop-jarvis.ps1"
    if (Test-Path -LiteralPath $repoCandidate) { return $repoCandidate }
    return ""
}

function Test-LockersUnderRoot {
    param([string]$Root)
    $forceScript = Resolve-ForceStopScript -AppDir $Root
    if (-not $forceScript) { return $true }
    $null = & powershell.exe -NoProfile -ExecutionPolicy Bypass -File $forceScript `
        -InstallRoot $Root -IncludeTray -MaxWaitSeconds 1 `
        -LogPath (Join-Path $Root "logs\installer-stop.log") 2>&1
    $forceText = Get-Content -LiteralPath (Join-Path $Root "logs\installer-stop.log") -Tail 5 -ErrorAction SilentlyContinue
    if ($forceText -match "still hold") { return $true }
    return $false
}

function Invoke-ForceStopAllRoots {
    param([string[]]$Roots)
    foreach ($root in $Roots) {
        $forceScript = Resolve-ForceStopScript -AppDir $root
        if (-not $forceScript) {
            Write-CleanLog "abort: force-stop-jarvis.ps1 missing under $root"
            return $false
        }
        $logPath = Join-Path $root "logs\installer-stop.log"
        $args = @(
            "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", $forceScript,
            "-InstallRoot", $root, "-IncludeTray", "-MaxWaitSeconds", $MaxWaitSeconds,
            "-LogPath", $logPath
        )
        $proc = Start-Process -FilePath "powershell.exe" -ArgumentList $args -WorkingDirectory $root -PassThru -WindowStyle Hidden -Wait
        if ($proc.ExitCode -ne 0) {
            Write-CleanLog "force-stop failed for root=$root exit=$($proc.ExitCode)"
            return $false
        }
        Write-CleanLog "force-stop ok root=$root"
    }
    return $true
}

function Test-AnyLockersRemain {
    param([string[]]$Roots)
    foreach ($root in $Roots) {
        $forceScript = Resolve-ForceStopScript -AppDir $root
        if (-not $forceScript) { return $true }
        $checkLog = Join-Path $root "logs\clean-reinstall-lockcheck.log"
        $args = @(
            "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", $forceScript,
            "-InstallRoot", $root, "-IncludeTray", "-MaxWaitSeconds", "3",
            "-LogPath", $checkLog
        )
        $proc = Start-Process -FilePath "powershell.exe" -ArgumentList $args -WorkingDirectory $root -PassThru -WindowStyle Hidden -Wait
        if ($proc.ExitCode -ne 0) {
            Write-CleanLog "locker recheck failed root=$root"
            return $true
        }
    }
    return $false
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
            if ($proc.ExitCode -ne 0) {
                Write-CleanLog "uninstall exit code=$($proc.ExitCode) (continuing wipe)"
            }
        }
    }

    try {
        Get-ChildItem -LiteralPath $Root -Force -ErrorAction Stop | ForEach-Object {
            if ($preserveExists -and $_.FullName.Equals($preserve, [StringComparison]::OrdinalIgnoreCase)) {
                Write-CleanLog "wipe skip preserved path=$preserve"
                return
            }
            Remove-Item -LiteralPath $_.FullName -Recurse -Force -ErrorAction Stop
            Write-CleanLog "deleted $($_.FullName)"
        }
    } catch {
        Write-CleanLog "wipe error root=$Root error=$($_.Exception.Message)"
        return $false
    }

    $left = @(Get-ChildItem -LiteralPath $Root -Force -ErrorAction SilentlyContinue | Where-Object {
        -not ($preserveExists -and $_.FullName.Equals($preserve, [StringComparison]::OrdinalIgnoreCase))
    })
    if ($left.Count -gt 0) {
        foreach ($item in $left) {
            Write-CleanLog "leftover path=$($item.FullName)"
        }
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

$install = Resolve-InstallRootCandidate -InstallRoot $InstallRoot
if (-not (Test-IsSafeJarvisInstallDir -Path $install)) {
    $exitReason = "unsafe-install-root"
    Write-CleanLog "abort: install root failed safety gate: $install"
    exit 10
}

$ownedRoots = @(Get-RegisteredOwnedJarvisRoots -InstallRoot $install)
if ($ownedRoots.Count -eq 0) {
    $exitReason = "no-owned-roots"
    Write-CleanLog "abort: no registered owned roots"
    exit 11
}

foreach ($root in $ownedRoots) {
    Write-CleanLog "owned-root $root"
}

$setupResolved = Resolve-SetupExe -Requested $SetupExePath -OwnedRoots $ownedRoots
if (-not $setupResolved -and $Mode -eq "Portal") {
    $exitReason = "setup-not-found"
    Write-CleanLog "abort: JarvisSetup.exe not found before wipe"
    exit 3
}
if ($setupResolved) {
    $setupLaunchPath = Stage-SetupOutsideOwnedRoots -SetupPath $setupResolved -OwnedRoots $ownedRoots
    Write-CleanLog "setup path=$setupLaunchPath"
}

if (-not (Confirm-OwnerWipe -Roots $ownedRoots)) {
    $exitReason = "cancelled"
    Write-CleanLog "cancelled by owner"
    exit 0
}

if (-not (Invoke-ForceStopAllRoots -Roots $ownedRoots)) {
    $exitReason = "force-stop-failed"
    exit 1
}
if (Test-AnyLockersRemain -Roots $ownedRoots) {
    $exitReason = "force-stop-failed"
    Write-CleanLog "abort: lockers still hold owned roots"
    exit 1
}

foreach ($root in $ownedRoots) {
    if (-not (Remove-OwnedRootTree -Root $root -InstallRootForPreserve $install)) {
        $exitReason = "wipe-incomplete"
        exit 2
    }
}

foreach ($root in $ownedRoots) {
    if (Test-Path -LiteralPath $root) {
        $remain = Get-ChildItem -LiteralPath $root -Force -ErrorAction SilentlyContinue
        $issuer = Get-LicenseIssuerPreservePath -InstallRoot $install
        $filtered = @($remain | Where-Object { -not $_.FullName.Equals($issuer, [StringComparison]::OrdinalIgnoreCase) })
        if ($filtered.Count -gt 0) {
            $exitReason = "wipe-incomplete"
            Write-CleanLog "abort: owned files remain under $root"
            exit 2
        }
    }
}

if ($Mode -eq "Inno") {
    $exitReason = "ok"
    Write-CleanLog "ok: inno wipe complete (Setup continues)"
    exit 0
}

if (-not $setupLaunchPath -or -not (Test-Path -LiteralPath $setupLaunchPath)) {
    $exitReason = "setup-not-found"
    Write-CleanLog "abort: Setup missing after wipe"
    exit 3
}

try {
    Write-CleanLog "launching Setup $setupLaunchPath"
    Start-Process -FilePath $setupLaunchPath -WindowStyle Normal | Out-Null
} catch {
    $exitReason = "setup-launch-failed"
    Write-CleanLog "setup launch failed: $($_.Exception.Message)"
    exit 4
}

$exitReason = "ok"
Write-CleanLog "ok: clean reinstall helper finished"
exit 0
