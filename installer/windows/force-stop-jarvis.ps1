#Requires -Version 5.1
<#
.SYNOPSIS
  RFC-0093: Force-stop Jarvis-related processes under the install tree before file replace.

.DESCRIPTION
  Polite stop via stop-jarvis.ps1 (optional), then force-kills remaining lockers with bounded waits.
  Writes installer-stop.log under {InstallRoot}\logs. Exits 0 when the tree is clear, 1 otherwise.
#>
param(
    [Parameter(Mandatory = $false)]
    [string]$InstallRoot = "",

    [string[]]$InstallRoots = @(),

    [switch]$IncludeTray,

    [int]$MaxWaitSeconds = 90,

    [string]$LogPath = ""
)

$ErrorActionPreference = "Continue"

$targets = @()
if ($InstallRoots -and $InstallRoots.Count -gt 0) {
    $targets = @($InstallRoots | ForEach-Object { $_.TrimEnd('\') } | Where-Object { $_ })
} elseif ($InstallRoot) {
    $targets = @($InstallRoot.TrimEnd('\'))
} else {
    Write-Error "InstallRoot or InstallRoots is required"
    exit 1
}

function Invoke-ForceStopSingleRoot {
    param(
        [string]$Root,
        [string]$LogPath,
        [int]$MaxWaitSeconds,
        [bool]$IncludeTray
    )

    $logDir = Split-Path -Parent $LogPath
    if ($logDir -and -not (Test-Path $logDir)) {
        New-Item -ItemType Directory -Force -Path $logDir | Out-Null
    }

    function Write-StopLog([string]$Message) {
        $line = "{0:yyyy-MM-dd HH:mm:ss} {1}" -f (Get-Date), $Message
        Add-Content -LiteralPath $LogPath -Value $line -Encoding UTF8
        Write-Host $line
    }

    function Test-ProcessUnderInstall([System.Management.ManagementObject]$Proc, [string]$RootNorm) {
        $name = $Proc.Name
        $cmd = [string]$Proc.CommandLine
        $exePath = [string]$Proc.ExecutablePath
        $rootLower = $RootNorm.ToLowerInvariant()

        if ($exePath -and $exePath.ToLowerInvariant().StartsWith($rootLower)) {
            return $true
        }
        if ($cmd -and $cmd.ToLowerInvariant().Contains($rootLower)) {
            return $true
        }
        if ($name -eq "llama-server.exe" -and $exePath -and $exePath.ToLowerInvariant().Contains("\runtime\llama.cpp\")) {
            if ($exePath.ToLowerInvariant().StartsWith($rootLower)) { return $true }
        }
        if ($name -match "^(node|npm|java|gradle)$" -and $cmd) {
            $cl = $cmd.ToLowerInvariant()
            if ($cl.Contains("$rootLower\mcp\") -or $cl.Contains("$rootLower\frontend\") -or $cl.Contains("$rootLower\android\")) {
                return $true
            }
        }
        if ($name -match "^(python|pythonw)$" -and ($exePath -or $cmd)) {
            $hay = (($exePath + " " + $cmd)).ToLowerInvariant()
            if ($hay.Contains($rootLower)) { return $true }
        }
        if ($name -eq "powershell.exe" -and $cmd -and $cmd -match "start-jarvis\.ps1") {
            if ($cmd.ToLowerInvariant().Contains($rootLower)) { return $true }
        }
        return $false
    }

    function Get-InstallLockers([string]$RootNorm) {
        $found = @()
        Get-CimInstance Win32_Process -ErrorAction SilentlyContinue | ForEach-Object {
            if (Test-ProcessUnderInstall $_ $RootNorm) {
                $found += $_
            }
        }
        return $found
    }

    function Stop-LockersForce([array]$Procs, [string]$Reason) {
        foreach ($p in $Procs) {
            $pid = [int]$p.ProcessId
            $pname = [string]$p.Name
            try {
                Stop-Process -Id $pid -Force -ErrorAction Stop
                Write-StopLog "force-kill PID=$pid name=$pname reason=$Reason"
            } catch {
                Write-StopLog "force-kill-failed PID=$pid name=$pname reason=$Reason error=$($_.Exception.Message)"
            }
        }
    }

    $deadline = (Get-Date).AddSeconds($MaxWaitSeconds)
    $rootNorm = (Resolve-Path -LiteralPath $Root -ErrorAction SilentlyContinue).Path
    if (-not $rootNorm) {
        $rootNorm = $Root
    }

    Write-StopLog "force-stop start InstallRoot=$rootNorm MaxWaitSeconds=$MaxWaitSeconds"

    $stopScript = Join-Path $Root "stop-jarvis.ps1"
    if (Test-Path $stopScript) {
        $politeArgs = @("-NoProfile", "-ExecutionPolicy", "Bypass", "-File", $stopScript)
        if ($IncludeTray) { $politeArgs += "-IncludeTray" }
        $polite = Start-Process -FilePath "powershell.exe" -ArgumentList $politeArgs -WorkingDirectory $Root -PassThru -WindowStyle Hidden
        $politeWait = [Math]::Min(15, $MaxWaitSeconds)
        $polite.WaitForExit($politeWait * 1000)
        if (-not $polite.HasExited) {
            Write-StopLog "polite stop-jarvis.ps1 still running after ${politeWait}s; continuing to force phase"
            try { Stop-Process -Id $polite.Id -Force -ErrorAction SilentlyContinue } catch { }
        } else {
            Write-StopLog "polite stop-jarvis.ps1 exited code=$($polite.ExitCode)"
        }
        Get-InstallLockers $rootNorm | ForEach-Object {
            Write-StopLog "polite-pass remaining PID=$($_.ProcessId) name=$($_.Name)"
        }
    } else {
        Write-StopLog "polite skip: stop-jarvis.ps1 not found at $stopScript"
    }

    while ((Get-Date) -lt $deadline) {
        $lockers = @(Get-InstallLockers $rootNorm)
        if ($lockers.Count -eq 0) {
            Write-StopLog "force-stop complete: no lockers under install tree"
            return 0
        }
        Stop-LockersForce $lockers "locker-under-install-tree"
        Start-Sleep -Milliseconds 500
    }

    $remaining = @(Get-InstallLockers $rootNorm)
    foreach ($p in $remaining) {
        Write-StopLog "still-running PID=$($p.ProcessId) name=$($p.Name)"
    }
    Write-StopLog "force-stop failed: $($remaining.Count) process(es) still hold the install tree"
    return 1
}

$overall = 0
foreach ($root in $targets) {
    $rootLog = $LogPath
    if (-not $rootLog) {
        $rootLog = Join-Path $root "logs\installer-stop.log"
    }
    $code = Invoke-ForceStopSingleRoot -Root $root -LogPath $rootLog -MaxWaitSeconds $MaxWaitSeconds -IncludeTray:$IncludeTray
    if ($code -ne 0) {
        $overall = $code
    }
}
exit $overall
